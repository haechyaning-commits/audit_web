/**
 * 검색 결과 목록 상단의 "이 검색어, 연도별로 얼마나 나왔나" 미니 막대그래프.
 *
 * 2026-08-26(기능 추가, 디자인 평가 피드백): 홈 화면의 YearChart(전체 문서 기준)와
 * 달리, 이건 지금 이 검색의 후보 풀(candidates, 최대 40~100건) 기준 분포임 —
 * "전체 코퍼스에서 이 주제가 몇 건인지"가 아니라 "지금 보고 있는 결과들이 어느
 * 연도에 몰려있는지" 감을 잡는 용도. data가 비어있으면(검색 실패/문서 0건) 아무것도
 * 렌더링하지 않음.
 *
 * @param {{year: number, count: number}[]} data - 연도 오름차순 정렬된 배열(백엔드가 이미 정렬해서 줌)
 */
export default function YearTrendChart({ data }) {
  if (!data || data.length === 0) return null;

  const max = Math.max(...data.map((d) => d.count));

  return (
    <div className="year-trend">
      <p className="year-trend-title">이 검색어, 연도별 분포</p>
      <div className="year-trend-bars">
        {data.map((d) => (
          <div className="year-trend-col" key={d.year} title={`${d.year}년 ${d.count}건`}>
            <div
              className="year-trend-bar"
              style={{ height: `${Math.max(8, (d.count / max) * 100)}%` }}
            />
            <span className="year-trend-year">{String(d.year).slice(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
