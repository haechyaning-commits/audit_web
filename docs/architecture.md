# 공공감사데이터 포트폴리오 웹사이트 — 아키텍처 설계 문서 v4

> v2 대비 변경점: ①리랭커 도입 여부 모순 해소, ②검색 결과 document 단위 dedup 로직 추가,
> ③한국어 전문검색(형태소 미분리) 문제 해결, ④임베딩+리랭커 동시 로드 메모리 예산 재계산.
> 이 4가지는 검토 결과 "구현 착수 전 반드시 결정해야 하는 항목"으로 분류되어 우선 반영함.
> v4 변경점: 레이어별(프론트/백엔드/DB/모델/배포) 기술 스택 선택 근거를 §5.7로 명시화.

## 0. v2 → v3 변경점 요약

| # | 문제 | v2 상태 | v3 결정 |
|---|---|---|---|
| ① | 리랭커 도입 여부가 §3.4(도입 확정)와 §5.6 ADR표("미도입, v1.1로 연기")에서 서로 모순 | 불일치 | **리랭커는 MVP(v1)에 포함**으로 확정. ADR 표의 모순 행 제거 |
| ② | 검색은 청크 단위 Top-N인데 카드 UI는 문서(사례) 단위 — 같은 문서가 여러 장 중복 노출될 수 있음 | dedup 로직 없음 | RRF 이후 `document_id` 기준 최고점 청크 1개만 남기는 dedup 단계 추가 |
| ③ | `ts_rank(tsv, plainto_tsquery('simple', ...))` — `simple` 사전은 한국어 형태소 분석을 하지 않아 조사/어미가 붙은 단어 매칭 실패 가능 | 미해결 리스크 | 배치·쿼리 양쪽에 **형태소 분석 전처리(kiwipiepy)** 추가, tsvector는 사전 토큰화된 텍스트로 생성 |
| ④ | BGE-m3(임베딩)+bge-reranker-v2-m3(리랭커) 동시 상시 로드 시 메모리 재계산 안 됨 | BGE-m3 단독 기준만 언급 | 두 모델 합산 예상치 재계산 + 배포 전 실측 검증 스텝을 체크리스트에 추가, 초과 시 대응 순서 확정 |

### 0.1 v3 → v4 변경점

| # | 내용 |
|---|---|
| ⑤ | §5.6 ADR 표의 "배포 = React(Vercel) + FastAPI/Postgres(Railway)" 행이 "무료/최소비용 티어" 한 줄로만 근거가 적혀 있어, 레이어별(프론트/백엔드/DB/임베딩모델/리랭커/캐시) 개별 선택 이유가 문서에 남아있지 않았음 → §5.7로 분리해 상세화 |

---

## 1. 프로젝트 목적 및 범위 (변경 없음)
- **목적**: 취업 포트폴리오용 — 완성도와 스토리(왜 이렇게 설계했는지 설명 가능한 것)가 최우선
- **MVP 범위**: RAG 검색 + 4줄 요약을 1차로 깊이 있게 구현. 키워드분석/인사이트는 v2(기능 버전).
- **데이터 범위**: partial/fallback 포함 전체 8만 건 사용 (파싱 품질 플래그로 신뢰도 구분)

---

## 2. 요구사항 정의 (v2와 동일)

| ID | 내용 | 상태 |
|---|---|---|
| FR1 | 키워드/자연어 입력 → 유사 감사사례 Top-10 검색 (하이브리드: RRF + 리랭커) | **확정** |
| FR2 | 검색결과 클릭 → 사례 상세페이지 (문서 원문 전체 표시) | 변경 없음 |
| FR3 | 상세페이지에 4줄 요약(지적사항/원인/조치/결과 구조) 자동 표시 | **확정** |
| FR4 | 파싱 품질에 따른 신뢰도 배지 표시 | 변경 없음 |
| FR5 (기관/연도 필터) | v1에서 **제외**, v1.1로 이연 | **확정** |

---

