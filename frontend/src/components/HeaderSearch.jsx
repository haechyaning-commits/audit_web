import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

/**
 * 헤더에 상시 붙어있는 검색창 — App.jsx가 "결과 화면이거나 다른 페이지일 때만" 렌더링함
 * (랜딩 화면에선 히어로 검색창과 중복되니 숨김, 두 검색창이 동시에 보이는 일은 없음).
 *
 * 어느 페이지에서 검색하든 결과는 "/"에서 보여줘야 하므로, 제출 시 먼저 "/"로 이동시키고
 * 그 자리에서 바로 검색까지 실행함(공유 runSearch를 직접 호출 — SearchPage의 마운트 이펙트가
 * 알아서 다시 검색해줄 때까지 안 기다림. loading 값이 먼저 true가 되므로 중복 실행 안 됨).
 */
export default function HeaderSearch({ runSearch }) {
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    function onKeyDown(e) {
      if (e.key !== "/") return;
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      e.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleSubmit(event) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    navigate(`/?q=${encodeURIComponent(trimmed)}`);
    runSearch(trimmed);
  }

  return (
    <form className="header-search" onSubmit={handleSubmit} role="search">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
        <path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="다시검색하기"
        aria-label="검색어"
      />
    </form>
  );
}
