import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, getInstitutionProfile } from "../api.js";
import ResultCard, { AUDIT_TYPE_CLASS } from "../components/ResultCard.jsx";
import useDocumentTitle from "../useDocumentTitle.js";

/**
 * 기관 프로필 미니페이지(GET /institutions/{name}) — "이 기관이 감사를 얼마나 자주/
 * 어떤 종류로 받았나"를 기관명 하나로 바로 보여줌(2026-08-26 기능 추가). 검색 결과
 * 카드의 기관명을 클릭하면 여기로 옴(ResultCard.jsx/DetailPage.jsx).
 *
 * YearChart(홈 화면용)를 그대로 재사용하지 않은 이유: 그 컴포넌트는 "배열의 마지막
 * 연도 = 지금 진행 중인 올해"라는 걸 전제로 "진행중" 배지를 붙이는데, 기관별로 잘라보면
 * 마지막 연도가 실제 올해가 아닐 수 있음(예: 최근 사례가 2020년이 마지막인 기관) —
 * 잘못된 배지가 붙는 걸 막으려고 이 페이지 전용의 더 단순한 막대만 씀.
 */
export default function InstitutionPage() {
  const { name } = useParams();
  const decodedName = decodeURIComponent(name);
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useDocumentTitle(profile ? `${profile.institution} - 공공감사데이터 검색` : "기관 프로필");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setProfile(null);
    getInstitutionProfile(decodedName)
      .then((data) => {
        if (!cancelled) setProfile(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError && err.status === 404
              ? "해당 기관의 사례를 찾을 수 없습니다."
              : err.message || "기관 정보를 불러오지 못했습니다.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [decodedName]);

  if (loading) {
    return (
      <div className="app-main">
        <p className="institution-loading">불러오는 중…</p>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="app-main">
        <div className="empty-state">
          <h3>{error || "기관 정보를 불러오지 못했습니다."}</h3>
          <Link to="/" className="chip">
            홈으로 돌아가기
          </Link>
        </div>
      </div>
    );
  }

  const maxYearCount = Math.max(1, ...profile.years.map((y) => y.count));

  return (
    <div className="app-main institution-page">
      <p className="detail-breadcrumb">
        <Link to="/">홈</Link>
        <span className="sep">›</span>
        기관 프로필
      </p>
      <h1 className="institution-title">{profile.institution}</h1>
      <p className="institution-total">
        전체 <b>{profile.total.toLocaleString()}건</b>의 감사 사례
      </p>

      <div className="institution-stats">
        <div className="institution-stat-card">
          <p className="institution-stat-title">연도별 사례 수</p>
          {profile.years.length === 0 ? (
            <p className="institution-empty">연도 정보가 있는 사례가 없습니다.</p>
          ) : (
            <>
              <div className="institution-year-bars">
                {profile.years.map((y) => (
                  <div className="institution-year-col" key={y.year}>
                    <span className="institution-year-val">{y.count}</span>
                    <div
                      className="institution-year-bar"
                      style={{ height: `${Math.max(6, (y.count / maxYearCount) * 100)}%` }}
                    />
                  </div>
                ))}
              </div>
              <div className="institution-year-labels">
                {profile.years.map((y) => (
                  <span key={y.year}>{y.year}</span>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="institution-stat-card">
          <p className="institution-stat-title">감사종류별 사례 수</p>
          {profile.audit_types.length === 0 ? (
            <p className="institution-empty">감사종류 정보가 있는 사례가 없습니다.</p>
          ) : (
            <ul className="institution-audit-type-list">
              {profile.audit_types.map((t) => (
                <li key={t.audit_type}>
                  <span
                    className={`institution-audit-type-dot ${AUDIT_TYPE_CLASS[t.audit_type] || ""}`}
                    aria-hidden="true"
                  />
                  <span className="institution-audit-type-name">{t.audit_type}</span>
                  <span className="institution-audit-type-count">{t.count}건</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <section>
        <p className="section-label">
          최신 사례 <span className="count">{profile.recent_cases.length}건</span>
        </p>
        <ul className="result-list">
          {profile.recent_cases.map((result) => (
            <li key={result.document_id}>
              <ResultCard result={result} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
