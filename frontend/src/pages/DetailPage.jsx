import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { getCaseDetail, searchCases } from "../api.js";
import ConfidenceBadge from "../components/ConfidenceBadge.jsx";
import ResultCard from "../components/ResultCard.jsx";

const SUMMARY_FIELDS = [
  { key: "summary_point", label: "지적사항" },
  { key: "summary_cause", label: "원인" },
  { key: "summary_action", label: "조치" },
  { key: "summary_result", label: "결과" },
];

const SCROLL_TOP_THRESHOLD = 480;

export default function DetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q") || "";

  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showRawText, setShowRawText] = useState(false);
  const [copied, setCopied] = useState(false);
  const [related, setRelated] = useState([]);
  const [showScrollTop, setShowScrollTop] = useState(false);

  const backLink = query ? `/?q=${encodeURIComponent(query)}` : "/";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDoc(null);
    setShowRawText(false);
    setCopied(false);
    setRelated([]);

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

  // 같이 검색된 관련 사례 — URL에 검색어(q)가 있을 때만 다시 검색해서, 현재 문서를 뺀
  // 나머지를 보여줌. q가 없으면(직접 URL 접속 등, 검색 컨텍스트가 없으면) 섹션 자체를 숨김
  useEffect(() => {
    let cancelled = false;
    if (!query) {
      setRelated([]);
      return;
    }
    searchCases(query)
      .then((data) => {
        if (cancelled) return;
        const filtered = data.results.filter((r) => r.document_id !== id).slice(0, 3);
        setRelated(filtered);
      })
      .catch(() => {
        if (!cancelled) setRelated([]);
      });
    return () => {
      cancelled = true;
    };
  }, [query, id]);

  useEffect(() => {
    function onScroll() {
      setShowScrollTop(window.scrollY > SCROLL_TOP_THRESHOLD);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function handleCopy() {
    if (!doc) return;
    const text = SUMMARY_FIELDS.map(({ label, key }) => `${label}: ${doc[key] || "미기재"}`).join("\n");
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      })
      .catch(() => {
        // 클립보드 API를 막아둔 브라우저 환경 — 조용히 무시 (버튼은 그대로 남아있어 재시도 가능)
      });
  }

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  if (loading) {
    return (
      <div className="app-main detail-page">
        <BackLink to={backLink} />
        {/* 온디맨드 요약 생성이 최초 조회 시 몇 초 걸릴 수 있음 (backend/app/main.py) */}
        <p className="loading-message">불러오는 중… (첫 조회 시 요약 생성으로 몇 초 걸릴 수 있어요)</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="app-main detail-page">
        <BackLink to={backLink} />
        <p className="error-message">{error}</p>
      </div>
    );
  }

  return (
    <div className="app-main detail-page">
      <BackLink to={backLink} />

      <div className="detail-card">
        <div className="detail-header">
          <span className="detail-institution">
            {doc.institution || "기관명 미상"}
            {doc.year ? ` · ${doc.year}년` : ""}
          </span>
          <ConfidenceBadge label={doc.confidence} />
        </div>

        {doc.summary_failed ? (
          <p className="summary-failed-notice">요약 어려움 — 원문 참고 필요</p>
        ) : (
          <>
            <div className="ai-notice">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
                <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.6" />
              </svg>
              AI가 원문을 분석해 자동 생성한 요약입니다. 정확한 내용은 원문을 확인하세요.
            </div>

            <div className="summary-toolbar">
              <span className="summary-toolbar-label">4줄 요약</span>
              <button
                type="button"
                className={`copy-btn ${copied ? "copied" : ""}`}
                onClick={handleCopy}
              >
                {copied ? (
                  "복사됨"
                ) : (
                  <>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <rect x="9" y="9" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.6" />
                      <path d="M5 15V5a2 2 0 0 1 2-2h10" stroke="currentColor" strokeWidth="1.6" />
                    </svg>
                    요약 복사
                  </>
                )}
              </button>
            </div>

            <dl className="summary-list">
              {SUMMARY_FIELDS.map(({ key, label }, i) => (
                <div key={key} className="summary-item">
                  <dt>
                    <span className="num">{i + 1}</span>
                    {label}
                  </dt>
                  <dd>{doc[key] || "미기재"}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </div>

      <button type="button" className="raw-text-toggle" onClick={() => setShowRawText((v) => !v)}>
        {showRawText ? "원문 접기 ▲" : "원문 펼쳐보기 ▼"}
      </button>

      {showRawText && <pre className="raw-text">{doc.raw_text}</pre>}

      {related.length > 0 && (
        <div className="related-section">
          <p className="section-label">같이 검색된 관련 사례</p>
          <ul className="result-list">
            {related.map((r, i) => (
              <li key={r.document_id}>
                <ResultCard result={r} rank={i + 2} query={query} className="related-card" />
              </li>
            ))}
          </ul>
          <Link to={backLink} className="back-link" style={{ marginBottom: 0 }}>
            ← 검색 결과 전체 보기
          </Link>
        </div>
      )}

      <button
        type="button"
        className={`scroll-top-btn ${showScrollTop ? "visible" : ""}`}
        onClick={scrollToTop}
        aria-label="맨 위로"
        title="맨 위로"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );
}

function BackLink({ to }) {
  return (
    <Link to={to} className="back-link">
      ← 검색으로 돌아가기
    </Link>
  );
}
