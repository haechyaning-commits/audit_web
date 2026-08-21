# ------------------------------------------------------------------
# HWP 원문 잘림/표 컬럼 뒤섞임 복구분 재청킹 + 재임베딩 (2026-08-14)
# ------------------------------------------------------------------
# 배경: 오늘 raw_text를 고친 두 묶음(HWP 잘림 5,389건 + 표 컬럼 뒤섞임 47건,
# 총 5,436건)은 옛 청크가 옛(잘못된) raw_text 기준으로 만들어져 있어서 그대로
# 두면 검색/의미검색이 여전히 옛 텍스트를 참조함. 청킹 로직 자체는 이 레포
# 밖(원래 파이프라인)에 있어서 없음 — 기존 청크 분포(평균 1,321자/중앙값
# 1,097자/최대 3,002자, id 형식 "{document_id}_{8자리해시}")를 보고 비슷하게
# 동작하는 청킹 함수를 새로 설계함(문단 단위로 묶어서 target_size 근처가 되면
# 새 청크 시작, 문단이 너무 길면 문장 단위로 강제 분할).
#
# GPU 필요(Colab 런타임 -> T4 GPU로 변경). 실제 신규/변경 청크 수는 약 2,757개
# 추정(재검증된 raw_text 순증가 3.6MB 기준) — 과거 34,764건급 재임베딩과 비교하면
# 훨씬 작은 규모라 인덱스 DROP 없이 진행해도 안전한 규모로 판단(참고:
# schema_tables.sql 주석의 "대량 쓰기 전 인덱스 DROP" 교훈은 수만 건 단위에서
# 나온 것).
#
# **실행 순서**:
#   1) DRY_RUN=True로 먼저 — 대상 문서 수, 예상 신규 청크 수, 샘플 청킹 결과 확인.
#   2) 이상 없으면 DRY_RUN=False로 재실행 — DELETE 옛 청크 -> INSERT 새 청크(임베딩 NULL)
#      -> GPU 임베딩(체크포인트) -> UPDATE.
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary FlagEmbedding pgvector

import hashlib
import json
import os
import re

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로

EMBED_CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/rechunk_embed_checkpoint.jsonl"
BATCH_SIZE = 64
MAX_LENGTH = 1024  # embed_chunks.py / reembed_changed_chunks.py와 동일 값

DATABASE_URL = None
try:
    from google.colab import userdata
    DATABASE_URL = userdata.get("DATABASE_PUBLIC_URL")
except Exception:
    pass
if not DATABASE_URL:
    DATABASE_URL = os.environ.get("DATABASE_URL")


# ------------------------------------------------------------------
# 청킹 함수 — 기존 청크 분포(평균 1,321자/중앙값 1,097자/최대 3,002자)에 맞춰 설계.
# 문단(빈 줄) 단위로 묶어서 target_size 근처가 되면 새 청크 시작, 문단 하나가
# max_size 넘으면 문장 단위로 강제 분할.
# ------------------------------------------------------------------
def split_into_chunks(text: str, target_size: int = 1300, max_size: int = 3000) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        stripped = text.strip()
        return [stripped] if stripped else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current))
        current, current_len = [], 0

    for p in paragraphs:
        if len(p) > max_size:
            flush()
            sentences = re.split(r"(?<=[.!?。])\s+", p)
            sub: list[str] = []
            sub_len = 0
            for s in sentences:
                # 문장 하나 자체가 max_size보다 길면(마침표 없는 표/나열식 텍스트 등)
                # 문장 분할로도 못 줄이므로 강제로 글자 수 기준 잘라냄 — 안 그러면
                # 청크가 임베딩 모델의 max_length(토큰 기준)를 훌쩍 넘겨서 뒷부분이
                # 통째로 잘려나가는 문제가 생김(실제 검증 중 39,337자짜리 청크 발견).
                if len(s) > max_size:
                    if sub:
                        chunks.append(" ".join(sub))
                        sub, sub_len = [], 0
                    for i in range(0, len(s), max_size):
                        chunks.append(s[i:i + max_size])
                    continue
                if sub_len + len(s) > max_size and sub:
                    chunks.append(" ".join(sub))
                    sub, sub_len = [], 0
                sub.append(s)
                sub_len += len(s)
            if sub:
                chunks.append(" ".join(sub))
            continue

        if current_len + len(p) > target_size and current:
            flush()
        current.append(p)
        current_len += len(p)

    flush()
    # 마지막 안전장치 — 위 로직에 놓친 엣지 케이스가 있어도 여기서 무조건
    # max_size 이하로 강제 캡(실제 검증 중 3,670자짜리가 하나 나온 적 있어서 추가).
    final_chunks = []
    for c in chunks:
        if len(c) > max_size:
            for i in range(0, len(c), max_size):
                final_chunks.append(c[i:i + max_size])
        else:
            final_chunks.append(c)
    return [c for c in final_chunks if c]


