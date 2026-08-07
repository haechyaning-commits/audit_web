# 진행 상황 로그

> 대화창이 바뀌어도 여기부터 이어서 보면 됨. 최신 항목이 맨 위.

## 🔜 오늘 할 일 (2026-08-07 기준)

어제 막혔던 Supabase 인증 문제는 오늘 세션에서 해결됨 (아래 13차 항목 참고). 오늘 남은 순서:

1. [ ] **데이터 적재 완료 확인** — Colab에서 돌린 `load_to_postgres.py`가 documents(72,913건) +
   chunks(96,355건, 벡터 포함) 끝까지 정상 적재됐는지 로그 확인. 끊겼으면 재실행(`ON CONFLICT DO
   NOTHING`이라 안전, 이어서 진행됨)
2. [ ] **인덱스 생성** — Supabase SQL Editor에서 `scripts/schema_indexes.sql` 실행 (HNSW/GIN/btree
   3개, 96,355건 규모라 몇 분 소요 가능)
3. [ ] **1주차 체크포인트** — SQL로 직접 벡터 유사도 검색 쿼리를 날려서 비슷한 사례가 순위대로
   나오는지 확인 (`development-plan.md` 1주차 목표: "DB에 SQL 쿼리 하나 날려보면 비슷한 사례가
   순위대로 나온다")
4. [ ] **(여유 되면) 2주차 착수** — 1주차 체크포인트 통과하면 FastAPI 프로젝트 뼈대만 만들어서
   서버 켜지는지 확인까지 (development-plan.md 2주차 시작, 필수 아님)

---

## 2026-08-07 (13차 — Supabase 인증 문제 해결, 테이블 생성, 데이터 적재 착수)

### 어제(12차) 막혔던 Supabase 인증 문제 해결
- 새 비밀번호를 재설정 화면에서 뜨는 즉시 그 자리에서 복사(대괄호 placeholder 남는 문제 방지) →
  Colab Secrets에 영숫자만으로 구성된 비밀번호로 `DATABASE_URL` 저장
- Session Pooler URI(`postgresql://postgres.hrhecriwbstcsgbhxotg:...@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres`)로
  연결 테스트(`psycopg2.connect` + `SELECT 1;`) 성공 확인
- 12차에서 겪었던 `FATAL: password authentication failed for user "postgres"`는, Supabase pooler가
  에러 메시지에서 사용자명을 `postgres`로 정규화해서 보여주는 것뿐이고 실제 원인은 비밀번호
  placeholder 미교체였을 가능성이 유력했음 — 이번엔 재발 안 함

### 완료
- **Supabase SQL Editor에서 `scripts/schema_tables.sql` 실행** — `documents`, `chunks` 테이블 생성
  ("Success. No rows returned" 확인, `information_schema.tables`로 테이블 존재도 확인 가능)
- **Colab에서 `scripts/load_to_postgres.py` 실행 시작** — documents(72,913건) → chunks(96,355건,
  벡터 포함) 순서로 5,000건씩 배치 커밋 진행 중

### 다음 (오늘 할 일 섹션과 동일)
- 적재 완료 확인 → `schema_indexes.sql` 실행 → 1주차 체크포인트 SQL 검증 → (여유되면) 2주차 착수

---

## 2026-08-06 (12차 — 오늘 마무리: Supabase 연결 인증 문제로 중단)

### 오늘 세션 마지막 상태: Supabase 연결이 계속 안 됨 (다음 세션에서 이어갈 것)

11차(Supabase 이전)에 이어서 실제 연결을 시도했는데, 순서대로 이런 문제들을 겪음:
1. `[YOUR-PASSWORD]` 자리는 채웠는데 비밀번호에 대괄호(`[`) 포함 → URL 파싱 깨짐 → `quote()`로 인코딩해서 해결
2. Direct connection(IPv6 전용) → Colab이 IPv6 미지원이라 `Network is unreachable` → Session Pooler(IPv4) 연결로 전환해서 해결
3. Pooler는 사용자명이 `postgres.프로젝트코드` 형식이어야 함 → 확인/수정함
4. **그런데도 계속 `FATAL: password authentication failed for user "postgres"`** — 사용자명 로컬 확인은 맞게 나오는데 실제 서버 인증은 계속 실패. 비밀번호 재설정을 이미 한 번 했는데도 동일 에러 반복됨
5. **원인 미확정 상태로 오늘 중단.** 마지막으로 사용자에게 안내한 것: 비밀번호 길이/앞뒤 2자리를 본인만 직접 확인해서 Supabase에서 재설정한 값과 실제로 일치하는지 눈으로 대조해보라고 안내 (Supabase가 비밀번호 재설정 시 새 비밀번호를 그 순간에만 화면에 보여주고 이후엔 평문으로 다시 안 보여주는 정책이라, 그 타이밍에 못 복사했으면 `[YOUR-PASSWORD]` placeholder만 남아있었을 가능성 있음 — 이게 유력한 원인 후보)

### 다음 세션에서 이어갈 것
1. Supabase 비밀번호를 **재설정 즉시 화면에 뜨는 값을 그 자리에서 바로 복사**해서 연결 문자열 재구성 (이전 시도들은 이 타이밍을 놓쳤을 가능성 있음)
2. 그래도 안 되면: `psql` CLI로 직접 접속 테스트해서 Python/psycopg2 쪽 문제인지 순수 인증 문제인지 분리 확인
3. 연결되면: `schema_tables.sql`(이미 완료됨, 재확인만) → `load_to_postgres.py`(documents는 Railway에서 이미 한 번 성공했었으나 Supabase는 새 DB라 처음부터 다시 넣어야 함) → `schema_indexes.sql`
4. 적재 성공하면 1주차 체크포인트(SQL로 유사 사례 순위 확인) 진행

### 코드/스크립트 쪽은 오늘 다 준비 완료 (막힌 건 순수 Supabase 자격증명 문제)
- `scripts/schema_tables.sql`, `scripts/schema_indexes.sql`, `scripts/load_to_postgres.py`(배치 커밋 + NUL 방어 + year 방어 전부 반영) — 전부 로컬 테스트 통과, GitHub에 푸시 완료
- Railway 인스턴스는 디스크 부족으로 죽은 채로 방치 (더 이상 안 씀, Supabase로 완전히 이전하는 방향)

## 2026-08-06 (11차 — Railway 디스크 부족으로 DB 다운 → Supabase로 이전)

### 사건: chunks 적재 도중 Railway 디스크 꽉 참 → DB 다운
- documents(72,913건)는 완전히 적재 성공, chunks(벡터 포함, 96,355건) 적재 중
  `psycopg2.errors.DiskFull: could not extend file ... No space left on device` 발생
- 추정 원인: 벡터(1024차원) 96,355개 원본 데이터만 약 395MB, HNSW 인덱스까지 합치면
  약 1~1.2GB 필요 — Railway Trial(무료 체험) 티어의 디스크 할당량을 넘은 것으로 추정
- 이후 DB 자체가 응답 없음(`server closed the connection unexpectedly`) — 재시작도 안 되는
  상태로 보임 (디스크가 없어서 부팅에 필요한 만큼도 못 만드는 것으로 추정)
- Railway 유료 업그레이드($5/월) vs 무료 대안(Supabase/Neon) 논의 → **사용자가 Supabase로
  이전하기로 결정**

### 재발 방지: 스키마를 "테이블 → 데이터 → 인덱스" 순서로 분리
- 기존 `schema.sql`은 인덱스(특히 HNSW)까지 먼저 만들어두고 그 상태로 데이터를 넣는 방식이었음
  → 96,355건 INSERT마다 HNSW 인덱스를 실시간 갱신해야 해서 디스크를 더 쓰고 비효율적
- **`scripts/schema_tables.sql`**(테이블만) / **`scripts/schema_indexes.sql`**(인덱스만, 데이터
  적재 후 실행)로 분리 — 데이터를 먼저 다 넣고 인덱스는 마지막에 벌크로 한 번에 생성
- 기존 `schema.sql`은 로컬 테스트/소량 데이터용으로 남겨두되, 대량 적재 시엔 분리된 버전
  쓰도록 주석에 명시
- 로컬 Postgres로 전체 흐름(테이블 생성 → 데이터 적재 → 인덱스 생성 → 벡터 검색 쿼리) 재검증
  완료, 정상 동작 확인

### 다음
- Supabase 프로젝트 생성 완료(사용자), `DATABASE_URL` 새로 받아서 진행 예정
- 순서: `schema_tables.sql` → `load_to_postgres.py` → `schema_indexes.sql`
- Supabase 무료 티어도 벡터+인덱스 용량(추정 1~1.2GB)을 못 감당할 가능성 있음 — 안 되면
  다시 판단 필요 (유료 전환 또는 halfvec 등 벡터 용량 축소 고려)

## 2026-08-06 (10차 — 실제 적재 중 NUL 문자 에러 + DATABASE_URL 줄바꿈 이슈)

`preflight_check.py` 통과 후 실제 Railway에 `load_to_postgres.py` 돌리다가 겪은 문제 2건.

### DATABASE_URL에 줄바꿈이 낀 채로 Colab Secrets에 저장됨
- 증상: `psycopg2.OperationalError: ... database "railway\npostgresql://..."` — DB 이름 자리에
  두 번째 URL이 통째로 이어붙어 나옴
- 원인: Colab Secrets에 `DATABASE_URL` 값을 복사할 때 줄바꿈+중복 내용이 같이 들어감.
  `.strip()`은 앞뒤 공백만 제거하지 문자열 중간 줄바꿈은 못 없앰
- 해결: Secrets 값을 깨끗하게 다시 저장 + 코드에서도 `.split("\n")[0]`으로 방어
- **주의**: 이 과정에서 실제 DB 비밀번호가 대화(에러 메시지)에 노출됨 — 사용자에게 Railway
  비밀번호 재발급 안내함
- 부수적으로 겪은 실수: Secrets 값을 고친 뒤에도 `os.environ["DATABASE_URL"]`은 이전 셀에서
  설정된 옛날 값이 그대로 메모리에 남아있어서 같은 에러가 재현됨 — Colab에서는 Secrets를
  고쳐도 `os.environ`에 다시 할당해야 실제로 반영된다는 걸 확인

### NUL(0x00) 문자로 documents 적재가 중간에 멈춤
- 증상: `ValueError: A string literal cannot contain NUL (0x00) characters` (`execute_values`
  단계에서 발생)
- 원인: PDF 원문 추출 과정에서 일부 텍스트에 NUL 바이트가 섞여 들어감 — Postgres text 컬럼은
  NUL을 아예 거부함. `preflight_check.py`가 이 케이스는 원래 체크 안 하고 있었음
- 재현: 로컬 Postgres에 NUL 포함 문자열 직접 삽입해서 정확히 같은 에러 재현 확인
- 수정:
  - `load_to_postgres.py`에 `_clean_text()` 추가 — `institution`/`raw_text`/`parsing_quality`/
    청크 `text` 전부에 적용, NUL 발견 시 제거 후 삽입
  - `preflight_check.py`에도 NUL 포함 여부 체크 추가 (정보성, 치명적 문제로 분류 안 함 —
    이제 자동으로 정리되니까)
  - 로컬에서 NUL 포함 fixture로 전체 파이프라인(사전점검 감지 + 실제 적재 성공) 재검증 완료

### 다음
- 사용자가 DATABASE_URL 다시 정리하고 `load_to_postgres.py` 재실행 예정 (이번엔 NUL 방어까지 반영된 최신 버전으로)

## 2026-08-06 (9차 — preflight_check.py가 실전에서 진짜 버그 잡아냄)

**실제 `documents_final.jsonl`(72,913건)로 `preflight_check.py`를 처음 돌려봄 — 바로 문제 2건 발견.**

### 진짜 버그: `build_final_dataset.py`의 parse_tier 정규화 누락
- 증상: `parsing_quality`가 `standard`/`partial`/`fallback`이 아니라 `fallback_split1of2`,
  `standard_split1of3` 같은 값으로 88건 남아있었음 (CHECK 제약 위반 → 적재 시 멈췄을 것)
- 원인: 같은 (source_file, case_number) 그룹 안에 **같은 등급인데 split된 레코드(idx 있음)와
  안 된 레코드(idx=None)가 섞여 있는 경우**, `else` 분기를 타면서 `chosen[0]`이 하필 split
  레코드면 원본 `parse_tier`(접미사 안 지워진 값)가 그대로 저장됨. `if` 분기(순수 split
  병합)만 `best_base`로 정규화하고 있었고 `else` 분기는 빠져있었음
- 재현: 합성 데이터로 정확히 이 상황(같은 그룹에 `fallback`과 `fallback_split1of2` 혼재)을
  만들어서 버그 확인 → 수정(`else` 분기도 `best_base`로 정규화) → 같은 재현 케이스로 재검증,
  정상 값(`fallback`)으로 나오는 것 확인
- **사용자가 해야 할 일**: Colab에서 `build_final_dataset.py` 최신 버전으로 재실행해서
  `documents_final.jsonl`/`chunks_final.jsonl` 다시 생성 필요

### 버그 아님으로 판명: `year` 필드가 문자열
- `year`가 72,911/72,913건에서 문자열(`"2019"` 등)이었지만, 실측 확인 결과 **Postgres/psycopg2가
  숫자 문자열은 자동으로 int로 캐스팅**해서 문제없음 (로컬 DB에 직접 넣어서 확인)
- 그래도 방어 코드는 추가: `load_to_postgres.py`에 `_parse_year()` 헬퍼 — 혹시 진짜 파싱 안 되는
  값(빈 문자열, "2020년" 등)이 하나라도 있으면 그 배치 전체가 죽는 대신 해당 값만 NULL로 대체하고
  경고 출력
- `preflight_check.py`도 "정수 타입 아니면 전부 경고"(72,911건 떠서 노이즈만 컸음)에서
  "진짜 파싱 안 되는 것만 경고"로 개선

### 다음에 할 일
1. Colab에서 `build_final_dataset.py` 재실행 (parse_tier 버그 수정된 최신 버전)
2. `preflight_check.py` 재실행해서 "치명적 문제 없음" 확인
3. `load_to_postgres.py` 실행

## 2026-08-06 (8차 — DB 적재 전 마지막 보강: 배치 커밋 + 사전 점검 스크립트)

DB 적재(`load_to_postgres.py`) 실행 직전에, float16 벡터 저장 검증 + 코드 보강 2건 진행.
(중간에 사용자 지적으로 미승인 변경을 한 번 되돌렸다가, 승인받고 다시 반영함 — 앞으로도
실제 파일 수정 전에는 먼저 여쭤보고 진행하는 것으로 함)

### 확인만 하고 코드는 안 건드린 것
- **float16 벡터가 pgvector에 안전하게 저장되는지 실측 검증** — 로컬 Postgres에 실제로
  float16 numpy 배열을 삽입 후 다시 읽어서 원본과 코사인 유사도 비교 (거의 1.0, 손실 없음
  확인). `load_to_postgres.py`는 수정 불필요.

### 코드 수정 1 — `load_to_postgres.py`: 배치 커밋
- 기존: `documents`(72,913건), `chunks`(96,355건, 벡터 포함이라 더 무거움) 각각 통째로
  하나의 트랜잭션 — Railway Public Network 연결이 도중에 끊기면 그 지점까지 넣은 것 전부
  롤백됨
- 변경: 5,000건 단위로 나눠서 커밋 + 진행 로그 출력. 끊겨도 이미 커밋된 배치는 남고,
  재실행하면 `ON CONFLICT DO NOTHING`으로 이어서 진행됨
- 로컬 Postgres로 정상 동작 확인 + 재실행 시 중복 안 생기는 것(idempotency)도 확인

### 코드 수정 2 — `scripts/preflight_check.py` (신규)
- DB 연결 없이 로컬 파일만으로 사전 점검: document_id FK 무결성, `parsing_quality` CHECK
  제약 위반 여부, `year` 타입, id 중복, 임베딩 누락 청크 수
- 일부러 문제 3개(잘못된 parsing_quality, year가 문자열, FK 깨진 청크) 주입한 가짜 데이터로
  테스트 → 전부 정확히 잡아내는 것 확인. 정상 데이터로는 통과하는 것도 확인
- **다음에 실제로 할 일**: Colab에서 `python preflight_check.py` 먼저 돌려서 "치명적 문제
  없음" 나오면 그다음에 `load_to_postgres.py` 실행

## 2026-08-06 (7차 — "4줄 전부 미기재" 처리 확정 + 카드 미리보기 모순 발견/수정)

### "4줄 전부 미기재" 최종 확정 (architecture.md §4.6, v11)
- 실측: 35건 중 1건(2.9%, `partial` 등급) → 72,913건 기준 95% 신뢰구간으로 최소 약 53건 ~ 최대 약 10,877건 예상. 0건은 아닐 게 거의 확실해서 안전장치 필요하다고 최종 판단
- **처리**: 1차 생성 실패(4줄 전부 탈출구 문구) → 재시도 1회 → 그래도 실패하면 `summary_failed=TRUE` 저장하고 원문만 반환
- **UI**: 새 화면 상태 안 만들고 기존 신뢰도 배지 체계에 "요약 어려움 — 원문 참고 필요" 티어만 추가
- **실패 캐싱**: `scripts/schema.sql`에 `documents.summary_failed BOOLEAN NOT NULL DEFAULT FALSE` 컬럼 추가 — 이거 없으면 진짜 요약 불가능한 문서는 조회될 때마다 매번 API 2번(1차+재시도)씩 낭비됨. 로컬 Postgres에서 재적용 테스트 완료 (컬럼 정상 생성 확인)
- **미룬 것**: 원문 인용 폴백(quote extraction) — 엣지케이스(3% 미만) 대비 API 호출 추가 비용이 안 맞아 스트레치로 이연

### 부수적으로 발견한 진짜 버그: 검색 카드 미리보기가 v9 이후로 깨져 있었음 (architecture.md §8.3, v12)
- §4.6 반영하려고 §8.3(검색 카드 설계)을 다시 보다가 발견: 카드 미리보기가 "4줄 요약 1번째 줄"에 의존하고 있었는데, **v9에서 요약을 배치→온디맨드로 바꾼 뒤로는 상세페이지 클릭 전까지 요약 자체가 존재하지 않음** — 그대로 뒀으면 검색 결과 카드 대부분이 빈 미리보기로 떴을 상황
- 카드에서도 온디맨드 생성을 걸면 검색 1회당 최대 10번 LLM 호출 → NFR2(1~2초) 예산 초과 위험
- **수정**: 카드 미리보기는 LLM 없는 `raw_text` 발췌로 되돌림, AI 4줄 요약은 상세페이지(단건 클릭) 전용으로 명확히 분리
- 교훈: 설계를 한 부분 바꾸면 그 설계에 의존하던 다른 부분도 같이 점검해야 함 — v9 커밋 때 §8.3까지 같이 안 봤던 게 원인

## 2026-08-06 (6차 — 임베딩 품질 검증, 벡터DB 선택 근거 문서화, 파이프라인 숫자 정리)

### 임베딩 품질 검증 완료 (Colab에서 실측)
```
shape: (124066, 1024)
dtype: float16
NaN 있는지: False
전부 0인 벡터 수: 0
벡터 크기(norm) 평균/표준편차: 0.9999997 / 0.00017351884
```
- **norm이 거의 정확히 1.0** → 벡터가 L2 정규화되어 있음이 실측으로 확인됨. 이건 5차에서 걱정했던
  "배치 임베딩(`FlagEmbedding`)과 온라인 쿼리 예시 코드(`sentence-transformers`)가 라이브러리가 달라
  정규화 방식이 어긋날 수 있다"는 우려를 상당 부분 해소함 — `FlagEmbedding`도 기본적으로 정규화된
  벡터를 내놓는다는 게 확인됨 (다만 두 라이브러리가 완전히 동일한 벡터공간을 내놓는지는 검색 API
  실제 구현 때 한 번 더 확인 권장)
- **의미 유사도 테스트도 통과**: 임의 청크 하나를 기준으로 코사인 유사도 상위 5개를 뽑아보니, 자기 자신(1.000) 다음으로
  다른 기관의 비슷한 양식(감사결과처분요구서) 문서들이 0.86~0.90대 유사도로 잡힘 — 임베딩이 의미적으로
  잘 작동하고 있다는 증거

### 벡터DB 선택 근거 보강: LangChain + FAISS 검토 후 기각
`docs/architecture.md` §5.6 ADR 표에 아래 행 추가 (근거는 §5.7과 동일 맥락이지만, "FAISS를 구체적으로
검토했었다"는 사실 자체가 문서에 없어서 명시적으로 추가함 — 포트폴리오 인터뷰에서 "왜 FAISS 안 썼냐"
질문 대비):
- FAISS는 순수 벡터 검색 속도는 더 빠르지만(인메모리 C++), 이 프로젝트 규모(청크 96,355개)에서는
  pgvector HNSW로도 충분히 빠르고, 진짜 지연시간 병목은 벡터 검색이 아니라 리랭커(크로스인코더)임
- FAISS를 쓰면 메타데이터/키워드검색/요약캐싱용 Postgres가 어차피 또 필요해져서, "벡터DB 왕복 + RDB
  왕복" 2번이 되는 반면 pgvector는 DB 왕복 1번으로 끝남 — 이 프로젝트 규모에선 이 차이가 알고리즘
  자체 속도차보다 체감에 더 영향을 줌
- LangChain은 이 프로젝트의 커스텀 검색 로직(RRF 융합 + document 단위 dedup + 리랭커 재채점)이 일반적인
  Retriever/Chain 추상화에 깔끔히 안 맞아서 채택 안 함

### 파이프라인 숫자 계보 정리 (그동안 여러 번 나온 숫자들, 한 곳에 정리)
| 단계 | 파일 | 건수 | 단위 | 비고 |
|---|---|---|---|---|
| 0. 원본 수집 | (이 저장소 밖) | 약 80,000건 | API 레코드 | 사용자 기억 기준, 이 저장소로는 확인 불가 |
| 1. 파싱 | `audit_cases_final_v2.jsonl` | 143,160줄 | 파싱 레코드 | 중복/분할(`_splitNofM`)/overview 포함 |
| 2. 청킹 대상 | `embed_ready_v2.jsonl` | 76,454건 | 고유 문서 | 0→1, 1→2 사이 정확한 사유는 미확인 |
| 3. 청킹 결과 | `embed_ready_v2.jsonl` | 124,066개 | 청크 | **임베딩은 이 전체를 대상으로 함** |
| 4. 1차 정리 | `build_final_dataset.py` (audit_cases 쪽) | 78,697건 | 고유 문서 | overview 4,723건 제외, extraction_failed만 있는 234건 제외, split 병합 |
| 5. 최종 매칭 | `documents_final.jsonl` | **72,913건** | 최종 문서 | 4번과 2번을 (source_file, title)로 매칭한 교집합 |
| 5-1. 최종 청크 | `chunks_final.jsonl` | **96,355건** | 최종 청크 | 위 72,913건에 속한 청크만 |

## 2026-08-06 (5차 — 임베딩 완료 + 4줄 요약을 배치→온디맨드로 재설계)

### 🎉 임베딩 완료
`embed_chunks.py`로 124,066개 청크 전부 임베딩 완료 확인 (`체크포인트 저장: 124066/124066건 완료`,
개수 검증 assert 통과). `embeddings_v2/embeddings.npy` + `chunk_ids.jsonl` 준비 끝남.
**다음 단계: `load_to_postgres.py`로 실제 DB 적재** (Railway 스키마는 이미 적용되어 있음, 3차 항목 참고).

### 설계 변경: 4줄 요약을 "배치 사전생성" → "상세 API 온디맨드 생성 + DB 캐싱"

사용자가 "검색 결과 여러 개 중 실제로 클릭해서 보는 건 일부인데, 72,913건 전체를 미리
요약해두는 게 비효율 아니냐"는 질문 → 맞는 지적이라 설계를 바꿈.

- **이전 설계**: Colab에서 72,913건 전체를 배치로 미리 요약 → DB에 채워 넣기 (스모크 테스트 실측 기준 약 7.2시간, $15 고정 비용, 체크포인트/재개 인프라 별도 필요)
- **바뀐 설계**: 상세 API가 문서 조회 시 `summary_point`가 NULL이면 그 자리에서 OpenAI 호출 → 결과를 DB에 저장(캐싱) → 반환. 이미 채워져 있으면 API 호출 없이 DB 값만 반환
- **왜 나은가**: 실제로 조회된 문서에 대해서만 비용 발생, 7시간짜리 배치+체크포인트 인프라 자체가 통째로 불필요해짐, 반복 조회 시 요약 문구가 매번 바뀌는 것도 방지(캐싱이라 최초 1회만 생성)
- **바뀌지 않은 것**: 프롬프트 설계(1~3줄 탈출구 포함, §4.1~4.2)와 `scripts/summary_smoke_test.py`는 그대로 유효 — "이 프롬프트가 실제로 잘 작동하는지" 사전 검증 용도로 계속 씀. 배치 실행 자체만 안 하는 것

### 수정한 문서
- `docs/architecture.md` → v9: §3.7 다이어그램(4줄요약을 오프라인 배치에서 상세 API 경로로 이동), §4.5 신규(온디맨드+캐싱 동작 방식), §4.4/§5.5/§5.6/§5.7/§6 관련 서술 전부 갱신
- `docs/development-plan.md` → v3: 1주차 "4줄 요약 배치 실행" 항목 제외, 2주차 "상세 API 구현"에 온디맨드 생성+캐싱 포함하는 걸로 명시
- `README.md`: 기술스택 표, 주요 설계 결정 목록, 비용 섹션 갱신

### 스모크 테스트 실측 결과 (참고용으로 계속 유효)
- 35건 실제 API(gpt-4o-mini) 테스트: 35/35 성공, 포맷 위반 1건(원인 미확인 — 다음에 확인 필요)
- 건당 평균 입력 948토큰 / 출력 105토큰 / 1.77초 / 약 $0.0002
- standard 등급은 1~3줄 미기재 사용 0% (모델이 게으르게 답한 흔적 없음, 좋은 신호)

## 2026-08-06 (4차 — 요약 LLM을 Anthropic Claude → OpenAI로 교체)

사용자가 OpenAI API 키로 진행하기로 결정 → **요약 배치 관련 코드/문서에서 Claude Haiku
언급을 전부 OpenAI(gpt-4o-mini)로 교체.**

### 변경한 파일
- `scripts/summary_smoke_test.py`: `anthropic` → `openai` SDK로 전면 교체
  - `MODEL = "gpt-4o-mini"` (기존 `claude-haiku-4-5`)
  - API 호출부: `client.messages.create(...)` → `client.chat.completions.create(...)`,
    응답 파싱(`resp.choices[0].message.content`, `resp.usage.prompt_tokens`/`completion_tokens`)도 OpenAI 형식으로 변경
  - 예외 처리: `anthropic.APIStatusError`/`APIConnectionError` → `openai.APIStatusError`/`APIConnectionError`
  - 필요 환경변수: `ANTHROPIC_API_KEY` → `OPENAI_API_KEY`
  - 가격 상수: gpt-4o-mini 참고치로 교체 ($0.15/1M input, $0.60/1M output) — **실행 직전 OpenAI 가격 페이지에서 재확인 필요**로 주석에 명시
  - DRY_RUN으로 재검증 완료 (openai 2.53.0 기준 `OpenAI`/`APIStatusError`/`APIConnectionError`/`with_options` 전부 존재 확인, 파이프라인 정상 동작)
- `docs/architecture.md` §4.4, §5.7 ADR 표 — Claude Haiku → OpenAI(gpt-4o-mini)로 갱신
- `README.md` 기술 스택 표, `docs/development-plan.md` 1주차 표 — 동일하게 갱신

### 참고
- 프롬프트 구조(1~3줄 탈출구 추가 등)는 이전 커밋에서 이미 반영된 내용 그대로 유지, 모델/SDK만 교체
- Colab에서 실행 시: `pip install openai`, `OPENAI_API_KEY` 환경변수(Colab Secrets 권장) 설정 필요

## 2026-08-06 (3차 — Railway DB 스키마 적용)

### 완료
- **Railway Postgres 서비스 생성** — Public Networking 활성화 (`DATABASE_PUBLIC_URL` 확보, Colab에서 쓸 때는 `DATABASE_URL` 환경변수명으로 매핑해서 사용)
- **`scripts/schema.sql`을 Railway에 실제 적용** — Railway 대시보드 Query 탭에서 실행, `documents`/`chunks` 테이블과 인덱스 5개 생성 확인 완료 (`information_schema.tables`, `pg_indexes`로 검증)

### DB 스키마 요약 (테이블은 만들었고, 데이터는 아직 안 들어간 상태)

**`documents`** — 사례 1건 = 행 1개, 상세페이지용
| 컬럼 | 용도 |
|---|---|
| `id` (PK) | 사례 고유번호 |
| `institution`, `year` | 기관명, 감사연도 |
| `raw_text` | 원문 전체 (상세페이지 "펼쳐보기") |
| `parsing_quality` | standard/partial/fallback — 신뢰도 배지용, CHECK 제약 있음 |
| `summary_point/cause/action/result` | 4줄 요약 (아직 비어있음, 상세 API에서 온디맨드 생성+캐싱으로 채워질 예정 — 5차 항목 참고) |

**`chunks`** — 문서를 쪼갠 검색 단위
| 컬럼 | 용도 |
|---|---|
| `id` (PK), `document_id` (FK → documents.id) | 청크 식별 + 소속 문서 |
| `text` | 청크 원문 |
| `embedding vector(1024)` | BGE-m3 임베딩 벡터 (현재 Colab에서 생성 중) |
| `tsv` | 키워드 검색용, `text` 저장 시 Postgres가 자동 생성(GENERATED ALWAYS) |

**인덱스 5개** (검색 속도용 — 없으면 검색할 때마다 테이블 전체를 훑어야 함)
- `chunks_embedding_hnsw_idx` (HNSW, `embedding`) — 벡터 유사도 검색
- `chunks_tsv_gin_idx` (GIN, `tsv`) — 키워드 검색
- `chunks_document_id_idx` (btree, `document_id`) — 청크→문서 조인
- pgvector 확장이 내부적으로 생성하는 인덱스 등

이 벡터 검색 + 키워드 검색 결과를 RRF로 합쳐서 최종 Top-10을 뽑는 게 검색 로직의 핵심 (architecture.md 참고).

### 다음
- 예상 건수: `documents` 72,913건, `chunks` 96,355건 (build_final_dataset.py 최신 실행 결과 기준)
- 임베딩(`embed_chunks.py`, 124,066개 중 진행 중) 완료 대기
- 완료되면 `load_to_postgres.py`로 실제 데이터 적재 → 1주차 체크포인트(SQL로 유사 사례 순위 확인)

## 2026-08-06

### 완료
- **데이터 정리** — 원본 `audit_cases_final_v2.jsonl`(143,160줄)에 중복/분할/비-사례 레코드가 섞여 있던 걸 발견하고 정리
  - 같은 사례가 여러 번 파싱된 것(순수 중복), 원문이 길어 여러 조각으로 쪼개진 것(split), 실제 지적사항이 아닌 "감사개요" 레코드(overview) 세 가지가 섞여 있었음
  - `scripts/build_final_dataset.py`로 재현 가능하게 정리 — 최종 **72,913건**의 documents/chunks 확정
- **DB 스키마 확정** — `scripts/schema.sql` (documents, chunks 테이블 + HNSW/GIN 인덱스)
- **DB 적재 스크립트 준비** — `scripts/load_to_postgres.py` (documents_final.jsonl + chunks_final.jsonl + 임베딩 파일 조인해서 적재)
- **요약 배치 스모크 테스트 스크립트 준비** — `scripts/summary_smoke_test.py` (DRY_RUN 모드 포함, documents_final.jsonl 기준으로 필드명 맞춤)
- **Drive 정리** — 중복/백업 파일 삭제로 ~5.6GB 확보
- Colab 임베딩 스크립트 개선안 준비 (chunk_ids.jsonl을 체크포인트마다 저장하도록 — 이번 세션 코드 블록에 있음, 다음 재시작 때 반영 필요)

### 진행 중 (Colab, Google Drive `MyDrive/audit_project/`)
- BGE-m3 임베딩: `embed_ready_v2.jsonl`(124,066개 청크) 기준으로 계속 진행 중, 8/6 기준 19,200개대
- 1만 건대 스냅샷 확보함: `embeddings_v2/embeddings_10k_snapshot.npy` + `chunk_ids_10k_snapshot.jsonl` (19,200개)

### 이어서 진행 (같은 날, 코드 샌드박스 세션 — Drive/Railway 접근 불가 환경)
> 이 세션은 Google Drive(Colab 데이터)와 Railway에 접근할 수 없어서, 실제 72,913건 데이터로는
> 아무것도 못 돌렸음. 대신 **로컬에 Postgres 16 + pgvector를 직접 설치하고, 실제 스키마를 흉내낸
> 합성 데이터로 스크립트 4개를 전부 실행해서 코드 자체의 버그를 미리 잡는 작업**을 했음.

- **버그 발견 및 수정**: `scripts/build_final_dataset.py`가 `overview`는 제외하면서 `extraction_failed`는
  제외하지 않고 있었음 — 한 사례(case_number)의 모든 레코드가 파싱 실패(`extraction_failed`)면
  그대로 `documents_final.jsonl`에 `parsing_quality: "extraction_failed"`로 흘러들어감.
  - 이건 (1) `summary_smoke_test.py` 주석("overview/extraction_failed는 이미 제외됨")과 실제 동작이
    어긋나고, (2) `schema.sql`의 `CHECK (parsing_quality IN ('standard','partial','fallback'))`을
    위반해서 **DB 적재(`load_to_postgres.py`)가 그 문서에서 통째로 실패**하는 문제였음
  - 합성 데이터로 재현 확인 후 수정 완료 (그룹 내 최고 등급이 `extraction_failed`면 스킵 + 카운트 로그 추가)
  - 실제 데이터로 이 스크립트를 다시 돌릴 때는 이 수정이 반영된 버전으로 돌려야 함 (Colab에 반영 필요)
- **검증 완료 (합성 데이터 기준, 로컬 Postgres+pgvector)**:
  - `schema.sql` 클린 실행 확인 (테이블/HNSW/GIN 인덱스 전부 생성됨)
  - `build_final_dataset.py` → `load_to_postgres.py` 전체 파이프라인 end-to-end 통과 (documents/chunks 적재, 임베딩 조인 정상)
  - 벡터 유사도 검색 SQL(`ORDER BY embedding <=>`) + documents JOIN 정상 동작 확인 — 1주차 체크포인트의 "SQL로 순위 확인"이 메커니즘 상 작동함을 확인 (실제 데이터의 순위 품질 자체는 아직 미확인)
  - `summary_smoke_test.py` DRY_RUN 실행 확인 — 합성 documents_final.jsonl(standard 25 / partial 12 / fallback 7)로 35건 층화 샘플링, 동시성, 포맷 검증, 저장, 리포트까지 전부 정상 동작 (실패 0건, 포맷 위반 0건)

### Colab 임베딩 체크포인트 FileNotFoundError 수정 (같은 날, 2차)
- 사용자가 Colab에서 체크포인트 저장 로직 추가 후 실행하다가
  `os.replace(tmp_path, EMBEDDINGS_PATH)`에서 `FileNotFoundError` 발생시킴
- **원인**: `tmp_path = EMBEDDINGS_PATH + ".tmp"` (예: `"embeddings.npy.tmp"`)는 `.npy`로 안 끝나서,
  `np.save()`가 자동으로 `.npy`를 붙여 실제로는 `"embeddings.npy.tmp.npy"`라는 파일이 생성됨.
  그 직후 `os.replace`가 찾는 `"embeddings.npy.tmp"`는 존재한 적이 없어서 죽음 — 체크포인트를
  저장하려는 시도마다 100% 재현되는 버그. 저장 도중 6,400건 단위 진행상황이 매번 유실됐을 것.
- **수정 + 저장소에 반영**: `scripts/embed_chunks.py`로 새로 커밋 — 임시 파일명을 처음부터
  `.npy`로 끝나게 바꾸고(`EMBEDDINGS_PATH.replace(".npy", ".tmp.npy")`), 실행 시작 시 이전 실행이
  남긴 stray 임시 파일도 정리하도록 추가. 모델 로딩 없이 체크포인트 저장/재개 로직만 격리해서
  로컬에서 재현 테스트 → 수정 후 정상 동작 확인 (`.tmp.npy` 잔여 파일 없이 `embeddings.npy` +
  `chunk_ids.jsonl`만 남음, resume 시 개수도 정확히 로드됨)
- **미확인**: 사용자의 실제 Google Drive에 이번 버그로 생긴 `embeddings.npy.tmp.npy` 같은
  잘못된 이름의 파일이 남아있는지는 이 세션에서 Drive 접근이 안 돼서 직접 확인 못함 —
  사용자가 Colab에서 `os.listdir(CHECKPOINT_DIR)`로 직접 확인 필요

### 아직 안 한 것 (다음 세션에서 이어갈 것 — Colab/Railway 실제 환경 필요)
1. **위 버그 수정을 Colab의 `build_final_dataset.py`에도 반영하고 재실행** — 기존 72,913건 중 extraction_failed로만 이루어진 사례가 있었다면 재확인 필요
2. **`scripts/summary_smoke_test.py` DRY_RUN을 실제 `documents_final.jsonl`로 실행** — 코드 자체는 이번 세션에서 검증했지만, 실데이터 분포 기준으로는 아직 안 돌려봄
3. **Railway Postgres 서비스 생성 여부 미확인** — 만들었으면 `DATABASE_URL` 확보 후 `scripts/schema.sql` 실행 → `scripts/load_to_postgres.py` 실행 (스크립트 자체는 로컬에서 검증 끝남)
4. **1주차 체크포인트** — 실제 DB 적재 후 SQL로 유사 사례 순위 확인 (development-plan.md 1주차 목표, 메커니즘은 검증됨)
5. 요약 스모크 테스트 소량 실제 실행 (비용 발생, 몇십 원 수준)
6. **`scripts/embed_chunks.py`로 Colab 임베딩 재개** — Drive에 잘못된 이름으로 남은 파일(있다면) 정리 후 실행
7. *(여유 있으면)* Railway/Vercel 빈 뼈대 배포로 4주차 배포 리스크 선제 검증
8. *(여유 있으면)* BGE-m3 단독 메모리 실측

### 파일 위치 참고
- 이 저장소(`scripts/`): `schema.sql`, `build_final_dataset.py`, `load_to_postgres.py`, `summary_smoke_test.py`, `embed_chunks.py`
- Google Drive `MyDrive/audit_project/`: 원본 데이터, 임베딩 체크포인트, `documents_final.jsonl`, `chunks_final.jsonl` (전부 여기, 이 git 저장소에는 없음)