## 3. RAG 검색 스코어링 설계

### 3.1 왜 RRF(Reciprocal Rank Fusion)인가
벡터 유사도(코사인, 0~1)와 전문검색 점수(`ts_rank`, 스케일 비고정)는 단순 합산 시 한쪽이 항상 우세해지는 문제가 있음. RRF는 점수 대신 **순위**를 합산하기 때문에 스케일 문제에서 자유롭고, 튜닝 파라미터가 상수 k 하나뿐이라 개인 프로젝트 규모에 적합.
```
score(doc) = Σ  1 / (k + rank_i(doc))     (k = 60, 표준값)
```

### 3.2 검색 SQL — document 단위 dedup 반영 (v3 변경)

> **변경 이유(②)**: 기존 SQL은 `chunk_id` 기준 Top-10만 반환해, 한 문서에서 여러 청크가 동시에 상위권에 오르면 검색결과 카드 10개 중 여러 개가 같은 사례로 중복 노출될 수 있었음. FR2 기준 카드는 "사례(문서) 단위"이므로, RRF 스코어링 이후 `document_id`별 최고점 청크 1개만 남기는 dedup을 추가.

```sql
WITH vector_search AS (
  SELECT id AS chunk_id, document_id,
         ROW_NUMBER() OVER (ORDER BY embedding <=> :query_embedding) AS rank
  FROM chunks
  ORDER BY embedding <=> :query_embedding
  LIMIT 50
),
text_search AS (
  SELECT id AS chunk_id, document_id,
         ROW_NUMBER() OVER (
           ORDER BY ts_rank(tsv, plainto_tsquery('simple', :query_tokens)) DESC
         ) AS rank
  FROM chunks
  WHERE tsv @@ plainto_tsquery('simple', :query_tokens)
  LIMIT 50
),
rrf_scored AS (
  SELECT
    COALESCE(v.chunk_id, t.chunk_id)       AS chunk_id,
    COALESCE(v.document_id, t.document_id) AS document_id,
    (1.0 / (60 + COALESCE(v.rank, 1000))) +
    (1.0 / (60 + COALESCE(t.rank, 1000))) AS score
  FROM vector_search v
  FULL OUTER JOIN text_search t ON v.chunk_id = t.chunk_id
),
doc_deduped AS (
  -- 문서(사례)당 최고 점수 청크 1개만 남김 → 카드 중복 방지
  SELECT DISTINCT ON (document_id)
    chunk_id, document_id, score
  FROM rrf_scored
  ORDER BY document_id, score DESC
)
SELECT chunk_id, document_id, score
FROM doc_deduped
ORDER BY score DESC
LIMIT 20;   -- 리랭커 입력 후보 (문서 기준 20건). 최종 응답은 리랭커 이후 top-10
```

- `:query_tokens`는 3.6에서 설명하는 형태소 토큰화 결과(전문검색 leg 전용). `:query_embedding`은 원문 그대로 인코딩한 벡터.
- 벡터 검색 전용 후보 / 텍스트 검색 전용 후보 모두 결과에 포함 (FULL OUTER JOIN)
- 이 단계의 출력은 **문서 20건**이며, 이후 리랭커가 최종 Top-10으로 압축

### 3.3 쿼리 임베딩 (온라인 추론)
- 배치와 달리 **검색 시점에 실시간으로** 쿼리 텍스트를 BGE-m3로 인코딩해야 함
- FastAPI 프로세스 시작 시 모델을 한 번 로드해 재사용 (요청마다 로드하면 지연시간 폭증)
```python
# 앱 시작 시 1회
model = SentenceTransformer("BAAI/bge-m3", device="cpu")  # Railway는 보통 GPU 없음
model.half()
model.max_seq_length = 512
# 요청마다
query_vec = model.encode([query_text], normalize_embeddings=True)[0]
```
> Railway는 CPU 인스턴스인 경우가 많아 쿼리 1건 인코딩(512토큰 이하)은 보통 100ms 이내 — NFR2(1~2초) 충족에 문제 없음.

