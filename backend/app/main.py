"""
검색 API 진입점 (development-plan.md 2주차 목표).

라우트를 전부 async def로 통일 — DB(asyncpg)와 OpenAI(AsyncOpenAI) 호출은 진짜 비동기라
await로 바로 처리하고, CPU 연산인 임베딩 인코딩만 asyncio.to_thread로 스레드에 넘겨서
이벤트 루프가 안 막히게 함 (embedding.encode_query 자체는 sentence-transformers가
비동기를 지원 안 해서 동기 함수로 남겨둠).
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# db.py가 import되는 시점에 이미 os.environ에서 DATABASE_URL을 읽으므로, 다른 import보다
# 먼저 .env를 로드해야 함. 이렇게 하면 `export $(cat .env | xargs)`처럼 OS별로 다른 쉘
# 명령이 필요 없어짐 — .env 파일만 있으면 Windows/Mac/Linux 어디서든 그냥
# `uvicorn app.main:app`으로 실행 가능
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import db, embedding, repository, summary
from .schemas import DocumentDetail, FilterOptions, SearchResponse, SearchResultCard, SummaryResponse
from .textutils import build_preview, build_source_url, extract_title

logger = logging.getLogger(__name__)

CONFIDENCE_LABELS = {
    "standard": "신뢰도 높음",
    "partial": "일부 참고",
    "fallback": "일부 참고",
}


def _confidence_label(parsing_quality: str | None) -> str:
    return CONFIDENCE_LABELS.get(parsing_quality, "일부 참고")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 모델/커넥션 풀은 앱 시작 시 딱 한 번만 로드 (요청마다 로드하면 지연시간 폭증, §3.3)
    await db.init_pool()
    await asyncio.to_thread(embedding.load_model)
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
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력해주세요")

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
    candidates = await repository.search_candidates(
        pool,
        query_vector,
        q,
        limit=search_limit,
        institution=institution,
        year=year,
        audit_type=audit_type,
        boost_institution=boost_institution,
    )
    candidates = repository.rerank(candidates, q)  # 지금은 no-op, 스트레치 목표(§3.4) 자리

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
        )
        for r in candidates
    ]
    return SearchResponse(query=q, results=results)


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
