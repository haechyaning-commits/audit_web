"""
검색 API 진입점 (development-plan.md 2주차 목표).

라우트를 전부 async def로 통일 — DB(asyncpg)와 OpenAI(AsyncOpenAI) 호출은 진짜 비동기라
await로 바로 처리하고, CPU 연산인 임베딩 인코딩만 asyncio.to_thread로 스레드에 넘겨서
이벤트 루프가 안 막히게 함 (embedding.encode_query 자체는 sentence-transformers가
비동기를 지원 안 해서 동기 함수로 남겨둠).
"""
import asyncio
import hashlib
import logging
import os
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date

from dotenv import load_dotenv

# db.py가 import되는 시점에 이미 os.environ에서 DATABASE_URL을 읽으므로, 다른 import보다
# 먼저 .env를 로드해야 함. 이렇게 하면 `export $(cat .env | xargs)`처럼 OS별로 다른 쉘
# 명령이 필요 없어짐 — .env 파일만 있으면 Windows/Mac/Linux 어디서든 그냥
# `uvicorn app.main:app`으로 실행 가능
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse

from . import db, embedding, repository, reranker, summary, tokenizer
from .schemas import (
    AuditTypeCount,
    DocumentDetail,
    ErrorReportCreate,
    FilterOptions,
    InstitutionProfile,
    RelatedLaw,
    SearchResponse,
    SearchResultCard,
    SummaryResponse,
    YearCount,
    YearStatsResponse,
)
from .textutils import build_preview, build_source_url, extract_law_citations, extract_title

logger = logging.getLogger(__name__)

CONFIDENCE_LABELS = {
    "standard": "신뢰도 높음",
    "partial": "일부 참고",
    "fallback": "일부 참고",
}


def _confidence_label(parsing_quality: str | None) -> str:
    return CONFIDENCE_LABELS.get(parsing_quality, "일부 참고")


# 2026-08-26(데이터 오류 신고 → 관리자 조회): GET /admin/reports 접근을 이 값으로만 제한함.
# 로그인/계정 시스템이 없는 포트폴리오 프로젝트라 별도 인증 체계 대신 URL에 붙이는
# 공유 비밀 토큰 방식(예: /admin/reports?token=...)을 씀 — Railway 환경변수로 등록.
# 값이 비어 있으면(로컬 등) 항상 403으로 막아서, 설정을 깜빡했을 때 실수로 열려있는
# 상태가 되는 걸 방지함(빈 문자열끼리 비교돼서 통과하는 사고 방지).
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# 악의적으로 아주 긴 문자열을 반복 제출하는 걸 막는 최소 방어선(신고 폼은 로그인 없이 누구나
# 씀) — 이 길이를 넘기면 그냥 사용자 입력 실수로 보고 400으로 거절.
MAX_REPORT_MESSAGE_LEN = 2000

