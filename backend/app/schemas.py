"""API가 주고받는 데이터 형태 (Pydantic 모델) — FastAPI가 이걸로 자동 검증 + Swagger 문서화."""
from pydantic import BaseModel


class SearchResultCard(BaseModel):
    """검색 결과 카드 1개 (architecture.md §8.3)."""
    document_id: str
    institution: str | None
    year: int | None
    confidence: str  # "신뢰도 높음" | "일부 참고" (parsing_quality를 사람이 읽을 말로 변환)
    preview_text: str  # raw_text 발췌 (§8.3 v12: AI 요약 아님, 검색 1회당 LLM 호출 방지)
    # 2026-08-12 임시: 동적 결과 개수(점수 컷오프) 캘리브레이션용으로만 잠깐 노출.
    # ?debug_score=1 없으면 항상 None이라 기존 프론트/응답 크기엔 영향 없음.
    # 컷오프 비율 정하고 나면 이 필드+쿼리파라미터 정리 예정.
    score: float | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultCard]


class DocumentDetail(BaseModel):
    """상세페이지 응답 — 요약 생성은 트리거하지 않고 DB에 캐싱된 값만 반환(없으면 전부 null).
    요약이 필요하면 프론트가 별도로 POST /documents/{id}/summary를 호출함."""
    id: str
    institution: str | None
    year: int | None
    confidence: str
    raw_text: str
    summary_point: str | None
    summary_cause: str | None
    summary_action: str | None
    summary_result: str | None
    summary_failed: bool  # true면 프론트에서 "요약 어려움 — 원문 참고 필요" 배지 표시
    summary_freeform: str | None  # 항목 구분 없는 자유형 4줄 요약(줄바꿈 구분), 별도 프롬프트
    summary_freeform_failed: bool


class SummaryResponse(BaseModel):
    """POST /documents/{id}/summary 응답 (§4.5 온디맨드 요약 + §4.6 실패 처리).
    "요약보기" 버튼 클릭 시에만 호출됨 — 이미 캐싱된 값이 있으면 재생성 없이 그대로 반환.
    구조화 요약(point/cause/action/result)과 자유형 요약(freeform)을 한 번의 호출로 같이 반환."""
    summary_point: str | None
    summary_cause: str | None
    summary_action: str | None
    summary_result: str | None
    summary_failed: bool
    summary_freeform: str | None
    summary_freeform_failed: bool
