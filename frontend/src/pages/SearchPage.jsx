import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { searchCases } from "../api.js";
import ResultCard from "../components/ResultCard.jsx";
import { addRecentSearch, getRecentSearches } from "../recentSearches.js";

const TOTAL_CASES = "72,913";
const EXAMPLE_QUERIES = ["수의계약 특혜", "보조금 부정수급", "초과근무수당 부당지급"];

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlQuery = searchParams.get("q") || "";

  const [query, setQuery] = useState(urlQuery);
  const [results, setResults] = useState(null); // null = 아직 검색 안 함
  const [searchedQuery, setSearchedQuery] = useState(""); // 실제로 검색이 실행된 검색어 (하이라이트용)
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [recentSearches, setRecentSearches] = useState(getRecentSearches);
  const inputRef = useRef(null);

  async function runSearch(q) {
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
  }

  // URL에 ?q=가 있으면(공유된 링크로 들어온 경우 등) 페이지 진입 시 자동으로 검색 실행
  useEffect(() => {
    if (urlQuery) runSearch(urlQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // "/" 단축키로 검색창 포커스 (다른 입력 요소에 포커스가 있을 땐 무시)
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key !== "/") return;
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      e.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

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
              placeholder="예: 출장비 부당 집행 (검색창 포커스는 / 키)"
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

          <p className="stat-strip">
            <b>{TOTAL_CASES}건</b>의 공공감사 사례를 학습한 검색입니다
          </p>
        </div>
      </section>

      <div className="app-main">
        {error && <p className="error-message">{error}</p>}

        {loading && (
          <>
            <p className="section-label">검색 중…</p>
            <div className="skeleton-list">
              {[0, 1, 2].map((i) => (
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
              {results.map((result, i) => (
                <li key={result.document_id}>
                  <ResultCard result={result} rank={i + 1} query={searchedQuery} />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </>
  );
}
