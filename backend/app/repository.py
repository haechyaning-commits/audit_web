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

# RRF(§3.1) + document 단위 dedup(§3.2) — 원래는 리랭커 입력용으로 top 20을 뽑아서
# top 10으로 압축할 계획이었으나, 리랭커가 스트레치로 빠져있어 지금은 top 40을 그대로
# 최종 결과로 반환함(main.py의 search_candidates(..., limit=40) 호출과 짝을 맞춤,
# 프론트 2열×N줄 그리드 표시 + 페이지네이션). 2026-08-12: 20건은 너무 적다는 피드백으로
# 40건으로 늘림 — vector_search/text_search 후보 풀도 50→100으로 같이 늘려서, dedup 후에도
# 40건을 채울 수 있을 만큼 후보가 남게 함(안 늘리면 소수 문서에 청크가 몰린 검색어에서
# dedup 후 40건에 못 미칠 수 있음). 나중에 리랭커 붙이면 LIMIT을 더 키우고 rerank()에서
# 압축하는 구조로 바꾸면 됨.
_SEARCH_SQL = """
WITH vector_search AS (
    SELECT id AS chunk_id, document_id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank
    FROM chunks
    ORDER BY embedding <=> $1
    LIMIT 100
),
text_search AS (
    SELECT id AS chunk_id, document_id,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(tsv, plainto_tsquery('simple', $2)) DESC
           ) AS rank
    FROM chunks
    WHERE tsv @@ plainto_tsquery('simple', $2)
    LIMIT 100
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
    doc.audit_type,
    doc.parsing_quality,
    -- 제목은 raw_text 맨 앞줄("제목 : ...")에서만 파싱하면 되므로 전체를 안 가져오고
    -- 200자만 잘라서 넘김(URL 슬러그용, 2026-08-13) — textutils.extract_title이 첫 줄만 봄.
    left(doc.raw_text, 200) AS title_buffer,
    -- 미리보기는 문서 맨 앞부분(raw_text)이 아니라 실제로 매치된 청크(c.text)에서 뽑음.
    -- raw_text 맨 앞은 "제 목 : ... 징 계 종 류 : ..." 같은 정형화된 서류 양식 헤더라
    -- 검색어랑 무관한 내용만 보여주는 문제가 있었음 — 매치된 청크를 쓰면 실제로
    -- 검색어와 관련된 본문이 보일 확률이 훨씬 높아짐.
    -- 320자로 넉넉히 가져오는 이유: 실제 자를 지점(문장/어절 경계)은 textutils.build_preview가
    -- Python에서 정함(2026-08-12) — 200자에서 그냥 뚝 자르면 문장 중간에서 끊기는 문제가
    -- 있었음. SQL은 여유분 있는 buffer만 넘겨줌.
    left(c.text, 320) AS preview_buffer
FROM doc_deduped dd
JOIN documents doc ON doc.id = dd.document_id
JOIN chunks c ON c.id = dd.chunk_id
ORDER BY dd.score DESC
LIMIT $3;
"""


async def search_candidates(
    pool: asyncpg.Pool,
    query_vector: list[float],
    query_text: str,
    limit: int = 40,
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
SELECT id, institution, year, audit_type, raw_text, parsing_quality,
       summary_point, summary_cause, summary_action, summary_result, summary_failed,
       summary_freeform, summary_freeform_failed
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


_SAVE_FREEFORM_SUMMARY_SQL = """
UPDATE documents
SET summary_freeform = $2,
    summary_freeform_failed = $3
WHERE id = $1;
"""


async def save_freeform_summary(
    pool: asyncpg.Pool,
    document_id: str,
    freeform_text: str | None,
    failed: bool,
) -> None:
    """구조화 요약(save_summary)과 별도 컬럼에 캐싱 — 프롬프트/생성 시점이 다르므로 독립적으로
    저장. 실패 캐싱 이유는 save_summary와 동일(§4.6)."""
    async with pool.acquire() as conn:
        await conn.execute(_SAVE_FREEFORM_SUMMARY_SQL, document_id, freeform_text, failed)
