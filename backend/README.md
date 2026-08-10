# 백엔드 (검색 API)

## 로컬 실행

**Mac / Linux**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

cp .env.example .env   # DATABASE_URL, OPENAI_API_KEY 채워넣기
uvicorn app.main:app --reload
```

**Windows (PowerShell)**
```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

copy .env.example .env
# .env 파일 열어서 DATABASE_URL, OPENAI_API_KEY 채워넣기
uvicorn app.main:app --reload
```

`.env` 파일은 `python-dotenv`가 자동으로 읽어오므로, OS별로 환경변수를 따로 export할 필요
없음 — `.env` 파일에 값만 채워두면 Mac/Windows/Linux 어디서든 위 명령 그대로 실행됨.

DB는 로컬에 설치하는 게 아니라 `.env`의 `DATABASE_URL`을 통해 **Railway에 있는 실제 DB에
그대로 연결**하는 것 — 로컬엔 파이썬 서버 코드만 실행됨.

서버 뜨면 `http://localhost:8000/docs`에서 Swagger UI로 바로 테스트 가능 (Postman 등 별도 설치 불필요).

## 엔드포인트

- `GET /health` — 서버 상태 확인
- `GET /search?q=검색어` — 자연어 검색 → 유사 사례 top 20 카드
- `GET /documents/{id}` — 상세 (원문 + 이미 캐싱된 요약이 있으면 같이 반환, 없으면 null — 자동 생성 안 함)
- `POST /documents/{id}/summary` — 4줄 요약 온디맨드 생성(프론트 "요약보기" 버튼용), 최초 호출 시 생성 후 캐싱

## 코드 구조 (파일별 설명)

### 한 줄 요약
검색어가 들어오면 → `embedding.py`가 숫자(벡터)로 바꾸고 → `repository.py`가 그 숫자+원문으로
DB에서 벡터검색과 키워드검색을 RRF로 합쳐 찾고 → `db.py`가 그 DB 연결을 담당하고 →
`main.py`가 이 전부를 순서대로 지휘해서 응답을 만들고 → 상세페이지에서만 `summary.py`가
OpenAI로 4줄 요약을 만들어 캐싱한다.

### 전체 그림

```
사용자 브라우저
   │  GET /search?q=출장비
   ▼
main.py  ← 요청을 받아서 어디로 보낼지 결정 (라우팅, "지휘자")
   │
   ├─▶ embedding.py  ← "출장비"라는 글자를 숫자(벡터)로 변환
   │
   ├─▶ repository.py ← DB에 실제 SQL 쿼리 던짐 (벡터+키워드 검색)
   │        │
   │        ▼
   │      db.py      ← DB랑 연결 유지해주는 통로
   │
   └─▶ summary.py    ← (상세페이지일 때만) 4줄 요약 필요하면 OpenAI 호출
```

**왜 5개 파일로 나눴나**: 하나가 바뀌어도 나머지는 안 건드리게 하려고. DB를 옮기면 `db.py`만,
검색 로직을 바꾸면 `repository.py`만, 임베딩 모델을 바꾸면 `embedding.py`만, 요약 LLM을
바꾸면 `summary.py`만 고치면 됨.

### `db.py` — DB 연결 관리

- **역할**: DB와의 연결(커넥션 풀)을 만들고 관리. 실제 쿼리 내용은 모름
- **커넥션 풀이란**: 요청마다 DB에 새로 연결하면 느리므로, 미리 연결 몇 개(`min_size=1~max_size=5`)를
  만들어두고 재사용하는 것. 5라는 숫자는 포트폴리오 규모 트래픽(최악 동시요청 5건 정도)과
  요청당 짧은 점유시간을 계산해서 나온 값
- **`register_vector`**: pgvector의 `vector` 타입을 파이썬이 다룰 수 있는 형태로 변환해주는
  어댑터. 풀에서 새 연결이 생길 때마다 등록해야 함
- **왜 asyncpg(비동기)인가**: FastAPI를 고른 이유 중 하나가 비동기 지원인데, 동기 드라이버
  (psycopg2)를 쓰면 그 장점을 못 씀 — `async def` 안에서 동기 I/O를 부르면 이벤트 루프가 막혀서
  그 요청 처리 중엔 다른 요청도 다 같이 멈춤

### `repository.py` — 실제 SQL 쿼리 (핵심 로직)