def make_chunk_id(document_id: str, index: int, text: str) -> str:
    h = hashlib.md5(f"{document_id}_{index}_{text[:30]}".encode("utf-8")).hexdigest()[:8]
    return f"{document_id}_{h}"


# ------------------------------------------------------------------
# 1) 대상 문서 조회 — 오늘 raw_text 고친 두 묶음(HWP 잘림 + 표 컬럼 뒤섞임)
# ------------------------------------------------------------------
HWP_CLEANED_PATH = "/content/drive/MyDrive/audit_project/hwp_truncation_checkpoint_cleaned.jsonl"
HWPX_LEAK_FIX_PATH = "/content/drive/MyDrive/audit_project/hwpx_leak_fix_checkpoint.jsonl"

target_ids = set()
with open(HWP_CLEANED_PATH, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if rec["status"] == "ok":
            target_ids.add(rec["id"])
if os.path.exists(HWPX_LEAK_FIX_PATH):
    with open(HWPX_LEAK_FIX_PATH, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["status"] == "ok":
                target_ids.add(rec["id"])

print(f"HWP 잘림 복구 대상: {len(target_ids)}건")

# 표 컬럼 뒤섞임 47건(서울대치과병원류 43건 + 한국소비자원/한국세라믹기술원 4건,
# 2026-08-14 세션 중 반영 완료 — scripts/backfill_table_column_fix.py 두 배치)도
# 같은 이유로 재청킹 필요해서 같이 포함
TABLE_FIX_IDS = [
    "5d67b59412b2194a", "4cc1570185e3eed1", "a4dbf432d7a30dd1", "646a0e2a80726289",
    "faf5c45ab2bd2804", "385ad4139acd0998", "c34d1181227f1d9f", "44ee95b20b2f9f27",
    "f0681e99f8e23256", "a35c9339c624731c", "345b7592401854c5", "2f66e79537a89c05",
    "0eb4f1585464c1dd", "bf834aec52e24643", "efb04f1e53ac84c8", "677bec13f59ef57e",
    "fd4a59c29ef8d09a", "2860942bad3de574", "ae0e332c1bd78ca6", "44ce3fb21c435944",
    "138efffa5e91f2d3", "0bbf9769ee9231cc", "a2f98cb0f2100252", "4d2ff0084d914671",
    "6abfcc2b550e4fec", "1334564331c57663", "f1036b59335d6322", "db7a32e5ae7befdb",
    "0818abc18a94f5e2", "6594d24883e33ef8", "d437b1b7c8962739", "0dba64c09eb8d484",
    "c6a234d772f9774a", "7f10a66914f434d5", "5e9c803a33072631", "b6f3be053273dead",
    "ca69206d7edaaca7", "3b3e1f35b5835514", "f439d96435a4a25f", "76d9baa8aabee5dc",
    "e1072879d7af96be", "b2507fef63c60856", "38b10537a489ad98", "97e10074ac8bf521",
    "83aa0e04fc26c51a", "19c29983ee3dd702", "e308f927ace00edf",
]
target_ids.update(TABLE_FIX_IDS)
print(f"표 컬럼 뒤섞임 복구 대상 추가: {len(TABLE_FIX_IDS)}건 (합계 {len(target_ids)}건)")

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '60s'")
    cur.execute("SELECT id, raw_text FROM documents WHERE id = ANY(%s)", (list(target_ids),))
    doc_rows = cur.fetchall()
conn.close()
print(f"실제 조회된 문서: {len(doc_rows)}건")

# ------------------------------------------------------------------
# 2) 재청킹
# ------------------------------------------------------------------
new_chunks = []  # (chunk_id, document_id, text)
for doc_id, raw_text in doc_rows:
    pieces = split_into_chunks(raw_text or "")
    for i, piece in enumerate(pieces):
        new_chunks.append((make_chunk_id(doc_id, i, piece), doc_id, piece))

print(f"신규 청크 수: {len(new_chunks)}건")
lens = [len(c[2]) for c in new_chunks]
if lens:
    print(f"청크 길이 — 평균 {sum(lens)/len(lens):.0f}, 최소 {min(lens)}, 최대 {max(lens)}")

print("\n샘플 3개:")
for cid, did, text in new_chunks[:3]:
    print(f"  {cid} (doc={did}, len={len(text)}): {text[:100]!r}")

if DRY_RUN:
    raise SystemExit(
        "\nDRY_RUN=True라 여기서 멈춤(DB 변경 없음). "
        "위 청크 수/샘플이 말이 되면 DRY_RUN=False로 바꿔서 다시 실행하세요."
    )

# ------------------------------------------------------------------
# 3) DELETE 옛 청크 + INSERT 새 청크 (embedding은 아직 NULL)
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '120s'")
        target_id_list = list(target_ids)
        cur.execute("DELETE FROM chunks WHERE document_id = ANY(%s)", (target_id_list,))
        print(f"옛 청크 삭제: {cur.rowcount}건")
        conn.commit()

        insert_rows = [(cid, did, text) for cid, did, text in new_chunks]
        for i in range(0, len(insert_rows), 500):
            batch = insert_rows[i:i + 500]
            execute_values(
                cur,
                "INSERT INTO chunks (id, document_id, text) VALUES %s",
                batch,
            )
            conn.commit()
            print(f"  새 청크 INSERT: {min(i + 500, len(insert_rows))}/{len(insert_rows)}")
finally:
    conn.close()

print("\n재청킹 완료 — 이제 임베딩 계산 단계로 넘어가세요 (GPU 런타임 필요, 아래 4번).")

# ------------------------------------------------------------------
# 4) GPU 임베딩 (체크포인트 지원) — 이 아래는 별도 셀에 나눠서 실행 권장
#    (재청킹까지 CPU로 끝내고, 여기부터는 GPU 런타임 전환 후 이어서)
# ------------------------------------------------------------------
from FlagEmbedding import BGEM3FlagModel  # noqa: E402
from pgvector.psycopg2 import register_vector  # noqa: E402

chunk_ids = [c[0] for c in new_chunks]
texts = [c[2] for c in new_chunks]

done: dict[str, list] = {}
if os.path.exists(EMBED_CHECKPOINT_PATH):
    with open(EMBED_CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            done[rec["chunk_id"]] = rec["embedding"]
    print(f"임베딩 체크포인트에서 {len(done)}건 이미 완료된 것 발견")

remaining_idx = [i for i, cid in enumerate(chunk_ids) if cid not in done]
print(f"임베딩 남은 것: {len(remaining_idx)}건")

if remaining_idx:
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    with open(EMBED_CHECKPOINT_PATH, "a", encoding="utf-8") as ckpt_f:
        for start in range(0, len(remaining_idx), BATCH_SIZE):
            batch_idx = remaining_idx[start:start + BATCH_SIZE]
            batch_texts = [texts[i] for i in batch_idx]
            output = model.encode(
                batch_texts, batch_size=BATCH_SIZE, max_length=MAX_LENGTH,
                return_dense=True, return_sparse=False, return_colbert_vecs=False,
            )
            for idx, vec in zip(batch_idx, output["dense_vecs"]):
                cid = chunk_ids[idx]
                emb_list = [round(float(x), 5) for x in vec]
                done[cid] = emb_list
                ckpt_f.write(json.dumps({"chunk_id": cid, "embedding": emb_list}) + "\n")
            ckpt_f.flush()
            print(f"  임베딩 진행: {min(start + BATCH_SIZE, len(remaining_idx))}/{len(remaining_idx)}")

print("임베딩 계산 완료 — DB 반영으로 넘어감")

vectors = np.array([done[cid] for cid in chunk_ids], dtype=np.float16)
norms = np.linalg.norm(vectors.astype(np.float32), axis=1)
print(f"벡터 norm 평균/표준편차: {norms.mean():.6f} / {norms.std():.6f}")
if abs(norms.mean() - 1.0) > 0.01:
    raise SystemExit("벡터 norm이 1.0에서 크게 벗어남 — DB 반영 전에 원인 확인 필요")

conn = psycopg2.connect(DATABASE_URL)
register_vector(conn)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        rows = list(zip(vectors, chunk_ids))
        for i in range(0, len(rows), 500):
            batch = rows[i:i + 500]
            cur.executemany("UPDATE chunks SET embedding = %s WHERE id = %s", batch)
            conn.commit()
            print(f"  임베딩 DB 반영: {min(i + 500, len(rows))}/{len(rows)}")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL AND document_id = ANY(%s)", (list(target_ids),))
        print(f"\n임베딩 안 된 청크(0이어야 정상): {cur.fetchone()[0]}건")
finally:
    conn.close()

print("\n완료 — 재청킹 + 재임베딩 끝")
