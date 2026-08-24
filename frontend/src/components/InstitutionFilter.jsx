import { useEffect, useState } from "react";

/**
 * 기관 필터 — 목록이 수십~백여 개라 평범한 <select>는 스크롤하며 찾기 불편하다는
 * 피드백(2026-08-24)으로, 입력하면 실시간으로 걸러지는 자동완성 콤보박스로 교체.
 * 외부 라이브러리 없이 최소 구현(이 프로젝트는 react/react-dom/react-router-dom
 * 외 의존성을 최소로 유지하는 방침 — README 기술 스택 참고).
 *
 * value(실제 적용된 필터)와 입력창 텍스트를 분리해서 관리 — 목록에서 선택해야만
 * onChange가 호출되고(실제 검색이 다시 실행됨), 타이핑 중에는 그냥 후보만 걸러
 * 보여줌. 제안 항목은 onMouseDown에서 preventDefault로 처리해서 클릭해도 입력창이
 * blur되지 않게 함 — blur와 클릭 선택 사이의 타이밍 경쟁(어느 게 먼저 발생할지
 * 브라우저마다 다름)을 아예 없애는 표준적인 방법.
 */
export default function InstitutionFilter({ institutions, value, onChange }) {
  const [inputValue, setInputValue] = useState(value || "");
  const [open, setOpen] = useState(false);

  // 바깥에서 필터가 바뀌면(예: URL 뒤로가기, 다른 검색으로 필터가 초기화되는 경우)
  // 입력창 표시도 실제 적용된 값과 맞춤.
  useEffect(() => {
    setInputValue(value || "");
  }, [value]);

  const trimmed = inputValue.trim();
  const filtered = trimmed
    ? institutions.filter((inst) => inst.includes(trimmed))
    : institutions;

  function selectInstitution(inst) {
    setInputValue(inst);
    setOpen(false);
    onChange(inst);
  }

  function clear() {
    setInputValue("");
    setOpen(false);
    onChange("");
  }

  return (
    <div className="institution-filter">
      <input
        type="text"
        className="institution-filter-input"
        value={inputValue}
        placeholder="전체 기관"
        onChange={(e) => {
          setInputValue(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          // 목록 클릭은 위 onMouseDown의 preventDefault로 blur 자체가 안 일어나므로,
          // 여기 도달하는 건 선택 없이 포커스를 벗어난 경우(탭 이동/바깥 클릭)뿐 —
          // 안전하게 실제 적용된 값으로 표시를 되돌림.
          setTimeout(() => {
            setOpen(false);
            setInputValue(value || "");
          }, 100);
        }}
        aria-label="기관 검색"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {inputValue && (
        <button
          type="button"
          className="institution-filter-clear"
          onMouseDown={(e) => {
            e.preventDefault();
            clear();
          }}
          aria-label="기관 필터 지우기"
        >
          ×
        </button>
      )}
      {open && filtered.length > 0 && (
        <ul className="institution-filter-dropdown" role="listbox">
          {filtered.slice(0, 30).map((inst) => (
            <li key={inst}>
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectInstitution(inst);
                }}
              >
                {inst}
              </button>
            </li>
          ))}
          {filtered.length > 30 && (
            <li className="institution-filter-more">
              +{filtered.length - 30}건 더 있음 — 계속 입력해서 좁혀보세요
            </li>
          )}
        </ul>
      )}
      {open && trimmed && filtered.length === 0 && (
        <ul className="institution-filter-dropdown">
          <li className="institution-filter-empty">일치하는 기관이 없습니다</li>
        </ul>
      )}
    </div>
  );
}
