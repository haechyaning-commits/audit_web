# 진행 상황 로그

> 대화창이 바뀌어도 여기부터 이어서 보면 됨. 최신 항목이 맨 위.

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
