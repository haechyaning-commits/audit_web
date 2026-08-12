/**
 * 검색어 하이라이트 — 백엔드가 매칭 위치를 안 내려주므로, 검색어를 공백 기준으로 나눠서
 * 미리보기 텍스트 안에서 등장하는 부분을 <mark>로 감싸는 클라이언트 사이드 근사치.
 * (실제 검색은 벡터+키워드 하이브리드라 완벽히 일치하진 않지만, "왜 이 카드가 뜨는지"
 * 감을 잡는 용도로는 충분함)
 *
 * 2026-08-12: 조사/어미 같은 기능어까지 그대로 매칭 대상에 넣었더니, "음주운전 했을 때
 * 조치 어케됨" 같은 문장형 검색에서 정작 "음주운전"은 원문에 그 형태 그대로 없어서
 * 하이라이트가 안 되고, 아무데나 나오는 "때" 같은 짧은 기능어만 잔뜩 하이라이트되는
 * 문제가 있었음. 불용어 목록으로 걸러내고, 남은 단어는 긴 것부터 매칭되도록 정렬.
 */
const STOPWORDS = new Set([
  // 조사
  "이", "가", "은", "는", "을", "를", "의", "에", "에서", "으로", "로", "와", "과",
  "도", "만", "까지", "부터", "이나", "나", "이란", "란", "이랑", "랑", "보다", "처럼",
  // 자주 나오는 기능어/어미 조합 (문장형 검색에서 많이 섞여 들어옴)
  "때", "때는", "때가", "때문", "때문에", "그", "저", "이런", "저런", "그런",
  "어떻게", "어케", "했을", "하다", "합니다", "했다", "된다", "됨", "되나요", "인가요",
  "무엇", "뭐", "어디", "언제", "어떤", "및", "등", "관련", "경우",
]);

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export default function highlightMatches(text, query) {
  const terms = [
    ...new Set(
      query
        .trim()
        .split(/\s+/)
        .filter((t) => t.length >= 2 && !STOPWORDS.has(t)),
    ),
  ].sort((a, b) => b.length - a.length); // 긴(구체적인) 단어부터 매칭되게

  if (terms.length === 0) return text;

  const pattern = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);

  return parts.map((part, i) =>
    terms.some((t) => t.toLowerCase() === part.toLowerCase()) ? (
      <mark key={i}>{part}</mark>
    ) : (
      part
    ),
  );
}
