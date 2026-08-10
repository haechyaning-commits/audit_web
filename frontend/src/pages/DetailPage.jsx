import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getCaseDetail } from "../api.js";
import ConfidenceBadge from "../components/ConfidenceBadge.jsx";

const SUMMARY_FIELDS = [
  { key: "summary_point", label: "지적사항" },
  { key: "summary_cause", label: "원인" },
  { key: "summary_action", label: "조치" },
  { key: "summary_result", label: "결과" },
];

export default function DetailPage() {
  const { id } = useParams();
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showRawText, setShowRawText] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDoc(null);
    setShowRawText(false);

    getCaseDetail(id)
      .then((data) => {
        if (!cancelled) setDoc(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "상세 정보를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="detail-page">
        <BackLink />
        {/* 온디맨드 요약 생성이 최초 조회 시 몇 초 걸릴 수 있음 (backend/app/main.py) */}
        <p className="loading-message">불러오는 중… (첫 조회 시 요약 생성으로 몇 초 걸릴 수 있어요)</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="detail-page">
        <BackLink />
        <p className="error-message">{error}</p>
      </div>
    );
  }

  return (
    <div className="detail-page">
      <BackLink />

      <div className="detail-header">
        <span className="detail-institution">
          {doc.institution || "기관명 미상"}
          {doc.year ? ` · ${doc.year}년` : ""}
        </span>
        <ConfidenceBadge label={doc.confidence} />
      </div>

      {doc.summary_failed ? (
        <p className="summary-failed-notice">
          요약 어려움 — 원문 참고 필요
        </p>
      ) : (
        <dl className="summary-list">
          {SUMMARY_FIELDS.map(({ key, label }) => (
            <div key={key} className="summary-item">
              <dt>{label}</dt>
              <dd>{doc[key] || "미기재"}</dd>
            </div>
          ))}
        </dl>
      )}

      <button
        type="button"
        className="raw-text-toggle"
        onClick={() => setShowRawText((v) => !v)}
      >
        {showRawText ? "원문 접기 ▲" : "원문 펼쳐보기 ▼"}
      </button>

      {showRawText && <pre className="raw-text">{doc.raw_text}</pre>}
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/" className="back-link">
      ← 검색으로 돌아가기
    </Link>
  );
}
