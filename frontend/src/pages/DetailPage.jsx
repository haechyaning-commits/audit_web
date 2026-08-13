import { useEffect, useMemo, useState } from "react";
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
// 원문에 자주 나오는 구조 패턴(제목, 번호/가나다 항목, 로마숫자 장 구분, 괄호라벨)만
// 정규식으로 감지해서 굵게+여백을 주고, 나머지 본문은 그대로 둠. 공사마다 양식이 달라
// 완벽한 파싱은 안 되지만, 눈에 띄는 패턴만 강조해도 완전히 평평한 텍스트보다는 훨씬
// 스캔하기 쉬워짐.
//
// 2026-08-12 2차: "가." "1."처럼 구두점 있는 경우보다 "가 업무개요"처럼 구두점 없이
// 띄어쓰기만 있는 경우가 더 흔했음 — 구두점을 선택(optional)으로 완화.
//
// 2026-08-12 3차: 실제 문서로 두 가지 더 발견—
//   1) "(현황)" "(위법부당내용)" 처럼 그 줄 전체가 괄호 라벨 하나뿐인 경우가 있는데
//      아무 패턴에도 안 걸려서 문단에 그냥 흡수돼 이상하게 붙어 보였음 -> 패턴 추가.
//   2) "○ ..." 불릿은 원래 짧은 소제목이 아니라 그 자체로 긴 문단(사실상 목록 항목)을
//      이끄는 경우가 많았음. 이걸 헤더 취급해서 굵게 만들면, 같은 문장이 "첫 줄만 굵고
//      나머지는 안 굵은" 상태로 쪼개져 보여서 오히려 더 이상해 보였음 — 그래서 불릿은
//      "새 문단 시작" 신호로만 쓰고(굵게 안 함, 문단 간 여백만 살짝 줌) 구분함.
// 문서 제목 줄 — HEADING_LABEL_PATTERNS에도 포함되지만(굵게 처리 대상), 목차/타이포에서
// "제목"은 다른 헤딩과 구분해서 더 크게 세리프로 보여주고 목차 항목에서는 제외하려고
// 별도 상수로 뺌(law.go.kr류 공식 문서 타이포 요청, 2026-08-12)
const TITLE_RE = /^제\s*목\s*[:：]?\s/;

const HEADING_LABEL_PATTERNS = [
  TITLE_RE, // 제목 / 제 목
  /^징\s*계\s*(대\s*상\s*자|종\s*류|사\s*유)/, // 징계대상자 / 징 계 종 류 / 징 계 사 유
  /^관\s*계\s*기\s*관\s*[:：]?/, // 관계기관
  /^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX]+[.)]?\s/, // Ⅰ. Ⅱ. 로마숫자 장 구분
  // 1. 2. 3. 번호 항목 — 마침표 뒤에 공백이 반드시 있어야 함("20.02.21" 같은 날짜는
  // 공백 없이 붙어있어서 이걸로 구분됨, 실제 오탐 발견돼서 \s*를 \s+로 강화함)
  /^\d{1,2}[.)]\s+\S/,
  // [표 1] [별표 1] [붙임] [참고] 같은 대괄호 캡션만 — "[부서]"(익명화 placeholder,
  // 문장 맨 앞에 수도 없이 나옴)까지 통째로 걸려서 문장을 헤딩 취급하던 심각한 오탐을
  // 6차 수정에서 발견(실제 문서로 확인) — 캡션 키워드로 한정해서 좁힘
  /^\[(표|그림|별표|붙임|별첨|참고|서식|양식)\s*\d*\]/,
  /^【.+】/, // 【 구간표시 】
  /^[(（][^()（）]{1,20}[)）]$/, // (현황) (위법부당내용) 처럼 줄 전체가 괄호 라벨뿐인 경우
  // 2026-08-13 7차: "[판단근거]" "[지적사항]" "[조치할 사항]" 처럼 대괄호 라벨이 그
  // 줄 통째로 나오는 양식이 실제 문서에 많음(제목/번호항목 없이 이 방식만 쓰는 문서는
  // 전부 강조 없이 밋밋한 본문으로만 보였음). 위 캡션 패턴과 달리 "[부서]사무소는..."처럼
  // 대괄호 뒤에 문장이 이어지면 여기 안 걸림(줄 끝 $ 고정) — 그래서 6차 수정 때 막았던
  // "[부서]" 문장 오탐과는 겹치지 않음(그 placeholder는 항상 문장 중간에 이어지는 형태로만
  // 실제 문서에서 확인됨, 대괄호 하나로 줄 전체를 채우는 사례는 못 찾음).
  /^\[[^[\]]{1,20}\]$/,
];

