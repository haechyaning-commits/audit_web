# 프론트엔드 (검색 화면)

React(Vite) SPA. 검색페이지(자연어 검색창 + 결과 카드)와 상세페이지(4줄 요약 + 원문 펼쳐보기)로 구성.
디자인은 data.go.kr(공공데이터포털)이 실제로 쓰는 KRDS(정부디자인시스템) 컬러 토큰을 참고해서
"관공서/금융권" 톤으로 맞춤.

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
  api.js                API 호출 래퍼 (fetch, 에러 처리)
  App.jsx                라우팅 + 헤더/푸터/다크모드/sticky 헤더
  useTheme.js            다크모드 토글 (localStorage 저장, 없으면 시스템 설정 따름)
  recentSearches.js      최근 검색어 (localStorage, 최대 5개)
  highlight.jsx          검색어 하이라이트 (미리보기 텍스트 내 <mark> 처리)
  pages/
    SearchPage.jsx       검색창 + 결과 카드 목록 (GET /search), URL(?q=)과 검색 상태 동기화
    DetailPage.jsx       4줄 요약 + 원문 토글 + 관련 사례 + 스크롤 위로가기 (GET /documents/{id})
  components/
    ResultCard.jsx       검색 결과 카드 1개 (순위 배지 + 검색어 하이라이트)
    ConfidenceBadge.jsx  신뢰도 배지 ("신뢰도 높음" / "일부 참고")
    Footer.jsx            공통 푸터 (프로젝트 안내 + 웹접근성 문구)
```

## 환경변수

- `VITE_API_BASE_URL` — 백엔드 API 주소. 배포 시 Railway 백엔드 URL로 변경 (Vercel 프로젝트 환경변수에 등록).

## 주요 UX 디테일

- **URL 쿼리 동기화** — 검색어가 `?q=`로 URL에 반영되어 링크 공유/새로고침/뒤로가기가 자연스러움.
  상세페이지도 `/documents/{id}?q=검색어` 형태로 이동하므로, 새로고침해도 같은 검색어로 다시 API를
  호출해서 "관련 사례" 섹션을 채울 수 있음 (검색 컨텍스트 없이 URL로 직접 들어오면 관련 사례
  섹션은 자연스럽게 숨김).
- **`/` 단축키** — 다른 입력창에 포커스가 없을 때 `/`를 누르면 검색창으로 포커스 이동.
- **최근 검색어** — 검색 성공 시 localStorage에 저장, 있으면 예시 검색어 대신 표시.
- **다크모드** — 헤더의 토글 버튼으로 명시적 전환 가능, 선택값은 localStorage에 저장. 토글한 적
  없으면 시스템 설정(`prefers-color-scheme`)을 따름.
- 상세페이지 최초 조회 시 백엔드가 OpenAI로 요약을 온디맨드 생성하므로 몇 초 걸릴 수 있음 (두 번째
  조회부터는 DB 캐시라 빠름) — 로딩 메시지에 안내 문구 포함.
- `summary_failed=true`(요약 생성 2회 실패, backend `summary.py`)인 문서는 4줄 요약 대신 "요약
  어려움 — 원문 참고 필요" 안내를 보여줌.
