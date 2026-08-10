import { Link } from "react-router-dom";
import ConfidenceBadge from "./ConfidenceBadge.jsx";
import highlightMatches from "../highlight.jsx";

/**
 * @param {object} result - 검색 결과 카드 데이터
 * @param {number} [rank] - 표시할 순위 (예: 1 → "TOP 1" 배지). 없으면 배지 생략
 * @param {string} [query] - 미리보기 텍스트에서 하이라이트할 검색어
 * @param {string} [className]
 */
export default function ResultCard({ result, rank, query, className = "" }) {
  const { document_id, institution, year, confidence, preview_text } = result;
  const to = query
    ? `/documents/${document_id}?q=${encodeURIComponent(query)}`
    : `/documents/${document_id}`;

  return (
    <Link to={to} className={`result-card ${className}`}>
      <div className="result-card-meta">
        <div className="result-card-left">
          {rank != null && <span className="rank-badge">TOP {rank}</span>}
          <span className="result-card-institution">
            {institution || "기관명 미상"}
            {year ? ` · ${year}년` : ""}
          </span>
        </div>
        <ConfidenceBadge label={confidence} />
      </div>
      <p className="result-card-preview">
        {query ? highlightMatches(preview_text, query) : preview_text}
      </p>
    </Link>
  );
}
