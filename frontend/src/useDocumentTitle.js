import { useEffect } from "react";

/**
 * 상세페이지 진입 시 브라우저 탭 타이틀을 문서 제목으로 바꿈(2026-08-13, URL 구조
 * 개선 후속 — STATUS.md "상세페이지 <title> 반영 안 했음" 항목).
 *
 * title이 없으면(아직 로딩 중이거나 제목 파싱 실패) 아무것도 안 바꾸고 index.html의
 * 기본 타이틀("공공감사데이터 검색")이 그대로 보임 — "제목 없음" 같은 걸로 덮어쓰지 않음.
 * 다른 페이지로 이동(언마운트)하면 이 훅이 바꾸기 전의 타이틀로 되돌려서, 검색 화면 등
 * 다른 페이지가 상세페이지의 옛 탭 타이틀을 그대로 물려받는 일이 없게 함.
 */
export default function useDocumentTitle(title) {
  useEffect(() => {
    if (!title) return;
    const prev = document.title;
    document.title = title;
    return () => {
      document.title = prev;
    };
  }, [title]);
}
