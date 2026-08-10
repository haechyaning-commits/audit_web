# 프론트엔드 (검색 화면)

React(Vite) SPA. 검색페이지(자연어 검색창 + 결과 카드)와 상세페이지(4줄 요약 + 원문 펼쳐보기)로 구성.

## 로컬 실행

```bash
cd frontend
npm install
cp .env.example .env   # 필요하면 VITE_API_BASE_URL 수정 (기본값: http://localhost:8000)
npm run dev
```

백엔드(`../backend`)를 먼저 `uvicorn app.main:app --reload`로 띄워둬야 검색/상세 API가 응답함.
백엔드 CORS 설정이 `http://localhost:5173`(Vite 기본 포트)을 기본 허용하므로 포트를 바꾸지 않으면
별도 설정 없이 바로 연동됨.

## 빌드

```bash
npm run build   # dist/ 생성, Vercel 등에 그대로 배포
```

## 구조

```
src/
  api.js              API 호출 래퍼 (fetch, 에러 처리)
  App.jsx             라우팅 (/  → 검색, /documents/:id → 상세)
  pages/
    SearchPage.jsx     검색창 + 결과 카드 목록 (GET /search)
    DetailPage.jsx     4줄 요약 + 원문 토글 + 신뢰도 배지 (GET /documents/{id})
  components/
    ResultCard.jsx     검색 결과 카드 1개
    ConfidenceBadge.jsx 신뢰도 배지 ("신뢰도 높음" / "일부 참고")
```

## 환경변수

- `VITE_API_BASE_URL` — 백엔드 API 주소. 배포 시 Railway 백엔드 URL로 변경 (Vercel 프로젝트 환경변수에 등록).

## 참고

- 상세페이지 최초 조회 시 백엔드가 OpenAI로 요약을 온디맨드 생성하므로 몇 초 걸릴 수 있음 (두 번째 조회부터는 DB 캐시라 빠름) — 로딩 메시지에 안내 문구 포함.
- `summary_failed=true`(요약 생성 2회 실패, backend `summary.py`)인 문서는 4줄 요약 대신 "요약 어려움 — 원문 참고 필요" 안내를 보여줌.
