/**
 * 원문에 낫표(「」/｢｣)로 인용된 법령명을 국가법령정보센터(law.go.kr) 검색 링크로 연결.
 *
 * 2026-08-26(기능 추가): 이 프로젝트가 "감사실 실무자가 궁금한 사안을 검색"하는 도구인
 * 만큼, 원문에 인용된 「여비규정」 같은 법령/규정명을 바로 law.go.kr에서 찾아볼 수 있게
 * 하는 게 실무 활용도에 제일 직접적으로 도움이 될 것 같아 추가함.
 *
 * 낫표(「」/｢｣) 자체는 이미 DetailPage.jsx의 여러 곳(LAW_CITATION_HINT_RE,
 * splitLawCitationHeading 등)에서 "법령명 인용"의 신호로 취급되고 있어서 — 이 프로젝트
 * 문서 특성상 낫표 안 내용은 거의 항상 법령/규정명이라, 별도 화이트리스트 없이 그대로
 * 링크로 연결함. 다만 문단 전체를 통째로 감싸는 등 지나치게 긴 인용까지 링크로 만들면
 * 오히려 부자연스러워서 길이 상한(30자)을 둠 — 실제 법령명은 대부분 그보다 훨씬 짧음.
 */
const LAW_CITATION_RE = /[「｢]([^」｣]{2,30})[」｣]/g;

function lawSearchUrl(lawName) {
  return `https://www.law.go.kr/lsSc.do?menuId=1&query=${encodeURIComponent(lawName)}`;
}

/**
 * text를 낫표 인용 구간 기준으로 나눠서, 문자열(일반 텍스트)과 JSX(<a> 링크)가 섞인
 * 배열로 반환. 낫표 자체(「」)는 링크 밖에 그대로 남겨서 원문 표기를 안 바꿈 — 링크는
 * 안의 법령명 글자에만 건다.
 */
export default function linkifyLawCitations(text) {
  if (typeof text !== "string" || !text.includes("「") && !text.includes("｢")) {
    return [text];
  }
  const parts = [];
  let lastIndex = 0;
  let m;
  LAW_CITATION_RE.lastIndex = 0;
  while ((m = LAW_CITATION_RE.exec(text)) !== null) {
    const [full, lawName] = m;
    const openBracket = full[0];
    const closeBracket = full[full.length - 1];
    if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index));
    parts.push(openBracket);
    parts.push(
      <a
        key={`${m.index}-law`}
        href={lawSearchUrl(lawName)}
        target="_blank"
        rel="noopener noreferrer"
        className="law-citation-link"
        title={`국가법령정보센터에서 "${lawName}" 검색`}
        // 카드/문단 전체가 <Link>(react-router)로 감싸여 있는 경우가 있어서(예: 목록
        // 카드), 그 상위 라우팅 클릭이 같이 발동하지 않게 막음
        onClick={(e) => e.stopPropagation()}
      >
        {lawName}
      </a>,
    );
    parts.push(closeBracket);
    lastIndex = m.index + full.length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}
