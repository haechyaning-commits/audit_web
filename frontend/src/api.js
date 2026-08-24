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
 * filters(선택): { institution, year } — 둘 다 없으면 기존과 동일한 URL(GET
 * /search?q=...)이라 백엔드 쿼리 캐시/로그 등에 영향 없음(FR5, 2026-08-24). */
export function searchCases(query, filters = {}) {
  const params = new URLSearchParams({ q: query });
  if (filters.institution) params.set("institution", filters.institution);
  if (filters.year) params.set("year", filters.year);
  return request(`/search?${params.toString()}`);
}

/** 검색 필터(기관/연도) 드롭다운용 값 목록 (GET /filters) — 페이지 로드 시 한 번만 호출 */
export function getFilterOptions() {
  return request("/filters");
}

/** 사례 상세 — 원문 + (있으면) 캐싱된 요약. 요약 자동 생성은 안 함 (GET /documents/{id}) */
export function getCaseDetail(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}`);
}

/** 4줄 요약 온디맨드 생성 — "요약보기" 버튼 클릭 시에만 호출 (POST /documents/{id}/summary) */
export function getCaseSummary(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}/summary`, { method: "POST" });
}

export { ApiError };
