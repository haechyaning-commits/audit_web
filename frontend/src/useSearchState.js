import { useCallback, useState } from "react";
import { searchCases } from "./api.js";
import { addRecentSearch, getRecentSearches } from "./recentSearches.js";

/**
 * 검색 상태를 App 레벨로 끌어올린 훅.
 *
 * 헤더 검색창(HeaderSearch)과 검색페이지(SearchPage) 히어로 검색창이 이 훅 하나를
 * 공유해서, 어느 쪽에서 검색해도 같은 results를 바라봄 — 그래서 상세페이지에서
 * 헤더로 새로 검색해도 "/"로 돌아갔을 때 방금 검색한 결과가 그대로 보임.
 *
 * 네비게이션(URL 이동)은 이 훅의 책임이 아니고 호출하는 쪽에서 처리함 — 이미 "/"에
 * 있을 때는 setSearchParams로 조용히 URL만 바꾸면 되고, 다른 페이지(상세페이지 등)에서
 * 부르는 헤더 검색은 navigate로 "/"까지 이동해야 해서 필요한 동작이 다르기 때문.
 */
export default function useSearchState() {
  const [results, setResults] = useState(null); // null = 아직 검색 안 함
  const [searchedQuery, setSearchedQuery] = useState(""); // 실제로 검색이 실행된 검색어 (하이라이트용)
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [recentSearches, setRecentSearches] = useState(getRecentSearches);

  const runSearch = useCallback(async (q) => {
    const trimmed = q.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    try {
      const data = await searchCases(trimmed);
      setResults(data.results);
      setSearchedQuery(trimmed);
      setRecentSearches(addRecentSearch(trimmed));
    } catch (err) {
      setError(err.message || "검색 중 오류가 발생했습니다.");
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, []);

  return { results, searchedQuery, loading, error, recentSearches, runSearch };
}
