# scripts/ 안내

전부 오프라인 배치 스크립트. 서비스(백엔드/프론트)는 이 폴더에 있는 어떤 파일도
런타임에 import하지 않음 — 데이터 구축(파싱→청킹→임베딩→적재) 1회성 파이프라인과,
그 이후 운영 사이트에서 발견한 데이터 품질 문제를 "조사(audit/investigate/diagnose) →
반영(fix/backfill/rechunk_reembed)" 순서로 대응한 기록이 섞여 있음.

파일이 60개가 넘고 `_round2`/`_round3`류 재시도가 많은 이유: 실제 문서 수만 건이 원본
자체부터 형식이 제각각이라, 한 번에 못 끝내고 규모조사 → 원인 재현 → 안전장치(유사도
게이트/DRY_RUN) → 표본 확대 재조사를 반복한 결과물이기 때문. 각 스크립트 상단 주석에
배경과 실행 시점을 적어뒀고, 문제별 최종 결론은 루트 [`README.md`](../README.md)의
"데이터 품질 문제 대응" 표에, 시행착오 전 과정은 [`STATUS.md`](../STATUS.md)에 있음.

아래는 그 60여 개를 이슈 스레드 단위로 묶은 색인. 각 그룹은 대략 조사(audit/investigate)
→ 수정(fix/backfill) → 재청킹·재임베딩(rechunk_reembed) 순.

## 데이터 구축 파이프라인 (1회성, 실행 순서대로)

| 스크립트 | 역할 |
|---|---|
| `textparse.py` | 원본 파일명에서 감사종류(audit_type) 파싱 |
| `build_final_dataset.py` | 최종 documents/chunks 데이터셋 빌드 |
| `preflight_check.py` | DB 적재 전 사전 점검 |
| `schema.sql` / `schema_tables.sql` / `schema_indexes.sql` | Postgres 스키마 정의 |
| `load_to_postgres.py` | pgvector 적재 |
| `embed_chunks.py` | BGE-m3 청크 임베딩 (체크포인트/재시작 지원) |
| `generate_sitemap.py` | 사례 상세페이지 전체를 담은 sitemap 생성 |

## 검색 품질 평가 / 배포 전 실측

| 스크립트 | 역할 |
|---|---|
| `eval_search_quality.py` / `eval_set_template.jsonl` | 오프라인 검색품질 평가(Recall@K/MRR) — RRF vs 벡터/키워드 단독 vs 리랭커 |
| `measure_model_memory.py` | 임베딩+리랭커 동시 로드 메모리 실측 (RERANKER_ENABLED 켜기 전 필수 확인) |
| `summary_smoke_test.py` | 4줄 요약 프롬프트 검증(할루시네이션 탈출구 문구 비율 실측) |

## 텍스트 오염 1차 대응 (2026-08-07~13, 최초 데이터 품질 진단)

| 스크립트 | 역할 |
|---|---|
| `fix_text_corruption.py` | "제목목목목"류 글자 연쇄 오염 수정 |
| `audit_isolated_duplicates.py` | 단독 한글 글자 중복(연쇄 아닌 것) 실태 조사 |
| `backup_before_fix.py` | 반영 전 chunks 백업 |
| `reembed_changed_chunks.py` | 텍스트 수정된 청크 재임베딩 + DB 반영 |
| `investigate_table_placeholder_spike.py` | table_placeholder_only 판정 급증 원인 조사 |
| `remove_unrecoverable_docs.py` | 재추출 불가 문서 제외 |
| `audit_duplicate_documents.py` | 중복 문서 실태 조사 |
| `backfill_audit_type.py` / `backfill_source_file.py` | 기적재 documents에 audit_type/source_file 소급 반영 |

## 표 컬럼 뒤섞임 (2단 표 텍스트 교차 오염)

| 스크립트 | 역할 |
|---|---|
| `audit_table_column_interleave.py` | 실태 조사 (2차 수정본) |
| `backfill_table_column_fix.py` | 반영 |

## PDF 2단(다단) 레이아웃 재추출

