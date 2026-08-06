-- ------------------------------------------------------------------
-- DB 스키마 2단계 — 인덱스 생성 (schema_tables.sql + load_to_postgres.py 이후 실행)
-- ------------------------------------------------------------------
-- 데이터가 다 들어간 뒤에 실행하는 것 — 순서 중요함 (schema_tables.sql 주석 참고).
-- chunks_document_id_idx는 가벼워서 금방 끝나지만, chunks_embedding_hnsw_idx(HNSW)와
-- chunks_tsv_gin_idx(GIN)는 96,355건 규모면 몇 분 정도 걸릴 수 있음 — 정상입니다.
-- ------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx
    ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_document_id_idx
    ON chunks (document_id);