# 2026-08-27: 리랭커(§3.4)/형태소 토큰화(§3.6) 코드 준비 — 둘 다 기본값 꺼짐.
# - RERANKER_ENABLED: bge-reranker-v2-m3를 임베딩 모델과 동시에 로드하는 게 Railway
#   메모리 상한을 넘길 위험이 있어(§3.5) 실측 전엔 켜지 않음.
# - TOKENIZER_ENABLED: chunks.tsv가 아직 원문(text) 기준으로 색인돼 있어서, 쿼리만
#   형태소 토큰화하면 오히려 매칭이 어긋남(tokenizer.py 모듈 docstring 참고) —
#   scripts/backfill_tsv_text.py로 실제 배치 백필+재색인을 끝낸 뒤에만 켤 것.
RERANKER_ENABLED = os.environ.get("RERANKER_ENABLED", "false").lower() == "true"
TOKENIZER_ENABLED = os.environ.get("TOKENIZER_ENABLED", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 모델/커넥션 풀은 앱 시작 시 딱 한 번만 로드 (요청마다 로드하면 지연시간 폭증, §3.3)
    await db.init_pool()
    await repository.ensure_error_reports_table(db.get_pool())
    await asyncio.to_thread(embedding.load_model)
    if RERANKER_ENABLED:
        await asyncio.to_thread(reranker.load_model)
    if TOKENIZER_ENABLED:
        await asyncio.to_thread(tokenizer.load_model)
    # 2026-08-25(성능 개선): 캐시 예열은 await로 기다리지 않고 백그라운드로 던짐 —
    # 예열 문구 4개가 각각 ~15초씩 걸릴 수 있어서 await하면 배포 직후 헬스체크/시작
    # 시간이 크게 늘어나 배포 자체가 불안정해질 위험이 있음(embedding.py 주석 참고).
    # 앱은 예열 완료를 기다리지 않고 바로 요청을 받기 시작 — 예열 전에 그 검색어가
    # 들어와도 그냥 평소처럼(느리게) 처리될 뿐 에러는 아님.
    asyncio.create_task(asyncio.to_thread(embedding.prewarm_cache))
    yield
    await db.close_pool()


app = FastAPI(title="공공감사데이터 검색 API", lifespan=lifespan)

# 프론트엔드(별도 origin에서 fetch로 호출)가 브라우저에서 API를 부를 수 있게 CORS 허용.
# 로컬 개발(Vite 기본 포트)은 기본값으로 항상 열어두고, 배포된 프론트(Vercel) origin은
# FRONTEND_ORIGIN 환경변수로 추가 — 와일드카드(*)를 쓰면 자격증명 포함 요청이 막히므로
# 명시적 origin 목록을 씀
_default_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_extra_origin = os.environ.get("FRONTEND_ORIGIN", "").strip()
allowed_origins = _default_origins + ([_extra_origin] if _extra_origin else [])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],  # POST: /documents/{id}/summary ('요약보기' 버튼용)
    allow_headers=["*"],
)

