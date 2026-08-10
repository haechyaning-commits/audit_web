import { useState } from "react";
import { searchCases } from "../api.js";
import ResultCard from "../components/ResultCard.jsx";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null); // null = 아직 검색 안 함
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    try {
      const data = await searchCases(trimmed);
      setResults(data.results);
    } catch (err) {
      setError(err.message || "검색 중 오류가 발생했습니다.");
      setResults(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="search-page">
      <p className="search-lead">
        궁금한 사안을 문장으로 입력하면 유사한 공공감사 사례를 찾아드려요.
      </p>

      <form className="search-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="예: 출장비 부당 집행"
          aria-label="검색어"
        />
        <button type="submit" disabled={loading || !query.trim()}>
          {loading ? "검색 중…" : "검색"}
        </button>
      </form>

      {error && <p className="error-message">{error}</p>}

      {!error && results !== null && results.length === 0 && (
        <p className="empty-message">일치하는 사례를 찾지 못했습니다. 다른 문장으로 시도해보세요.</p>
      )}

      {results !== null && results.length > 0 && (
        <ul className="result-list">
          {results.map((result) => (
            <li key={result.document_id}>
              <ResultCard result={result} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
