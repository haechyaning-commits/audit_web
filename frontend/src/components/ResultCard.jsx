import { Link } from "react-router-dom";
import ConfidenceBadge from "./ConfidenceBadge.jsx";

export default function ResultCard({ result }) {
  const { document_id, institution, year, confidence, preview_text } = result;

  return (
    <Link to={`/documents/${document_id}`} className="result-card">
      <div className="result-card-meta">
        <span className="result-card-institution">
          {institution || "기관명 미상"}
          {year ? ` · ${year}년` : ""}
        </span>
        <ConfidenceBadge label={confidence} />
      </div>
      <p className="result-card-preview">{preview_text}</p>
    </Link>
  );
}
