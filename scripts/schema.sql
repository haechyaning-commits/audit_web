-- ------------------------------------------------------------------
-- DB 스키마 — documents / chunks
-- ------------------------------------------------------------------
-- Railway Postgres에서 실행. pgvector 확장 필요.
-- 실행 순서: 이 파일 전체를 psql 또는 Railway Query 콘솔에 붙여넣기
-- ------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;

-- documents: 상세페이지/카드 메타정보 (architecture.md §8.3)
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,   -- build_final_dataset.py가 부여한 document_id
    institution     TEXT,
    year            INT,
    raw_text        TEXT NOT NULL,      -- 원문 전체 ("원문 펼쳐보기"용)
    parsing_quality TEXT NOT NULL CHECK (parsing_quality IN ('standard', 'partial', 'fallback')),
    summary_point   TEXT,               -- 4줄 요약 1번째 줄: 지적사항
    summary_cause   TEXT,               -- 2번째 줄: 원인/경위
    summary_action  TEXT,               -- 3번째 줄: 조치사항
    summary_result  TEXT,               -- 4번째 줄: 처리결과 ("처리결과 미기재" 포함)
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- chunks: 검색용 (architecture.md §3.2)
CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,   -- 임베딩 스크립트의 chunk_id 그대로 사용
    document_id     TEXT NOT NULL REFERENCES documents(id),
    text            TEXT NOT NULL,      -- 청크 원문 (검색 결과 대표 청크 재조회용)
    embedding       vector(1024),       -- BGE-m3 차원 — 실제 embeddings.npy shape[1]과 다르면 수정
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- 인덱스 (architecture.md §5.1)
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx
    ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_document_id_idx
    ON chunks (document_id);
