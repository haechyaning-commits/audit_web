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


def _clean_text(s):
    """PDF 원문 추출 과정에서 가끔 NUL(0x00) 바이트가 섞여 들어옴 — Postgres text 컬럼은
    NUL을 아예 허용하지 않아서(psycopg2가 ValueError로 거부) 있으면 통째로 제거.
    institution/raw_text/parsing_quality/chunk text 전부에 방어적으로 적용."""
    if isinstance(s, str) and "\x00" in s:
        s = s.replace("\x00", "")
    return s


def _parse_year(raw_year) -> int | None:
    """year가 documents_final.jsonl에 문자열로 들어있는 경우가 대부분이라(예: "2019")
    명시적으로 int 변환. psycopg2/Postgres가 숫자 문자열은 알아서 캐스팅해주긴 하지만,
    혹시 지저분한 값("2020년", "" 등)이 하나라도 섞여 있으면 그 배치 전체가 예외로
    죽는 걸 막기 위해 여기서 방어적으로 처리 — 실패하면 None으로 두고 경고만 출력."""
    if raw_year is None or raw_year == "":
        return None
    try:
        return int(raw_year)
    except (ValueError, TypeError):
        print(f"  [경고] year 값 파싱 실패, NULL로 대체: {raw_year!r}")
        return None


def load_documents(cur, conn, path: str, batch_size: int = 5000) -> int:
    docs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            docs.append((
                d["id"],
                _clean_text(d.get("institution")),
                _parse_year(d.get("year")),
                _clean_text(d.get("raw_text")),
                _clean_text(d.get("parsing_quality")),
            ))

    total = len(docs)
    # 배치별로 나눠서 중간중간 commit -> Railway Public Network 연결이 도중에 끊겨도
    # 이미 커밋된 배치는 남아있음 (전체 하나의 트랜잭션으로 묶으면 끊기는 순간 전부 롤백됨).
    # ON CONFLICT DO NOTHING이라 재실행해도 이미 들어간 행은 건드리지 않고 이어서 진행됨.
    for i in range(0, total, batch_size):
        batch = docs[i:i + batch_size]
        execute_values(
            cur,
            "INSERT INTO documents (id, institution, year, raw_text, parsing_quality) "
            "VALUES %s ON CONFLICT (id) DO NOTHING",
            batch,
        )
        conn.commit()
        print(f"  documents 진행: {min(i + batch_size, total)}/{total}")
    return total


def load_chunk_embeddings(chunk_ids_path: str, embeddings_path: str) -> dict:
    chunk_ids = []
    with open(chunk_ids_path, encoding="utf-8") as f:
        for line in f:
            chunk_ids.append(json.loads(line)["chunk_id"])
    embeddings = np.load(embeddings_path)
    return dict(zip(chunk_ids, embeddings))


def load_chunks(cur, conn, path: str, chunk_id_to_vec: dict, batch_size: int = 5000) -> tuple[int, int]:
    rows, skipped = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            vec = chunk_id_to_vec.get(c["id"])
            if vec is None:
                skipped += 1
                continue
            rows.append((c["id"], c["document_id"], _clean_text(c["text"]), vec))

    total = len(rows)
    # documents와 동일한 이유로 배치 커밋 — 여기가 특히 중요함: 벡터(1024차원)까지
    # 같이 실어 나르는 INSERT라 documents보다 훨씬 오래 걸리고, 끊길 위험도 더 큼
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        execute_values(
            cur,
            "INSERT INTO chunks (id, document_id, text, embedding) VALUES %s ON CONFLICT (id) DO NOTHING",
            batch,
        )
        conn.commit()
        print(f"  chunks 진행: {min(i + batch_size, total)}/{total}")
    return total, skipped


if __name__ == "__main__":
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL 환경변수를 설정하세요 (Railway Postgres 서비스 -> Connect 탭)")

    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    cur = conn.cursor()

    n_docs = load_documents(cur, conn, DOCUMENTS_PATH)
    print(f"documents 적재: {n_docs}건")

    chunk_id_to_vec = load_chunk_embeddings(CHUNK_IDS_PATH, EMBEDDINGS_PATH)
    n_chunks, n_skipped = load_chunks(cur, conn, CHUNKS_PATH, chunk_id_to_vec)
    print(f"chunks 적재: {n_chunks}건 (임베딩 없어서 스킵: {n_skipped}건)")

    cur.close()
    conn.close()
