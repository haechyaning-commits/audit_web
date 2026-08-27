-- ------------------------------------------------------------------
-- chunks 테이블에 형태소 토큰화 컬럼 추가 (architecture.md §3.6, 2026-08-27 코드 준비)
-- ------------------------------------------------------------------
-- 지금 chunks.tsv는 GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED 라서
-- 원문(text) 기준으로 색인돼 있음 — "예산낭비가"처럼 조사가 붙어 있으면 "예산 낭비"로
-- 검색해도 매칭되지 않을 수 있음(실측 확인, tokenizer.py 모듈 docstring 참고).
--
-- **실행 순서 — 반드시 이 순서대로, 한 단계씩 확인하며 실행할 것**
-- (backfill_source_file.py류 마이그레이션과 같은 이유: 순서를 건너뛰면 배포된 백엔드가
-- 없는 컬럼을 SELECT하다가 500을 내거나, 검색이 한동안 0건만 반환할 수 있음)
--
-- 1) 이 파일의 STEP 1만 먼저 실행 — 기존 서비스에 영향 없음(tsv는 여전히 text 기준).
-- 2) scripts/backfill_tsv_text.py를 DRY_RUN=True로 먼저 돌려서 토큰화 결과 샘플이
--    말이 되는지 확인 → DRY_RUN=False로 재실행해서 chunks.tsv_text 전체(96,355건
--    안팎) 백필. 몇 분~몇십 분 걸릴 수 있음(모델 로딩 + 텍스트 96,355건 형태소 분석).
-- 3) 백필이 끝났으면 STEP 2 실행 — tsv를 tsv_text 기준 생성 컬럼으로 교체하고 GIN
--    인덱스 재생성. **이 단계 동안 잠깐 tsv 컬럼이 없어지는 순간이 있어 그 사이
--    키워드 검색(text_search leg)은 매치가 0건이 됨(벡터 검색은 영향 없음)** —
--    트래픽이 적은 시간대에 실행하거나, 몇 초~몇 분 내 완료되는 걸 감안할 것
--    (96,355건 규모면 STATUS.md 8/7 실측 기준 GIN 인덱스 생성 자체가 몇 분 걸림).
-- 4) STEP 2까지 끝난 뒤에만 backend .env의 TOKENIZER_ENABLED=true로 재배포.
--    (순서 거꾸로 하면: TOKENIZER_ENABLED를 먼저 켜면 쿼리만 토큰화되고 색인은 아직
--    원문 기준이라 매칭이 어긋남 — main.py/tokenizer.py 주석 참고)


-- ============================================================
-- STEP 1 — 새 컬럼 추가 (nullable, 즉시 실행 가능, 기존 서비스 영향 없음)
-- ============================================================
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv_text text;


-- ============================================================
-- (여기서 scripts/backfill_tsv_text.py 실행 — STEP 2 전에 tsv_text가 다 채워져 있어야 함)
-- ============================================================


-- ============================================================
-- STEP 2 — tsv를 tsv_text 기준 생성 컬럼으로 교체 + GIN 인덱스 재생성
-- ============================================================
-- 생성 컬럼의 생성식(expression)은 Postgres에서 직접 ALTER 불가 — DROP 후 재생성만 가능.
DROP INDEX IF EXISTS chunks_tsv_gin_idx;
ALTER TABLE chunks DROP COLUMN tsv;
ALTER TABLE chunks ADD COLUMN tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', COALESCE(tsv_text, text))) STORED;
-- COALESCE(tsv_text, text): 만에 하나 백필 누락 행(tsv_text가 NULL인 채로 남은 청크)이
-- 있어도 원문 기준으로라도 색인되게 하는 안전망 — 백필 스크립트가 실패한 행을 로그로
-- 남기지만(backfill_tsv_text.py 참고), 그 행이 아예 검색에서 빠지는 것보단 나음.

-- 96,355건 규모 GIN 인덱스 재생성은 몇 분 걸릴 수 있음(2026-08-07 STATUS.md 실측 참고).
-- CONCURRENTLY로 만들면 이 인덱스 생성 중에도 다른 쿼리가 안 막히지만, CONCURRENTLY는
-- 트랜잭션 블록 안에서 못 씀 — Railway Query 탭에서 이 줄만 따로(자동 커밋 상태로) 실행할 것.
CREATE INDEX CONCURRENTLY IF NOT EXISTS chunks_tsv_gin_idx ON chunks USING GIN (tsv);


-- ============================================================
-- 확인 쿼리 (STEP 2 이후 실행해서 실제로 개선됐는지 눈으로 확인)
-- ============================================================
-- 예: "예산낭비가"가 원문에 포함된 청크를 "예산 낭비"(공백으로 띄어 쓴 검색어)로 찾아지는지
-- SELECT id, left(text, 80) FROM chunks
-- WHERE tsv @@ plainto_tsquery('simple', '예산 낭비') LIMIT 5;
