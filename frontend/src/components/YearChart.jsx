/**
 * 히어로 하단 연도별 문서 수 막대그래프.
 *
 * data가 비어있으면 아무것도 렌더링하지 않음 — 재임베딩/DB 정리(STATUS.md 참고)가 끝나고
 * 실제 연도별 카운트를 SearchPage.jsx의 YEAR_COUNTS에 채워 넣기 전까지는 화면에 안 뜸.
 * 가짜 예시 숫자를 실제 서비스에 노출시키지 않기 위한 안전장치.
 *
 * @param {{year: number, count: number}[]} data - 연도 오름차순 정렬된 배열
 */
export default function YearChart({ data }) {
  if (!data || data.length === 0) return null;

  const max = Math.max(...data.map((d) => d.count));
  const lastYear = data[data.length - 1].year;

  return (
    <div className="year-chart">
      <p className="year-chart-title">연도별 사례 수</p>
      <div className="year-chart-bars">
        {data.map((d) => (
          <div className="year-chart-col" key={d.year}>
            <span className="year-chart-val">{d.count.toLocaleString()}</span>
            <div
              className={`year-chart-bar ${d.year === lastYear ? "is-latest" : ""}`}
              style={{ height: `${Math.max(6, (d.count / max) * 100)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="year-chart-labels">
        {data.map((d) => (
          <span key={d.year}>{d.year}</span>
        ))}
      </div>
    </div>
  );
}
