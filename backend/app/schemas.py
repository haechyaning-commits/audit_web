"""API가 주고받는 데이터 형태 (Pydantic 모델) — FastAPI가 이걸로 자동 검증 + Swagger 문서화."""
from pydantic import BaseModel


class SearchResultCard(BaseModel):
    """검색 결과 카드 1개 (architecture.md §8.3)."""
    document_id: str
    institution: str | None
    year: int | None
    confidence: str  # "신뢰도 높음" | "일부 참고" (parsing_quality를 사람이 읽을 말로 변환)
    preview_text: str  # raw_text 발췌 (§8.3 v12: AI 요약 아님, 검색 1회당 LLM 호출 방지)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultCard]


class DocumentDetail(BaseModel):
    """상세페이지 응답 (§4.5 온디맨드 요약 + §4.6 실패 처리)."""
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
