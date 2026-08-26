import { useCallback, useRef, useState } from "react";
import { searchCases } from "./api.js";
import { addRecentSearch, clearRecentSearches, getRecentSearches } from "./recentSearches.js";

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
  // 2026-08-26(기능 교체): 처음엔 연도별 분포였다가 "관련 법령 모아보기"로 교체(연도
  // 분포는 사이드바 필터와 정보가 겹쳐서). /search 응답의 related_laws 필드를 results와
  // 별도로 보관 — results처럼 카드 배열이 아니라 화면 상단 칩 목록 하나에만 쓰임.
  const [relatedLaws, setRelatedLaws] = useState(null);
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
  // 2026-08-24(피드백 반영): 필터를 빠르게 연달아 클릭하면(예: 응답 오기 전에 다른 필터
  // 또 클릭) runSearch가 겹쳐서 여러 번 실행되는데, 지금까지는 "먼저 도착한 응답"이 아니라
  // "나중에 도착한 응답"이 항상 상태를 덮어썼음 — 네트워크 지연 때문에 나중에 누른 필터의
  // 응답이 먼저 오고, 먼저 눌렀던(이미 낡은) 필터 응답이 뒤늦게 도착하면 화면의 필터 체크
  // 상태와 실제 결과 목록이 어긋나는 경합 조건(race condition)이 됨. 요청마다 순번을 매겨서,
  // 응답이 왔을 때 그게 여전히 "가장 최근에 보낸 요청"일 때만 상태를 반영하도록 함.
  const requestIdRef = useRef(0);

  // 헤더 로고/타이틀 클릭 시 진짜 첫 화면(히어로)으로 되돌아가기 위한 초기화.
  // Link to="/"만으로는 URL만 바뀌고 이 훅의 results가 안 지워져서, 검색 결과 화면이
  // "/"에서도 그대로 남아있는 문제가 있었음.
  const resetSearch = useCallback(() => {
    setResults(null);
    setRelatedLaws(null);
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
    const requestId = ++requestIdRef.current;
    // 이 호출이 여전히 "가장 최근에 보낸 요청"인지 — 응답을 반영하기 직전마다 다시 확인.
    // 응답이 왔을 시점엔 이미 그 뒤에 다른 필터 클릭으로 새 요청이 나갔을 수 있어서, await
    // 직후 한 번만 확인하면 안 되고 각 setXxx 지점마다(특히 finally) 다시 체크해야 함.
    const isStale = () => requestIdRef.current !== requestId;

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
      // 기다리는 동안 더 최신 요청이 나갔으면(사용자가 그 사이 필터를 또 눌렀으면), 이
      // 응답은 이미 낡은 것 — 화면 상태를 덮어쓰지 않고 조용히 버림(최신 요청의 응답이
      // 알아서 뒤이어 반영됨).
      if (isStale()) return;
      setResults(data.results);
      setRelatedLaws(data.related_laws);
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
      if (isStale()) return;
      setError(err.message || "검색 중 오류가 발생했습니다.");
      setResults(null);
      setRelatedLaws(null);
    } finally {
      // 낡은 요청이 뒤늦게 끝났다고 loading을 false로 내리면, 그 사이 시작된 최신 요청이
      // 아직 진행 중인데도 로딩 스피너가 사라지는 깜빡임이 생김 — 최신 요청일 때만 내림.
      if (!isStale()) setLoading(false);
    }
  }, []);

  // 2026-08-24(피드백 반영): "최근 검색" 칩 옆 지우기 버튼용 — localStorage도 같이 비움.
  const clearRecent = useCallback(() => {
    setRecentSearches(clearRecentSearches());
  }, []);

  return {
    results,
    relatedLaws,
    baseResults,
    searchedQuery,
    loading,
    error,
    recentSearches,
    appliedFilters,
    runSearch,
    resetSearch,
    clearRecent,
  };
}