// 새 문단(목록 항목) 시작 신호로만 쓰는 불릿 — 굵게 만들지 않음(위 3차 수정 이유 참고).
// "❍"(U+274D)도 실제 문서에서 "○"와 같은 용도로 쓰이는 걸 확인해서 추가함(4차).
// "※"/"*"도 실제 문서에서 각주(비고) 여러 개를 줄바꿈으로 나열할 때 씀 — 없으면
// "※ ... ※ ... ※ ..."가 한 문단으로 다 이어붙어서 뒤섞여 보임(5차, 실제 문서로 확인).
// 2026-08-13 7차: "①②③..." 원문자 번호도 "가/나/다"처럼 하위 항목을 나열할 때 씀
// (예: "[지적내용]\n① 『인사규정』...\n② 『복무규정』..."). 지금까지는 이게 그냥
// body로 뭉쳐서 항목 구분이 안 보였음 — 다른 불릿과 같은 이유로 굵게는 안 하고
// 문단 시작 신호로만 추가.
//
// 2026-08-13 7차 회귀: 원문자는 다른 불릿과 달리 "①제1항의..."처럼 공백 없이 문장
// 중간 조항번호로도 흔히 쓰임(특히 띄어쓰기가 통째로 빠진 추출 문서에서). 이런 줄이
// PDF 줄바꿈으로 우연히 문단 맨 앞에 오면, 같은 조항 나열인데 ①②는 한 문단에 붙어있고
// ③만 새 줄 첫머리라는 이유로 뜬금없이 쪼개지는 문제가 실제 문서로 확인됨(한국수력원자력
// 사례). 실제 목록 항목은 항상 "① 검강검진..."처럼 뒤에 공백이 있으므로, 원문자만
// 공백 필수(\s+)로 다른 불릿(\s*)과 다르게 조건을 둬서 구분함.
const BULLET_RE =
  /^(?:[-–—□○◦▪‣·❍※*]\s*\S|[①②③④⑤⑥⑦⑧⑨⑩]\s+\S)/;

// 2026-08-12 4차: 전처리 단계에서 표/그림 이미지 자체는 지웠지만, 표 안 내용이 셀 구분
// 없이 텍스트로만 남아있는 경우가 있음(예: "근무일자 근태구분 직번 질병명 ~201905
// 질병휴직 [부서] ..."). 이걸 일반 문단처럼 공백으로 이어붙이면 뜻 없는 단어 나열이라
// 오히려 더 안 읽힘 — "【표 N】"/"[표 N]"/"【그림 N】"/"[그림 N]" 캡션 직후에 이어지는
// 문단은 "표/그림에서 남은 조각"으로 보고 접어서(기본 숨김) 따로 표시함.
// 실제 문서로 확인해보니 표 데이터 바로 뒤에 빈 줄 없이 "❍ ..." 같은 실제 문장이 곧바로
// 이어지는 경우가 있어서, 그 경계를 잡으려면 BULLET_RE에 "❍"가 포함돼 있어야 함(위에서 추가).
const TABLE_CAPTION_RE = /^[【[]\s*(표|그림|별표)\s*\d*\s*[】\]]/;