### 3.4 리랭커 (Reranker) — MVP(v1) 포함으로 확정 (v3, 모순 해소)

> **변경 이유(①)**: v2에서 §3.4는 "리랭커 v1에 추가 확정"이라 서술했지만, §5.6 ADR 요약표에는 "리랭커 미도입(MVP) — v1.1에서 추가"라는 상반된 행이 남아 있었음. 두 서술이 공존하면 실제 구현 여부를 문서만으로 판단할 수 없어, **리랭커는 MVP(v1)에 포함**하는 쪽으로 확정하고 ADR 표의 모순 행은 제거함(§5.6 참조).

RRF로 뽑아 document 단위로 dedup한 20건을 크로스인코더로 한 번 더 정밀 채점하는 2단계 검색.

```python
from sentence_transformers import CrossEncoder
reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")  # 앱 시작 시 1회 로드

# 3.2 SQL 결과로 얻은 document 20건의 대표 청크 원문을 chunk_id로 재조회
candidate_texts = fetch_chunk_texts(chunk_ids)  # SELECT text FROM chunks WHERE id = ANY(:ids)

pairs = [(query_text, text) for text in candidate_texts]
scores = reranker.predict(pairs)
# scores 기준 재정렬 후 top-10 문서만 최종 반환
```

- 흐름: **RRF(청크 50개 후보) → document 단위 dedup(문서 20건) → 리랭커(20건 재채점) → 최종 Top-10 문서 카드 반환**
- 오픈소스 모델(`bge-reranker-v2-m3`) 사용 시 API 비용 없음, 검색 API 서버(Railway)에 상시 로드해두고 재사용
- 지연시간 영향: 20개 쌍 재채점은 CPU 기준 수백 ms 수준 — NFR2(1~2초) 예산 안에서 흡수 가능
- 리랭커 타임아웃/예외 시 폴백: RRF+dedup 결과(리랭커 이전 순위)를 그대로 반환 — 검색 자체가 죽는 상황은 구조적으로 방지

### 3.5 임베딩+리랭커 동시 로드 메모리 예산 재계산 (v3 신규)

> **변경 이유(④)**: v2는 BGE-m3(FP16, ~1.1GB) 단독 기준으로만 메모리를 언급했으나, 실제로는 리랭커(`bge-reranker-v2-m3`)도 같은 FastAPI 프로세스에 **동시에** 상시 로드된다. 두 모델을 합산한 예산 재계산이 빠져 있었음.

| 구성요소 | FP32 추정 | FP16 추정 |
|---|---|---|
| BGE-m3 (임베딩, ~568M 파라미터) | ~2.2GB | ~1.1GB |
| bge-reranker-v2-m3 (리랭커, 동일 backbone 계열) | ~2.2GB | ~1.1GB |
| **모델 가중치 합산** | ~4.4GB | **~2.2GB** |
| FastAPI/Python 런타임 + 요청 처리 오버헤드 | — | +0.3~0.5GB |
| **실사용 RSS 예상치** | — | **~2.5~3GB** |

이 수치는 두 모델을 동시에 올리는 순간 개인 프로젝트용 최소/무료 티어 메모리 상한을 넘길 가능성이 높다는 뜻이므로, "확인 필요"로 남겨두지 않고 아래 순서로 **배포 전에 실측 기반으로 확정**한다.

