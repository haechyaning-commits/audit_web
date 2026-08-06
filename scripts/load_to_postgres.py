# ------------------------------------------------------------------
# pgvector 적재 스크립트
# ------------------------------------------------------------------
# build_final_dataset.py의 출력(documents_final.jsonl, chunks_final.jsonl)과
# 임베딩 파일(embeddings.npy, chunk_ids.jsonl)을 합쳐서 Railway Postgres에 적재.
#
# 사전 준비:
#   1) scripts/schema.sql을 Railway Postgres에 먼저 실행 (테이블/인덱스 생성)
#   2) pip install psycopg2-binary pgvector
#   3) DATABASE_URL 환경변수 설정 (Railway 서비스 -> Connect 탭에서 복사)
#
# 1만 건대 스냅샷으로 먼저 테스트하려면 CHUNK_IDS_PATH/EMBEDDINGS_PATH를
# 스냅샷 파일 경로로 바꿔서 실행 — 스냅샷에 없는 chunk_id는 자동 스킵됨
# (에러 아님, 정상 동작).
# ------------------------------------------------------------------

import json
import os

import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector

BASE = "/content/drive/MyDrive/audit_project/"
DOCUMENTS_PATH = BASE + "documents_final.jsonl"
CHUNKS_PATH = BASE + "chunks_final.jsonl"

# 전체 임베딩 or 스냅샷 중 선택 — 스냅샷 테스트 시 아래 두 줄을 스냅샷 경로로 교체
CHUNK_IDS_PATH = BASE + "embeddings_v2/chunk_ids.jsonl"
EMBEDDINGS_PATH = BASE + "embeddings_v2/embeddings.npy"

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def load_documents(cur, path: str) -> int:
    docs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            docs.append((d["id"], d.get("institution"), d.get("year"), d.get("raw_text"), d.get("parsing_quality")))

    execute_values(
        cur,
        "INSERT INTO documents (id, institution, year, raw_text, parsing_quality) "
        "VALUES %s ON CONFLICT (id) DO NOTHING",
        docs,
    )
    return len(docs)


def load_chunk_embeddings(chunk_ids_path: str, embeddings_path: str) -> dict:
    chunk_ids = []
    with open(chunk_ids_path, encoding="utf-8") as f:
        for line in f:
            chunk_ids.append(json.loads(line)["chunk_id"])
    embeddings = np.load(embeddings_path)
    return dict(zip(chunk_ids, embeddings))


def load_chunks(cur, path: str, chunk_id_to_vec: dict) -> tuple[int, int]:
    rows, skipped = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            vec = chunk_id_to_vec.get(c["id"])
            if vec is None:
                skipped += 1
                continue
            rows.append((c["id"], c["document_id"], c["text"], vec))

    execute_values(
        cur,
        "INSERT INTO chunks (id, document_id, text, embedding) VALUES %s ON CONFLICT (id) DO NOTHING",
        rows,
    )
    return len(rows), skipped


if __name__ == "__main__":
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL 환경변수를 설정하세요 (Railway Postgres 서비스 -> Connect 탭)")

    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    cur = conn.cursor()

    n_docs = load_documents(cur, DOCUMENTS_PATH)
    conn.commit()
    print(f"documents 적재: {n_docs}건")

    chunk_id_to_vec = load_chunk_embeddings(CHUNK_IDS_PATH, EMBEDDINGS_PATH)
    n_chunks, n_skipped = load_chunks(cur, CHUNKS_PATH, chunk_id_to_vec)
    conn.commit()
    print(f"chunks 적재: {n_chunks}건 (임베딩 없어서 스킵: {n_skipped}건)")

    cur.close()
    conn.close()
