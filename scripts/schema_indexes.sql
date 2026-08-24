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

-- 2026-08-24: 기관/연도 검색 필터(FR5) 추가 — repository.py의 filtered_docs CTE가
-- 매 검색마다 documents.institution/year로 걸러서 vector_search/text_search의
-- document_id IN 서브쿼리 조건으로 씀. 문서 수(6.8만 건 규모)면 인덱스 없어도
-- 정확성엔 문제없지만(로컬 pgvector 테스트로 이미 검증됨), 매 검색마다 도는
-- 쿼리라 인덱스가 있는 게 안전 — 가볍고 즉시 끝나는 B-tree라 다른 인덱스들처럼
-- 데이터 적재 후에 만들 필요 없이 아무 때나 실행해도 됨(기존 운영 DB에도 바로 적용 가능).
CREATE INDEX IF NOT EXISTS documents_institution_idx
    ON documents (institution);
CREATE INDEX IF NOT EXISTS documents_year_idx
    ON documents (year);
