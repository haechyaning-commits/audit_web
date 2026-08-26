import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDailyCase } from "../api.js";
import { buildCaseUrl } from "../caseUrl.js";

/**
 * 홈 화면 "오늘의 사례" — 검색 전(히어로 영역)이 지금까지 완전히 정적이라 재방문
 * 유인이 없었음(디자인 평가 피드백, 2026-08-26). GET /documents/daily가 날짜 기준으로
 * 결정적으로 고른 문서 1건을 반환하므로, 같은 날 안에는 새로고침해도 항상 같은 사례가
 * 보임 — "오늘의"라는 이름과 실제 동작이 일치함.
 *
 * 연도별 통계(yearStats)와 같은 원칙: 로딩 스피너/빈 화면 없이 실패하면 조용히
 * 섹션 자체를 숨김(부가 기능이 히어로 영역 전체를 막을 이유가 없음, /similar와 같은 패턴).
 */
export default function DailyCase() {
  const [item, setItem] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getDailyCase()
      .then((data) => {
        if (!cancelled) setItem(data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed || !item) return null;

  return (
    <Link to={buildCaseUrl(item)} className="daily-case">
      <span className="daily-case-label">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.8" />
          <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
        오늘의 사례
      </span>
      <span className="daily-case-title">
        {item.title || `${item.institution || "기관명 미상"}${item.year ? ` · ${item.year}년` : ""}`}
      </span>
      <span className="daily-case-preview">{item.preview_text}</span>
    </Link>
  );
}