| 스크립트 | 역할 |
|---|---|
| `audit_pdf_column_layout.py` | 다단 레이아웃 의심 문서 실태 조사 |
| `reextract_pdf_text.py` | 재추출 프로토타입(컬럼 순서 + 띄어쓰기 복구) |
| `rechunk_reembed_pdf_column_fix.py` / `_round2` / `_round3` | 재추출분 반영 + 재청킹 + 재임베딩 (1~3차, 순서만 바뀐 문서 구제 → 원문자 서식 재적용) |
| `diagnose_pdf_reextract_review_queue.py` | 자동반영 게이트를 통과 못 한 수동검토 큐 진단 |
| `audit_title_number_and_wordbreak.py` / `audit_wordbreak_safe_particles.py` | 재추출 검증 중 발견한 "1. 제목:" 번호 유실 + 단어 중간 줄바꿈 규모조사 |
| `fix_title_number_loss.py` | 번호 유실 수정 |
| `audit_footnote_loss_pdf_compare.py` | 각주 유실 의심 문서 원본 PDF/HWP 직접 대조 |

## 심볼폰트 불릿 오염 (Wingdings류)

| 스크립트 | 역할 |
|---|---|
| `audit_v_bullet_diagnose.py` / `audit_v_bullet_font_check.py` | 'v' 단독 토큰 = 불릿 오염 가설 검증 → 원본 폰트 확인 |
| `audit_symbol_font_leak_scope.py` | 전체 범위 조사 |
| `audit_symbol_font_leak_font_check2~5.py` | 후보 문자별(m/q/y/r 등) 원본 폰트 재확인 |
| `fix_symbol_font_bullet_leak.py` | 반영 |
| `fix_symbol_font_bullet_leak_digit_check.py` / `_preview.py` | 반영 전 안전장치(숫자 뒤 매칭 확인) / 확장 샘플 프리뷰 |
| `reembed_bullet_fix_from_db.py` | 수정 후 재임베딩 (중간 jsonl 없이 DB에서 바로) |
| `repair_bullet_leak_digit_regression.py` | 반영 중 캐시된 구버전 스크립트 실행 정황 긴급 복구 |

## HWP 원문 잘림 (구버전 .hwp 900~1020자 캡)

| 스크립트 | 역할 |
|---|---|
| `audit_truncated_documents.py` | 실태 조사 |
| `audit_hwp_truncation_extract.py` | 원본 재다운로드 후 전체 텍스트 재추출 |
| `backfill_hwp_truncation_fix.py` | 반영 |
| `audit_hwpx_leak_fix_extract.py` | .hwpx 추출 함수 재수정(태그 누출 후속) |
| `rechunk_reembed_hwp_fix.py` | 반영분 재청킹 + 재임베딩 |

## HWPX 내부 태그 누출

| 스크립트 | 역할 |
|---|---|
| `audit_hwp_tag_leak.py` | 실태 재조사 |
| `audit_hwpx_tag_leak_round2.py` | 2차 재조사(처리 대상 0건 확인) |

## 구버전 HWP 표 내용 손실

| 스크립트 | 역할 |
|---|---|
| `audit_hwp_table_loss.py` | 실태 조사(표본) |
| `audit_hwp5txt_env_check.py` | hwp5txt 런타임 정상 동작 여부 진단 |
| `audit_hwp_table_loss_full_population.py` | 전수(모집단 전체) 조사 |
| `audit_hwp_table_loss_full_checkpoint_diagnose.py` | 전수조사 체크포인트 결과 재진단 |
| `rechunk_reembed_hwp_table_fix.py` | hwp5txt+hwp5html 병합 복구 + 재청킹 + 재임베딩 (DRY_RUN 검증 대기) |

## 부서/기관명 익명화 심볼 누출

| 스크립트 | 역할 |
|---|---|
| `audit_dept_anon_symbol_leak_scope.py` / `_round2` / `_round3` | 규모조사 1~3차(합집합 확정) |
| `backfill_dept_anon_symbol_fix.py` | `[비공개]`로 통일 반영 |
| `fix_dept_anon_symbol_chunks_residual.py` | chunks 잔여분 정리 |

## 렌더링 이상 전수조사 / 형태소 토큰화

| 스크립트 | 역할 |
|---|---|
| `audit_render_anomalies.py` | 사용자 스크린샷 제보로 발견한 렌더링 버그 관련 원문 구조 이상 전수조사 |
| `backfill_tsv_text.py` / `tsv_text_migration.sql` | 한국어 형태소 토큰화(kiwipiepy) 적용을 위한 `chunks.tsv_text` 배치 백필 + 재색인 |
