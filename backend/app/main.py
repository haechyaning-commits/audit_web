"""
검색 API 진입점 (development-plan.md 2주차 목표).

라우트를 전부 async def로 통일 — DB(asyncpg)와 OpenAI(AsyncOpenAI) 호출은 진짜 비동기라
await로 바로 처리하고, CPU 연산인 임베딩 인코딩만 asyncio.to_thread로 스레드에 넘겨서
이벤트 루프가 안 막히게 함 (embedding.encode_query 자체는 sentence-transformers가
비동기를 지원 안 해서 동기 함수로 남겨둠).
"""
import asyncio
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
from .schemas import DocumentDetail, SearchResponse, SearchResultCard, SummaryResponse
from .textutils import build_preview

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
async def search(q: str, debug_score: bool = False) -> SearchResponse:
    """debug_score=1: 고정 개수 대신 점수 기반 컷오프로 바꾸기 위해, RRF 점수 분포를
    실측하려고 임시로 추가한 파라미터. 기본값 False면 기존 응답과 완전히 동일함
    (score 필드가 항상 None) — 컷오프 비율 정하고 나면 이 파라미터+로직 정리 예정."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력해주세요")

    pool = db.get_pool()
    query_vector = await asyncio.to_thread(embedding.encode_query, q)
    # debug_score일 땐 컷오프 지점을 보려고 후보 풀 끝(100건)까지 넉넉히 봄
    search_limit = 100 if debug_score else 40
    candidates = await repository.search_candidates(pool, query_vector, q, limit=search_limit)
    candidates = repository.rerank(candidates, q)  # 지금은 no-op, 스트레치 목표(§3.4) 자리

    results = [
        SearchResultCard(
            document_id=r["document_id"],
            institution=r["institution"],
            year=r["year"],
            audit_type=r["audit_type"],
            confidence=_confidence_label(r["parsing_quality"]),
            preview_text=build_preview(r["preview_buffer"]),
            score=float(r["score"]) if debug_score else None,
        )
        for r in candidates
    ]
    return SearchResponse(query=q, results=results)


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
        institution=doc["institution"],
        year=doc["year"],
        audit_type=doc["audit_type"],
        confidence=_confidence_label(doc["parsing_quality"]),
        raw_text=doc["raw_text"],
        summary_point=doc["summary_point"],
        summary_cause=doc["summary_cause"],
        summary_action=doc["summary_action"],
        summary_result=doc["summary_result"],
        summary_failed=doc["summary_failed"],
        summary_freeform=doc["summary_freeform"],
        summary_freeform_failed=doc["summary_freeform_failed"],
    )


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
