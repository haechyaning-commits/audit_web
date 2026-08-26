import { Link } from "react-router-dom";
import { buildCaseUrl } from "../caseUrl.js";
import highlightMatches from "../highlight.jsx";

// 2026-08-26(디자인 평가 피드백): 지금까지 감사종류 배지가 4종 전부 같은 파란 틴트라,
// title 없는 문서가 많은 목록에서 행끼리 구분이 잘 안 됐음. 데이터/API 변경 없이 CSS
// 색상만으로 스캔하기 쉽게 함 — 새 색을 만들지 않고 기존 토큰(success/warn/amend)만
// 재사용(index.css 참고). 종합감사(가장 흔한 기본형)는 기존 primary 틴트 그대로 둠.
const AUDIT_TYPE_CLASS = {
  재무감사: "result-card-audit-type-finance",
  복무감사: "result-card-audit-type-conduct",
  특정감사: "result-card-audit-type-special",
};

/**
 * 2026-08-12: law.go.kr류 목록형으로 재구성 — 카드(둥근모서리+그림자) 그리드 대신
 * 왼쪽 번호열 / 가운데 본문 / 오른쪽 메타(감사종류·연도) 3열 행으로 촘촘하게 나열.
 *
 * @param {object} result - 검색 결과 카드 데이터
 * @param {number} [rank] - 표시할 순위(왼쪽 번호열, 예: 01). 없으면 번호열 생략
 * @param {string} [query] - 미리보기 텍스트에서 하이라이트할 검색어
 * @param {number} [topScore] - 이 검색의 1위 결과 스코어(상대 관련도 막대 기준값,
 *   없으면 막대 생략) — SearchPage.jsx가 results[0].score를 넘겨줌
 * @param {string} [className]
 */
export default function ResultCard({ result, rank, query, topScore, className = "" }) {
  const { title, institution, year, audit_type, preview_text, score } = result;
  const to = buildCaseUrl(result, query);
  // 2026-08-24(피드백 반영): score 자체(예: 0.031)는 사용자가 봐도 의미를 알기 어려워서,
  // 1위 대비 상대값(%)으로 정규화해서 막대로만 보여줌 — 정확한 스코어 수치를 노출하지
  // 않는 이유는 RRF 점수가 "이 검색어 안에서의 상대적 순위"일 뿐 절대적인 신뢰도가
  // 아니라서, 숫자를 그대로 보여주면 오히려 오해를 살 수 있음. 최소 6%는 항상 채워서
  // 40위 결과도 막대가 아예 안 보이진 않게 함(있다는 것 자체는 알 수 있게).
  const relevancePct =
    topScore && score != null ? Math.max(6, Math.round((score / topScore) * 100)) : null;

  return (
    <Link to={to} className={`result-card ${className}`}>
      {rank != null && (
        <span className="result-card-rank mono" aria-hidden="true">
          {String(rank).padStart(2, "0")}
        </span>
      )}
      <div className="result-card-body">
        {/* 2026-08-25(베타테스트 피드백 4번): 지금까지 카드에 title이 아예 안 쓰이고
            있었음 — raw_text 맨 앞줄이 "제목 : ..." 형식으로 안 된 문서(전체의 약
            절반, textutils.extract_title 참고)는 title이 null이라 아예 못 보여주는
            게 원래 이유. null일 땐 그냥 생략 — 지금처럼 기관명 줄이 유일한 제목
            역할을 그대로 하게 둠(레이아웃 안 깨짐). title이 있을 때만 그 위에
            추가로 보여줘서, 있는 문서는 목록에서 바로 스캔 가능하게 함. */}
        {title && <h3 className="result-card-title">{title}</h3>}
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
        {audit_type && (
          <span
            className={`result-card-audit-type ${AUDIT_TYPE_CLASS[audit_type] || ""}`}
          >
            {audit_type}
          </span>
        )}
        {relevancePct != null && (
          <span
            className="result-card-relevance"
            title={`1위 결과 대비 상대 관련도 ${relevancePct}%`}
          >
            <span className="result-card-relevance-fill" style={{ width: `${relevancePct}%` }} />
          </span>
        )}
      </div>
    </Link>
  );
}
