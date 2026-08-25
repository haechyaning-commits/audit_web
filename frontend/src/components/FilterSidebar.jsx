import { useMemo, useState } from "react";

// 2026-08-24(FR5 2차): 기관/연도/감사유형 필터 — 처음엔 <select>/자동완성 콤보박스로
// 시도했다가 두 가지 실사용 피드백으로 이 형태(고정 사이드바 + 체크박스)로 바뀜:
//   ① "기관이 너무 많아서 스크롤/드래그해서 찾아야 한다" — 검색 결과에 실제로 있는
//      값만 보여주면 훨씬 짧아짐(아래 buildOrder)
//   ② "누를 때마다 목록이 재배치돼서 정신없다" — 그래서 각 필터의 "자리 순서"는
//      baseResults(이 검색어의 필터 없는 기준 결과)로 딱 한 번만 정하고 그 뒤로는
//      절대 안 바뀜. 값이 바뀌는 건 옆에 붙은 개수뿐이고, 0건이 된 항목도 목록에서
//      없애지 않고 흐리게만 표시함 — AI허브류 정부 데이터 포털 필터 참고(사용자 요청).
//
// counts는 baseResults가 아니라 매번 새로 받아오는 results(현재 적용된 다른 필터가
// 이미 반영된 실제 검색 결과)로 계산함 — 그래야 "기관 A로 좁혔을 때 연도별 개수"처럼
// 다른 필터 조합까지 반영된 숫자가 나옴. 지금 필터링 중인 바로 그 차원 자체는 결과가
// 이미 그 값 하나로만 좁혀져 있어서 다른 값들이 전부 0으로 보이는데, "전체보기"로
// 리셋하면 되므로 크게 문제되지 않음.
function countBy(list, key) {
  const m = new Map();
  for (const r of list) {
    const v = r[key];
    if (v === null || v === undefined || v === "") continue;
    m.set(v, (m.get(v) || 0) + 1);
  }
  return m;
}

// 감사유형/기관은 개수 많은 순(빈도)이 자연스럽지만, 연도는 그 자체로 순서가 있는
// 값이라 빈도순으로 두면 뒤죽박죽으로 보임(2026-08-24, 사용자 제보) — sortMode로
// "year"일 땐 최신순(내림차순)으로, 나머지는 기존처럼 빈도순으로 정렬.
function buildOrder(baseResults, key, sortMode = "frequency") {
  const counts = countBy(baseResults || [], key);
  const values = [...counts.keys()];
  if (sortMode === "chronological") {
    return values.sort((a, b) => b - a);
  }
  return values.sort((a, b) => counts.get(b) - counts.get(a));
}

function FilterGroup({
  title,
  order,
  activeValue,
  counts,
  formatLabel,
  onToggle,
  extra,
  fixedHeight,
}) {
  return (
    <div className="filter-group">
      <p className="filter-group-title">
        {title}
        {activeValue ? (
          <button type="button" className="filter-reset" onClick={() => onToggle(activeValue)}>
            전체보기
          </button>
        ) : null}
      </p>
      {extra}
      {/* 2026-08-24(3차): 기관 검색창에 타이핑하면 후보가 줄어드는데, 목록 박스가
          내용 높이만큼 줄어들면서 그 아래 "연도" 칸이 따라 올라오는 문제(틀이
          흔들린다는 피드백) — 검색 가능한 목록(fixedHeight)은 내용이 몇 개든
          박스 높이를 고정해서, 타이핑해도 사이드바 전체 레이아웃이 안 움직이게 함. */}
      <ul className={`filter-list ${fixedHeight ? "filter-list-fixed" : ""}`}>
        {order.map((value) => {
          const n = counts.get(value) || 0;
          const checked = String(activeValue) === String(value);
          const zero = n === 0 && !checked;
          return (
            <li key={value}>
              <button
                type="button"
                className={`filter-row ${checked ? "checked" : ""} ${zero ? "zero" : ""}`}
                disabled={zero}
                onClick={() => onToggle(value)}
              >
                <span className="box" aria-hidden="true" />
                <span className="name">{formatLabel(value)}</span>
                <span className="n">{n}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function FilterSidebar({
  baseResults,
  results,
  filters,
  onChange,
  onResetAll,
  className = "",
}) {
  const [instQuery, setInstQuery] = useState("");
  const hasActiveFilter = Boolean(filters.institution || filters.year || filters.audit_type);

  // 순서는 baseResults가 바뀔 때만(=검색어가 바뀔 때만) 다시 계산 — 필터 조작 중엔
  // 재계산 안 됨(자리 고정의 핵심).
  const instOrder = useMemo(() => buildOrder(baseResults, "institution"), [baseResults]);
  const yearOrder = useMemo(
    () => buildOrder(baseResults, "year", "chronological"),
    [baseResults],
  );
  const typeOrder = useMemo(() => buildOrder(baseResults, "audit_type"), [baseResults]);

  const list = results || [];
  const instCounts = countBy(list, "institution");
  const yearCounts = countBy(list, "year");
  const typeCounts = countBy(list, "audit_type");

  const filteredInstOrder = instQuery
    ? instOrder.filter((inst) => inst.includes(instQuery))
    : instOrder;

  return (
    <aside className={`filter-sidebar ${className}`}>
      {hasActiveFilter && (
        <div className="filter-sidebar-header">
          <button type="button" className="filter-reset-all" onClick={onResetAll}>
            필터 전체 초기화
          </button>
        </div>
      )}
      <FilterGroup
        title="감사유형"
        order={typeOrder}
        activeValue={filters.audit_type}
        counts={typeCounts}
        formatLabel={(v) => v}
        onToggle={(v) => onChange("audit_type", filters.audit_type === v ? "" : v)}
      />
      <FilterGroup
        title="기관"
        order={filteredInstOrder}
        activeValue={filters.institution}
        counts={instCounts}
        formatLabel={(v) => v}
        onToggle={(v) => onChange("institution", filters.institution === v ? "" : v)}
        fixedHeight={instOrder.length > 8}
        extra={
          instOrder.length > 8 && (
            <input
              type="text"
              className="filter-search"
              placeholder="기관명 검색"
              value={instQuery}
              onChange={(e) => setInstQuery(e.target.value.trim())}
              aria-label="기관 목록 검색"
            />
          )
        }
      />
      <FilterGroup
        title="연도"
        order={yearOrder}
        activeValue={filters.year ? Number(filters.year) : ""}
        counts={yearCounts}
        formatLabel={(v) => `${v}년`}
        onToggle={(v) => onChange("year", String(filters.year) === String(v) ? "" : v)}
      />
    </aside>
  );
}
