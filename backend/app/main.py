"""
검색 API 진입점 (development-plan.md 2주차 목표).

라우트를 전부 async def로 통일 — DB(asyncpg)와 OpenAI(AsyncOpenAI) 호출은 진짜 비동기라
await로 바로 처리하고, CPU 연산인 임베딩 인코딩만 asyncio.to_thread로 스레드에 넘겨서
이벤트 루프가 안 막히게 함 (embedding.encode_query 자체는 sentence-transformers가
비동기를 지원 안 해서 동기 함수로 남겨둠).
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import db, embedding, repository, summary
from .schemas import DocumentDetail, SearchResponse, SearchResultCard

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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/search", response_model=SearchResponse)
async def search(q: str) -> SearchResponse:
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력해주세요")

    pool = db.get_pool()
    query_vector = await asyncio.to_thread(embedding.encode_query, q)
    candidates = await repository.search_candidates(pool, query_vector, q, limit=10)
    candidates = repository.rerank(candidates, q)  # 지금은 no-op, 스트레치 목표(§3.4) 자리

    results = [
        SearchResultCard(
            document_id=r["document_id"],
            institution=r["institution"],
            year=r["year"],
            confidence=_confidence_label(r["parsing_quality"]),
            preview_text=r["preview_text"],
        )
        for r in candidates
    ]
    return SearchResponse(query=q, results=results)


@app.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document_detail(document_id: str) -> DocumentDetail:
    pool = db.get_pool()
    doc = await repository.get_document(pool, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    summary_point = doc["summary_point"]
    summary_cause = doc["summary_cause"]
    summary_action = doc["summary_action"]
    summary_result = doc["summary_result"]
    summary_failed = doc["summary_failed"]

    # 온디맨드 생성 + 캐싱 (§4.5) — 요약이 비어있고 이전에 실패 처리된 적도 없을 때만 생성 시도.
    # summary_failed=True로 이미 캐싱돼 있으면 재시도 안 함 (§4.6, API 비용 낭비 방지)
    if summary_point is None and not summary_failed:
        generated, failed = await summary.generate_summary(doc["raw_text"])
        await repository.save_summary(pool, document_id, generated, failed)
        if generated:
            summary_point = generated["point"]
            summary_cause = generated["cause"]
            summary_action = generated["action"]
            summary_result = generated["result"]
        summary_failed = failed

    return DocumentDetail(
        id=doc["id"],
        institution=doc["institution"],
        year=doc["year"],
        confidence=_confidence_label(doc["parsing_quality"]),
        raw_text=doc["raw_text"],
        summary_point=summary_point,
        summary_cause=summary_cause,
        summary_action=summary_action,
        summary_result=summary_result,
        summary_failed=summary_failed,
    )
