-- ------------------------------------------------------------------
-- DB 스키마 — documents / chunks (전체를 한 번에, 테이블+인덱스 같이)
-- ------------------------------------------------------------------
-- Postgres에서 실행. pgvector 확장 필요.
-- 실행 순서: 이 파일 전체를 psql 또는 SQL 콘솔에 붙여넣기
--
-- [주의] 96,355건 같은 대량 청크를 로딩할 때는 이 파일 대신
-- schema_tables.sql(테이블만) -> load_to_postgres.py(데이터 적재) ->
-- schema_indexes.sql(인덱스는 맨 마지막에) 순서로 나눠서 실행하는 걸 권장함 —
-- 인덱스를 먼저 만들어두고 그 상태로 대량 INSERT하면 디스크 사용량이 커져서
-- 저장공간이 빠듯한 환경(Supabase/Railway 무료·최소 티어)에서 문제가 될 수 있음
-- (실제로 이 순서 그대로 하다가 디스크 부족으로 DB가 죽은 사례 있음).
-- 이 파일은 로컬 테스트나 소량 데이터로 빠르게 스키마만 확인할 때 쓰면 됨.
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
    summary_failed  BOOLEAN NOT NULL DEFAULT FALSE,  -- 온디맨드 생성 1차+재시도 모두 4줄 전부
                                                      -- 미기재로 나온 경우 TRUE (architecture.md §4.6).
                                                      -- TRUE면 상세 API가 재생성 시도 없이 바로
                                                      -- 원문만 반환 — 실패를 캐싱해서 매번 재시도하며
                                                      -- API 비용 나가는 것 방지
    summary_freeform        TEXT,             -- 자유형 4줄 요약(지적/원인/조치/결과 틀 없이,
                                               -- 줄바꿈으로 구분된 4줄) — 구조화 요약과 별도 프롬프트로 생성
    summary_freeform_failed BOOLEAN NOT NULL DEFAULT FALSE,  -- summary_failed와 동일한 이유로
                                                              -- 자유형 요약에도 별도로 실패 캐싱
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

-- error_reports: 상세페이지 "오류 신고" 모달 제출값 (2026-08-26) — 백엔드가 시작할 때마다
-- CREATE TABLE IF NOT EXISTS로 알아서 만듦(repository.py ensure_error_reports_table 참고).
CREATE TABLE IF NOT EXISTS error_reports (
    id          SERIAL PRIMARY KEY,
    document_id TEXT,
    institution TEXT,
    year        INT,
    audit_type  TEXT,
    message     TEXT NOT NULL,
    page_url    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
