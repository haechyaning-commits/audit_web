/**
 * 사례 상세페이지 URL 빌더 — `/documents/:id`(예전) -> `/cases/:id/:slug`(law.go.kr류,
 * STATUS.md "URL 구조 개선") 전환용.
 *
 * :id는 실제 조회 키(document_id) 그대로 씀 — :slug는 순수 표시/SEO용 장식이라 파싱
 * 안 함(중복 기관명/연도/제목 조합이 있어도 조회는 항상 :id 하나로만 결정돼서 충돌 걱정
 * 없음). 그래서 App.jsx의 라우트도 "/documents/:id"와 "/cases/:id/:slug" 둘 다 파라미터
 * 이름을 "id"로 맞춰뒀고, DetailPage는 useParams().id만 읽으면 됨 — 어느 라우트로
 * 들어왔는지 분기할 필요가 없음.
 */

const SLUG_MAX_LEN = 100;

/** 기관명/연도/제목을 이어붙여 사람이 읽을 수 있는 slug 하나로 만듦.
 * 셋 다 없으면(파싱 실패한 소수 문서) "사례"로 폴백 — 빈 세그먼트로 라우트가 깨지는 것 방지. */
export function buildCaseSlug({ institution, year, title } = {}) {
  const parts = [institution, year ? String(year) : null, title].filter(
    (p) => p && String(p).trim(),
  );
  const raw = parts.join(" ").trim();
  if (!raw) return "사례";

  const slug = raw
    .replace(/\s+/g, "-") // 공백 -> 하이픈 (law.go.kr류 URL 느낌)
    .replace(/[/\\?#%]/g, "-") // 경로/쿼리스트링에서 문제되는 문자만 제거
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, SLUG_MAX_LEN);

  return slug || "사례";
}

/** 상세페이지 경로(쿼리스트링 제외). id는 buildCaseSlug와 별개로 항상 그대로 인코딩만. */
export function buildCasePath(id, meta) {
  return `/cases/${encodeURIComponent(id)}/${encodeURIComponent(buildCaseSlug(meta))}`;
}

/** 검색 결과 카드 등에서 바로 쓰는 전체 링크(검색어 쿼리스트링 포함). */
export function buildCaseUrl(result, query) {
  const path = buildCasePath(result.document_id, result);
  return query ? `${path}?q=${encodeURIComponent(query)}` : path;
}
