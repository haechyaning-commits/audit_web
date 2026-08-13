import { useEffect, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import SearchPage from "./pages/SearchPage.jsx";
import DetailPage from "./pages/DetailPage.jsx";
import NotFoundPage from "./pages/NotFoundPage.jsx";
import Footer from "./components/Footer.jsx";
import HeaderSearch from "./components/HeaderSearch.jsx";
import useSearchState from "./useSearchState.js";
import useTheme from "./useTheme.js";

const GITHUB_URL = "https://github.com/haechyaning-commits/audit_web";

export default function App() {
  const { theme, toggleTheme } = useTheme();
  const [isScrolled, setIsScrolled] = useState(false);
  const location = useLocation();
  const search = useSearchState();

  // 헤더 검색창은 "검색 결과 화면"이거나 "다른 페이지(상세페이지 등)"일 때만 보임 —
  // 랜딩 화면("/", 검색 전)에선 히어로 검색창과 중복되니 숨김. 항상 둘 중 하나만 보임.
  const showHeaderSearch = location.pathname !== "/" || search.results !== null;

  useEffect(() => {
    function onScroll() {
      setIsScrolled(window.scrollY > 8);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="app">
      <div className="util-bar">
        <div className="util-bar-inner">
          <span className="util-bar-text">공공감사 사례 데이터를 활용한 AI 검색 포트폴리오 프로젝트</span>
          <span className="util-links">
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.1.68-.22.68-.49 0-.24-.01-.87-.01-1.71-2.78.62-3.37-1.37-3.37-1.37-.46-1.19-1.11-1.51-1.11-1.51-.91-.64.07-.63.07-.63 1 .07 1.53 1.05 1.53 1.05.89 1.56 2.34 1.11 2.91.85.09-.66.35-1.11.63-1.37-2.22-.26-4.56-1.14-4.56-5.06 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.31.1-2.73 0 0 .84-.28 2.75 1.05a9.3 9.3 0 0 1 5 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.42.2 2.47.1 2.73.64.72 1.03 1.63 1.03 2.75 0 3.93-2.34 4.79-4.57 5.05.36.32.68.94.68 1.9 0 1.37-.01 2.48-.01 2.81 0 .27.18.6.69.49A10.26 10.26 0 0 0 22 12.25C22 6.58 17.52 2 12 2z" />
              </svg>
              GitHub
            </a>
          </span>
        </div>
      </div>

      <header className={`app-header ${isScrolled ? "is-scrolled" : ""}`}>
        <div className="app-header-inner">
          <Link to="/" className="app-logo-badge" onClick={search.resetSearch}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M12 2L4 5v6c0 5.25 3.4 9.74 8 11 4.6-1.26 8-5.75 8-11V5l-8-3z"
                fill="#fff"
              />
              <path
                d="M9 12l2 2 4-4"
                stroke="var(--primary)"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </Link>
          <Link to="/" className="app-title-group" onClick={search.resetSearch}>
            <span className="app-title">공공감사데이터 검색</span>
            <span className="app-tagline">감사 유사사례 검색 서비스</span>
          </Link>
          {showHeaderSearch && <HeaderSearch runSearch={search.runSearch} />}
          <div className="header-actions">
            <span className="beta-tag">BETA</span>
            <button
              type="button"
              className="icon-btn"
              onClick={toggleTheme}
              title={theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"}
              aria-label={theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"}
            >
              {theme === "dark" ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <circle cx="12" cy="12" r="4.5" stroke="currentColor" strokeWidth="1.7" />
                  <path
                    d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                  />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="app-body">
        <Routes>
          <Route path="/" element={<SearchPage search={search} />} />
          {/* /cases/:id/:slug가 새 URL 구조(law.go.kr류) — :slug는 표시용이라 안 읽음.
              /documents/:id는 예전 링크/북마크가 안 깨지게 그대로 유지 (DetailPage가
              로드 후 새 URL로 자동 교체함, caseUrl.js 참고). 두 라우트 다 파라미터
              이름을 "id"로 맞춰서 DetailPage가 어느 쪽으로 들어왔는지 분기 안 해도 됨. */}
          <Route path="/cases/:id/:slug" element={<DetailPage />} />
          <Route path="/documents/:id" element={<DetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>

      <Footer />
    </div>
  );
}
