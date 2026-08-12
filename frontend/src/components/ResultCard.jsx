import { Link } from "react-router-dom";
import highlightMatches from "../highlight.jsx";

/**
 * 2026-08-12: law.go.kr류 목록형으로 재구성 — 카드(둥근모서리+그림자) 그리드 대신
 * 왼쪽 번호열 / 가운데 본문 / 오른쪽 메타(감사종류·연도) 3열 행으로 촘촘하게 나열.
 *
 * @param {object} result - 검색 결과 카드 데이터
 * @param {number} [rank] - 표시할 순위(왼쪽 번호열, 예: 01). 없으면 번호열 생략
 * @param {string} [query] - 미리보기 텍스트에서 하이라이트할 검색어
 * @param {string} [className]
 */
export default function ResultCard({ result, rank, query, className = "" }) {
  const { document_id, institution, year, audit_type, preview_text } = result;
  const to = query
    ? `/documents/${document_id}?q=${encodeURIComponent(query)}`
    : `/documents/${document_id}`;

  return (
    <Link to={to} className={`result-card ${className}`}>
      {rank != null && (
        <span className="result-card-rank mono" aria-hidden="true">
          {String(rank).padStart(2, "0")}
        </span>
      )}
      <div className="result-card-body">
        <span className="result-card-institution">
          {institution || "기관명 미상"}
          {year ? ` · ${year}년` : ""}
        </span>
        <p className="result-card-preview">
          {query ? highlightMatches(preview_text, query) : preview_text}
        </p>
      </div>
      {/* audit_type은 source_file명 파싱으로 채워짐(백필 전 문서는 아직 null일 수 있음,
          2026-08-12) — 없으면 조용히 생략 */}
      <div className="result-card-side">
        {audit_type && <span className="result-card-audit-type">{audit_type}</span>}
      </div>
    </Link>
  );
}
