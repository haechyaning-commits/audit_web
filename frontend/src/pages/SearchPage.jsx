import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getYearStats } from "../api.js";
import FilterSidebar from "../components/FilterSidebar.jsx";
import ResultCard from "../components/ResultCard.jsx";
import YearChart from "../components/YearChart.jsx";

// 2026-08-25(베타테스트 피드백 5번): 이 두 값이 지금까지 여기 하드코딩돼 있어서, DB에
// 새 문서가 계속 반영되고 있는데도(HWP 표 손실 복구 등 진행 중) 프론트를 재배포하지
// 않는 한 이 시점 스냅샷(2026-08-10 데이터 품질 정리 직후 수치)에 멈춰있는 문제가
// 있었음 — GET /stats/years로 대체(아래 useEffect). 이 상수들은 그 요청이 아직
// 안 왔거나 실패했을 때 보여줄 폴백으로만 남겨둠(빈 화면/로딩 깜빡임 방지) — 값이
// 오차 없이 최신일 필요는 없고, 그냥 "완전히 빈 것보단 나은" 대체재 역할.
const TOTAL_CASES_FALLBACK = "67,751";
const YEAR_COUNTS_FALLBACK = [
  { year: 2016, count: 4457 },
  { year: 2017, count: 4552 },
  { year: 2018, count: 4665 },
  { year: 2019, count: 4927 },
  { year: 2020, count: 4838 },
  { year: 2021, count: 5113 },
  { year: 2022, count: 5905 },
  { year: 2023, count: 6014 },
  { year: 2024, count: 12000 },
  { year: 2025, count: 11762 },
  { year: 2026, count: 3516 },
];
// 키워드형/문장형을 섞어서 어느 쪽으로 검색해도 되는 걸 예시로 같이 보여줌
const EXAMPLE_QUERIES = [
  "수의계약 특혜",
  "출장비를 부풀려 청구한 사례",
  "보조금 부정수급",
  "직장 상사가 부하직원을 괴롭힌 사례",
];
const PAGE_SIZE = 10; // 2열 x 5줄

/**
 * search prop: App.jsx의 useSearchState()가 만든 공유 상태 { results, searchedQuery,
 * loading, error, recentSearches, runSearch }. 헤더 검색창과 여기 히어로 검색창이
 * 이 상태를 같이 씀 — 어느 쪽에서 검색해도 같은 results가 반영됨.
 */
