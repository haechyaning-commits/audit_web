import { useCallback, useRef, useState } from "react";
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
  // 2026-08-24(FR5): 마지막으로 실제 적용된 필터 — SearchPage가 필터 드롭다운
  // 초기값을 검색 결과와 맞게 보여주는 데 씀(예: URL로 필터가 걸린 링크로 바로 들어온 경우).
  const [appliedFilters, setAppliedFilters] = useState({});
  // 2026-08-24(FR5 2차 — 고정 사이드바 필터): 필터 없이 검색했을 때의 결과.
  // FilterSidebar가 "어떤 기관/연도/감사유형이 있는지(칩 목록 자체)"와 "각각 몇 건인지"를
  // 계산하는 기준으로 씀 — results(필터 적용된 실제 검색 결과)로 이걸 계산하면, 이미
  // 기관으로 필터링된 상태에서는 다른 기관들이 화면에서 아예 사라져버려서 "다른 기관으로
  // 바꿔보기"가 안 됨(칩 자리 고정 요구사항과 충돌). baseResults는 필터와 무관하게
  // "이 검색어 전체에서 뭐가 있었는지"를 유지해서 칩 목록/순서의 기준이 되고, results는
  // 화면에 실제로 보여줄 목록(필터 적용됨)으로 역할을 분리함.
  const [baseResults, setBaseResults] = useState(null);
  // baseResults가 어느 검색어 기준으로 계산된 것인지 — 검색어 자체가 바뀌면(필터만
  // 바뀐 게 아니라) baseResults도 새로 받아와야 하므로 추적.
  const baseQueryRef = useRef("");

  // 헤더 로고/타이틀 클릭 시 진짜 첫 화면(히어로)으로 되돌아가기 위한 초기화.
  // Link to="/"만으로는 URL만 바뀌고 이 훅의 results가 안 지워져서, 검색 결과 화면이
  // "/"에서도 그대로 남아있는 문제가 있었음.
  const resetSearch = useCallback(() => {
    setResults(null);
    setSearchedQuery("");
    setError(null);
    setAppliedFilters({});
    setBaseResults(null);
    baseQueryRef.current = "";
  }, []);

  const runSearch = useCallback(async (q, filters = {}) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    const hasFilters = Boolean(filters.institution || filters.year || filters.audit_type);

    setLoading(true);
    setError(null);
    try {
      // 필터가 걸려있고, baseResults가 지금 검색어 기준이 아니면(검색어 자체가 방금
      // 바뀐 경우) 필터 없는 기준 결과도 같이 받아옴 — 사이드바 칩 목록/순서 갱신용.
      // 필터가 없으면 어차피 이 결과 자체가 기준이라 따로 안 받아도 됨.
      const needFreshBase = hasFilters && trimmed !== baseQueryRef.current;
      const [data, baseData] = await Promise.all([
        searchCases(trimmed, filters),
        needFreshBase ? searchCases(trimmed, {}) : Promise.resolve(null),
      ]);
      setResults(data.results);
      setSearchedQuery(trimmed);
      setAppliedFilters(filters);
      setRecentSearches(addRecentSearch(trimmed));
      if (!hasFilters) {
        setBaseResults(data.results);
        baseQueryRef.current = trimmed;
      } else if (baseData) {
        setBaseResults(baseData.results);
        baseQueryRef.current = trimmed;
      }
    } catch (err) {
      setError(err.message || "검색 중 오류가 발생했습니다.");
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    results,
    baseResults,
    searchedQuery,
    loading,
    error,
    recentSearches,
    appliedFilters,
    runSearch,
    resetSearch,
  };
}