# /documents/{id}가 raw_text 원문 전체(길게는 수십 KB)를 압축 없이 내려보내면 Railway
# egress 비용($0.05/GB)이 그대로 커짐 — 한글 텍스트는 gzip으로 보통 60~80% 줄어드므로
# 응답 압축만 켜도 egress 비용이 크게 줄어듦(2026-08-12, Railway 비용 실측 기준 대응).
# minimum_size=1000: 검색 결과(짧은 preview_text)처럼 이미 작은 응답까지 압축 오버헤드를
# 들일 필요는 없어서, 어느 정도 큰 응답(주로 상세페이지 원문)에만 적용되게 함.
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/search", response_model=SearchResponse)
async def search(
    q: str,
    institution: str | None = None,
    year: int | None = None,
    audit_type: str | None = None,
    debug_score: bool = False,
) -> SearchResponse:
    """institution/year/audit_type: 검색 결과 필터(FR5, 2026-08-24) — 전부 선택값이라
    안 주면 기존과 동일하게 전체 문서 대상으로 검색됨. 값이 실제 DB에 없는 조합이어도
    그냥 결과 0건으로 응답(별도 검증 안 함 — /filters가 내려준 값만 프론트가 쓰므로
    잘못된 값이 들어올 일이 원래 없음).
    debug_score=1: 고정 개수(40) 대신 점수 기반 컷오프로 바꾸기 위해, RRF 점수 분포를
    실측하려고 임시로 추가한 파라미터 — 켜면 컷오프 지점을 보려고 후보 풀을 100건까지
    넉넉히 가져옴(응답에 노출되는 건수 자체가 늘어남). 컷오프 비율 정하고 나면 이
    파라미터+search_limit 분기는 정리 예정.
    2026-08-24(피드백 반영): score 필드 자체는 이제 debug_score와 무관하게 항상 채워서
    내려줌 — 프론트 결과 카드에 상대 관련도(막대) 표시용(ResultCard.jsx 참고). 원래
    이 파라미터가 하던 "후보 풀 100건까지 확장" 역할만 남기고, "score를 감춘다"는
    부수효과는 분리함(스코어 노출과 컷오프 실험은 서로 다른 관심사라 같이 묶여있을
    이유가 없었음)."""
    q_stripped = q.strip()
    if not q_stripped:
        raise HTTPException(status_code=400, detail="검색어를 입력해주세요")
    # 2026-08-25(베타테스트 피드백 3번, 축소 범위): "a"처럼 의미 없는 한 글자 검색어도
    # 검색 결과 40건이 그럴듯하게 나오는 문제 확인 — RRF score도, 순수 코사인 유사도도
    # 정상 질문과 실측 비교해보니 안정적으로 안 갈려서(repository.py의 vector_similarity
    # 주석 참고, "a"가 오히려 정상 질문보다 유사도가 더 높게 나온 사례까지 있었음) 점수
    # 기반 필터링은 보류. 대신 확실하게 잡을 수 있는 극단적 케이스(1글자 이하)만 우선
    # 서버에서 거절 — 감사 사례를 한 글자로 검색할 일은 사실상 없어서 오탐 위험이 거의
    # 없음. "abc"/"12345" 같은 케이스까진 못 막지만, 정식 eval set 없이 억지로 임계값을
    # 잡아서 진짜 관련 있는 결과까지 숨기는 위험보다는 안전한 선택.
    if len(q_stripped) < 2:
        raise HTTPException(status_code=400, detail="검색어를 2자 이상 입력해주세요")

    pool = db.get_pool()
    # 2026-08-25: 기관명 정확 매칭 가산점 — 검색어 자체에 실제 DB 기관명이 포함돼
    # 있으면 그 기관 문서에 점수 가산치를 줌(repository._SEARCH_SQL 주석 참고).
    # institution 필터(사이드바)가 이미 선택된 상태면 결과가 어차피 그 기관으로만
    # 좁혀져 있어 가산점이 순위에 영향을 못 주므로(모든 후보에 똑같이 더해짐),
    # 그 경우엔 조회 자체를 건너뜀. encode_query(CPU 스레드)와 독립적인 DB 조회라
    # gather로 동시에 실행해서 지연시간을 추가로 늘리지 않음.
    query_vector_task = asyncio.to_thread(embedding.encode_query, q)
    boost_institution_task = (
        repository.find_matching_institution(pool, q)
        if institution is None
        else asyncio.sleep(0, result=None)
    )
    query_vector, boost_institution = await asyncio.gather(
        query_vector_task, boost_institution_task
    )
    # debug_score일 땐 컷오프 지점을 보려고 후보 풀 끝(100건)까지 넉넉히 봄
    search_limit = 100 if debug_score else 40
    # §3.6: TOKENIZER_ENABLED가 켜져 있을 때만 형태소 토큰으로 바꿔서 text_search
    # leg(plainto_tsquery)에 넘김 — 꺼져 있으면(기본값) 지금까지처럼 원문 그대로.
    # tokenize()가 빈 문자열을 반환하면(검색어가 전부 조사/어미뿐인 극단적 케이스)
    # plainto_tsquery('')는 아무것도 매치 안 되는 빈 tsquery가 되어 text_search leg만
    # 조용히 0건이 되고 벡터 검색은 정상 동작 — 검색 자체가 죽지는 않음.
    query_tokens = await asyncio.to_thread(tokenizer.tokenize, q) if TOKENIZER_ENABLED else q
    candidates = await repository.search_candidates(
        pool,
        query_vector,
        query_tokens,
        limit=search_limit,
        institution=institution,
        year=year,
        audit_type=audit_type,
        boost_institution=boost_institution,
    )
    # §3.4: RERANKER_ENABLED가 꺼져 있으면(기본값) repository.rerank가 no-op이라
    # to_thread로 넘겨도 사실상 비용이 없음 — CPU 연산(크로스인코더 추론)이라
    # encode_query와 같은 이유로 스레드에 넘겨서 이벤트 루프를 안 막음.
    candidates = await asyncio.to_thread(repository.rerank, candidates, q)

    results = [
        SearchResultCard(
            document_id=r["document_id"],
            title=extract_title(r["title_buffer"]),
            institution=r["institution"],
            year=r["year"],
            audit_type=r["audit_type"],
            confidence=_confidence_label(r["parsing_quality"]),
            preview_text=build_preview(r["preview_buffer"]),
            score=float(r["score"]),
            # chunks.embedding이 NULL인 소수 케이스(schema_tables.sql엔 NOT NULL 제약이
            # 없음, repository.py의 get_similar_documents 버그 수정 때 확인된 것과 동일한
            # 이슈)에서는 vector_similarity도 NULL로 내려올 수 있음 — 그대로 None 전달.
            vector_similarity=(
                float(r["vector_similarity"]) if r["vector_similarity"] is not None else None
            ),
        )
        for r in candidates
    ]
    # 2026-08-26(기능 추가, 2차): "이 검색어, 연도별 분포" 미니차트를 시도했다가 사이드바
    # 연도 필터(체크박스, 이미 건수 보여주고 클릭도 됨)와 정보가 겹친다는 피드백으로
    # "관련 법령 모아보기"로 교체함 — 후보 문서(candidates)들의 raw_text를 한 번 더
    # 가져와(repository.get_raw_texts, PK 조회라 가벼움) 실제 법령으로 보이는 낫표 인용만
    # 집계(textutils.extract_law_citations — 법/법률/시행령/시행규칙/조례로 끝나는 것만,
    # DetailPage.jsx의 법령 하이퍼링크와 같은 기준). count는 인용 "횟수"가 아니라 "몇 개
    # 문서가 이 법을 언급하는지"(문서당 중복 제거) — 한 문서가 같은 법을 열 번 인용해도
    # 1로 침, 그래야 이 검색어 전반에 걸쳐 실제로 자주 등장하는 법령이 상위에 옴.
    candidate_ids = [r["document_id"] for r in candidates]
    raw_rows = await repository.get_raw_texts(pool, candidate_ids)
    law_counter = Counter()
    for row in raw_rows:
        law_counter.update(extract_law_citations(row["raw_text"]))
    related_laws = [
        RelatedLaw(name=name, count=count) for name, count in law_counter.most_common(8)
    ]
    return SearchResponse(query=q, results=results, related_laws=related_laws)


