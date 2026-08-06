# ------------------------------------------------------------------
# BGE-m3 청크 임베딩 스크립트 (체크포인트/재시작 지원)
# ------------------------------------------------------------------
# Colab에서 GPU 런타임으로 실행 (런타임 -> 런타임 유형 변경 -> T4 GPU).
# 노트북 셀에 이 파일 내용을 그대로 붙여넣어 실행하면 됨.
#
# 입력: embed_ready_v2.jsonl (chunk_id, text)
# 출력: embeddings_v2/embeddings.npy, embeddings_v2/chunk_ids.jsonl
#       (두 파일은 인덱스 순서로 서로 짝이 맞아야 함 —
#        load_to_postgres.py가 zip(chunk_ids, embeddings)로 조인해서 씀)
#
# 이어하기(resume): progress 파일을 따로 두지 않고, embeddings.npy에
# 실제로 저장된 개수(start_idx)를 진실의 원천으로 사용함. 체크포인트는
# 임시 파일에 먼저 쓰고 os.replace()로 교체하는 원자적 쓰기 패턴이라,
# 저장 도중 런타임이 끊겨도 기존 체크포인트 파일 자체는 손상되지 않음.
#
# [버그 수정 이력 — 2026-08-06]
#   이전 버전은 임시 파일명을 EMBEDDINGS_PATH + ".tmp" (예:
#   "embeddings.npy.tmp")로 만들었는데, np.save()는 파일명이 .npy로
#   끝나지 않으면 자동으로 .npy를 뒤에 붙이는 동작이 있어서 실제로는
#   "embeddings.npy.tmp.npy"라는 파일이 저장됐음. 그 직후
#   os.replace(tmp_path, EMBEDDINGS_PATH)는 존재하지도 않는
#   "embeddings.npy.tmp"를 찾다가 FileNotFoundError로 죽었음 —
#   체크포인트를 저장하려는 시도마다 100% 재현되는 버그.
#   아래에서는 임시 파일명 자체를 ".npy"로 끝나게 바꿔서 numpy가
#   확장자를 몰래 건드릴 여지를 없앴음 (로컬에서 재현 후 수정 확인).
# ------------------------------------------------------------------

# !pip install -q FlagEmbedding
# from google.colab import drive
# drive.mount('/content/drive')

from FlagEmbedding import BGEM3FlagModel
import json
import numpy as np
import os

# ------------------------------------------------------------------
# 1) 설정
# ------------------------------------------------------------------
INPUT_PATH = "/content/drive/MyDrive/audit_project/embed_ready_v2.jsonl"
CHECKPOINT_DIR = "/content/drive/MyDrive/audit_project/embeddings_v2"
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

BATCH_SIZE = 64
MAX_LENGTH = 1024   # 청킹 시 최대 길이 설정과 맞는지 반드시 확인!
CHECKPOINT_EVERY_N_BATCHES = 100   # 6,400건마다 저장

EMBEDDINGS_PATH = os.path.join(CHECKPOINT_DIR, "embeddings.npy")
IDS_PATH = os.path.join(CHECKPOINT_DIR, "chunk_ids.jsonl")

# 체크포인트 임시 파일 — 반드시 .npy로 끝나야 함 (numpy가 확장자를
# 자동으로 붙이는 걸 이용하는 게 아니라, 아예 처음부터 .npy로 끝나게
# 만들어서 "생성된 파일명"과 "os.replace가 찾는 이름"을 일치시킴)
EMBEDDINGS_TMP_PATH = EMBEDDINGS_PATH.replace(".npy", ".tmp.npy")
IDS_TMP_PATH = IDS_PATH + ".tmp"  # .jsonl은 open()으로 직접 쓰므로 확장자 문제 없음

