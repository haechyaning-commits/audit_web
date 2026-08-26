"""API가 주고받는 데이터 형태 (Pydantic 모델) — FastAPI가 이걸로 자동 검증 + Swagger 문서화."""
from pydantic import BaseModel


class SearchResultCard(BaseModel):
    """검색 결과 카드 1개 (architecture.md §8.3)."""
    document_id: str
    title: str | None  # raw_text 첫 줄("제목 : ...")에서 파싱 — 프론트 URL 슬러그용, 2026-08-13
    institution: str | None
    year: int | None
    audit_type: str | None  # 감사종류(복무감사/회계감사 등) — source_file명에서 파싱, 2026-08-12
    confidence: str  # "신뢰도 높음" | "일부 참고" (parsing_quality를 사람이 읽을 말로 변환)
    preview_text: str  # raw_text 발췌 (§8.3 v12: AI 요약 아님, 검색 1회당 LLM 호출 방지)
    # RRF 점수(순위 기반 융합 스코어) — 카드 순서를 매기는 데 쓰는 그 값 그대로.
    # 2026-08-12: 원래 ?debug_score=1(동적 결과 개수 컷오프 캘리브레이션용) 없이는
    # 항상 None으로 감춰뒀었는데, 2026-08-24(피드백 반영)부터는 항상 채워서 내려줌 —
    # 프론트가 결과 카드에 상대 관련도(1위 대비 %) 막대로 보여주는 데 씀
    # (ResultCard.jsx). debug_score는 이제 후보 풀 크기(40건 vs 100건) 조절만 담당함.
    score: float
    # 2026-08-25(베타테스트 피드백 3번): RRF score(순위 기반)와 별개로, 순위 융합을
    # 거치지 않은 원래 코사인 유사도(쿼리 ↔ 실제 매치된 청크) — "관련성 낮음" 판단
    # 기준을 실측으로 잡기 위해 우선 노출만 함(main.py __init__ 주석 참고). /search만
    # 채워서 보냄 — /similar는 이미 score 자체가 코사인 유사도(1-distance)라 중복이라
    # 안 채움(None).
    vector_similarity: float | None = None


class YearCount(BaseModel):
    year: int
    count: int


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultCard]
    # 2026-08-26(기능 추가): 이 검색어가 연도별로 얼마나 나오는지 — results(최대 40~100건,
    # RRF 후보 풀)를 연도별로 집계한 것. 전체 6.8만 건 중 "이 검색어와 매칭된 문서 전체"의
    # 정확한 연도 분포가 아니라 "지금 이 검색의 후보 풀 안에서의" 분포임에 유의(주석은
    # main.py 계산부에 상세).
    year_distribution: list[YearCount]


class YearStatsResponse(BaseModel):
    """홈 화면 '연도별 사례 수' 막대그래프용 (베타테스트 피드백 5번, 2026-08-25) —
    지금까지 프론트에 값이 통째로 하드코딩돼 있던 걸 라이브 집계로 대체."""
    total: int
    years: list[YearCount]


class FilterOptions(BaseModel):
    """검색 필터 사이드바(기관/연도/감사유형)를 채우는 값 목록 — 2026-08-24, FR5
    (v1.1로 미뤄뒀던 필터). 검색 응답과 분리된 별도 엔드포인트(GET /filters)로
    캐싱하기 쉽게 함(값 목록 자체는 새 데이터가 들어오기 전까진 안 바뀜)."""
    institutions: list[str]
    years: list[int]
    audit_types: list[str]


class DocumentDetail(BaseModel):
    """상세페이지 응답 — 요약 생성은 트리거하지 않고 DB에 캐싱된 값만 반환(없으면 전부 null).
    요약이 필요하면 프론트가 별도로 POST /documents/{id}/summary를 호출함."""
    id: str
    title: str | None  # raw_text 첫 줄에서 파싱 — 프론트 URL 슬러그용, 2026-08-13
    institution: str | None
    year: int | None
    audit_type: str | None  # 감사종류(복무감사/회계감사 등) — source_file명에서 파싱, 2026-08-12
    confidence: str
    raw_text: str
    source_url: str | None  # 원본 PDF/HWP 링크(GitHub raw) — 백필 전/파싱 실패 문서는 null, 2026-08-13
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