1. **실측 우선**: 로컬(또는 Railway와 동일 스펙 컨테이너)에서 두 모델을 FP16으로 동시 로드한 뒤 실제 RSS를 측정 (`/usr/bin/time -v`, 또는 `docker run --memory=<Railway플랜상한>`으로 재현). 이 결과를 §6 체크리스트에 배포 전 필수 항목으로 추가.
2. 예산 초과 시 1순위 대응: 리랭커를 int8 동적 양자화(`onnxruntime` 또는 `bitsandbytes`)로 축소 — 추론 정확도 손실 최소화하며 메모리 절반 이하로 축소 가능
3. 그래도 부족하면: Railway 플랜을 개인 프로젝트가 감당 가능한 최소 유료 티어로 상향 (배포 직전 최신 요금/메모리 한도를 Railway 대시보드에서 재확인 — 문서 작성 시점 수치를 그대로 신뢰하지 않음)
4. 최후수단: 리랭커를 별도 워커/프로세스로 분리해 필요 시에만 lazy load (콜드스타트 지연 트레이드오프를 감수)
- 후보 개수(20→10)를 줄이는 것은 **추론 배치 크기**에만 영향을 주고 상시 로드된 모델 가중치 자체의 메모리는 줄이지 못하므로, 메모리 문제의 근본 대응책은 아님 (지연시간 개선 목적일 때만 유효)

### 3.6 한국어 전문검색 — 형태소 토큰화 (v3 신규)

> **변경 이유(③)**: PostgreSQL의 `to_tsvector('simple', ...)` / `plainto_tsquery('simple', ...)`는 공백·구두점 기준 토큰화만 수행하고 한국어 형태소 분석을 하지 않는다. "예산 낭비"로 검색해도 원문에 "예산낭비가"처럼 조사가 붙어 있으면 매칭되지 않을 수 있어, 하이브리드 검색의 절반 축(전문검색)이 사실상 정상 동작하지 않을 위험이 있었음.

**해결 방식**: Postgres 확장(`pg_bigm` 등) 설치 대신, 애플리케이션 레벨에서 형태소 분석기로 사전 토큰화 후 `simple` 사전에 태워서 인덱싱/검색한다. `pg_bigm`은 Railway 관리형 Postgres에서 임의 확장 설치가 가능한지 사전 보장이 안 되는 반면, 이 방식은 순수 Python 레이어에서만 처리되어 배포 환경에 의존하지 않는다.

- **형태소 분석기 선택: `kiwipiepy`** — 시스템 레벨 mecab 바이너리 설치가 필요 없는 순수 Python 패키지라 Railway 빌드팩에서 별도 apt 의존성 없이 pip 설치만으로 동작. (`konlpy`+시스템 mecab-ko 조합은 빌드 환경에 따라 깨지기 쉬워 배제)
- **배치(색인 시점, Colab)**: 청크 원문을 형태소 분석해 토큰을 공백으로 join한 컬럼을 별도로 저장하고, 그 컬럼으로부터 `tsvector`를 생성

```sql
ALTER TABLE chunks ADD COLUMN tsv_text text;   -- 형태소 토큰을 공백 join한 값 (배치 시 채움)
ALTER TABLE chunks ADD COLUMN tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', tsv_text)) STORED;
CREATE INDEX ON chunks USING GIN (tsv);
```

- **온라인(검색 시점, FastAPI)**: 쿼리 텍스트도 동일한 토큰화 로직을 거쳐야 배치 시점 인덱스와 매칭 기준이 일치함

```python
from kiwipiepy import Kiwi
kiwi = Kiwi()  # 앱 시작 시 1회 로드 (임베딩/리랭커와 동일한 패턴)

def tokenize_query(text: str) -> str:
    tokens = kiwi.tokenize(text)
    # 명사/동사/부사 위주로 추출 — 조사·어미 등 기능어 제거
    return " ".join(t.form for t in tokens if t.tag.startswith(("N", "V", "MAG")))

query_tokens = tokenize_query(query_text)   # 3.2 SQL의 :query_tokens 파라미터로 전달
```

- 배치·온라인 양쪽에서 **동일한 토큰화 함수**를 쓰는 것이 핵심 — 색인과 쿼리의 토큰화 기준이 어긋나면 매칭 자체가 깨짐. 배치 스크립트와 FastAPI 서버가 같은 tokenize 함수를 import하도록 공통 모듈로 분리 권장.
- 실제 매칭 품질 개선 여부는 §5.3 오프라인 eval set으로 "형태소 토큰화 적용 전/후" 비교표를 만들어 수치로 증명 (설계만으로는 완전히 검증되지 않는 부분 — §7 참고)

