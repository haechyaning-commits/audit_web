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

### 아직 안 한 것 (다음 세션에서 이어갈 것)
1. **`scripts/summary_smoke_test.py` DRY_RUN 실행** — 한 번도 안 돌려봄. `DRY_RUN=1 python summary_smoke_test.py`부터
2. **Railway Postgres 서비스 생성 여부 미확인** — 만들었으면 `DATABASE_URL` 확보 후 `scripts/schema.sql` 실행 → `scripts/load_to_postgres.py` 실행
3. **1주차 체크포인트** — DB 적재 후 SQL로 유사 사례 순위 확인 (development-plan.md 1주차 목표)
4. 요약 스모크 테스트 소량 실제 실행 (비용 발생, 몇십 원 수준)
5. *(여유 있으면)* Railway/Vercel 빈 뼈대 배포로 4주차 배포 리스크 선제 검증
6. *(여유 있으면)* BGE-m3 단독 메모리 실측

### 파일 위치 참고
- 이 저장소(`scripts/`): `schema.sql`, `build_final_dataset.py`, `load_to_postgres.py`, `summary_smoke_test.py`
- Google Drive `MyDrive/audit_project/`: 원본 데이터, 임베딩 체크포인트, `documents_final.jsonl`, `chunks_final.jsonl` (전부 여기, 이 git 저장소에는 없음)
