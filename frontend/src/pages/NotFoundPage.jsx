import { Link } from "react-router-dom";

/** 정의되지 않은 경로("/asdf" 등) 접근 시 보여주는 404 화면.
 * 예전엔 라우터에 catch-all이 없어서 완전히 빈 화면이 떴었음(2026-08-12 발견). */
export default function NotFoundPage() {
  return (
    <div className="app-main">
      <div className="empty-state">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6" />
          <path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        <h3>존재하지 않는 페이지입니다</h3>
        <p>주소를 다시 확인하시거나 검색으로 돌아가주세요.</p>
        <Link to="/" className="chip">
          ← 검색으로 돌아가기
        </Link>
      </div>
    </div>
  );
}