### 3.7 전체 시스템 아키텍처 다이어그램 (v3 갱신)

```
┌─────────────────────────────────────────────────────────────┐
│  오프라인 배치 (1회 실행)                                        │
│  파싱 → 청킹 → 형태소 토큰화(kiwipiepy) → 임베딩(BGE-m3, Colab GPU)│
│       → 4줄요약(LLM 배치)                                       │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              [ pgvector 적재 스크립트 ]
   embed_ready.jsonl + embeddings.npy + tsv_text + summary
                → chunks/documents 테이블
                          │
                          ▼
              PostgreSQL + pgvector (Railway)
                          ▲
                          │  (읽기 전용)
┌─────────────────────────┴─────────────────────────────────────┐
│  온라인 서비스 경로 (사용자 요청마다)                              │
│                                                                │
│  사용자 검색어                                                   │
│     │                                                          │
│     ▼                                                          │
│  [ LRU 캐시 조회 ] ── hit ──▶ 캐시된 결과(top-10 문서) 반환         │
│     │ miss                                                     │
│     ▼                                                          │
│  [ 쿼리 임베딩 (BGE-m3) ]   [ 쿼리 형태소 토큰화 (kiwipiepy) ]      │
│    FastAPI 상시 로드, CPU     텍스트검색 leg 전용                   │
│     │                             │                            │
│     ▼                             ▼                            │
│  [ 검색 API — RRF(벡터검색 + 전문검색) ]                          │
│     │                                                          │
│     ▼                                                          │
│  [ document_id 단위 dedup — 문서 20건으로 압축 ]                  │
│     │                                                          │
│     ▼                                                          │
│  [ 리랭커 (크로스인코더, bge-reranker-v2-m3) — 20건 재채점 ]        │
│     │                                                          │
│     ▼                                                          │
│  최종 top-10 문서 ──▶ 캐시 저장                                  │
│     │                                                          │
│     ▼                                                          │
│  검색결과 카드 (React/Vercel)                                    │
│     │ 클릭                                                      │
│     ▼                                                          │
│  [ 상세 API — 문서 전체 + 4줄요약 반환 ]                           │
│     │                                                          │
│     ▼                                                          │
│  상세페이지 (원문 + 요약 + 신뢰도 배지)                             │
└─────────────────────────────────────────────────────────────────┘
```

핵심 변경점(v2 대비):
- 임베딩 모델 + 리랭커 모델이 **동시에 상시 로드**된다는 사실을 다이어그램에서도 명확히 표시 → §3.5 메모리 예산과 바로 연결되도록
- `document_id` dedup 단계를 RRF와 리랭커 사이에 명시적으로 배치 → 카드 중복 방지 로직이 "어디서" 일어나는지 다이어그램만 봐도 알 수 있게 함
- 텍스트검색 leg에 쿼리 형태소 토큰화 단계 추가 (임베딩과 별개 경로)
- 배치 파이프라인은 여전히 **쓰기 전용**, 온라인 경로는 **읽기 전용** — 이 원칙은 v2와 동일하게 유지

---

## 4. 4줄 요약 생성 설계 (v2와 동일, 변경 없음)

### 4.1 구조 고정
```
1줄: 지적사항 (무엇이 문제였는지)
2줄: 원인/경위
3줄: 조치사항 (시정/개선 요구)
4줄: 처리결과 (원문에 없으면 "처리결과 미기재")
```

### 4.2 프롬프트 골격
```
아래 감사 사례 원문을 읽고 정확히 4줄로 요약해라.
1줄: 지적사항 한 문장
2줄: 원인/경위 한 문장
3줄: 조치사항 한 문장
4줄: 처리결과 한 문장 (원문에 결과 정보가 없으면 "처리결과 미기재"로 표시)
원문:
{raw_text}
```

