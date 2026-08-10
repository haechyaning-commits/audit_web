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