검색 SQL을 4단계 `WITH` 절로 이해하면 쉬움:
1. **`vector_search`**: `embedding <=> $1`(벡터 거리)로 가장 비슷한 청크 50개, 순위 매김
2. **`text_search`**: `tsv @@ plainto_tsquery(...)`(키워드 매칭)로 상위 50개, 순위 매김
3. **`rrf_scored`**: 두 순위를 `1/(60+rank)` 공식(RRF)으로 점수화해서 더함. 점수(스케일이
   다른 것)를 직접 더치는 대신 순위로 통일해서 공평하게 합침. `FULL OUTER JOIN`이라 한쪽
   검색에만 뽑힌 것도 안 버림(없는 쪽은 1000등 취급 페널티)
4. **`doc_deduped`**: 같은 문서(document_id)에서 여러 청크가 뽑히면 점수 제일 높은 것 1개만
   남김 (카드가 같은 사례로 중복 노출되는 것 방지)
5. 마지막에 `documents` 테이블과 JOIN해서 기관명/연도/원문 미리보기 붙여서 반환

- **`rerank()`**: 리랭커(스트레치 목표) 자리를 미리 만들어둔 no-op 함수 — 지금은 받은 걸 그대로
  반환. 나중에 여기 내용만 채우면 되고 검색 흐름 전체를 다시 안 뜯어도 됨
- **`get_document` / `save_summary`**: 상세페이지용 문서 조회 / 온디맨드 생성한 요약 캐싱 저장

### `embedding.py` — 검색어 → 벡터 변환

- **`load_model()`**: BGE-m3 모델을 메모리에 로드 (서버 켤 때 딱 1번만 — 매 요청마다 하면
  느려짐)
- **`encode_query()`**: 문장을 1024차원 벡터로 변환. `normalize_embeddings=True`가 중요한
  이유 — 배치 임베딩(콜랩)도 정규화해서 저장했으므로, 검색어도 똑같이 정규화해야 같은
  기준으로 거리 비교가 의미 있음

### `summary.py` — 온디맨드 4줄 요약 생성

- **`PROMPT_TEMPLATE`**: "내용 없으면 OO 미기재라고 써라"는 탈출구 문구 포함 — AI가 없는
  내용을 지어내는 것 방지 (35건 실측 검증된 프롬프트)
- **`_call_once()`**: API 1번 호출 + 응답을 줄바꿈 기준으로 4줄 파싱. 4줄이 아니면 형식 깨진
  것으로 판단해 실패 처리
- **`_all_fallback()`**: 4줄 전부가 "미기재" 계열 문구면 사실상 요약 실패로 판단
- **`generate_summary()`**: 최대 2번(1차+재시도 1회) 시도. 둘 다 실패하면 `summary_failed=True`
  반환 — 이걸 DB에 캐싱해두면 다음 조회부터 재시도 안 해서 API 비용 낭비 방지

### `main.py` — 전체를 엮는 지휘자

- **`lifespan`**: 서버 켤 때 DB 풀 생성 + 임베딩 모델 로드(둘 다 딱 1번), 끌 때 DB 연결 정리.
  모델 로딩은 CPU 작업이라 `asyncio.to_thread`로 스레드에 맡겨서 이벤트 루프가 안 막히게 함
- **`/search`**: `q` 검사 → `embedding.encode_query` → `repository.search_candidates` →
  `repository.rerank`(현재 no-op) → 카드 목록으로 포장해서 반환. 계산은 직접 안 하고 다른
  파일들을 순서대로 불러 조합만 함
- **`/documents/{id}`** (GET): 문서 조회만 하고 바로 반환 — 요약 생성은 안 함(원문을 지연 없이
  보여주기 위함)
- **`/documents/{id}/summary`** (POST): 프론트 "요약보기" 버튼 클릭 시에만 호출됨.
  **`summary_point is None and not summary_failed`**일 때만 온디맨드로 요약 생성 + 저장 →
  이미 있으면(두 번째 호출부터) 이 블록을 건너뛰고 DB 값을 바로 반환 (캐싱이 일어나는 지점)

## 아직 안 한 것 (스트레치 목표, architecture.md 참고)

- 리랭커(§3.4) — `app/repository.py`의 `rerank()`가 현재 no-op
- 한국어 형태소 토큰화(§3.6) — 검색어 원문을 그대로 키워드 검색에 사용 중