### 4.3 parsing_quality별 처리 규칙
| parsing_quality | 처리 방식 |
|---|---|
| standard | 정상 생성 |
| partial / fallback | 정상 생성 + "일부 내용만으로 생성된 요약입니다" 배너 표시 |
| extraction_failed | 요약 생성 대상 제외 (청킹도 이미 제외되어 일관성 유지) |

### 4.4 모델/비용
- 8만 건 1회성 배치 → Claude Haiku 등 저비용 모델로 충분
- 배치 실행 시 rate limit 대응을 위해 동시 요청 수 제한 + 실패 시 재시도(exponential backoff) 필요

---

## 5. 고도화 항목 (v2와 동일, 변경 없음)

### 5.1 HNSW 인덱스 파라미터 튜닝
```sql
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
SET hnsw.ef_search = 40;
```

### 5.2 검색 캐싱
- in-memory LRU 캐시 (`functools.lru_cache`), 캐시 키: `(query_text 정규화, top_n)`
- **주의**: uvicorn을 멀티 워커로 띄우면 워커별로 캐시가 분리되어 히트율이 떨어짐 → 개인 프로젝트 규모에서는 단일 워커로 고정하는 것을 전제로 함 (§5.6 ADR에 명시)

### 5.3 검색 품질 평가
- 수작업으로 20~30개 쿼리-정답 쌍 오프라인 eval set 구성
- RRF vs 벡터 단독 vs 텍스트 검색 단독 vs (RRF+리랭커) 비교표
- v3 추가: **형태소 토큰화 적용 전/후** 비교도 이 eval set으로 함께 측정 (§3.6 검증 근거)

### 5.4 모니터링/로깅
- 배치 스크립트 실패 항목 로그 (`failed_batch.log`)
- 검색 API 응답시간 로깅 → NFR2(1~2초) 충족 여부를 캐시 hit/miss별로 수치 제시

### 5.5 비용 추정
| 항목 | 추정 |
|---|---|
| 임베딩 생성 | Colab GPU 1회성, 비용 없음(무료 티어) 또는 Pro 요금만 |
| 4줄 요약 8만 건 | 저비용 LLM 기준 소액 (실측치는 배치 실행 후 문서에 기록) |
| 배포 | Vercel(프론트) + Railway(백엔드/DB) — 리랭커 동시 로드로 인해 최소 유료 티어가 필요할 가능성 높음(§3.5) |

### 5.6 주요 설계 결정 근거 (ADR 요약 — v3 갱신, 모순 행 제거)

