# ------------------------------------------------------------------
# Wingdings 불릿 오염 수정 후 재임베딩 — 중간 jsonl 파일 없이 DB에서 바로
# (2026-08-24)
# ------------------------------------------------------------------
# 배경: fix_symbol_font_bullet_leak.py DRY_RUN=False 반영 시 export한
# reembed_input_bullet_fix.jsonl / repair 스크립트가 만든 v2 파일 둘 다,
# 새 Colab 세션(다른 Drive 마운트로 추정)에서 못 찾는 문제 발생. 중간 파일에
# 의존하지 않고 DB에서 직접 다시 뽑는 걸로 우회.
#
# reembed_changed_chunks.py처럼 "정확히 바뀐 chunk만" 골라내려면 수정 전 텍스트가
# 필요한데 이미 DB가 수정된 상태라 재계산 불가능 — 대신 **대상 5개 기관의 chunk
# 전부**(1,758건, fix_symbol_font_bullet_leak.py 실행 시 이미 확인된 모수)를
# 재임베딩함. 안 바뀐 chunk는 텍스트가 원래와 같으니 같은 벡터가 나올 뿐이라
# 무해함(약간의 GPU 시간 낭비만 있고 정확성 문제는 없음) — 정확히 444건만 고르는
# 것보다 훨씬 안전하고 이 문제 자체를 원천 차단함.
#
# **반드시 Colab 노트북 셀에 이 파일 내용을 그대로 붙여넣거나 %run으로 실행할 것**
# (!python 서브프로세스 금지 — google.colab.userdata 연결 끊김, reembed_changed_chunks.py
# 주석과 동일한 이유).
# ------------------------------------------------------------------

# !pip install -q FlagEmbedding psycopg2-binary pgvector

import json
import os

import numpy as np
import psycopg2
from FlagEmbedding import BGEM3FlagModel
from pgvector.psycopg2 import register_vector

# fix_symbol_font_bullet_leak.py의 CONFIRMED_BULLET_RULES와 반드시 일치시킬 것
CONFIRMED_INSTITUTIONS = [
    "한국수력원자력",
    "서울대학교병원",
    "국립부산과학관",
    "한국수자원조사기술원",
    "한국원자력통제기술원",
]

BATCH_SIZE = 64
MAX_LENGTH = 1024  # 청킹 시 max_length와 반드시 일치 (embed_chunks.py와 동일 값)

# 체크포인트는 있으면 Drive에, 없으면 로컬(/content)에 — 이번 사고 원인(Drive
# 세션 불일치)을 감안해 Drive가 없어도 동작하도록 방어적으로 작성.
_drive_dir = "/content/drive/MyDrive/audit_project/"
CHECKPOINT_PATH = (
    _drive_dir + "reembed_checkpoint_bullet_fix_v3.jsonl"
    if os.path.isdir(_drive_dir)
    else "reembed_checkpoint_bullet_fix_v3.jsonl"
)
print(f"체크포인트 경로: {CHECKPOINT_PATH}")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

# ------------------------------------------------------------------
# 1) 대상 5개 기관의 chunk 전부 조회 (DB에서 바로 — 중간 파일 없음)
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute(
        "SELECT c.id, c.text FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE d.institution = ANY(%s)",
        (CONFIRMED_INSTITUTIONS,),
    )
    rows = cur.fetchall()
conn.close()

chunk_ids = [r[0] for r in rows]
texts = [r[1] for r in rows]
total = len(texts)
print(f"재임베딩 대상(5개 기관 전체 chunk): {total}건")

if total == 0:
    raise SystemExit("대상 chunk가 없음 — 기관명 철자 확인할 것")

# ------------------------------------------------------------------
# 2) 체크포인트 로드 — 이미 계산된 chunk_id는 건너뜀
# ------------------------------------------------------------------
done: dict[str, list] = {}
if os.path.exists(CHECKPOINT_PATH):
    with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            done[rec["chunk_id"]] = rec["embedding"]
    print(f"체크포인트에서 {len(done)}건 이미 완료된 것 발견 — 이어서 진행")

remaining_idx = [i for i, cid in enumerate(chunk_ids) if cid not in done]
print(f"남은 것: {len(remaining_idx)}건 (전체 {total}건 중)")

# ------------------------------------------------------------------
# 3) BGE-m3로 재임베딩 (남은 것만) — 배치마다 체크포인트에 즉시 저장
# ------------------------------------------------------------------
if remaining_idx:
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)

    with open(CHECKPOINT_PATH, "a", encoding="utf-8") as ckpt_f:
        for start in range(0, len(remaining_idx), BATCH_SIZE):
            batch_idx = remaining_idx[start:start + BATCH_SIZE]
            batch_texts = [texts[i] for i in batch_idx]
            output = model.encode(
                batch_texts,
                batch_size=BATCH_SIZE,
                max_length=MAX_LENGTH,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            for idx, vec in zip(batch_idx, output["dense_vecs"]):
                cid = chunk_ids[idx]
                emb_list = [round(float(x), 5) for x in vec]
                done[cid] = emb_list
                ckpt_f.write(json.dumps({"chunk_id": cid, "embedding": emb_list}) + "\n")
            ckpt_f.flush()
            os.fsync(ckpt_f.fileno())
            print(f"  임베딩 진행: {min(start + BATCH_SIZE, len(remaining_idx))}/{len(remaining_idx)} "
                  f"(전체 기준 {len(done)}/{total})")

print("전체 임베딩 계산 완료")

# ------------------------------------------------------------------
# 4) 벡터 정합성 체크
# ------------------------------------------------------------------
vectors = np.array([done[cid] for cid in chunk_ids], dtype=np.float16)
norms = np.linalg.norm(vectors.astype(np.float32), axis=1)
print(f"벡터 norm 평균/표준편차: {norms.mean():.6f} / {norms.std():.6f}")
if abs(norms.mean() - 1.0) > 0.01:
    raise SystemExit("벡터 norm이 1.0에서 크게 벗어남 — DB 반영 전에 원인 확인 필요")

# ------------------------------------------------------------------
# 5) chunks.embedding UPDATE — UPDATE는 멱등이라 재실행해도 안전
# ------------------------------------------------------------------
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
            print(f"  DB 반영: {min(i + 500, len(rows))}/{len(rows)}")

    with conn.cursor() as cur:
        cur.execute("SELECT embedding FROM chunks WHERE id = %s", (chunk_ids[0],))
        sample = cur.fetchone()[0]
        sample_arr = sample.to_numpy() if hasattr(sample, "to_numpy") else np.array(sample)
        print(f"반영 확인(샘플 1건) norm: {np.linalg.norm(sample_arr):.6f}")
finally:
    conn.close()

print(f"완료 — {total}건(5개 기관 chunk 전체) 재임베딩 + chunks.embedding 반영 끝")
print(f"체크포인트 파일은 안 지웠음 — 확인 후 필요 없으면 삭제: !rm {CHECKPOINT_PATH}")
