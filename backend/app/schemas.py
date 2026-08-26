"""API가 주고받는 데이터 형태 (Pydantic 모델) — FastAPI가 이걸로 자동 검증 + Swagger 문서화."""
from datetime import datetime

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


class RelatedLaw(BaseModel):
    """검색 결과 상단 "관련 법령 모아보기"용 — 이 검색의 후보 문서들이 인용한 법령 중
    빈도순 상위 몇 개(main.py 참고). count는 인용 횟수가 아니라 "몇 개 문서가 이
    법을 언급하는지"(textutils.extract_law_citations가 문서당 1회로 셈)."""
    name: str
    count: int


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultCard]
    # 2026-08-26(기능 추가 → 후속 교체): 처음엔 "이 검색어, 연도별 분포" 미니차트였는데,
    # 사이드바 연도 필터(체크박스, 이미 건수까지 보여주고 클릭도 됨)와 정보가 그대로
    # 겹친다는 피드백으로 related_laws(관련 법령 모아보기)로 교체함 — 다른 화면에 없는
    # 새 정보이고, 이 사이트의 실무 도구 성격에 더 맞는다고 판단.
    related_laws: list[RelatedLaw]


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


class AuditTypeCount(BaseModel):
    audit_type: str
    count: int


class InstitutionProfile(BaseModel):
    """기관 프로필 미니페이지(GET /institutions/{name}) — "이 기관이 감사를 얼마나
    자주 받았나 / 어떤 지적을 주로 받나"를 한눈에 보여주는 용도. 검색과 무관하게
    기관명 하나로 바로 조회(2026-08-26 기능 추가)."""
    institution: str
    total: int
    years: list[YearCount]
    audit_types: list[AuditTypeCount]
    # 최신순 상위 몇 건 — 벡터/키워드 검색이 아니라 그냥 연도순 나열이라 score는
    # 의미가 없음(SearchResultCard 재사용을 위해 0 고정, "오늘의 사례"와 같은 패턴).
    recent_cases: list[SearchResultCard]


class ErrorReportCreate(BaseModel):
    """상세페이지 "오류 신고" 모달 제출값(POST /reports) — 2026-08-26. 처음엔 GitHub 이슈
    새로 만들기 링크로 연결했는데, "그게 아니라 신고창 뜨고 제출하면 내가 볼 수 있게"라는
    피드백으로 자체 저장(DB)+관리자 조회(GET /admin/reports)로 교체함. document_id 등
    메타는 프론트가 이미 알고 있는 값을 그대로 실어 보냄 — 백엔드가 document_id로 다시
    조회하지 않는 이유는 신고 자체는 원문이 이상하다는 제보라 문서가 이미 지워졌거나
    document_id를 못 찾는 경우에도 신고는 그대로 접수돼야 하기 때문."""
    document_id: str | None = None
    institution: str | None = None
    year: int | None = None
    audit_type: str | None = None
    message: str
    page_url: str | None = None


class ErrorReportOut(BaseModel):
    """GET /admin/reports 조회용 — 관리자 HTML 페이지 렌더링에만 씀(외부 공개 API 아님)."""
    id: int
    document_id: str | None
    institution: str | None
    year: int | None
    audit_type: str | None
    message: str
    page_url: str | None
    created_at: datetime


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