| 결정 | 근거 |
|---|---|
| 검색 단위 = 청크, 상세 단위 = 문서 | 유사사례 검색 시 관련 없는 지적사항까지 섞이는 노이즈 방지, 상세페이지는 원문 전체 맥락 필요 |
| 스코어링 = RRF | 벡터·전문검색 점수 스케일이 달라 단순 합산은 한쪽 우세 문제 발생. RRF는 순위 기반이라 스케일 무관 |
| **리랭커(bge-reranker-v2-m3)를 MVP(v1)에 포함** *(v3 확정)* | RRF만으로는 순위 기반 융합의 한계(둘 다 하위권인 후보가 과대평가될 수 있음)가 있어, 오픈소스 크로스인코더로 2차 정밀 채점. API 비용 없이 상시 로드로 지연시간 예산(NFR2) 내 흡수 가능 |
| **RRF 이후 document_id 기준 dedup 추가** *(v3 신규)* | 검색은 청크 단위, 카드 UI는 문서 단위이므로 dedup 없이는 카드가 같은 사례로 중복될 수 있음 |
| **한국어 전문검색은 kiwipiepy 사전 토큰화 방식 채택** *(v3 신규)* | Postgres `simple` 사전은 형태소 분석을 하지 않아 조사/어미 매칭 실패. Postgres 확장(pg_bigm 등) 설치는 Railway 관리형 환경에서 보장이 안 되므로, 배포 환경에 의존하지 않는 애플리케이션 레벨 토큰화(순수 Python, 시스템 mecab 불필요)를 선택 |
| **임베딩+리랭커 동시 로드 메모리는 실측 후 확정** *(v3 신규)* | 두 모델 합산 시 개인 프로젝트 최소 티어를 초과할 가능성이 있어, "충분할 것"이라는 가정 대신 배포 전 실측 → 초과 시 양자화/플랜 상향 순으로 대응하는 프로세스를 미리 확정 |
| 4줄 요약 구조 고정 | 자유형식은 LLM 출력 편차가 커서 프론트 렌더링 불안정. 구조 고정 시 파싱·표시 로직 단순화 |
| extraction_failed는 요약도 제외 | 원문 자체가 없어 요약 생성이 불가능/무의미 — 청킹 제외와 일관성 유지 |
| 쿼리 임베딩은 배치 모델과 별도 인스턴스(FastAPI 상시 로드) | 배치(Colab GPU)와 온라인 서비스(Railway CPU) 환경이 달라 같은 모델 로딩 방식을 그대로 쓸 수 없음 |
| 캐싱은 Redis 대신 in-memory LRU, 단일 워커 전제 | 개인 프로젝트 규모(단일 인스턴스)에서 별도 캐시 서버 운영은 과한 인프라 복잡도. 멀티 워커 시 캐시 분산 문제가 있어 단일 워커로 고정 |
| 임베딩 = BGE-m3 로컬(Colab GPU) | 1회성 배치라 API 반복 비용 없음, 한국어 다국어 지원 우수 |
| 배치 = 1회 실행 (스케줄러 없음) | 신규 데이터 유입 없는 전제, Airflow 등 불필요한 인프라 복잡도 회피 |
| 배포 = React(Vercel) + FastAPI/Postgres(Railway) | 무료/최소비용 티어로 개인 프로젝트 규모에 적합. 레이어별 상세 근거는 §5.7 참고 |

### 5.7 기술 스택 선택 근거 (v4 신규)

> 5.6의 ADR 표는 "결정 → 근거"를 한 줄로 요약한 것이라, 레이어별로 왜 그 대안을 골랐는지(다른 대안과 비교했을 때의 트레이드오프)가 드러나지 않았음. 아래는 레이어별 선택 이유를 조금 더 풀어서 정리한 것.