# 2026-08-26(기능 추가): 홈 화면 "오늘의 사례" — 매 새로고침마다 바뀌면 "오늘의"라는
# 이름과 안 맞아서, 날짜(UTC)를 시드로 결정적으로 하나를 고름(repository.get_daily_case
# 참고 — 같은 날 안에는 몇 번을 다시 불러도 항상 같은 문서가 나옴).
@app.get("/documents/daily", response_model=SearchResultCard)
async def get_daily_case() -> SearchResultCard:
    pool = db.get_pool()
    seed = int(hashlib.md5(date.today().isoformat().encode()).hexdigest(), 16)
    row = await repository.get_daily_case(pool, seed)
    if row is None:
        raise HTTPException(status_code=404, detail="사례가 없습니다")
    return SearchResultCard(
        document_id=row["id"],
        title=extract_title(row["raw_text"]),
        institution=row["institution"],
        year=row["year"],
        audit_type=row["audit_type"],
        confidence=_confidence_label(row["parsing_quality"]),
        preview_text=build_preview(row["raw_text"]),
        score=0.0,  # "오늘의 사례"는 검색 관련도 개념이 없음 — SearchResultCard 재사용을 위해 0 고정
        vector_similarity=None,
    )


# 2026-08-26(기능 추가): 기관 프로필 미니페이지 — "이 기관이 감사를 얼마나 자주/어떤
# 종류로 받았나"를 기관명 하나로 바로 조회. 검색(벡터/키워드)이 아니라 단순 집계라
# 쿼리 4개를 동시에 날림(서로 독립적, repository.py 참고). 존재하지 않는 기관명(오타
# 등)이면 total=0이라 404.
@app.get("/institutions/{name}", response_model=InstitutionProfile)
async def get_institution_profile(name: str) -> InstitutionProfile:
    pool = db.get_pool()
    total, year_rows, audit_type_rows, recent_rows = await asyncio.gather(
        repository.get_institution_total(pool, name),
        repository.get_institution_years(pool, name),
        repository.get_institution_audit_types(pool, name),
        repository.get_institution_recent(pool, name),
    )
    if not total:
        raise HTTPException(status_code=404, detail="해당 기관의 사례를 찾을 수 없습니다")
    return InstitutionProfile(
        institution=name,
        total=total,
        years=[YearCount(year=r["year"], count=r["count"]) for r in year_rows],
        audit_types=[
            AuditTypeCount(audit_type=r["audit_type"], count=r["count"]) for r in audit_type_rows
        ],
        recent_cases=[
            SearchResultCard(
                document_id=r["id"],
                title=extract_title(r["raw_text"]),
                institution=r["institution"],
                year=r["year"],
                audit_type=r["audit_type"],
                confidence=_confidence_label(r["parsing_quality"]),
                preview_text=build_preview(r["raw_text"]),
                score=0.0,  # 최신순 나열이라 관련도 개념 없음 — 오늘의 사례와 같은 패턴
                vector_similarity=None,
            )
            for r in recent_rows
        ],
    )


