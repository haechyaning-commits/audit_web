"""
실제 SQL 쿼리 모음 (architecture.md §3.2 RRF 검색 SQL을 asyncpg용으로 옮긴 것).

db.py(연결 방법)와 분리한 이유: "DB에 어떻게 연결하는지"와 "무슨 쿼리를 날리는지"가 섞이면
연결 방식이 바뀔 때(예: Railway→다른 곳)마다 쿼리 코드까지 같이 건드려야 해서 분리함.

- 리랭커(§3.4)는 스트레치 목표라 아직 없음 — rerank()는 지금은 아무것도 안 하고 그대로
  통과시키는 자리만 만들어둠. 나중에 bge-reranker-v2-m3 붙일 때 이 함수 내용만 채우면 되고
  검색 흐름 전체를 다시 안 뜯어도 됨.
- 한국어 형태소 토큰화(kiwipiepy, §3.6)도 스트레치 목표라, 지금은 검색어 원문을 그대로
  plainto_tsquery에 넘김 (정확 매칭이 약해질 수 있으나 벡터 검색이 하이브리드의 절반을
  담당하므로 검색 자체가 안 되는 수준은 아님).
"""
from typing import Any

import asyncpg

# RRF(§3.1) + document 단위 dedup(§3.2) — 후보 단계에서 top 20을 뽑던 원래 설계는
# 리랭커 입력용이었음. 리랭커가 스트레치로 빠져있어 바로 top 10을 반환하도록 LIMIT을
# 줄임 (나중에 리랭커 붙일 때 LIMIT 20으로 되돌리고 rerank()에서 10건으로 압축하면 됨).
_SEARCH_SQL = """
WITH vector_search AS (
    SELECT id AS chunk_id, document_id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank
    FROM chunks
    ORDER BY embedding <=> $1
    LIMIT 50
),
text_search AS (
    SELECT id AS chunk_id, document_id,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(tsv, plainto_tsquery('simple', $2)) DESC
           ) AS rank
    FROM chunks
    WHERE tsv @@ plainto_tsquery('simple', $2)
    LIMIT 50
),
rrf_scored AS (
    SELECT
        COALESCE(v.chunk_id, t.chunk_id)       AS chunk_id,
        COALESCE(v.document_id, t.document_id) AS document_id,
        (1.0 / (60 + COALESCE(v.rank, 1000))) +
        (1.0 / (60 + COALESCE(t.rank, 1000))) AS score
    FROM vector_search v
    FULL OUTER JOIN text_search t ON v.chunk_id = t.chunk_id
),
doc_deduped AS (
    -- 문서(사례)당 최고 점수 청크 1개만 남김 → 카드 중복 방지 (§3.2 변경이유②)
    SELECT DISTINCT ON (document_id)
        chunk_id, document_id, score
    FROM rrf_scored
    ORDER BY document_id, score DESC
)
SELECT
    dd.document_id,
    dd.chunk_id,
    dd.score,
    doc.institution,
    doc.year,
    doc.parsing_quality,
    left(doc.raw_text, 150) AS preview_text
FROM doc_deduped dd
JOIN documents doc ON doc.id = dd.document_id
ORDER BY dd.score DESC
LIMIT $3;
"""


async def search_candidates(
    pool: asyncpg.Pool,
    query_vector: list[float],
    query_text: str,
    limit: int = 10,
) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(_SEARCH_SQL, query_vector, query_text, limit)


def rerank(candidates: list[asyncpg.Record], query_text: str) -> list[asyncpg.Record]:
    """
    스트레치 목표(§3.4) — bge-reranker-v2-m3로 20건 재채점 후 top 10 반환 예정.
    지금은 RRF+dedup 순위를 그대로 통과시킴 (no-op). 함수 시그니처를 미리 맞춰둬서
    나중에 여기 안만 채우면 main.py/search_candidates 쪽은 안 건드려도 됨.
    """
    return candidates


_GET_DOCUMENT_SQL = """
SELECT id, institution, year, raw_text, parsing_quality,
       summary_point, summary_cause, summary_action, summary_result, summary_failed
FROM documents
WHERE id = $1;
"""


async def get_document(pool: asyncpg.Pool, document_id: str) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        return await conn.fetchrow(_GET_DOCUMENT_SQL, document_id)


_SAVE_SUMMARY_SQL = """
UPDATE documents
SET summary_point = $2,
    summary_cause = $3,
    summary_action = $4,
    summary_result = $5,
    summary_failed = $6
WHERE id = $1;
"""


async def save_summary(
    pool: asyncpg.Pool,
    document_id: str,
    summary: dict[str, Any] | None,
    failed: bool,
) -> None:
    """
    §4.5 온디맨드 생성 + DB 캐싱: 상세 API가 문서 조회 시 요약이 비어있으면 그 자리에서
    생성하고 여기로 저장 — 다음 조회부터는 API 호출 없이 DB 값만 반환됨.
    summary_failed=TRUE로 저장해두면(§4.6) 진짜 요약 불가능한 문서를 매번 재시도하며
    API 비용 낭비하는 것도 방지됨.
    """
    point = summary.get("point") if summary else None
    cause = summary.get("cause") if summary else None
    action = summary.get("action") if summary else None
    result = summary.get("result") if summary else None
    async with pool.acquire() as conn:
        await conn.execute(_SAVE_SUMMARY_SQL, document_id, point, cause, action, result, failed)
