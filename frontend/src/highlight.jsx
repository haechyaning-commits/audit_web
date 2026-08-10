/**
 * 검색어 하이라이트 — 백엔드가 매칭 위치를 안 내려주므로, 검색어를 공백 기준으로 나눠서
 * 미리보기 텍스트 안에서 등장하는 부분을 <mark>로 감싸는 클라이언트 사이드 근사치.
 * (실제 검색은 벡터+키워드 하이브리드라 완벽히 일치하진 않지만, "왜 이 카드가 뜨는지"
 * 감을 잡는 용도로는 충분함)
 */
function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export default function highlightMatches(text, query) {
  const terms = [...new Set(query.trim().split(/\s+/).filter((t) => t.length > 0))];
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
