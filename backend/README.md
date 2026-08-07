# 백엔드 (검색 API)

## 로컬 실행

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

cp .env.example .env   # DATABASE_URL, OPENAI_API_KEY 채워넣기
export $(cat .env | xargs)

uvicorn app.main:app --reload
```

서버 뜨면 `http://localhost:8000/docs`에서 Swagger UI로 바로 테스트 가능 (Postman 등 별도 설치 불필요).

## 엔드포인트

- `GET /health` — 서버 상태 확인
- `GET /search?q=검색어` — 자연어 검색 → 유사 사례 top 10 카드
- `GET /documents/{id}` — 상세 (원문 + 4줄 요약, 요약은 최초 조회 시 생성 후 캐싱)

## 아직 안 한 것 (스트레치 목표, architecture.md 참고)

- 리랭커(§3.4) — `app/repository.py`의 `rerank()`가 현재 no-op
- 한국어 형태소 토큰화(§3.6) — 검색어 원문을 그대로 키워드 검색에 사용 중
