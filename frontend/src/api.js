/**
 * 백엔드 API 호출 래퍼.
 *
 * VITE_API_BASE_URL 환경변수로 백엔드 주소를 바꿀 수 있음 (.env.example 참고).
 * 로컬 개발에서 .env를 안 만들었으면 localhost:8000으로 기본 동작.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET" } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { method });
  } catch {
    // 네트워크 자체가 끊긴 경우 (서버 안 켜짐, CORS 차단 등)
    throw new ApiError("서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", 0);
  }

  if (!response.ok) {
    let detail = "요청을 처리하지 못했습니다.";
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // 에러 응답이 JSON이 아닐 수도 있음 — 기본 메시지 사용
    }
    throw new ApiError(detail, response.status);
  }

  return response.json();
}

/** 자연어 검색 → 유사 사례 카드 목록 (GET /search?q=...).
 * filters(선택): { institution, year, audit_type } — 다 없으면 기존과 동일한
 * URL(GET /search?q=...)이라 백엔드 쿼리 캐시/로그 등에 영향 없음(FR5, 2026-08-24). */
export function searchCases(query, filters = {}) {
  const params = new URLSearchParams({ q: query });
  if (filters.institution) params.set("institution", filters.institution);
  if (filters.year) params.set("year", filters.year);
  if (filters.audit_type) params.set("audit_type", filters.audit_type);
  return request(`/search?${params.toString()}`);
}

/** 검색 필터(기관/연도) 드롭다운용 값 목록 (GET /filters) — 페이지 로드 시 한 번만 호출 */
export function getFilterOptions() {
  return request("/filters");
}

/** 홈 화면 "연도별 사례 수" 막대그래프 + 전체 건수 (GET /stats/years) — 베타테스트 피드백
 * 5번(2026-08-25): 지금까지 SearchPage.jsx에 값이 하드코딩돼 있던 걸 라이브 집계로 대체.
 * 페이지 로드 시 한 번만 호출. */
export function getYearStats() {
  return request("/stats/years");
}

/** 사례 상세 — 원문 + (있으면) 캐싱된 요약. 요약 자동 생성은 안 함 (GET /documents/{id}) */
export function getCaseDetail(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}`);
}

/** 4줄 요약 온디맨드 생성 — "요약보기" 버튼 클릭 시에만 호출 (POST /documents/{id}/summary) */
export function getCaseSummary(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}/summary`, { method: "POST" });
}

/** 상세페이지 "유사 사례" 섹션 — 이 문서 자체를 쿼리로 삼은 벡터검색 결과(최대 5건).
 * 요약과 달리 LLM 호출이 아니라 순수 벡터검색이라 원문 로딩과 같이 자동 호출해도 됨
 * (GET /documents/{id}/similar). */
export function getSimilarCases(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}/similar`);
}

/** 홈 화면 "오늘의 사례" — 날짜 기준으로 결정적으로 고른 문서 1건(GET /documents/daily).
 * 같은 날 안에는 다시 불러도 항상 같은 문서. 페이지 로드 시 한 번만 호출. */
export function getDailyCase() {
  return request("/documents/daily");
}

/** 기관 프로필 미니페이지 — 이 기관의 전체 건수/연도별·감사종류별 분포/최신 사례
 * (GET /institutions/{name}). 존재하지 않는 기관명이면 404. */
export function getInstitutionProfile(name) {
  return request(`/institutions/${encodeURIComponent(name)}`);
}

export { ApiError };
