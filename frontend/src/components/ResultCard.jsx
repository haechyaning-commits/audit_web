import { Link } from "react-router-dom";
import highlightMatches from "../highlight.jsx";

/**
 * @param {object} result - 검색 결과 카드 데이터
 * @param {number} [rank] - 표시할 순위 (예: 1 → "TOP 1" 배지). 없으면 배지 생략
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
      <div className="result-card-meta">
        {rank != null && <span className="rank-badge">TOP {rank}</span>}
        {/* 기관명/연도를 분리 — 기관명이 길어도(공공기관명은 대체로 긴 편) 연도가
            같이 잘려나가지 않도록. 신뢰도 배지는 목록에서 제거(상세페이지에만 남김) —
            검색 관련도(TOP N)와 무관한 데이터 품질 정보라 목록에서 오해를 줄 수 있었음 */}
        <span className="result-card-institution">{institution || "기관명 미상"}</span>
        {year && <span className="result-card-year">{year}년</span>}
        {/* audit_type은 source_file명 파싱으로 채워짐(백필 전 문서는 아직 null일 수 있음,
            2026-08-12) — 없으면 조용히 생략 */}
        {audit_type && <span className="result-card-audit-type">{audit_type}</span>}
      </div>
      <p className="result-card-preview">
        {query ? highlightMatches(preview_text, query) : preview_text}
      </p>
    </Link>
  );
}