| 레이어 | 선택 | 이유 |
|---|---|---|
| **백엔드 프레임워크** | FastAPI | 이 프로젝트의 전제 조건에 가까운 선택. BGE-m3(임베딩)·kiwipiepy(형태소분석)·CrossEncoder(리랭커)가 전부 Python 라이브러리라, 백엔드를 Node/Express 등으로 짰다면 이 모델들을 돌리기 위한 별도 Python 마이크로서비스를 분리해야 했음. FastAPI를 쓰면 **모델 상시로드 + API 서빙을 같은 프로세스**에서 처리할 수 있어 §3.5 아키텍처(오프라인 배치는 쓰기 전용, 온라인은 읽기 전용 단일 서비스)가 그대로 성립. Flask/Django 대비로는 비동기 지원과 Pydantic 기반 자동 타입검증·OpenAPI 문서화가 개인 프로젝트 규모에 가볍고 빠름 |
| **DB** | PostgreSQL + pgvector | 벡터검색(`pgvector`) + 전문검색(`ts_rank`) + 문서 메타데이터(관계형)를 **DB 하나로 통합**. 전용 벡터DB(Pinecone, Weaviate 등)를 썼다면 벡터 저장소와 메타데이터 저장소가 분리되어 조인/동기화 문제가 생겼을 것. 14만 청크 규모에서는 pgvector + HNSW 인덱스(§5.1) 성능으로 충분하고, 전용 벡터DB의 초대규모 확장성 이점은 이 프로젝트 규모에서 의미가 없음 |
| **프론트 프레임워크** | React (SPA, SSR 프레임워크 없이) | 검색페이지·상세페이지 2개짜리 단순 구조라 SSR/SEO가 필요 없음 → Next.js 등 풀프레임워크의 라우팅/서버 오버헤드는 불필요, 클라이언트에서 API fetch만 하면 되는 순수 React(Vite)로 충분. React 자체는 카드 UI·배지 등 반복되는 컴포넌트를 재사용하기 쉽고, 채용시장에서 표준 스택이라 포트폴리오 설명력도 있음 |
| **배포 — 프론트: Vercel / 백엔드·DB: Railway** | 개인 프로젝트라 비용이 1순위 제약. Railway는 매니지드 Postgres와 백엔드 앱을 한 플랫폼에서 같이 운영할 수 있어 인프라 관리 부담이 적고, Vercel은 React SPA 배포의 사실상 표준이며 무료 티어가 넉넉함 |
| **임베딩 모델** | BGE-m3 | 오픈소스라 API 반복 비용 없음(1회성 배치라 Colab GPU로 무료 처리), 다국어 지원 모델 중 한국어 성능이 검증된 축에 속함 |
| **리랭커** | bge-reranker-v2-m3 | BGE-m3와 같은 계열 모델이라 한국어 지원 수준이 일관되고, 같은 `sentence-transformers` API로 다뤄 새 생태계를 따로 학습할 필요가 없음. 오픈소스라 API 비용 없음 |
| **요약 LLM** | Claude Haiku | 8만 건 1회성 배치에서 프롬프트·출력이 둘 다 짧아 저비용 모델로도 §4.1 구조 고정 요약 품질이 충분, 대형 모델 대비 비용이 크게 낮음 |
| **캐시** | in-memory LRU (Redis 아님) | 단일 Railway 인스턴스로 운영하는 개인 프로젝트 규모에서 별도 캐시 서버를 두는 건 인프라 복잡도 대비 이득이 없음 (§5.2) |

공통 원칙 2가지: **① Python 생태계 통합** — ML 모델과 백엔드를 분리하지 않기 위해 FastAPI를 고른 것이 나머지 선택들의 전제가 됨. **② 개인 프로젝트 비용/운영 부담 최소화** — pgvector로 벡터DB를 통합하고, LRU로 Redis를 대체하고, 무료/최소 티어로 배포.

---

## 6. 진행 상황 (2026-08 기준, v3 갱신)
- [x] 8만 건 원본 파싱
- [x] 노이즈 제거 및 임베딩 대상 확정 (142,201건, embed_ready.jsonl)
- [~] BGE-m3 임베딩 생성 (거의 마무리 단계)
- [x] 하이브리드 검색 스코어링(RRF) 설계 확정
- [x] document 단위 dedup 로직 확정 *(v3)*
- [x] 한국어 형태소 토큰화(kiwipiepy) 설계 확정 *(v3)*
- [x] 4줄 요약 프롬프트/처리규칙 확정
- [ ] **배포 전 필수: 임베딩+리랭커 동시 로드 실측 RSS 측정** *(v3 신규, §3.5)*
- [ ] pgvector 적재 스크립트 (tsv_text 컬럼 포함)
- [ ] 검색 API / 상세 API 구현
- [ ] 프론트엔드 (검색페이지 / 상세페이지)
- [ ] 4줄 요약 배치 생성
- [ ] 검색 품질 오프라인 eval set 구성 (RRF/리랭커/토큰화 전후 비교 포함)

## 7. 설계 결정 완료 사항
- **extraction_failed 표시**: 별도 처리 불필요 — 청킹 대상에서 이미 제외
- **fallback 표시**: 검색 결과에서 제외/토글하지 않고 배지로만 표시
- **FR5(기관/연도 필터)**: v1 제외, v1.1로 이연
- **리랭커**: MVP(v1) 포함 *(v3 확정)*
- **검색 결과 dedup 단위**: document_id *(v3 확정)*
- **한국어 전문검색 토큰화**: kiwipiepy, 배치/온라인 공통 모듈로 통일 *(v3 확정)*