// 2026-08-12 6차: 표 데이터 뒤에는 보통 "자료: ○○ 제출자료 재구성" 같은 출처 표기가
// 붙는데, 그 바로 뒤에 헤딩/불릿 없이 실제 문장이 곧장 이어지는 경우가 있었음(실제 문서로
// 확인 — "자료: 지사 제출자료 및 현지 확인 결과 재구성" 다음 줄에 "♠♡지사에서는 ①
// 차량번호..."라는 진짜 감사 내용이 헤딩/불릿 없이 바로 나옴). 이걸 못 끊으면 표 블록이
// 실제 내용까지 통째로 삼켜서 접힌 박스 안에 숨겨버리는 심각한 문제가 생김 — "자료:"/
// "출처:" 줄을 표 블록을 반드시 끝내는 경계로 인식시킴.
const SOURCE_NOTE_RE = /^(자료|출처)\s*[:：]/;

/** 줄 하나를 "heading"(굵게, 독립 블록) / "bullet"(새 문단 시작, 안 굵음) /
 * "caption"(작고 흐린 출처 표기, 독립 블록) / "body"(이어지는 일반 줄) /
 * "blank"(빈 줄, 문단 구분)로 분류. */
function classifyLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return "blank";

  // 가/나/다 단독 소제목은 원문에서 보통 그 줄 전체가 짧은 편(예: "가 업무개요") —
  // 본문 문장이 우연히 "나"로 시작하는 경우까지 오탐하지 않게 길이 상한을 둠
  if (
    /^[가나다라마바사아자차카타파하][.)]?\s+\S/.test(trimmed) &&
    trimmed.length <= 24
  ) {
    return "heading";
  }
  if (HEADING_LABEL_PATTERNS.some((re) => re.test(trimmed))) return "heading";
  if (SOURCE_NOTE_RE.test(trimmed)) return "caption";
  if (BULLET_RE.test(trimmed)) return "bullet";
  return "body";
}

/** 원문을 문단 단위 블록으로 나눔(렌더링 전 순수 데이터 단계) — renderRawText와
 * buildToc가 같은 블록 목록을 같이 써서 목차 항목과 실제 앵커가 항상 일치하게 함
 * (law.go.kr류 조문 목차 참고 요청, 2026-08-12).
 *
 * 원문의 줄바꿈(\n)은 대부분 PDF가 페이지 폭에 맞춰 끊은 자리라 실제 문장/문단 구분과
 * 다름(심하면 "근무하" / "고 있는" 처럼 단어 중간에서도 끊김) — 그 줄을 그대로 각자 블록
 * 으로 렌더링하면 원래 한 문장이 짧은 조각으로 뚝뚝 끊겨 보임(2026-08-12 피드백).
 * 그래서 헤딩/불릿 줄이나 빈 줄(진짜 문단 구분)을 만나기 전까지 이어지는 일반 줄들은
 * 공백으로 합쳐서 하나의 문단으로 흘러가게 함. */
function splitIntoBlocks(text) {
  const blocks = [];
  let para = [];
  let paraType = "body";
  let nextIsTable = false; // 표/그림 캡션 바로 다음 문단인지

  function flushPara() {
    if (para.length === 0) return;
    blocks.push({ type: paraType, text: para.join(" ") });
    para = [];
    paraType = "body";
  }

  for (const rawLine of text.split("\n")) {
    const kind = classifyLine(rawLine);
    const trimmed = rawLine.trim();

    if (kind === "blank") {
      flushPara();
      continue;
    }
    if (kind === "heading") {
      flushPara();
      blocks.push({ type: "heading", text: trimmed });
      nextIsTable = TABLE_CAPTION_RE.test(trimmed);
      continue;
    }
    if (kind === "caption") {
      flushPara(); // 표 블록이 진행 중이었으면 여기서 확실히 끝냄(6차 수정 이유 참고)
      blocks.push({ type: "caption", text: trimmed });
      nextIsTable = false;
      continue;
    }
    if (kind === "bullet") {
      flushPara(); // 불릿은 새 항목 시작 — 앞 문단과 분리(표 캡션 뒤라도 여기서 끊음)
      paraType = "bullet";
      nextIsTable = false;
      para.push(trimmed);
      continue;
    }
    if (para.length === 0 && nextIsTable) {
      paraType = "table";
      nextIsTable = false;
    }
    para.push(trimmed);
  }
  flushPara();
  return blocks;
}

