import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { getCaseDetail, getCaseSummary } from "../api.js";
import ConfidenceBadge from "../components/ConfidenceBadge.jsx";
import highlightMatches from "../highlight.jsx";

const SUMMARY_FIELDS = [
  { key: "summary_point", label: "지적사항" },
  { key: "summary_cause", label: "원인" },
  { key: "summary_action", label: "조치" },
  { key: "summary_result", label: "결과" },
];

const SCROLL_TOP_THRESHOLD = 480;

// 원문이 그냥 통짜 텍스트로 나열돼서 보기 힘들다는 피드백(2026-08-12) 대응 — 감사보고서
// 원문에 자주 나오는 구조 패턴(제목, 번호/가나다 항목, 로마숫자 장 구분, 불릿)만 정규식으로
// 감지해서 굵게+여백을 주고, 나머지 본문은 그대로 둠. 공사마다 양식이 달라 완벽한 파싱은
// 안 되지만, 눈에 띄는 패턴만 강조해도 완전히 평평한 텍스트보다는 훨씬 스캔하기 쉬워짐.
const HEADING_PATTERNS = [
  /^제\s*목\s*[:：]/, // 제 목 : ...
  /^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX]+\s*[.)]/, // Ⅰ. Ⅱ. 로마숫자 장 구분
  /^\d+\s*[.)]\s*\S/, // 1. 2. 3. 번호 항목
  /^[가나다라마바사아자차카타파하]\s*[.)]/, // 가. 나. 다. 항목
  /^[□○◦▪‣·]\s*\S/, // □ ○ 불릿
  /^【.+】/, // 【 구간표시 】
];

function isHeadingLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return false;
  return HEADING_PATTERNS.some((re) => re.test(trimmed));
}

/** 원문을 줄 단위로 나눠서 구조 패턴에 맞는 줄만 강조 클래스를 붙여 렌더링.
 * query가 있으면 줄마다 검색어 하이라이트도 같이 적용. */
function renderRawText(text, query) {
  return text.split("\n").map((line, i) => (
    <div key={i} className={`raw-line ${isHeadingLine(line) ? "raw-line-heading" : ""}`}>
      {query ? highlightMatches(line, query) : line || " "}
    </div>
  ));
}

export default function DetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q") || "";

  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [showScrollTop, setShowScrollTop] = useState(false);

  // 4줄 요약 — "요약보기" 버튼을 눌러야 채워짐(§4.5 온디맨드, POST /documents/{id}/summary).
  // summary === null이면 아직 안 본 상태. doc에 이미 캐싱된 값이 있으면 API 호출 없이 그대로 씀.
  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState(null);

  const backLink = query ? `/?q=${encodeURIComponent(query)}` : "/";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDoc(null);
    setCopied(false);
    setSummary(null);
    setSummaryLoading(false);
    setSummaryError(null);

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

  useEffect(() => {
    function onScroll() {
      setShowScrollTop(window.scrollY > SCROLL_TOP_THRESHOLD);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function handleShowSummary() {
    if (summary || summaryLoading || !doc) return;

    // doc 조회 시점에 이미 둘 다 캐싱돼 있으면(예전에 누가 먼저 생성해둔 경우) API 호출 없이
    // 바로 표시 — 구조화/자유형 둘 중 하나라도 아직 없으면 서버에 다시 요청(그쪽만 새로 생성됨)
    const structuredCached = doc.summary_point || doc.summary_failed;
    const freeformCached = doc.summary_freeform || doc.summary_freeform_failed;
    if (structuredCached && freeformCached) {
      setSummary({
        summary_point: doc.summary_point,
        summary_cause: doc.summary_cause,
        summary_action: doc.summary_action,
        summary_result: doc.summary_result,
        summary_failed: doc.summary_failed,
        summary_freeform: doc.summary_freeform,
        summary_freeform_failed: doc.summary_freeform_failed,
      });
      return;
    }

    setSummaryLoading(true);
    setSummaryError(null);
    getCaseSummary(id)
      .then((data) => setSummary(data))
      .catch((err) => setSummaryError(err.message || "요약을 가져오지 못했습니다."))
      .finally(() => setSummaryLoading(false));
  }

  function handleCopy() {
    if (!summary) return;
    const text = SUMMARY_FIELDS.map(({ label, key }) => `${label}: ${summary[key] || "미기재"}`).join("\n");
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
        <p className="loading-message">불러오는 중…</p>
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

        {/* 검색 결과에서 이어져 들어온 경우(?q= 있음)에만 표시 — 이 사례가 왜 노출됐는지
            알려주고, 아래 원문에서 일치하는 부분을 하이라이트 처리함 */}
        {query && (
          <p className="search-context-note">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6" />
              <path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            '<strong>{query}</strong>' 검색 결과와 유사해서 노출된 사례입니다 — 아래 원문에서
            일치하는 부분을 표시했습니다
          </p>
        )}

        {/* 원문은 요약을 기다릴 필요 없이 바로 보여줌 (§4.5 — 조회와 요약 생성을 분리).
            줄 단위로 나눠서 렌더링 — 제목/번호항목 같은 구조는 강조하고(renderRawText),
            나머지는 그대로 흘러가는 본문으로 둠. */}
        <div className="raw-text">{renderRawText(doc.raw_text, query)}</div>
      </div>

      <div className="summary-card">
        {!summary && !summaryLoading && (
          <button type="button" className="summary-reveal-btn" onClick={handleShowSummary}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
              <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.6" />
            </svg>
            4줄 요약보기 (AI 생성, 몇 초 걸릴 수 있어요)
          </button>
        )}

        {summaryLoading && <p className="loading-message">요약 생성 중…</p>}

        {summaryError && <p className="error-message">{summaryError}</p>}

        {summary && summary.summary_failed && (
          <p className="summary-failed-notice">요약 어려움 — 원문 참고 필요</p>
        )}

        {summary && !summary.summary_failed && (
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
                  <dd>{summary[key] || "미기재"}</dd>
                </div>
              ))}
            </dl>
          </>
        )}

        {/* 문장형 요약 — 지적/원인/조치/결과 틀 없이 자유롭게 뽑은 버전. 위 박스 요약의
            성공/실패와는 별개 결과라 독립적으로 표시함 */}
        {summary && (summary.summary_freeform || summary.summary_freeform_failed) && (
          <div className="summary-freeform-block">
            <p className="summary-toolbar-label">문장으로 보기</p>
            {summary.summary_freeform_failed ? (
              <p className="summary-failed-notice">문장형 요약 어려움 — 원문 참고 필요</p>
            ) : (
              <p className="summary-freeform-text">{summary.summary_freeform.split("\n").join(" ")}</p>
            )}
          </div>
        )}
      </div>

      <Link to={backLink} className="back-link bottom-back-link">
        ← 검색 결과 전체 보기
      </Link>

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
