-- ------------------------------------------------------------------
-- DB 스키마 1단계 — 테이블만 생성 (인덱스는 나중에, schema_indexes.sql 참고)
-- ------------------------------------------------------------------
-- Supabase(또는 Railway) Postgres에서 실행. pgvector 확장 필요.
--
-- [변경 이유] 원래 schema.sql은 인덱스(특히 HNSW)까지 한 번에 다 만들어두고
-- 그 상태로 데이터를 넣었음. 그러면 96,355개 청크를 넣는 INSERT 하나하나마다
-- HNSW 인덱스를 실시간으로 갱신해야 해서 디스크를 더 많이/비효율적으로 씀
-- (Railway에서 이 방식으로 돌리다가 실제로 디스크가 꽉 차서 DB가 죽는 걸 겪음).
--
-- 데이터를 먼저 다 넣고 인덱스는 마지막에 한 번에 만들면(벌크 빌드), 인덱스
-- 구축 자체가 더 효율적이고 빠르며, 로딩 도중 디스크 사용량 피크도 낮아짐.
--
-- 실행 순서:
--   1) 이 파일(schema_tables.sql) 실행 — 테이블만 생성
--   2) load_to_postgres.py 실행 — 데이터 적재
--   3) schema_indexes.sql 실행 — 인덱스 생성 (여기서 시간이 좀 걸릴 수 있음)
-- ------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;

-- documents: 상세페이지/카드 메타정보 (architecture.md §8.3)
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,   -- build_final_dataset.py가 부여한 document_id
    institution     TEXT,
    year            INT,
    audit_type      TEXT,               -- 감사종류(복무감사/회계감사/특정감사 등) — 원본 파일명
                                         -- "기관이름_연도_감사종류" 패턴에서 파싱(2026-08-12 추가,
                                         -- scripts/textparse.py의 parse_source_file 참고)
    source_file     TEXT,               -- 적재 당시 원본 파일 상대경로("data_repo/자체감사파일1/...") —
                                         -- backend/app/textutils.py의 build_source_url()이 이 값에서
                                         -- "data_repo/" 접두어만 떼서 haechyaning-commits/data 리포의
                                         -- raw 파일 URL로 변환함(원본 PDF/HWP 링크, 2026-08-13 추가)
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

-- chunks: 검색용 (architecture.md §3.2) — 인덱스는 아직 안 만듦, schema_indexes.sql에서
CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,   -- 임베딩 스크립트의 chunk_id 그대로 사용
    document_id     TEXT NOT NULL REFERENCES documents(id),
    text            TEXT NOT NULL,      -- 청크 원문 (검색 결과 대표 청크 재조회용)
    embedding       vector(1024),       -- BGE-m3 차원 — 실제 embeddings.npy shape[1]과 다르면 수정
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- error_reports: 상세페이지 "오류 신고" 모달 제출값 (2026-08-26) — documents/chunks와 달리
-- 백엔드가 시작할 때마다 CREATE TABLE IF NOT EXISTS로 알아서 만듦(backend/app/repository.py
-- ensure_error_reports_table 참고). 이 파일에는 로컬 테스트/문서화 목적으로만 같이 적어둠.
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