# ------------------------------------------------------------------
# 2) 전체 청크 로드 (텍스트 + chunk_id만 메모리에 올림 — 나머지 메타는 pgvector 적재 때 원본에서 다시 조인)
# ------------------------------------------------------------------
chunk_ids = []
texts = []
with open(INPUT_PATH, "r", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        chunk_ids.append(rec["chunk_id"])
        texts.append(rec["text"])

total = len(texts)
print(f"전체 청크 수: {total}")

# ------------------------------------------------------------------
# 3) 이어하기(resume) 체크
#    — progress.txt를 따로 두지 않고, embeddings.npy에 실제로 저장된
#      개수를 진실의 원천으로 사용한다 (저장 순서 레이스 컨디션 방지)
# ------------------------------------------------------------------
all_embeddings = []
start_idx = 0
if os.path.exists(EMBEDDINGS_PATH):
    all_embeddings = list(np.load(EMBEDDINGS_PATH))
    start_idx = len(all_embeddings)
    print(f"이전 진행상황 발견 — {start_idx}건부터 이어서 진행합니다.")

# 이전 실행이 체크포인트 저장 도중 죽어서 임시 파일이 남아있을 수 있음
# (특히 위 버그로 인해 "embeddings.npy.tmp.npy" 같은 파일이 남아있을 수
# 있음) — 이번 실행 결과와 섞이지 않도록 시작 전에 정리
for stray in (EMBEDDINGS_TMP_PATH, IDS_TMP_PATH, EMBEDDINGS_PATH + ".tmp.npy"):
    if os.path.exists(stray):
        print(f"이전 실행의 임시 파일 발견, 삭제: {stray}")
        os.remove(stray)

# ------------------------------------------------------------------
# 4) 모델 로드
# ------------------------------------------------------------------
model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

# ------------------------------------------------------------------
# 5) 배치 임베딩 + 체크포인트 저장
# ------------------------------------------------------------------
n_batches_since_checkpoint = 0

for i in range(start_idx, total, BATCH_SIZE):
    batch = texts[i:i + BATCH_SIZE]
    output = model.encode(
        batch,
        batch_size=BATCH_SIZE,
        max_length=MAX_LENGTH,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    dense_vecs = output['dense_vecs']
    all_embeddings.extend(dense_vecs)

    n_batches_since_checkpoint += 1
    current_idx = min(i + BATCH_SIZE, total)

    if n_batches_since_checkpoint >= CHECKPOINT_EVERY_N_BATCHES or current_idx >= total:
        # 임시 파일에 먼저 쓰고 교체 -> 저장 도중 끊겨도 기존 체크포인트가 손상되지 않음
        # (EMBEDDINGS_TMP_PATH는 이미 .npy로 끝나므로 np.save가 파일명을
        #  건드리지 않고, os.replace가 찾는 이름과 정확히 일치함)
        np.save(EMBEDDINGS_TMP_PATH, np.array(all_embeddings))
        os.replace(EMBEDDINGS_TMP_PATH, EMBEDDINGS_PATH)

        # chunk_ids도 같은 시점(current_idx)까지 같이 저장
        # — 매번 체크포인트마다 embeddings와 짝이 맞는 상태로 갱신되어
        #   중간에 스냅샷이 필요할 때 원본 파일에서 다시 뽑을 필요가 없어짐
        with open(IDS_TMP_PATH, "w", encoding="utf-8") as f:
            for cid in chunk_ids[:current_idx]:
                f.write(json.dumps({"chunk_id": cid}, ensure_ascii=False) + "\n")
        os.replace(IDS_TMP_PATH, IDS_PATH)

        print(f"체크포인트 저장: {current_idx}/{total}건 완료 (embeddings + chunk_ids)")
        n_batches_since_checkpoint = 0

print("임베딩 완료:", len(all_embeddings), "개")

# ------------------------------------------------------------------
# 6) 개수 검증 — 하나라도 안 맞으면 pgvector 적재 시 chunk_id-벡터가
#    어긋나므로 여기서 바로 잡아낸다
#    (chunk_ids.jsonl은 위 체크포인트 루프에서 이미 최종 저장됨 — 별도 저장 불필요)
# ------------------------------------------------------------------
assert len(all_embeddings) == len(chunk_ids) == total, (
    f"개수 불일치: emb={len(all_embeddings)}, ids={len(chunk_ids)}, total={total}"
)

print("완료. chunk_ids.jsonl과 embeddings.npy의 순서가 일치합니다.")
