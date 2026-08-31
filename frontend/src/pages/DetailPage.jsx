import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { buildCasePath } from "../caseUrl.js";
import { getCaseDetail, getCaseSummary, getSimilarCases } from "../api.js";
import useDocumentTitle from "../useDocumentTitle.js";
import ConfidenceBadge from "../components/ConfidenceBadge.jsx";
import ReportErrorModal from "../components/ReportErrorModal.jsx";
import ResultCard from "../components/ResultCard.jsx";
import { splitIntoBlocks, renderRawText, buildToc, TocSidebar } from "./rawTextParsing.jsx";

const SUMMARY_FIELDS = [
  { key: "summary_point", label: "지적사항" },
  { key: "summary_cause", label: "원인" },
  { key: "summary_action", label: "조치" },
  { key: "summary_result", label: "결과" },
];

const SCROLL_TOP_THRESHOLD = 480;

// 2026-08-13: "감사결과 처분서(연번/지적사항/처분)" 3단 표 양식에서, 지적사항/처분 두
// 컬럼의 텍스트가 PDF 추출 시 줄 단위로 서로 교차돼 섞여 들어가는 오염이 확인됨
// (49건, 서울대학교치과병원에 86% 집중 — scripts/audit_table_column_interleave.py로
// 규모 확인). 표 구조가 이미 사라진 뒤라 어느 줄이 어느 칸 것이었는지 표식이 안 남아서
// 정규식으로 안전하게 복원할 방법이 없음(억지로 줄 길이로 갈라 붙이면 서로 다른 문장을
// 섞어 만들어내는 위험이 있어 "그럴듯하게 틀린" 내용이 될 수 있음 — 눈에 띄게 이상한
// 원문보다 더 나쁨). 그래서 텍스트를 고치는 대신, 이 양식임을 감지해서 뒤섞였을 수
// 있다고 투명하게 알려주는 배너만 띄움. 오탐 위험 있는 통계적 방법(줄 길이 번갈아짐)
// 대신, 실제 오염 문서에서만 나타나는 걸 확인한 정확한 헤더 문자열만 매칭
// (스캔 스크립트에서 검증된 방식과 동일 — 지금까지 오탐 0건).
const TABLE_INTERLEAVE_RE = /연번[\s\n]*지적사항[\s\n]*처분/;

