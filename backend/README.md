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
- `GET /search?q=검색어` — 자연어 검색 → 유사 사례 top 10 카드
- `GET /documents/{id}` — 상세 (원문 + 4줄 요약, 요약은 최초 조회 시 생성 후 캐싱)

## 아직 안 한 것 (스트레치 목표, architecture.md 참고)

- 리랭커(§3.4) — `app/repository.py`의 `rerank()`가 현재 no-op
- 한국어 형태소 토큰화(§3.6) — 검색어 원문을 그대로 키워드 검색에 사용 중
