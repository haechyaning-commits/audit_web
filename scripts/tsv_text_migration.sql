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
--    말이 되는지 확인 → DRY_RUN=False로 재실행해서 chunks.tsv_text 전체(92,136건,
--    2026-08-27 코랩 실행 기준) 백필.
-- 3) 백필이 끝났으면 STEP 2 실행 — tsv 컬럼/트리거/배치 UPDATE로 tsv_text 기준
--    색인을 만들고 GIN 인덱스 생성.
-- 4) STEP 2까지 끝난 뒤에만 backend .env의 TOKENIZER_ENABLED=true로 재배포.
--    (순서 거꾸로 하면: TOKENIZER_ENABLED를 먼저 켜면 쿼리만 토큰화되고 색인은 아직
--    원문 기준이라 매칭이 어긋남 — main.py/tokenizer.py 주석 참고)
--
-- **2026-08-27 실측 — STEP 2를 GENERATED ALWAYS AS로 시도했다가 실패, 트리거
-- 방식으로 교체함**: 원래 STEP 2는 `ALTER TABLE chunks DROP COLUMN tsv; ALTER TABLE
-- chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (...) STORED;`로 92,136건을
-- 한 번에 재작성하는 방식이었는데, Railway 컨테이너에서
-- `DiskFull: could not resize shared memory segment ... No space left on device`
-- 에러로 두 번 다 실패함(병렬 워커를 꺼도(`max_parallel_workers_per_gather = 0`)
-- 동일 — 실제 디스크 공간이 아니라 컨테이너의 `/dev/shm` 한도로 추정, 관리형 DB라
-- 우리가 그 한도 자체를 늘릴 방법이 없음). 그래서 "한 번에 전체 재작성" 대신 이미
-- 검증된 배치 패턴(backfill_tsv_text.py와 동일하게 2,000건씩)으로 우회함 — 아래 STEP 2가
-- 그 결과 반영된 버전. `tsv`가 더는 GENERATED 컬럼이 아니라 일반 컬럼 + 트리거 조합이라
-- 최종 동작(항상 tsv_text 기준으로 자동 갱신됨)은 동일함.


-- ============================================================
-- STEP 1 — 새 컬럼 추가 (nullable, 즉시 실행 가능, 기존 서비스 영향 없음)
-- ============================================================
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv_text text;


-- ============================================================
-- (여기서 scripts/backfill_tsv_text.py 실행 — STEP 2 전에 tsv_text가 다 채워져 있어야 함)
-- ============================================================


-- ============================================================
-- STEP 2 — tsv 컬럼 + 트리거로 tsv_text 기준 색인 (2026-08-27 2차, 배치 우회 버전)
-- ============================================================
-- 2-1) 기존 GIN 인덱스/generated 컬럼 제거 (이미 DROP된 상태일 수도 있음 — IF EXISTS)
DROP INDEX IF EXISTS chunks_tsv_gin_idx;
ALTER TABLE chunks DROP COLUMN IF EXISTS tsv;

-- 2-2) 일반(비생성) tsvector 컬럼으로 추가 — 즉시 끝남(테이블 전체 재작성 없음)
ALTER TABLE chunks ADD COLUMN tsv tsvector;

-- 2-3) 트리거로 "항상 tsv_text(없으면 text) 기준으로 자동 갱신" 보장
--      — GENERATED ALWAYS AS와 최종 동작은 동일, 대신 한 번에 재작성하지 않고
--      INSERT/UPDATE될 때마다 그 행 하나만 계산하므로 위 DiskFull 문제를 피함.
CREATE OR REPLACE FUNCTION chunks_tsv_trigger() RETURNS trigger AS $$
BEGIN
  NEW.tsv := to_tsvector('simple', COALESCE(NEW.tsv_text, NEW.text));
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER tsv_update_trigger BEFORE INSERT OR UPDATE
ON chunks FOR EACH ROW EXECUTE FUNCTION chunks_tsv_trigger();

-- 2-4) 기존 92,136건은 배치 UPDATE로 채움 (2,000건씩, Python으로 실행 —
--      scripts/backfill_tsv_text.py와 동일한 패턴, SQL 클라이언트에서 한 문장으로는
--      못 함). 아래는 그 배치 루프가 실제로 실행하는 SQL 한 건의 형태(참고용):
--        UPDATE chunks SET tsv = to_tsvector('simple', COALESCE(tsv_text, text))
--        WHERE id = ANY(:batch_ids);

-- 2-5) 배치 백필이 다 끝난 뒤 GIN 인덱스 생성. CONCURRENTLY는 트랜잭션 블록 안에서
--      못 씀 — autocommit 상태에서 이 줄만 따로 실행할 것.
--      max_parallel_maintenance_workers=0으로 혹시 모를 같은 DiskFull 재현을 예방.
SET max_parallel_maintenance_workers = 0;
CREATE INDEX CONCURRENTLY IF NOT EXISTS chunks_tsv_gin_idx ON chunks USING GIN (tsv);


-- ============================================================
-- 확인 쿼리 (STEP 2 이후 실행해서 실제로 개선됐는지 눈으로 확인)
-- ============================================================
-- 예: "예산낭비가"가 원문에 포함된 청크를 "예산 낭비"(공백으로 띄어 쓴 검색어)로 찾아지는지
-- SELECT id, left(text, 80) FROM chunks
-- WHERE tsv @@ plainto_tsquery('simple', '예산 낭비') LIMIT 5;
