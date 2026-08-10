export default function Footer() {
  return (
    <footer className="app-footer">
      <div>
        <strong>공공감사데이터 검색</strong> — 본 서비스는 공개된 공공감사 사례 데이터를
        재구성한 포트폴리오 프로젝트입니다.
      </div>
      <div className="footer-a11y">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.6" />
          <path d="M12 8v5M12 16h.01" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        이 웹사이트는 웹 접근성을 고려하여 제작되었습니다
      </div>
    </footer>
  );
}
