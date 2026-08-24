/** 최근 검색어 (localStorage, 최대 5개, 최신순, 중복 제거) */
const STORAGE_KEY = "recentSearches";
const MAX_ITEMS = 5;

export function getRecentSearches() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

export function addRecentSearch(query) {
  const trimmed = query.trim();
  if (!trimmed) return getRecentSearches();

  const existing = getRecentSearches().filter((q) => q !== trimmed);
  const updated = [trimmed, ...existing].slice(0, MAX_ITEMS);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  return updated;
}

/** 2026-08-24(피드백 반영): 최근 검색어는 로컬 저장이라 UI에서 지울 방법이 지금까지
 * 아예 없었음 — 이 서비스가 다루는 검색어 성격상(예: "직장 상사가 지속적으로 괴롭혀서
 * 신고하고 싶어요") 같은 기기를 다른 사람과 같이 쓰는 경우 신경 쓰일 수 있어서 추가.
 * 개별 삭제가 아니라 전체 지우기만 우선 제공(가장 저렴하면서 효과 큰 선). */
export function clearRecentSearches() {
  localStorage.removeItem(STORAGE_KEY);
  return [];
}