/** 헤딩 블록에만 앵커 id를 붙여서 렌더링 — 목차(TocSidebar)가 이 id로 점프함.
 * id는 등장 순서 기반("heading-3")으로만 부여, buildToc와 항상 같은 순서/조건이어야 함.
 * 제목 줄(TITLE_RE)은 별도 "title" 타입으로 렌더링 — 다른 헤딩보다 크게, 세리프로. */
function renderRawText(blocks, query) {
  let headingIdx = 0;
  return blocks.map((b, i) => {
    if (b.type === "table") {
      return (
        <details key={i} className="raw-line-table">
          <summary>표/그림 데이터 (펼쳐보기)</summary>
          <div>{query ? highlightMatches(b.text, query) : b.text}</div>
        </details>
      );
    }
    if (b.type !== "heading") {
      return (
        <div key={i} className={`raw-line raw-line-${b.type}`}>
          {query ? highlightMatches(b.text, query) : b.text}
        </div>
      );
    }
    const isTitle = TITLE_RE.test(b.text);
    const id = `heading-${headingIdx++}`;
    return (
      <div
        key={i}
        id={id}
        className={`raw-line ${isTitle ? "raw-line-title" : "raw-line-heading"}`}
      >
        {query ? highlightMatches(b.text, query) : b.text}
      </div>
    );
  });
}

/** 목차 항목만 뽑음 — renderRawText의 id 채번 방식과 반드시 같은 순서/조건("heading"
 * 블록만, 등장 순서대로 — 제목도 포함해서 카운트)이어야 앵커가 안 어긋남. 다만 목차
 * 화면에는 제목 자체는 안 보여줌(페이지에 이미 큼직하게 있어서 중복). */
function buildToc(blocks) {
  let headingIdx = 0;
  const items = [];
  for (const b of blocks) {
    if (b.type !== "heading") continue;
    const id = `heading-${headingIdx++}`;
    if (TITLE_RE.test(b.text)) continue;
    items.push({ id, text: b.text });
  }
  return items;
}

function TocSidebar({ items }) {
  if (items.length < 3) return null; // 항목 적으면 스크롤 한 번이면 끝 — 목차가 노이즈만 됨

  function handleClick(e, id) {
    e.preventDefault();
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <nav className="toc-sidebar" aria-label="원문 목차">
      <p className="toc-label">목차</p>
      <ol>
        {items.map((item) => (
          <li key={item.id}>
            <a href={`#${item.id}`} onClick={(e) => handleClick(e, item.id)}>
              {item.text}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
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

  // raw_text -> 블록 목록은 doc이 바뀔 때만 다시 계산(문서 하나가 꽤 길어서 매 렌더마다
  // 다시 파싱하면 낭비) — renderRawText(본문)와 buildToc(목차)가 같은 블록 목록을 공유
  const blocks = useMemo(
    () => (doc ? splitIntoBlocks(doc.raw_text) : []),
    [doc],
  );
  const tocItems = useMemo(() => buildToc(blocks), [blocks]);

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
        if (!cancelled)
          setError(err.message || "상세 정보를 불러오지 못했습니다.");
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
              <b>{doc.institution || "기관명 미상"}</b>
              {doc.year ? <span className="sep">›</span> : null}
              {doc.year ? `${doc.year}년` : ""}
              {doc.audit_type ? <span className="sep">›</span> : null}
              {doc.audit_type || ""}
            </p>
            <div className="detail-header">
              <ConfidenceBadge label={doc.confidence} />
            </div>

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
