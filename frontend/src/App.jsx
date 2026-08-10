import { Link, Route, Routes } from "react-router-dom";
import SearchPage from "./pages/SearchPage.jsx";
import DetailPage from "./pages/DetailPage.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="app-title">
          공공감사데이터 검색
        </Link>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/documents/:id" element={<DetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
