/**
 * 원문에 낫표(「」/｢｣)로 인용된 "국가 법령"만 국가법령정보센터(law.go.kr) 검색 링크로 연결.
 *
 * 2026-08-26 최초 구현: 낫표 안 내용이면 뭐든 링크로 연결했었음("낫표 = 법령명"이라고
 * 가정) — 배포 후 실제로 눌러보니 "검색결과가 없습니다"가 자주 뜬다는 피드백으로 원인
 * 확인. 실제 배포 데이터 56건에서 낫표 인용 231건을 뽑아보니:
 *   - 진짜 국가 법령(law.go.kr에 있음): "공공기관의 운영에 관한 법률",
 *     "부정청탁 및 금품등 수수의 금지에 관한 법률 시행령" 등
 *   - 기관 내부 지침/규정/요령(law.go.kr에 등록 자체가 안 됨 — 개별 공공기관의 사내
 *     규정이라 국가법령정보센터 관할이 아님): "법인카드 사용 및 관리지침",
 *     "여비지급요령", "감사규정", "회계요령" 등 — 압도적으로 더 많았음
 *   - 아예 법령이 아닌 문서/사업명: "2023년 제13차 감염관리 연수과정",
 *     "2021년 한국수자원조사기술원 연간감사계획" 등
 * "낫표 안이면 뭐든 링크"는 틀린 가정이었음 — 후자 두 부류를 클릭하면 항상 없다고
 * 뜨는 게 당연한 결과였음.
 *
 * 수정: 정규화한 인용문이 법/법률/시행령/시행규칙/조례로 끝나는 경우만 링크로 연결.
 * 이 5개 접미사는 law.go.kr 법령 검색이 실제로 다루는 범주(국가 법률·하위법령·자치법규)와
 * 거의 1:1로 대응돼서, 오탐(내부 지침/문서명을 법령으로 착각)을 크게 줄임. 나머지는
 * 링크 없이 원문 그대로(이 기능이 생기기 전과 동일하게) 보여줌 — "없다"가 뜰 걸 알면서
 * 링크를 거는 것보다, 확신 없으면 안 거는 쪽이 나음.
 */
const LAW_CITATION_RE = /[「｢]([^」｣]{2,60})[」｣]/g;
// 실제 국가 법령 체계의 마지막 단어 패턴만 — 기관 내부 지침/규정/요령/강령/계획/과정
// 등은 여기 안 걸림(의도적으로 좁게 잡음, 위 주석 참고).
const LAW_SUFFIX_RE = /(법|법률|시행령|시행규칙|조례)$/;

function normalizeCitation(raw) {
  // 원문 줄바꿈으로 인용문이 중간에 꺾인 경우(예: "…금지\n에 관한 법률 시행령") 대비 —
  // 공백류를 전부 한 칸으로 합쳐야 접미사 판별도 정확해지고, URL 쿼리도 안 깨짐.
  return raw.replace(/\s+/g, " ").trim();
}

// export: RelatedLaws.jsx("관련 법령 모아보기" 칩)도 같은 URL 규칙을 써야 해서 공유.
export function lawSearchUrl(lawName) {
  return `https://www.law.go.kr/lsSc.do?menuId=1&query=${encodeURIComponent(lawName)}`;
}

/**
 * text를 낫표 인용 구간 기준으로 나눠서, 문자열(일반 텍스트)과 JSX(<a> 링크)가 섞인
 * 배열로 반환. 법령으로 확신되는 인용만 링크가 되고, 나머지는 원문 그대로(낫표 포함)
 * 손 안 댐 — 화면 표시가 이 기능 도입 전과 똑같이 유지됨.
 */
export default function linkifyLawCitations(text) {
  if (typeof text !== "string" || (!text.includes("「") && !text.includes("｢"))) {
    return [text];
  }
  const parts = [];
  let lastIndex = 0;
  let m;
  LAW_CITATION_RE.lastIndex = 0;
  while ((m = LAW_CITATION_RE.exec(text)) !== null) {
    const [full, rawCitation] = m;
    const normalized = normalizeCitation(rawCitation);
    // "○○○"(부서명 익명화 표시)로 시작하는 경우는 애초에 법령명일 수 없음 — 정규화된
    // 텍스트가 법령 접미사로 끝나도 제외.
    const looksLikeLaw = LAW_SUFFIX_RE.test(normalized) && !normalized.startsWith("○");
    if (!looksLikeLaw) {
      // 링크 안 걸고 원문 그대로 — 이 매치를 건너뛴 것처럼 처리
      continue;
    }
    if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index));
    const openBracket = full[0];
    const closeBracket = full[full.length - 1];
    parts.push(openBracket);
    parts.push(
      <a
        key={`${m.index}-law`}
        href={lawSearchUrl(normalized)}
        target="_blank"
        rel="noopener noreferrer"
        className="law-citation-link"
        title={`국가법령정보센터에서 "${normalized}" 검색`}
        // 카드/문단 전체가 <Link>(react-router)로 감싸여 있는 경우가 있어서(예: 목록
        // 카드), 그 상위 라우팅 클릭이 같이 발동하지 않게 막음
        onClick={(e) => e.stopPropagation()}
      >
        {rawCitation}
      </a>,
    );
    parts.push(closeBracket);
    lastIndex = m.index + full.length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}
