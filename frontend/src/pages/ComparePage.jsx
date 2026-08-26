import { Fragment, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getCaseDetail, getCaseSummary } from "../api.js";
import { buildCaseUrl } from "../caseUrl.js";
import ConfidenceBadge from "../components/ConfidenceBadge.jsx";
import useDocumentTitle from "../useDocumentTitle.js";

const SUMMARY_ROWS = [
  { key: "summary_point", label: "지적사항" },
  { key: "summary_cause", label: "원인" },
  { key: "summary_action", label: "조치" },
  { key: "summary_result", label: "결과" },
];

/**
 * 나란히 비교(MVP+본기능, 2026-08-26 기능 추가) — 여러 사례를 한 화면에서 항목별로
 * 비교. 설계 근거는 아티팩트("나란히 보기")로 미리 공유했던 것 그대로:
 *   - 새 백엔드 엔드포인트 없음 — 기존 GET /documents/{id}를 선택된 개수만큼
 *     Promise.allSettled로 병렬 호출(상세페이지가 이미 하는 일을 여러 번 하는 것뿐)
 *   - URL(?ids=id1,id2,id3)이 상태의 전부 — 새로고침/공유 링크로도 재현됨
 *   - 요약이 아직 캐싱 안 된 문서는 "요약 생성" 버튼만(진입 즉시 일괄 생성 안 함 —
 *     상세페이지와 같은 온디맨드 원칙, LLM 호출 N배 방지)
 */
export default function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const ids = (searchParams.get("ids") || "").split(",").filter(Boolean);

  const [docs, setDocs] = useState({}); // id -> DocumentDetail | { error: true }
  const [loadingIds, setLoadingIds] = useState(new Set());
  const [summarizingIds, setSummarizingIds] = useState(new Set());

  useDocumentTitle(ids.length > 0 ? `사례 비교 (${ids.length}건) - 공공감사데이터 검색` : null);

  useEffect(() => {
    let cancelled = false;
    const missing = ids.filter((id) => !(id in docs));
    if (missing.length === 0) return;

    setLoadingIds((prev) => new Set([...prev, ...missing]));
    Promise.allSettled(missing.map((id) => getCaseDetail(id))).then((results) => {
      if (cancelled) return;
      setDocs((prev) => {
        const next = { ...prev };
        missing.forEach((id, i) => {
          const r = results[i];
          next[id] = r.status === "fulfilled" ? r.value : { error: true };
        });
        return next;
      });
      setLoadingIds((prev) => {
        const next = new Set(prev);
        missing.forEach((id) => next.delete(id));
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);

  function removeId(id) {
    const remaining = ids.filter((x) => x !== id);
    if (remaining.length === 0) {
      setSearchParams({});
    } else {
      setSearchParams({ ids: remaining.join(",") });
    }
  }

  async function generateSummary(id) {
    setSummarizingIds((prev) => new Set([...prev, id]));
    try {
      const summary = await getCaseSummary(id);
      setDocs((prev) => ({ ...prev, [id]: { ...prev[id], ...summary } }));
    } catch {
      // 실패해도 조용히 — 요약 셀이 그냥 "생성 실패, 다시 시도" 버튼 그대로 남음
    } finally {
      setSummarizingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  if (ids.length === 0) {
    return (
      <div className="app-main">
        <div className="empty-state">
          <h3>비교할 사례가 없습니다</h3>
          <p>검색 결과에서 "비교 모드"를 켜고 2건 이상 선택해주세요.</p>
          <Link to="/" className="chip">
            검색으로 돌아가기
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="app-main compare-page">
      <p className="section-label">
        사례 비교 <span className="count">{ids.length}건</span>
      </p>
      <div className="compare-scroll">
        <div className="compare-grid" style={{ "--compare-cols": ids.length }}>
          {/* 헤더 행 — 기관/연도/감사유형/신뢰도, sticky */}
          <div className="compare-cell compare-row-label compare-head-label" />
          {ids.map((id) => {
            const doc = docs[id];
            return (
              <div className="compare-cell compare-head" key={id}>
                <button
                  type="button"
                  className="compare-remove"
                  onClick={() => removeId(id)}
                  aria-label="비교에서 제거"
                  title="비교에서 제거"
                >
                  ✕
                </button>
                {loadingIds.has(id) && <p className="compare-loading">불러오는 중…</p>}
                {doc?.error && <p className="compare-error">불러오지 못했습니다</p>}
                {doc && !doc.error && (
                  <>
                    <Link to={buildCaseUrl({ document_id: id, ...doc })} className="compare-inst">
                      {doc.institution || "기관명 미상"}
                    </Link>
                    <div className="compare-meta">
                      {doc.year ? `${doc.year}년` : ""}
                      {doc.audit_type ? ` · ${doc.audit_type}` : ""}
                    </div>
                    <ConfidenceBadge label={doc.confidence} />
                  </>
                )}
              </div>
            );
          })}

          {/* 4줄 요약 행들 */}
          {SUMMARY_ROWS.map((row) => (
            <Fragment key={row.key}>
              <div className="compare-cell compare-row-label">
                {row.label}
              </div>
              {ids.map((id) => {
                const doc = docs[id];
                const value = doc?.[row.key];
                const failed = row.key === "summary_point" && doc?.summary_failed;
                return (
                  <div className="compare-cell compare-body" key={`${row.key}-${id}`}>
                    {!doc || doc.error ? (
                      "—"
                    ) : value ? (
                      value
                    ) : failed ? (
                      "요약 어려움 — 원문 참고 필요"
                    ) : (
                      <button
                        type="button"
                        className="compare-summary-btn"
                        disabled={summarizingIds.has(id)}
                        onClick={() => generateSummary(id)}
                      >
                        {summarizingIds.has(id) ? "생성 중…" : "요약 생성"}
                      </button>
                    )}
                  </div>
                );
              })}
            </Fragment>
          ))}

          {/* 원문 첫 부분 */}
          <div className="compare-cell compare-row-label">원문(일부)</div>
          {ids.map((id) => {
            const doc = docs[id];
            return (
              <div className="compare-cell compare-body compare-raw" key={`raw-${id}`}>
                {!doc || doc.error ? "—" : (doc.raw_text || "").slice(0, 300)}
                {doc && !doc.error && doc.raw_text?.length > 300 ? "…" : ""}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
