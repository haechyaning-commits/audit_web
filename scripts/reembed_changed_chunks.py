# ------------------------------------------------------------------
# 변경된 chunk 재임베딩 + DB 반영 스크립트 (체크포인트 지원)
# ------------------------------------------------------------------
# fix_text_corruption.py 실행 후 같은 디렉터리에 생긴 reembed_input.jsonl
# (바뀐 chunk의 chunk_id + 수정된 text)을 입력으로 받아:
#   1) BGE-m3(GPU)로 재임베딩
#   2) chunks.embedding UPDATE
# 텍스트만 고치고 벡터를 그대로 두면 검색은 여전히 옛날(오염된) 텍스트 기준
# 벡터로 동작하므로 반드시 필요한 단계.
#
# **중요: 반드시 Colab 노트북 셀에 이 파일 내용을 그대로 붙여넣어서 실행할 것.**
# `!python scripts/reembed_changed_chunks.py`처럼 서브프로세스로 돌리면 안 됨 —
# google.colab.userdata가 Colab 프론트엔드(커널)와 통신해야 하는데 서브프로세스에서는
# 그 연결이 없어서 실패함(2026-08-11 데이터 복구 중 이 문제로 두 번 크래시).
#
# Colab에서 GPU 런타임으로 실행 (런타임 -> 런타임 유형 변경 -> T4 GPU).
#
# **체크포인트(2026-08-11 추가)**: 배치마다 계산된 벡터를 CHECKPOINT_PATH(Google Drive)에
# 즉시 append 저장함. 중간에 끊겨도(런타임 초기화, 브라우저 종료 등) 재실행하면 이미 계산된
# 만큼은 건너뛰고 남은 것부터 이어서 함 — 몇십 분짜리 GPU 연산을 한 번 더 통째로 날리는
# 사고를 막기 위함. 체크포인트가 로컬(/content)이 아니라 Drive에 있는 이유: 런타임이 완전히
# 새로 배정되면 /content는 통째로 비워지지만 Drive는 그대로 남음.
# ------------------------------------------------------------------

# !pip install -q FlagEmbedding psycopg2-binary pgvector

import json
import os

import numpy as np
import psycopg2
from FlagEmbedding import BGEM3FlagModel
from pgvector.psycopg2 import register_vector

# fix_text_corruption.py의 export_reembed_input() 기본 저장 위치와 일치시킴
# (2026-08-12: 로컬 상대경로 대신 Drive 고정 경로로 변경 — 이유는 fix_text_corruption.py의
# _default_reembed_input_path() 주석 참고. 예전 "reembed_input_2.jsonl 안 맞음" 같은
# 스크립트 간 네이밍/경로 불일치 문제도 이걸로 같이 해소됨.)
INPUT_PATH = "/content/drive/MyDrive/audit_project/reembed_input.jsonl"
CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/reembed_checkpoint.jsonl"
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
    raise SystemExit("재임베딩 대상 없음 (reembed_input.jsonl이 비어있음) — 반영할 것이 없어 종료합니다.")

# ------------------------------------------------------------------
# 2) 체크포인트 로드 — 이미 계산된 chunk_id는 건너뜀
# ------------------------------------------------------------------
os.makedirs(os.path.dirname(CHECKPOINT_PATH), exist_ok=True)
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
                # float16 정밀도(유효숫자 약 3~4자리)에 맞춰 5자리로 반올림 — 체크포인트
                # 파일 용량을 크게 줄임(전체 정밀도 그대로 저장하면 수백MB까지 커짐)
                emb_list = [round(float(x), 5) for x in vec]
                done[cid] = emb_list
                ckpt_f.write(json.dumps({"chunk_id": cid, "embedding": emb_list}) + "\n")
            ckpt_f.flush()
            os.fsync(ckpt_f.fileno())  # 디스크에 즉시 반영 — 여기서 끊겨도 이 배치까지는 안전
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
# 5) chunks.embedding UPDATE — UPDATE는 멱등이라 재실행해도 안전(같은 값 덮어씀)
# ------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")
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
        print(f"반영 확인(샘플 1건) norm: {np.linalg.norm(np.array(sample)):.6f}")
finally:
    conn.close()

print(f"완료 — {total}건 재임베딩 + chunks.embedding 반영 끝")
print("체크포인트 파일은 안 지웠음 — 확인 후 필요 없으면 직접 삭제해도 됨:")
print(f"  !rm {CHECKPOINT_PATH}")