@app.get("/filters", response_model=FilterOptions)
async def get_filter_options() -> FilterOptions:
    """검색 필터(기관/연도) 드롭다운을 채울 값 목록(FR5). 검색 자체와 무관한 정적에
    가까운 값이라 별도 엔드포인트로 분리 — 프론트가 페이지 로드 시 한 번만 불러서
    필터 UI를 구성함."""
    pool = db.get_pool()
    row = await repository.get_filter_options(pool)
    return FilterOptions(
        institutions=row["institutions"], years=row["years"], audit_types=row["audit_types"]
    )


@app.get("/stats/years", response_model=YearStatsResponse)
async def get_year_stats() -> YearStatsResponse:
    """홈 화면 '연도별 사례 수' 막대그래프(베타테스트 피드백 5번, 2026-08-25) — 지금까지
    프론트(SearchPage.jsx)에 값이 통째로 하드코딩돼 있어서 DB에 새 문서가 반영돼도
    프론트를 재배포하지 않는 한 그 시점 스냅샷에 멈춰있던 문제를 라이브 집계로 대체.
    /filters와 같은 이유로 별도 엔드포인트로 분리 — 검색 자체와 무관하고, 페이지 로드
    시 한 번만 불러서 씀."""
    pool = db.get_pool()
    total, rows = await repository.get_year_stats(pool)
    years = [YearCount(year=r["year"], count=r["count"]) for r in rows]
    return YearStatsResponse(total=total, years=years)


