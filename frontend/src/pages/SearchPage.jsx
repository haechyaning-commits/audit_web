import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ResultCard from "../components/ResultCard.jsx";
import YearChart from "../components/YearChart.jsx";

// 2026-08-10 데이터 품질 정리(재추출 불가 문서 삭제)로 72,913 -> 67,751건으로 조정됨
// (STATUS.md "데이터 품질 사고 대응 완료" 항목 참고)
const TOTAL_CASES = "67,751";

// 연도별 문서 수 (2026-08-12, DB 복구 후 재조회) — Railway Query 탭에서 실행:
//   SELECT year, count(*) FROM documents GROUP BY year ORDER BY year;
// year가 NULL인 2건은 차트에 표시할 수 없어 제외(총합 67,751건 중 67,749건만 반영).
const YEAR_COUNTS = [
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
  const { results, searchedQuery, loading, error, recentSearches, runSearch } = search;
  const [searchParams, setSearchParams] = useSearchParams();
  const urlQuery = searchParams.get("q") || "";

  const [query, setQuery] = useState(urlQuery);
  const inputRef = useRef(null);

  // 페이지네이션 — URL의 page 파라미터가 진실의 원천 (새로고침해도 보던 페이지 유지,
  // 새 검색(q 변경) 시엔 setSearchParams({q})가 page를 같이 지워버려서 자동으로 1페이지로 리셋됨)
  const pageParam = parseInt(searchParams.get("page"), 10);
  const page = Number.isInteger(pageParam) && pageParam > 0 ? pageParam : 1;
  const totalPages = results ? Math.max(1, Math.ceil(results.length / PAGE_SIZE)) : 1;
  const pagedResults = results ? results.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) : [];

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
      runSearch(urlQuery);
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

  function handleSubmit(event) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    setSearchParams({ q: trimmed });
    runSearch(trimmed);
  }

  function handleChipClick(text) {
    setQuery(text);
    setSearchParams({ q: text });
    runSearch(text);
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
                placeholder="예: 직장 상사가 부하 직원을 지속적으로 괴롭혀서 신고하고 싶어요"
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
            </div>

            <div className="stat-cards">
              <div className="stat-card">
                <span className="stat-card-icon">
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M6 3h9l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.6" />
                  </svg>
                </span>
                <span className="stat-card-num">{TOTAL_CASES}건</span>
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
                <span className="stat-card-num">AI 4줄 요약 자동 생성</span>
                <span className="stat-card-label">사례 클릭 시 온디맨드 생성</span>
              </div>
            </div>

            <YearChart data={YEAR_COUNTS} />
          </div>
        </section>
      )}

      <div className="app-main">
        {error && <p className="error-message">{error}</p>}

        {loading && (
          <>
            <p className="section-label">검색 중…</p>
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
            <p className="section-label">
              검색 결과 <span className="count">{results.length}건</span>
            </p>
            <ul className="result-list">
              {pagedResults.map((result, i) => (
                <li key={result.document_id}>
                  <ResultCard result={result} rank={(page - 1) * PAGE_SIZE + i + 1} query={searchedQuery} />
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
    </>
  );
}