export default function DetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const location = useLocation();
  const navigate = useNavigate();

  const [doc, setDoc] = useState(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [showScrollTop, setShowScrollTop] = useState(false);

  // 4줄 요약 — "요약보기" 버튼을 눌러야 채워짐(§4.5 온디맨드, POST /documents/{id}/summary).
  // summary === null이면 아직 안 본 상태. doc에 이미 캐싱된 값이 있으면 API 호출 없이 그대로 씀.
  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState(null);

  // 2026-08-24(피드백 반영): "유사 사례" 섹션 — 요약과 달리 LLM 호출이 아니라 순수
  // 벡터검색이라 버튼 뒤로 안 미루고 원문과 같이 자동으로 불러옴(아래 useEffect 참고).
  // null = 아직 로딩 중, []는 "이 문서 기준으로 유사 사례를 못 찾음"(정상적인 결과).
  const [similarCases, setSimilarCases] = useState(null);

  const backLink = query ? `/?q=${encodeURIComponent(query)}` : "/";

  // 탭 타이틀 — 제목 파싱 실패한 소수 문서는 기관명으로, 그것도 없으면 그냥 기본 타이틀
  // (useDocumentTitle이 falsy면 안 건드림) 유지. "공공감사데이터 검색" 접미사를 붙여서
  // 여러 탭 열어놨을 때 어느 서비스인지 구분되게 함.
  useDocumentTitle(
    doc && (doc.title || doc.institution)
      ? `${doc.title || doc.institution} - 공공감사데이터 검색`
      : null,
  );

  // raw_text -> 블록 목록은 doc이 바뀔 때만 다시 계산(문서 하나가 꽤 길어서 매 렌더마다
  // 다시 파싱하면 낭비) — renderRawText(본문)와 buildToc(목차)가 같은 블록 목록을 공유
  const blocks = useMemo(
    () => (doc ? splitIntoBlocks(doc.raw_text) : []),
    [doc],
  );
  const tocItems = useMemo(() => buildToc(blocks), [blocks]);
  const tableInterleaveSuspect = useMemo(
    () => Boolean(doc && TABLE_INTERLEAVE_RE.test(doc.raw_text)),
    [doc],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDoc(null);
    setCopied(false);
    setSummary(null);
    setSummaryLoading(false);
    setSummaryError(null);
    setSimilarCases(null);

    getCaseDetail(id)
      .then((data) => {
        if (!cancelled) setDoc(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err.message || "상세 정보를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    // 원문 로딩과 별도 요청으로 병렬 호출 — 하나가 실패/지연돼도 서로 안 막음(원문이
    // 이 페이지의 핵심이라 유사 사례 쪽 에러 때문에 원문까지 못 보여주면 안 됨). 실패하면
    // 그냥 빈 배열로 둬서 섹션 자체가 조용히 생략되게 함(에러 배너 없음 — 부가 정보라).
    getSimilarCases(id)
      .then((data) => {
        if (!cancelled) setSimilarCases(data);
      })
      .catch(() => {
        if (!cancelled) setSimilarCases([]);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  // 예전 링크(/documents/:id)나 title 파싱이 안 됐던 시점에 만들어진 URL로 들어온
  // 경우, 문서 로드가 끝나 title/institution/year를 알게 되면 새 URL(/cases/:id/:slug)로
  // 조용히 교체함(replace라 히스토리에 새 엔트리 안 남고, 뒤로가기는 여전히 검색 결과로 감).
  // 이미 최신 slug와 일치하면(캐노니컬 링크로 바로 들어온 경우) 아무것도 안 함.
  useEffect(() => {
    if (!doc) return;
    const canonicalPath = buildCasePath(doc.id, doc);
    if (location.pathname !== canonicalPath) {
      navigate(`${canonicalPath}${location.search}`, { replace: true });
    }
  }, [doc]); // eslint-disable-line react-hooks/exhaustive-deps -- location/navigate는 매 렌더 안정적이지 않아 제외, doc만 트리거로 충분

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
      .catch((err) =>
        setSummaryError(err.message || "요약을 가져오지 못했습니다."),
      )
      .finally(() => setSummaryLoading(false));
  }

  function handleCopy() {
    if (!summary) return;
    const text = SUMMARY_FIELDS.map(
      ({ label, key }) => `${label}: ${summary[key] || "미기재"}`,
    ).join("\n");
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

      {/* 목차(TocSidebar)가 있는 문서(헤딩 3개 이상)는 좌-사이드바/우-본문 2단 레이아웃.
          detail-card와 summary-card를 detail-content로 같이 묶어서 오른쪽 열에 둠 —
          예전엔 summary-card가 detail-layout 밖에 있어서 목차 왼쪽 끝부터 전체폭으로
          걸쳐 보이고, 원문 박스랑 왼쪽 줄이 안 맞았음("상자 위치" 피드백, 2026-08-12) */}
      <div className="detail-layout">
        <TocSidebar items={tocItems} />
        <div className="detail-content">
          <div className="detail-card">
            <p className="detail-breadcrumb">
              {/* 2026-08-26(기관 프로필 기능 추가): 이 페이지는 카드 전체가 링크로
                  감싸여 있지 않아서(ResultCard.jsx와 달리) 그냥 <Link>로 바로 연결 가능 */}
              {doc.institution ? (
                <Link to={`/institutions/${encodeURIComponent(doc.institution)}`} className="detail-institution-link">
                  <b>{doc.institution}</b>
                </Link>
              ) : (
                <b>기관명 미상</b>
              )}
              {doc.year ? <span className="sep">›</span> : null}
              {doc.year ? `${doc.year}년` : ""}
              {doc.audit_type ? <span className="sep">›</span> : null}
              {doc.audit_type || ""}
            </p>
            <div className="detail-header">
              {/* source_url은 백필 전이거나 원본 경로를 못 구한 소수 문서는 null이라
                  백엔드가 그냥 필드를 null로 내려줌 — 조건부로 숨김(2026-08-13) */}
              {doc.source_url && (
                <a
                  href={doc.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="source-file-link"
                >
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M14 3h7v7M21 3l-9 9M19 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  원본 파일 보기
                </a>
              )}
              <ConfidenceBadge label={doc.confidence} />
              <button
                type="button"
                className="report-error-link"
                onClick={() => setReportOpen(true)}
                title="이 사례의 데이터가 잘못됐다면 신고해 주세요"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M12 9v4M12 17h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L14.71 3.86a2 2 0 0 0-3.42 0Z"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                오류 신고
              </button>
            </div>
            {reportOpen && (
              <ReportErrorModal doc={doc} docId={id} onClose={() => setReportOpen(false)} />
            )}

            {/* 검색 결과에서 이어져 들어온 경우(?q= 있음)에만 표시 — 이 사례가 왜 노출됐는지
                알려주고, 아래 원문에서 일치하는 부분을 하이라이트 처리함 */}
            {query && (
              <p className="search-context-note">
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <circle
                    cx="11"
                    cy="11"
                    r="7"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <path
                    d="M21 21l-4.3-4.3"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
                '<strong>{query}</strong>' 검색 결과와 유사한 사례입니다 — 아래
                원문에서 일치하는 부분을 표시했습니다
              </p>
            )}

            {/* 표(연번/지적사항/처분) 추출 오염 의심 문서 — 위 TABLE_INTERLEAVE_RE 주석
                참고. 내용을 고치지 않고 사실만 투명하게 알림. */}
            {tableInterleaveSuspect && (
              <p className="data-quality-notice">
                ⚠️ 이 문서는 표(연번·지적사항·처분) 추출 과정에서 지적사항과 처분
                내용이 줄 단위로 뒤섞였을 수 있습니다. 정확한 내용은 원본 문서를
                확인해주세요.
              </p>
            )}

            {/* 원문은 요약을 기다릴 필요 없이 바로 보여줌 (§4.5 — 조회와 요약 생성을 분리).
                문단 단위로 나눠서 렌더링 — 제목/번호항목 같은 구조는 강조하고(renderRawText),
                나머지는 그대로 흘러가는 본문으로 둠. blocks는 useMemo로 doc이 바뀔 때만 재계산. */}
            <div className="raw-text">{renderRawText(blocks, query)}</div>
          </div>

          <div className="summary-card">
            {!summary && !summaryLoading && (
              <button
                type="button"
                className="summary-reveal-btn"
                onClick={handleShowSummary}
              >
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                  <circle
                    cx="12"
                    cy="12"
                    r="4"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                </svg>
                4줄 요약보기 (AI 생성, 몇 초 걸릴 수 있습니다.)
              </button>
            )}

            {summaryLoading && <p className="loading-message">요약 생성 중…</p>}

            {summaryError && <p className="error-message">{summaryError}</p>}

            {summary && summary.summary_failed && (
              <p className="summary-failed-notice">
                요약 어려움 — 원문 참고 필요
              </p>
            )}

            {summary && !summary.summary_failed && (
              <>
                <div className="ai-notice">
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                    />
                    <circle
                      cx="12"
                      cy="12"
                      r="4"
                      stroke="currentColor"
                      strokeWidth="1.6"
                    />
                  </svg>
                  AI가 원문을 분석해 자동 생성한 요약입니다. 정확한 내용은
                  원문을 확인하세요.
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
                        <svg
                          width="13"
                          height="13"
                          viewBox="0 0 24 24"
                          fill="none"
                          aria-hidden="true"
                        >
                          <rect
                            x="9"
                            y="9"
                            width="12"
                            height="12"
                            rx="2"
                            stroke="currentColor"
                            strokeWidth="1.6"
                          />
                          <path
                            d="M5 15V5a2 2 0 0 1 2-2h10"
                            stroke="currentColor"
                            strokeWidth="1.6"
                          />
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
            {summary &&
              (summary.summary_freeform || summary.summary_freeform_failed) && (
                <div className="summary-freeform-block">
                  <p className="summary-toolbar-label">문장으로 보기</p>
                  {summary.summary_freeform_failed ? (
                    <p className="summary-failed-notice">
                      문장형 요약 어려움 — 원문 참고 필요
                    </p>
                  ) : (
                    <p className="summary-freeform-text">
                      {summary.summary_freeform.split("\n").join(" ")}
                    </p>
                  )}
                </div>
              )}
          </div>
        </div>
      </div>

      {/* 2026-08-24(피드백 반영): 유사 사례 — detail-layout(목차+본문 2단) 밖에 둬서
          전체 폭을 씀. similarCases가 null이면(아직 로딩 중) 아무것도 안 보여주고,
          빈 배열이면(실패 또는 진짜로 유사 사례가 없음) 섹션 자체를 생략함 — "0건"
          같은 빈 상태 UI를 굳이 안 만듦(부가 정보라 없으면 조용히 없는 게 나음). */}
      {similarCases && similarCases.length > 0 && (
        <section className="similar-cases">
          <p className="section-label">유사 사례</p>
          <ul className="result-list">
            {similarCases.map((result, i) => (
              <li key={result.document_id}>
                <ResultCard result={result} rank={i + 1} topScore={similarCases[0].score} />
              </li>
            ))}
          </ul>
        </section>
      )}

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
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M12 19V5M5 12l7-7 7 7"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
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
