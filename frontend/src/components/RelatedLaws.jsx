import { lawSearchUrl } from "../lawLink.jsx";

/**
 * 검색 결과 상단 "관련 법령 모아보기".
 *
 * 2026-08-26(기능 교체): 원래 "이 검색어, 연도별 분포" 미니차트였는데, 사이드바 연도
 * 필터(체크박스, 이미 건수 보여주고 클릭도 됨)와 정보가 그대로 겹친다는 피드백으로
 * 교체함 — 이건 다른 화면 어디에도 없는 새 정보이고, law.go.kr 하이퍼링크 기능(원문
 * 상세페이지)과 자연스럽게 이어져서 실무 도구 성격에 더 맞음.
 *
 * data가 비어있으면(이 검색 결과에 법령 인용이 하나도 없거나 전부 내부규정/문서명이라
 * 걸러진 경우) 아무것도 렌더링하지 않음 — 억지로 빈 자리를 안 채움.
 *
 * @param {{name: string, count: number}[]} data - 빈도순 정렬(백엔드가 이미 정렬해서 줌)
 */
export default function RelatedLaws({ data }) {
  if (!data || data.length === 0) return null;

  return (
    <div className="related-laws">
      <p className="related-laws-title">관련 법령 모아보기</p>
      <div className="related-laws-chips">
        {data.map((law) => (
          <a
            key={law.name}
            href={lawSearchUrl(law.name)}
            target="_blank"
            rel="noopener noreferrer"
            className="related-laws-chip"
            title={`국가법령정보센터에서 "${law.name}" 검색`}
          >
            {law.name}
            <span className="related-laws-count">{law.count}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
