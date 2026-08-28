# ------------------------------------------------------------------
# 부서/기관명 익명화 심볼 누출 — chunks 잔여분 정리 (2026-08-28)
# ------------------------------------------------------------------
# 배경: `backfill_dept_anon_symbol_fix.py`가 2026-08-27 새벽 documents.raw_text에
# DRY_RUN=False로 실제 반영 완료(42종 마스킹 심볼 + 기존 "[부서]" 라벨을 "[비공개]"로
# 통일, 50,344건). 원래는 그 뒤 `rechunk_reembed_dept_anon_symbol_fix.py`로 chunks
# 테이블까지 재청킹+재임베딩해야 완결되는데, 그 단계가 "GPU 할당량 소진으로 다음날 이월"된
# 채로 세션이 끊겼고, 그 브랜치(claude/daily-task-summary-qoehlz)가 main에 병합된 적이
# 없어서 이 사실 자체가 이 저장소에 기록돼 있지 않았음(STATUS.md 2026-08-28 참고).
#
# 이번 세션에서 SQL로 직접 확인해보니 chunks 50,344건 중 50,294건(99.9%)은 원인 미상의
# 다른 재청킹 작업에 우연히 딸려 들어가 이미 새 텍스트로 맞춰져 있었고, **잔여 60건만**
# 옛 텍스트("[부서]" 또는 원본 마스킹 심볼)로 남아있었음 — 이 스크립트는 그 잔여분만
# 정확히 찾아서 text/tsv_text(형태소 재토큰화)/embedding(BGE-m3 재임베딩)을 한 번에
# 갱신함. 전체 재청킹(rechunk_reembed_dept_anon_symbol_fix.py)을 다시 돌릴 필요 없음 —
# 대상이 극소수라 이 스크립트로 충분.
#
# **실행 위치**: 이 저장소(backend/app/tokenizer.py)를 그대로 import해서 쓰므로, 이
# 저장소 클론 루트에서 실행. FlagEmbedding은 kiwipiepy와 달리 이 스크립트 자체에서
# pip install 필요(아래 주석 참고). google.colab.userdata를 쓰지 않고 DATABASE_URL
# 환경변수만 읽으므로 서브프로세스(`!python ...`)로 실행해도 무방.
#
# 실행:
#   !pip install -q FlagEmbedding psycopg2-binary pgvector
#   DATABASE_URL=postgresql://... python scripts/fix_dept_anon_symbol_chunks_residual.py
#
# 2026-08-28 실제 실행 결과: 후보 60건, 전부 실제로 텍스트 변경 대상으로 확정 → 반영 후
# 재검증(`WHERE text LIKE '%[부서]%'`, `WHERE text ~ '[♣♧▩▧♥♠⊗♡♤]'`) 둘 다 0건 확인 완료.
# ------------------------------------------------------------------
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
from pgvector.psycopg2 import register_vector

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    try:
        from google.colab import userdata

        DATABASE_URL = userdata.get("DATABASE_URL")
    except Exception:
        pass
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL 환경변수가 필요합니다.")

BACKUP_PATH = os.environ.get(
    "BACKUP_PATH", "/content/drive/MyDrive/audit_project/dept_anon_chunk_fix_backup.jsonl"
)

# --- backfill_dept_anon_symbol_fix.py와 동일한 정규화 로직 (일관성 유지 위해 그대로 복제) ---
MASK_ONLY_CHARS = "♣♧▩▧♥♠⊗♡♤◉▤◐◁▷◍▥▨◎◈◒▣◌◧◊▒◕◫◑◩◷◨◰⊠◪◘▦"
AMBIGUOUS_DUAL_USE_CHARS = "○□△▲▽▼◇◆▢■▶●★☆"
PLACEHOLDER = "[비공개]"

_MASK_ONLY_RE = re.compile("[" + re.escape(MASK_ONLY_CHARS) + "]+")
_AMBIGUOUS_RUN_RE = re.compile("([" + re.escape(AMBIGUOUS_DUAL_USE_CHARS) + "])\\1+")
_OLD_PLACEHOLDER_RE = re.compile(re.escape("[부서]"))
_REPEATED_PLACEHOLDER_RE = re.compile(f"(?:{re.escape(PLACEHOLDER)})+")


def normalize_masked_glyphs(text: str) -> str:
    if not text:
        return text
    text = _MASK_ONLY_RE.sub(PLACEHOLDER, text)
    text = _AMBIGUOUS_RUN_RE.sub(PLACEHOLDER, text)
    text = _OLD_PLACEHOLDER_RE.sub(PLACEHOLDER, text)
    text = _REPEATED_PLACEHOLDER_RE.sub(PLACEHOLDER, text)
    return text


def main() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, text FROM chunks
            WHERE text LIKE '%[부서]%'
               OR text ~ '[♣♧▩▧♥♠⊗♡♤◉▤◐◁▷◍▥▨◎◈◒▣◌◧◊▒◕◫◑◩◷◨◰⊠◪◘▦]'
               OR text ~ '([○□△▲▽▼◇◆▢■▶●★☆])\\1'
            """
        )
        candidates = cur.fetchall()
    conn.close()
    print(f"후보 청크: {len(candidates)}건")

    to_fix = [(cid, old, normalize_masked_glyphs(old)) for cid, old in candidates]
    to_fix = [(cid, old, new) for cid, old, new in to_fix if new != old]
    print(f"실제로 바뀌는 청크: {len(to_fix)}건")
    if not to_fix:
        print("고칠 게 없습니다 — 이미 다 반영된 상태.")
        return

    os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
    with open(BACKUP_PATH, "w", encoding="utf-8") as f:
        for cid, old, _ in to_fix:
            f.write(json.dumps({"id": cid, "text": old}) + "\n")
    print(f"백업 완료: {BACKUP_PATH}")

    from app import tokenizer

    tokenizer.load_model()
    new_texts = [new for _, _, new in to_fix]
    tsv_texts = tokenizer.tokenize_batch(new_texts)

    from FlagEmbedding import BGEM3FlagModel

    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    output = model.encode(
        new_texts,
        batch_size=32,
        max_length=1024,  # embed_chunks.py/reembed_changed_chunks.py와 동일 값 — 반드시 일치
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    vectors = output["dense_vecs"]

    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    with conn.cursor() as cur:
        for (cid, _, new_text), tsv_text, vec in zip(to_fix, tsv_texts, vectors):
            cur.execute(
                "UPDATE chunks SET text = %s, tsv_text = %s, embedding = %s WHERE id = %s",
                (new_text, tsv_text, vec, cid),
            )
        conn.commit()
    conn.close()
    print(f"완료 — {len(to_fix)}건 text/tsv_text/embedding 반영")

    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks WHERE text LIKE '%[부서]%'")
        print("잔여 [부서]:", cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM chunks WHERE text ~ '[♣♧▩▧♥♠⊗♡♤]'")
        print("잔여 원본 심볼:", cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