@app.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document_detail(document_id: str) -> DocumentDetail:
    """문서 조회만 함 — 요약은 자동 생성하지 않고 DB에 캐싱된 값(없으면 null)만 그대로 반환.
    원문을 지연 없이 바로 보여주기 위해 §4.5 온디맨드 생성 트리거는 /summary로 분리함."""
    pool = db.get_pool()
    doc = await repository.get_document(pool, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    return DocumentDetail(
        id=doc["id"],
        title=extract_title(doc["raw_text"]),
        institution=doc["institution"],
        year=doc["year"],
        audit_type=doc["audit_type"],
        confidence=_confidence_label(doc["parsing_quality"]),
        raw_text=doc["raw_text"],
        source_url=build_source_url(doc["source_file"]),
        summary_point=doc["summary_point"],
        summary_cause=doc["summary_cause"],
        summary_action=doc["summary_action"],
        summary_result=doc["summary_result"],
        summary_failed=doc["summary_failed"],
        summary_freeform=doc["summary_freeform"],
        summary_freeform_failed=doc["summary_freeform_failed"],
    )


@app.get("/documents/{document_id}/similar", response_model=list[SearchResultCard])
async def get_similar_cases(document_id: str, limit: int = 5) -> list[SearchResultCard]:
    """2026-08-24(피드백 반영): 상세페이지 "유사 사례" 섹션. /search와 같은 벡터검색
    로직을 재사용하되, 쿼리 임베딩을 사용자 입력 대신 이 문서 자체(청크 임베딩 평균)로
    만듦(repository.get_similar_documents 참고). LLM 호출이 아니라 순수 벡터검색이라
    원문 로딩과 같이 자동으로 보여줘도 지연 걱정이 없음(요약보기처럼 버튼 뒤로 미룰
    필요 없음).
    문서가 존재하지 않아도(또는 청크가 없어도) 404 대신 빈 배열 반환 — 이 섹션은
    상세페이지의 부가 정보라, 있으면 좋고 없어도 원문 조회 자체는 막지 않아야 함.
    2026-08-25(버그 수정): 위 원칙이 지금까지 프론트(.catch(()=>[]))에서만 지켜지고
    있었고, 백엔드는 예외가 나면 그냥 500을 냈음(실사용 중 재현됨 — repository.py의
    get_similar_documents 주석 참고). 원인이 된 케이스(embedding NULL)는 거기서
    고쳤지만, 데이터 품질 문제가 계속 나오는 프로젝트 특성상 "이 부가 기능 하나가
    상세페이지 전체를 못 열게 만드는" 상황을 원천 차단하려고 여기서도 한 번 더
    방어함 — 원인은 삼키지 않고 로그로 남기되, 사용자에게는 500 대신 빈 배열로 응답."""
    pool = db.get_pool()
    try:
        rows = await repository.get_similar_documents(pool, document_id, limit=limit)
    except Exception:
        logger.exception("유사 사례 조회 실패 (document_id=%s)", document_id)
        return []
    return [
        SearchResultCard(
            document_id=r["document_id"],
            title=extract_title(r["title_buffer"]),
            institution=r["institution"],
            year=r["year"],
            audit_type=r["audit_type"],
            confidence=_confidence_label(r["parsing_quality"]),
            preview_text=build_preview(r["preview_buffer"]),
            # pgvector cosine distance(<=>)는 0(동일)~2(반대) 범위라, "높을수록 유사"로
            # 방향을 맞추기 위해 1-distance로 뒤집음 — /search의 RRF score와 스케일은
            # 다르지만 "숫자가 클수록 더 관련 있다"는 의미는 같아서, 프론트의 상대
            # 관련도 막대(ResultCard.jsx)가 그대로 재사용 가능함.
            score=1 - r["distance"],
        )
        for r in rows
    ]


@app.post("/documents/{document_id}/summary", response_model=SummaryResponse)
async def get_document_summary(document_id: str) -> SummaryResponse:
    """프론트의 '4줄 요약보기' 버튼을 눌렀을 때만 호출됨 (온디맨드, §4.5).
    이미 캐싱된 요약이 있으면 재생성 없이 그대로 반환하고, summary_failed=True로 캐싱돼
    있으면 재시도하지 않음(§4.6, API 비용 낭비 방지) — GET 시절 로직 그대로 옮긴 것.
    구조화 요약(지적/원인/조치/결과)과 자유형 요약을 한 번에 같이 반환 — 둘 다 새로 생성해야
    하면 asyncio.gather로 동시에 호출해서 지연시간을 순차 호출 대비 절반으로 줄임."""
    pool = db.get_pool()
    doc = await repository.get_document(pool, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    summary_point = doc["summary_point"]
    summary_cause = doc["summary_cause"]
    summary_action = doc["summary_action"]
    summary_result = doc["summary_result"]
    summary_failed = doc["summary_failed"]
    summary_freeform = doc["summary_freeform"]
    summary_freeform_failed = doc["summary_freeform_failed"]

    need_structured = summary_point is None and not summary_failed
    need_freeform = summary_freeform is None and not summary_freeform_failed

    tasks = {}
    if need_structured:
        tasks["structured"] = summary.generate_summary(doc["raw_text"])
    if need_freeform:
        tasks["freeform"] = summary.generate_freeform_summary(doc["raw_text"])

    if tasks:
        results = dict(zip(tasks.keys(), await asyncio.gather(*tasks.values())))

        if "structured" in results:
            generated, failed = results["structured"]
            await repository.save_summary(pool, document_id, generated, failed)
            if generated:
                summary_point = generated["point"]
                summary_cause = generated["cause"]
                summary_action = generated["action"]
                summary_result = generated["result"]
            summary_failed = failed

        if "freeform" in results:
            freeform_text, freeform_failed = results["freeform"]
            await repository.save_freeform_summary(pool, document_id, freeform_text, freeform_failed)
            summary_freeform = freeform_text
            summary_freeform_failed = freeform_failed

    return SummaryResponse(
        summary_point=summary_point,
        summary_cause=summary_cause,
        summary_action=summary_action,
        summary_result=summary_result,
        summary_failed=summary_failed,
        summary_freeform=summary_freeform,
        summary_freeform_failed=summary_freeform_failed,
    )


@app.post("/reports", status_code=201)
async def submit_error_report(payload: ErrorReportCreate) -> dict:
    """상세페이지 "오류 신고" 모달 제출 (2026-08-26) — 처음엔 GitHub 새 이슈 링크로 보냈는데,
    "그게 아니라 신고창 뜨고 제출하면 내가 볼 수 있게"라는 피드백으로 자체 저장으로 교체함.
    로그인 없이 누구나 호출 가능한 공개 엔드포인트라 메시지 길이만 최소한으로 검증."""
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="신고 내용을 입력해 주세요.")
    if len(message) > MAX_REPORT_MESSAGE_LEN:
        raise HTTPException(
            status_code=400, detail=f"신고 내용은 {MAX_REPORT_MESSAGE_LEN}자 이내로 작성해 주세요."
        )
    pool = db.get_pool()
    await repository.create_error_report(
        pool,
        document_id=payload.document_id,
        institution=payload.institution,
        year=payload.year,
        audit_type=payload.audit_type,
        message=message,
        page_url=payload.page_url,
    )
    return {"ok": True}


def _admin_reports_html(rows: list) -> str:
    """관리자 전용이라 프론트(React) 없이 백엔드가 직접 HTML을 만들어 반환 — 이 화면 하나
    때문에 프론트 라우트/빌드를 늘릴 필요가 없다고 판단함(2026-08-26). 신고 내용은 사용자
    입력값이므로 escape 필수(XSS 방지)."""
    import html as html_lib

    if not rows:
        body = "<p>아직 접수된 신고가 없습니다.</p>"
    else:
        items = []
        for r in rows:
            meta = " · ".join(
                str(v)
                for v in [r["institution"], f"{r['year']}년" if r["year"] else None, r["audit_type"]]
                if v
            )
            page_link = (
                f'<a href="{html_lib.escape(r["page_url"])}" target="_blank" rel="noreferrer">페이지 열기</a>'
                if r["page_url"]
                else ""
            )
            items.append(
                f"""
                <li>
                  <div class="meta">#{r['id']} · {r['created_at']:%Y-%m-%d %H:%M} ·
                    문서 {html_lib.escape(r['document_id'] or '미상')}
                    {f' · {html_lib.escape(meta)}' if meta else ''}
                    {f' · {page_link}' if page_link else ''}
                  </div>
                  <div class="msg">{html_lib.escape(r['message'])}</div>
                </li>
                """
            )
        body = f"<ul>{''.join(items)}</ul>"

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>데이터 오류 신고 목록</title>
<style>
  body {{ font-family: -apple-system, "Pretendard", sans-serif; max-width: 760px;
         margin: 40px auto; padding: 0 16px; color: #222; }}
  h1 {{ font-size: 20px; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }}
  .meta {{ font-size: 12.5px; color: #777; margin-bottom: 6px; }}
  .msg {{ white-space: pre-wrap; line-height: 1.5; }}
</style></head>
<body>
<h1>데이터 오류 신고 목록 (최근 {len(rows)}건)</h1>
{body}
</body></html>"""


@app.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports(token: str = "") -> HTMLResponse:
    """토큰 기반 관리자 조회 페이지 — 로그인 시스템이 없는 프로젝트 규모에 맞춘 최소 인증
    (2026-08-26). ADMIN_TOKEN 미설정 시 항상 거부(주석 참고)."""
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    pool = db.get_pool()
    rows = await repository.list_error_reports(pool)
    return HTMLResponse(_admin_reports_html(rows))
