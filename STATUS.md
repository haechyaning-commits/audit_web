# 진행 상황 로그

> 대화창이 바뀌어도 여기부터 이어서 보면 됨. 최신 항목이 맨 위.

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

### 아직 안 한 것 (다음 세션에서 이어갈 것 — Colab/Railway 실제 환경 필요)
1. **위 버그 수정을 Colab의 `build_final_dataset.py`에도 반영하고 재실행** — 기존 72,913건 중 extraction_failed로만 이루어진 사례가 있었다면 재확인 필요
2. **`scripts/summary_smoke_test.py` DRY_RUN을 실제 `documents_final.jsonl`로 실행** — 코드 자체는 이번 세션에서 검증했지만, 실데이터 분포 기준으로는 아직 안 돌려봄
3. **Railway Postgres 서비스 생성 여부 미확인** — 만들었으면 `DATABASE_URL` 확보 후 `scripts/schema.sql` 실행 → `scripts/load_to_postgres.py` 실행 (스크립트 자체는 로컬에서 검증 끝남)
4. **1주차 체크포인트** — 실제 DB 적재 후 SQL로 유사 사례 순위 확인 (development-plan.md 1주차 목표, 메커니즘은 검증됨)
5. 요약 스모크 테스트 소량 실제 실행 (비용 발생, 몇십 원 수준)
6. *(여유 있으면)* Railway/Vercel 빈 뼈대 배포로 4주차 배포 리스크 선제 검증
7. *(여유 있으면)* BGE-m3 단독 메모리 실측

### 파일 위치 참고
- 이 저장소(`scripts/`): `schema.sql`, `build_final_dataset.py`, `load_to_postgres.py`, `summary_smoke_test.py`
- Google Drive `MyDrive/audit_project/`: 원본 데이터, 임베딩 체크포인트, `documents_final.jsonl`, `chunks_final.jsonl` (전부 여기, 이 git 저장소에는 없음)
