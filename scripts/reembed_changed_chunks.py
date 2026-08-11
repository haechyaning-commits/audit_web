# ------------------------------------------------------------------
# 변경된 chunk 재임베딩 + DB 반영 스크립트
# ------------------------------------------------------------------
# fix_text_corruption.py 실행 후 같은 디렉터리에 생긴 reembed_input.jsonl
# (바뀐 chunk의 chunk_id + 수정된 text)을 입력으로 받아:
#   1) BGE-m3(GPU)로 재임베딩
#   2) chunks.embedding UPDATE
# 텍스트만 고치고 벡터를 그대로 두면 검색은 여전히 옛날(오염된) 텍스트 기준
# 벡터로 동작하므로 반드시 필요한 단계 (1차 때와 동일한 이유).
#
# **중요: 반드시 Colab 노트북 셀에 이 파일 내용을 그대로 붙여넣어서 실행할 것.**
# `!python scripts/reembed_changed_chunks.py`처럼 서브프로세스로 돌리면 안 됨 —
# google.colab.userdata가 Colab 프론트엔드(커널)와 통신해야 하는데 서브프로세스에서는
# 그 연결이 없어서 실패하고, 그 시점까지 계산한 임베딩(수십 분 분량의 GPU 연산)이
# 서브프로세스 메모리와 함께 통째로 날아감(2026-08-11 데이터 복구 중 실제로 겪음).
#
# Colab에서 GPU 런타임으로 실행 (런타임 -> 런타임 유형 변경 -> T4 GPU) — 중간에
# 런타임이 바뀌면(재시작되면) 이 파일이 만든 로컬 임시 파일도 같이 날아가니, 반드시
# 맨 처음부터 GPU 런타임으로 시작할 것.
#
# 대상 건수가 embed_chunks.py의 12만 건 배치와는 규모가 다르게 적을 것으로
# 예상되어(수백~수천 건 수준) 체크포인트/재개 인프라는 일부러 생략함 —
# 중간에 실패하면 그냥 처음부터 재실행.
# ------------------------------------------------------------------

# !pip install -q FlagEmbedding psycopg2-binary pgvector

import json
import os

import numpy as np
import psycopg2
from FlagEmbedding import BGEM3FlagModel
from pgvector.psycopg2 import register_vector

INPUT_PATH = "reembed_input.jsonl"  # fix_text_corruption.py의 export_reembed_input() 기본 저장 위치와 일치시킴
BATCH_SIZE = 64
MAX_LENGTH = 1024  # 청킹 시 max_length와 반드시 일치해야 함 (embed_chunks.py와 동일 값)

# ------------------------------------------------------------------
# 1) 입력 로드
# ------------------------------------------------------------------
chunk_ids, texts = [], []
with open(INPUT_PATH, "r", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        chunk_ids.append(rec["chunk_id"])
        texts.append(rec["text"])

total = len(texts)
print(f"재임베딩 대상: {total}건")

if total == 0:
    raise SystemExit("재임베딩 대상 없음 (reembed_input_2.jsonl이 비어있음) — 반영할 것이 없어 종료합니다.")

# ------------------------------------------------------------------
# 2) BGE-m3로 재임베딩
# ------------------------------------------------------------------
model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)

all_embeddings = []
for i in range(0, total, BATCH_SIZE):
    batch = texts[i:i + BATCH_SIZE]
    output = model.encode(
        batch,
        batch_size=BATCH_SIZE,
        max_length=MAX_LENGTH,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    all_embeddings.extend(output["dense_vecs"])
    print(f"  임베딩 진행: {min(i + BATCH_SIZE, total)}/{total}")

assert len(all_embeddings) == total, f"개수 불일치: emb={len(all_embeddings)}, total={total}"

# embed_chunks.py로 만든 기존 벡터(embeddings_v2/embeddings.npy)가 float16로
# 저장돼 있었음(6차 실측 검증) — 새로 만드는 벡터도 같은 정밀도로 맞춰 일관성 유지
vectors = np.array(all_embeddings, dtype=np.float16)

# 가벼운 안전장치: norm이 1.0 근처인지 확인 (6차 때 실측 검증한 것과 같은 체크 —
# "벡터 크기(norm) 평균/표준편차: 0.9999997 / 0.00017351884" 결과와 비슷해야 정상)
norms = np.linalg.norm(vectors.astype(np.float32), axis=1)
print(f"벡터 norm 평균/표준편차: {norms.mean():.6f} / {norms.std():.6f}")
if abs(norms.mean() - 1.0) > 0.01:
    raise SystemExit("벡터 norm이 1.0에서 크게 벗어남 — DB 반영 전에 원인 확인 필요")

# ------------------------------------------------------------------
# 3) chunks.embedding UPDATE
# ------------------------------------------------------------------
# os.environ에 이미 값이 있으면 그걸 우선 씀(예: 노트북 앞부분에서
# os.environ["DATABASE_URL"] = userdata.get("DATABASE_URL")로 미리 세팅해둔 경우) —
# userdata.get()을 여기서 또 부르면 커널 연결이 끊긴 상태일 때 실패할 수 있어서(위 경고 참고),
# 가능하면 os.environ 값을 재사용해 그 위험을 줄임.
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
register_vector(conn)  # numpy 배열을 pgvector 타입으로 직접 바인딩 가능하게 함

try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        rows = list(zip(vectors, chunk_ids))  # (embedding, id) 순서 -> UPDATE ... SET embedding=%s WHERE id=%s
        for i in range(0, len(rows), 500):
            batch = rows[i:i + 500]
            cur.executemany("UPDATE chunks SET embedding = %s WHERE id = %s", batch)
            conn.commit()
            print(f"  DB 반영: {min(i + 500, len(rows))}/{len(rows)}")

    # 반영 확인: 방금 업데이트한 것 중 1건을 다시 읽어서 norm 재확인
    with conn.cursor() as cur:
        cur.execute("SELECT embedding FROM chunks WHERE id = %s", (chunk_ids[0],))
        sample = cur.fetchone()[0]
        print(f"반영 확인(샘플 1건) norm: {np.linalg.norm(np.array(sample)):.6f}")
finally:
    conn.close()

print(f"완료 — {total}건 재임베딩 + chunks.embedding 반영 끝")
print('다음: 라이브 DB에서 "폭력" 검색으로 최종 확인 (STATUS.md 3번 단계)')