export default function SearchPage({ search }) {
  const {
    results,
    baseResults,
    searchedQuery,
    loading,
    error,
    recentSearches,
    runSearch,
    clearRecent,
  } = search;
  const [searchParams, setSearchParams] = useSearchParams();
  const urlQuery = searchParams.get("q") || "";
  // 2026-08-24(FR5): 필터도 URL이 진실의 원천 — 새로고침/공유 링크로 들어와도
  // 같은 필터 상태가 재현됨(page 파라미터와 같은 방침).
  const filterInstitution = searchParams.get("institution") || "";
  const filterYear = searchParams.get("year") || "";
  const filterAuditType = searchParams.get("audit_type") || "";
  // 2026-08-24(피드백 반영): 정렬 — 기본은 백엔드가 계산한 RRF 관련도순 그대로, "최신순"은
  // 이미 받아온 results(최대 40건)를 프론트에서 연도 기준으로 재정렬만 하면 돼서 백엔드
  // 변경 없이 구현 가능(추가 API 호출 없음). URL 파라미터로 둬서 새로고침/공유해도 유지됨.
  const sortMode = searchParams.get("sort") === "latest" ? "latest" : "relevance";

  const [query, setQuery] = useState(urlQuery);
  const inputRef = useRef(null);
  // 2026-08-24(피드백 반영): 모바일(≤720px)에서는 필터 사이드바가 기본으로 접혀있음 —
  // 감사유형/기관/연도 세 그룹이 다 펼쳐진 채로 검색 결과보다 위에 쌓이면, 화면을 한참
  // 내려야 결과가 보이는 문제(index.css의 .filter-sidebar 관련 미디어쿼리 참고). 데스크톱
  // 폭에서는 이 상태와 무관하게 CSS가 항상 펼쳐서 보여줌(아래 toggle 버튼도 그때만 보임).
  const [filtersOpen, setFiltersOpen] = useState(false);

  // 2026-08-25(성능 피드백 대응): 처음 보는 검색어는 서버가 AI 임베딩 모델을 CPU로
  // 실시간 추론해야 해서 15초 안팎 걸릴 수 있음(백엔드 embedding.py 참고, 근본 해결은
  // 백엔드 성능 개선 쪽에서 계속 진행 중) — "검색 중…" 스켈레톤만 보이면 사용자가
  // "느린 게 아니라 멈춘 것/고장난 것"으로 오해하기 쉬움. 2.5초 넘게 로딩 중이면
  // (재검색 캐시 히트처럼 원래 빠른 경우엔 안 보이게) 안내 문구를 추가로 보여줘서
  // "느리지만 정상 동작 중"이라는 기대치를 맞춰줌 — 실제 지연을 없애진 못하지만
  // 체감 이탈은 줄일 수 있는 임시 완화책.
  const [showSlowHint, setShowSlowHint] = useState(false);
  useEffect(() => {
    if (!loading) {
      setShowSlowHint(false);
      return;
    }
    const timer = setTimeout(() => setShowSlowHint(true), 2500);
    return () => clearTimeout(timer);
  }, [loading]);

  // 2026-08-25(베타테스트 피드백 5번): 홈 화면 상단 통계(전체 건수 + 연도별 막대그래프)를
  // 하드코딩 상수 대신 GET /stats/years 라이브 값으로 교체. 폴백 상수로 초기화해두고
  // 로드되면 조용히 교체하는 방식 — 로딩 스피너나 빈 화면 없이(히어로 영역이라 첫
  // 진입에 바로 보여야 함), 실패해도(네트워크 문제 등) 그냥 폴백 값이 계속 보이는
  // 채로 남음(에러 노출 안 함 — 이 통계는 부가 정보라 검색 기능 자체를 막을 이유가 없음,
  // /similar와 같은 원칙).
  const [yearStats, setYearStats] = useState({
    total: TOTAL_CASES_FALLBACK,
    years: YEAR_COUNTS_FALLBACK,
  });
  useEffect(() => {
    let cancelled = false;
    getYearStats()
      .then((data) => {
        if (!cancelled) setYearStats({ total: data.total.toLocaleString(), years: data.years });
      })
      .catch(() => {
        // 조용히 무시 — 폴백 값이 계속 보임
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 2026-08-24(피드백 반영): 결과 카드의 상대 관련도 막대(ResultCard.jsx)용 기준값.
  // results[0]은 정렬 모드와 무관하게 항상 백엔드가 매긴 1위 스코어(ORDER BY score DESC로
  // 응답됨) — "최신순" 정렬로 화면 순서가 바뀌어도 막대 기준(=1위 점수)은 안 바뀌어야
  // 하므로 sortedResults가 아니라 results[0]에서 구함.
  const topScore = results && results.length > 0 ? results[0].score : null;

  const sortedResults = useMemo(() => {
    if (!results) return results;
    if (sortMode !== "latest") return results;
    // 연도만 보고 정렬 — 같은 연도 안에서는 원래(관련도) 순서를 그대로 유지(안정 정렬).
    return [...results].sort((a, b) => (b.year || 0) - (a.year || 0));
  }, [results, sortMode]);

  // 페이지네이션 — URL의 page 파라미터가 진실의 원천 (새로고침해도 보던 페이지 유지,
  // 새 검색(q 변경) 시엔 setSearchParams({q})가 page를 같이 지워버려서 자동으로 1페이지로 리셋됨)
  const pageParam = parseInt(searchParams.get("page"), 10);
  const page = Number.isInteger(pageParam) && pageParam > 0 ? pageParam : 1;
  const totalPages = sortedResults ? Math.max(1, Math.ceil(sortedResults.length / PAGE_SIZE)) : 1;
  const pagedResults = sortedResults
    ? sortedResults.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
    : [];

  function handleSortChange(mode) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (mode === "latest") next.set("sort", "latest");
      else next.delete("sort");
      next.delete("page"); // 정렬이 바뀌면 이전 페이지 번호가 의미 없어지므로 1페이지로
      return next;
    });
  }

  function goToPage(p) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("page", String(p));
      return next;
    });
    document.querySelector(".app-main")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // URL의 ?q=가 아직 검색 안 된(또는 다른) 값이면 자동 실행 — 공유된 링크로 들어온 경우,
  // 새로고침, 뒤로/앞으로가기 등. loading 중엔 건너뜀(헤더 검색창이 이미 트리거한 검색과
  // 중복 실행되는 것 방지 — 헤더는 navigate 직후 곧바로 runSearch도 직접 호출하므로,
  // 이 이펙트가 뒤따라와도 loading=true인 걸 보고 조용히 넘어감).
  useEffect(() => {
    if (urlQuery && urlQuery !== searchedQuery && !loading) {
      runSearch(urlQuery, {
        institution: filterInstitution,
        year: filterYear,
        audit_type: filterAuditType,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery]);

  // 히어로가 보이는(아직 검색 전) 상태에서만 "/" 단축키로 히어로 검색창 포커스 —
  // 검색 후엔 히어로가 사라지고 헤더 검색창(HeaderSearch)이 단축키를 대신 담당함
  useEffect(() => {
    if (results !== null) return;
    function onKeyDown(e) {
      if (e.key !== "/") return;
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      e.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [results]);

  // 2026-08-24(FR5): 새 검색어를 넣어도(검색창 제출/예시칩 클릭) 이미 골라둔
  // 기관/연도 필터는 그대로 유지 — "이 기관 안에서 다른 검색어로 다시 찾고 싶다"는
  // 흐름이 자연스러워서(선택 안 한 필터는 params에 아예 안 넣음, {q}만 있던 기존
  // 동작과 동일하게 유지됨).
  function runSearchWithFilters(text) {
    const params = { q: text };
    if (filterInstitution) params.institution = filterInstitution;
    if (filterYear) params.year = filterYear;
    if (filterAuditType) params.audit_type = filterAuditType;
    setSearchParams(params);
    runSearch(text, {
      institution: filterInstitution,
      year: filterYear,
      audit_type: filterAuditType,
    });
  }

  function handleSubmit(event) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    runSearchWithFilters(trimmed);
  }

  function handleChipClick(text) {
    setQuery(text);
    runSearchWithFilters(text);
  }

  // 필터 드롭다운 변경 — 이미 검색어가 있으면(결과 화면) 그 자리에서 바로 재검색.
  // 페이지 파라미터는 지워서 1페이지로(필터가 바뀌면 이전 페이지 번호가 새 결과
  // 개수보다 클 수 있음).
  function handleFilterChange(field, value) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(field, value);
      else next.delete(field);
      next.delete("page");
      return next;
    });
    if (searchedQuery) {
      const nextInstitution = field === "institution" ? value : filterInstitution;
      const nextYear = field === "year" ? value : filterYear;
      const nextAuditType = field === "audit_type" ? value : filterAuditType;
      runSearch(searchedQuery, {
        institution: nextInstitution,
        year: nextYear,
        audit_type: nextAuditType,
      });
    }
  }

  // 필터 3종을 한 번에 초기화 — handleFilterChange를 3번 연달아 부르면 매번 그
  // 시점의 (아직 안 바뀐) filterInstitution/filterYear/filterAuditType 클로저값을
  // 기준으로 runSearch를 호출해서 중간 호출들이 서로 어긋난 params로 낭비 요청을
  // 날리게 됨 — 그래서 URL/검색 둘 다 한 번에 정리하는 별도 핸들러로 분리.
  function handleResetFilters() {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("institution");
      next.delete("year");
      next.delete("audit_type");
      next.delete("page");
      return next;
    });
    if (searchedQuery) {
      runSearch(searchedQuery, { institution: "", year: "", audit_type: "" });
    }
  }

  const chipSource = recentSearches.length > 0 ? recentSearches : EXAMPLE_QUERIES;
  const chipLabel = recentSearches.length > 0 ? "최근 검색" : "예시";

  return (
    <>
      {/* 검색 전(랜딩)에만 히어로+검색창 표시 — 검색 후엔 결과만 보여주고, 재검색은
          헤더 상시 검색창(HeaderSearch)으로 함.
          !loading도 같이 봐야 함(2026-08-12) — 검색 버튼을 누르면 loading이 먼저 true가
          되고 results는 응답이 올 때까지 계속 null이라서, !loading이 없으면 히어로(통계
          카드+그래프)가 아래 로딩 스켈레톤이랑 같이 떠서 겹쳐 보이는 문제가 있었음. */}
      {results === null && !loading && (
        <section className="hero">
          <div className="hero-inner">
            <h1>궁금한 사안을 검색해보세요</h1>
            <p>문장으로 입력하면 AI가 유사한 공공감사 사례를 찾아드립니다.</p>

            <form className="search-form" onSubmit={handleSubmit}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                <path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="예: 직장 상사가 지속적으로 괴롭혀서 신고하고 싶어요"
                aria-label="검색어"
              />
              <button type="submit" disabled={loading || !query.trim()}>
                {loading ? "검색 중…" : "검색"}
              </button>
            </form>

            <div className="example-chips">
              <span className="example-chips-label">{chipLabel}</span>
              {chipSource.map((text) => (
                <button key={text} type="button" className="chip" onClick={() => handleChipClick(text)}>
                  {text}
                </button>
              ))}
              {/* 2026-08-24(피드백 반영): 최근 검색어는 localStorage에 계속 쌓이는데
                  지우는 방법이 지금까지 없었음(recentSearches.js 참고) — 예시 칩으로
                  바뀌는 게 아니라 "최근 검색"일 때만 노출 */}
              {recentSearches.length > 0 && (
                <button type="button" className="chip-clear" onClick={clearRecent}>
                  지우기
                </button>
              )}
            </div>

            <div className="stat-cards">
              <div className="stat-card">
                <span className="stat-card-icon">
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M6 3h9l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.6" />
                  </svg>
                </span>
                <span className="stat-card-num">{yearStats.total}건</span>
                <span className="stat-card-label">공공감사 사례 데이터</span>
              </div>
              <div className="stat-card">
                <span className="stat-card-icon">
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </span>
                <span className="stat-card-num">벡터 검색 + 키워드 검색 결합</span>
                <span className="stat-card-label">RRF로 두 결과를 합쳐 랭킹</span>
              </div>
              <div className="stat-card">
                <span className="stat-card-icon">
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.6" />
                  </svg>
                </span>
                <span className="stat-card-num">AI 전체 요약 자동 생성</span>
                <span className="stat-card-label">사례 클릭 시 온디맨드 생성</span>
              </div>
            </div>

            <YearChart data={yearStats.years} />
          </div>
        </section>
      )}

      <div className="app-main">
        {error && <p className="error-message">{error}</p>}

        {/* 2026-08-24(FR5 2차): 기관/연도/감사유형 필터 — 검색이 한 번이라도 실행된
            뒤에만 사이드바를 보여줌(히어로 단계에선 아직 결과가 없어서 필터를 걸
            대상 자체가 없음). baseResults가 아직 없으면(첫 로딩 등) 사이드바는
            빈 채로 렌더링됨 — FilterSidebar 내부에서 안전하게 처리. */}
        {(results !== null || loading) && (
          <div className="search-layout">
            {/* 모바일 전용 — 데스크톱 폭에서는 CSS(min-width 미디어쿼리)로 숨김 */}
            <button
              type="button"
              className="filter-toggle-mobile"
              onClick={() => setFiltersOpen((v) => !v)}
              aria-expanded={filtersOpen}
            >
              필터
              <span className="filter-toggle-mobile-arrow" aria-hidden="true">
                {filtersOpen ? "▴" : "▾"}
              </span>
            </button>
            <FilterSidebar
              className={filtersOpen ? "is-open" : ""}
              baseResults={baseResults}
              results={results || []}
              filters={{
                institution: filterInstitution,
                year: filterYear,
                audit_type: filterAuditType,
              }}
              onChange={handleFilterChange}
              onResetAll={handleResetFilters}
            />

            <div className="search-main">
              {loading && (
                <>
                  <p className="section-label">
                    검색 중…
                    {showSlowHint && (
                      <span className="search-slow-hint">
                        {" "}
                        처음 입력하신 문장은 AI가 새로 분석하고 있어요 — 최대 15초 정도 걸릴 수 있어요.
                      </span>
                    )}
                  </p>
                  <div className="skeleton-list">
                    {[0, 1, 2, 3].map((i) => (
                      <div className="skeleton-card" key={i}>
                        <div className="skel-line skel-title" />
                        <div className="skel-line skel-text" />
                        <div className="skel-line skel-text short" />
                      </div>
                    ))}
                  </div>
                </>
              )}

              {!loading && !error && results !== null && results.length === 0 && (
                <div className="empty-state">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                  <h3>일치하는 사례를 찾지 못했습니다</h3>
                  <p>다른 문장으로 다시 시도하거나 아래 예시를 눌러보세요.</p>
                  <div className="example-chips">
                    {EXAMPLE_QUERIES.map((text) => (
                      <button key={text} type="button" className="chip" onClick={() => handleChipClick(text)}>
                        {text}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {!loading && results !== null && results.length > 0 && (
                <>
                  <div className="result-list-header">
                    <p className="section-label">
                      검색 결과 <span className="count">{results.length}건</span>
                    </p>
                    <div className="sort-toggle" role="group" aria-label="정렬 방식">
                      <button
                        type="button"
                        className={sortMode === "relevance" ? "active" : ""}
                        onClick={() => handleSortChange("relevance")}
                      >
                        관련도순
                      </button>
                      <button
                        type="button"
                        className={sortMode === "latest" ? "active" : ""}
                        onClick={() => handleSortChange("latest")}
                      >
                        최신순
                      </button>
                    </div>
                  </div>
                  <ul className="result-list">
                    {pagedResults.map((result, i) => (
                      <li key={result.document_id}>
                        <ResultCard
                          result={result}
                          rank={(page - 1) * PAGE_SIZE + i + 1}
                          query={searchedQuery}
                          topScore={topScore}
                        />
                      </li>
                    ))}
                  </ul>

                  {totalPages > 1 && (
                    <nav className="pagination" aria-label="검색 결과 페이지">
                      {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                        <button
                          key={p}
                          type="button"
                          className={`page-btn ${p === page ? "active" : ""}`}
                          onClick={() => goToPage(p)}
                          aria-current={p === page ? "page" : undefined}
                        >
                          {p}
                        </button>
                      ))}
                    </nav>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
