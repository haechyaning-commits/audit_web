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
import numpy as np

# RRF(§3.1) + document 단위 dedup(§3.2) — 원래는 리랭커 입력용으로 top 20을 뽑아서
# top 10으로 압축할 계획이었으나, 리랭커가 스트레치로 빠져있어 지금은 top 40을 그대로
# 최종 결과로 반환함(main.py의 search_candidates(..., limit=40) 호출과 짝을 맞춤,
# 프론트 2열×N줄 그리드 표시 + 페이지네이션). 2026-08-12: 20건은 너무 적다는 피드백으로
# 40건으로 늘림 — vector_search/text_search 후보 풀도 50→100으로 같이 늘려서, dedup 후에도
# 40건을 채울 수 있을 만큼 후보가 남게 함(안 늘리면 소수 문서에 청크가 몰린 검색어에서
# dedup 후 40건에 못 미칠 수 있음). 나중에 리랭커 붙이면 LIMIT을 더 키우고 rerank()에서
# 압축하는 구조로 바꾸면 됨.
# 2026-08-24: 기관/연도 필터(FR5, v1.1로 미뤄뒀던 것) 추가 — filtered_docs CTE로
# 후보 문서 id를 먼저 좁혀두고, vector_search/text_search 둘 다 그 안에서만 순위를
# 매기게 함. 필터를 "다 뽑은 뒤에" 걸면(WHERE를 최종 SELECT에만 두면) 상위 100건
# 후보가 필터에 안 걸리는 문서들로 이미 채워진 경우 필터링 후 결과가 몇 건 안
# 남을 수 있어서(예: 특정 기관으로 좁혔는데 그 기관 문서가 벡터 유사도 상위 100위
# 안에 하나도 없으면 0건) — 반드시 랭킹 전에 걸러야 함. 필터 없을 땐($4/$5/$6 전부
# NULL) 이 서브쿼리가 documents 테이블 id를 전부 반환해서 기존 동작과 동일함.
# 2026-08-24(2차): 감사유형(audit_type) 필터도 같은 방식으로 추가 — 고정 사이드바
# 필터 UI(기관/연도/감사유형 3종)를 위해 institution/year와 동일하게 확장.
_SEARCH_SQL = """
WITH filtered_docs AS (
    SELECT id FROM documents
    WHERE ($4::text IS NULL OR institution = $4)
      AND ($5::int IS NULL OR year = $5)
      AND ($6::text IS NULL OR audit_type = $6)
),
vector_search AS (
    SELECT id AS chunk_id, document_id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank
    FROM chunks
    WHERE document_id IN (SELECT id FROM filtered_docs)
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
      AND document_id IN (SELECT id FROM filtered_docs)
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
    -- 2026-08-25: 기관명 정확 매칭 가산점 — 검색어(자유 텍스트) 안에 실제 DB
    -- 기관명이 그대로 들어있으면($7, main.py에서 미리 찾아둔 값) 그 기관 문서
    -- 점수에 고정 가산치($8)를 더함. RRF 점수 최댓값은 두 leg 모두 1등일 때
    -- 1/61+1/61 ≈ 0.033이므로, $8이 그보다 충분히 크면(기본 0.05) 기관이
    -- 일치하는 문서가 항상 그렇지 않은 문서보다 위로 옴 — "한국관광공사 2024년
    -- 특정감사"처럼 기관명을 포함한 자연어 질의를 던졌을 때, 그 기관명이 본문에
    -- 그대로 안 남아있어 벡터/키워드 검색만으로는 순위가 안 나오는 문제(§FR5
    -- 필터와 별개로, 자유 텍스트 질의 자체에서 기관을 우선하고 싶은 경우) 완화.
    -- $7이 NULL이면(검색어에 기관명이 없거나, 사이드바 필터로 이미 institution이
    -- 좁혀져 있어 가산점이 의미 없는 경우 main.py가 아예 안 채워서 보냄) 항상 0.
    dd.score
      + CASE WHEN $7::text IS NOT NULL AND doc.institution = $7 THEN $8::float ELSE 0 END
      AS score,
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
    left(c.text, 320) AS preview_buffer,
    -- 2026-08-25(베타테스트 피드백 3번 착수): RRF score는 "두 검색(벡터/키워드) 중
    -- 어느 쪽에서 몇 등이었나"만 반영하는 순위 기반 값이라, 실측해보니 완전히 무의미한
    -- 검색어("a")와 정상적인 문장의 1위 점수가 소수점까지 동일하게 나오는 경우가 있음
    -- (우연이 아니라 "한쪽 leg 1등 + 다른 leg 후보 100건 밖" 조합이 흔해서 구조적으로
    -- 자주 나오는 값) — 즉 RRF score만으로는 "진짜 관련 있음"을 판단할 근거가 안 됨.
    -- 그래서 순위 융합을 거치지 않은 원래 코사인 유사도(쿼리 벡터 ↔ 실제 매치된 청크)를
    -- 별도로 노출함 — 이 값의 정상/의미없는 질문 간 분포 차이를 실측해서 "관련성 낮음"
    -- 판단 기준을 정할 예정(아직 응답에만 추가, 필터링/배지 로직은 실측 후 다음 작업).
    1 - (c.embedding <=> $1) AS vector_similarity
FROM doc_deduped dd
JOIN documents doc ON doc.id = dd.document_id
JOIN chunks c ON c.id = dd.chunk_id
ORDER BY score DESC
LIMIT $3;
"""


async def search_candidates(
    pool: asyncpg.Pool,
    query_vector: list[float],
    query_text: str,
    limit: int = 40,
    institution: str | None = None,
    year: int | None = None,
    audit_type: str | None = None,
    boost_institution: str | None = None,
    boost_amount: float = 0.05,
) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            _SEARCH_SQL,
            query_vector,
            query_text,
            limit,
            institution,
            year,
            audit_type,
            boost_institution,
            boost_amount,
        )


# 2026-08-25: 검색어(자유 텍스트)에 실제 DB 기관명이 그대로 포함돼 있는지 찾음 —
# 위 _SEARCH_SQL의 기관명 가산점($7)에 넘길 값을 구하는 용도. 후보를 Python으로
# 다 끌어와 반복문 돌리는 대신, DISTINCT 기관명 목록(개수가 적어 이 프로젝트
# 규모에선 충분히 가벼움 — get_filter_options와 같은 전제) 안에서 strpos로 부분
# 문자열 매칭을 SQL이 직접 하게 함. 여러 기관명이 동시에 부분 매칭되면(예: 한
# 기관명이 다른 기관명을 포함하는 경우) 가장 긴(가장 구체적인) 것 하나만 채택.
_MATCH_INSTITUTION_SQL = """
SELECT institution
FROM (SELECT DISTINCT institution FROM documents
      WHERE institution IS NOT NULL AND institution <> '') AS insts
WHERE strpos($1, institution) > 0
ORDER BY length(institution) DESC
LIMIT 1;
"""


async def find_matching_institution(pool: asyncpg.Pool, query_text: str) -> str | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_MATCH_INSTITUTION_SQL, query_text)
        return row["institution"] if row else None


_FILTER_OPTIONS_SQL = """
SELECT
    ARRAY(SELECT DISTINCT institution FROM documents
          WHERE institution IS NOT NULL ORDER BY institution) AS institutions,
    ARRAY(SELECT DISTINCT year FROM documents
          WHERE year IS NOT NULL ORDER BY year) AS years,
    ARRAY(SELECT DISTINCT audit_type FROM documents
          WHERE audit_type IS NOT NULL ORDER BY audit_type) AS audit_types;
"""


async def get_filter_options(pool: asyncpg.Pool) -> asyncpg.Record:
    """기관/연도 필터 드롭다운용 값 목록(FR5) — documents 테이블 규모(6.8만 건)가
    작아서 매 요청 직접 조회해도 부담 없음(캐싱은 필요해지면 나중에 추가)."""
    async with pool.acquire() as conn:
        return await conn.fetchrow(_FILTER_OPTIONS_SQL)


# 2026-08-25(베타테스트 피드백 5번): 홈 화면 "연도별 사례 수" 막대그래프가 지금까지
# frontend/src/pages/SearchPage.jsx에 값이 통째로 하드코딩돼 있어서, DB에 새 문서가
# 계속 반영되고 있는데도(HWP 표 손실 복구 등 진행 중) 프론트를 재배포하지 않는 한 그
# 시점 스냅샷에 멈춰있는 문제. get_filter_options와 같은 이유로 매 요청 직접 집계해도
# 부담 없는 규모.
# year가 NULL인 문서(현재 2건, README §스크린샷 참고)는 막대그래프엔 못 넣지만 "전체
# 건수" 통계에선 빠지면 안 되므로, total은 year 조건 없이 documents 테이블 전체를
# 따로 셈 — years 배열의 count 합과 total이 살짝 다를 수 있는 게 정상(연도 미상 문서 수만큼).
_TOTAL_DOCUMENTS_SQL = "SELECT count(*) AS total FROM documents;"

_YEAR_STATS_SQL = """
SELECT year, count(*) AS count
FROM documents
WHERE year IS NOT NULL
GROUP BY year
ORDER BY year;
"""


async def get_year_stats(pool: asyncpg.Pool) -> tuple[int, list[asyncpg.Record]]:
    async with pool.acquire() as conn:
        total_row = await conn.fetchrow(_TOTAL_DOCUMENTS_SQL)
        years = await conn.fetch(_YEAR_STATS_SQL)
        return total_row["total"], years


def rerank(candidates: list[asyncpg.Record], query_text: str) -> list[asyncpg.Record]:
    """
    스트레치 목표(§3.4) — bge-reranker-v2-m3로 20건 재채점 후 top 10 반환 예정.
    지금은 RRF+dedup 순위를 그대로 통과시킴 (no-op). 함수 시그니처를 미리 맞춰둬서
    나중에 여기 안만 채우면 main.py/search_candidates 쪽은 안 건드려도 됨.
    """
    return candidates


_GET_DOCUMENT_SQL = """
SELECT id, institution, year, audit_type, raw_text, parsing_quality, source_file,
       summary_point, summary_cause, summary_action, summary_result, summary_failed,
       summary_freeform, summary_freeform_failed
FROM documents
WHERE id = $1;
"""


async def get_document(pool: asyncpg.Pool, document_id: str) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        return await conn.fetchrow(_GET_DOCUMENT_SQL, document_id)


# 2026-08-24(피드백 반영): 상세페이지 "유사 사례" 섹션 — 검색(_SEARCH_SQL)과 똑같은
# 벡터 검색을 재사용하되, "사용자가 입력한 문장" 대신 "지금 보고 있는 이 문서 자체"를
# 쿼리로 삼음. 쿼리 임베딩을 SQL 밖(파이썬)에서 만드는 것도 search_candidates와 동일한
# 패턴 — main.py가 encode_query()로 벡터를 만든 뒤 SQL에 넘기는 것처럼, 여기서는 그
# 문서에 속한 모든 청크 임베딩의 평균(centroid)을 만들어서 넘김.
#
# 청크 하나(예: 첫 청크)만 대표로 쓰지 않고 평균을 쓰는 이유: 문서 하나가 여러 주제를
# 걸칠 수 있는데(지적사항/원인/조치/결과 등 서로 다른 문단), 특정 청크 하나만 기준으로
# 삼으면 그 청크 내용에만 치우친 "유사"가 나올 위험이 있음. 평균을 내면 문서 전체
# 주제를 고르게 반영함 — Postgres 쪽에 vector AVG 집계를 시키는 대신(pgvector 버전에
# 따라 지원 여부가 갈릴 수 있어 안전하게) numpy로 파이썬에서 계산.
_DOC_CHUNK_EMBEDDINGS_SQL = "SELECT embedding FROM chunks WHERE document_id = $1;"

_SIMILAR_SQL = """
WITH ranked AS (
    SELECT c.id AS chunk_id, c.document_id,
           c.embedding <=> $1 AS distance
    FROM chunks c
    WHERE c.document_id != $2
    ORDER BY c.embedding <=> $1
    LIMIT 100
),
deduped AS (
    -- 검색(_SEARCH_SQL)과 동일한 이유로 문서당 최고(=최소 거리) 청크 1개만 남김
    SELECT DISTINCT ON (document_id) chunk_id, document_id, distance
    FROM ranked
    ORDER BY document_id, distance ASC
)
SELECT
    d.document_id,
    d.distance,
    doc.institution,
    doc.year,
    doc.audit_type,
    doc.parsing_quality,
    left(doc.raw_text, 200) AS title_buffer,
    left(c.text, 320) AS preview_buffer
FROM deduped d
JOIN documents doc ON doc.id = d.document_id
JOIN chunks c ON c.id = d.chunk_id
ORDER BY d.distance ASC
LIMIT $3;
"""


async def get_similar_documents(
    pool: asyncpg.Pool, document_id: str, limit: int = 5
) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(_DOC_CHUNK_EMBEDDINGS_SQL, document_id)
        # 2026-08-25(진짜 원인, 500 버그 2차 수정): db.py에서 register_vector(conn)로
        # 등록한 asyncpg 코덱은 vector 컬럼을 numpy 배열이 아니라 pgvector.Vector
        # 객체로 디코딩함(pgvector.asyncpg.register 참고) — Vector는 numpy가 이해하는
        # __array__ 같은 인터페이스가 없어서, np.stack([Vector, ...])가 그냥 "파이썬
        # 객체 배열"을 만들고 그 뒤 np.mean(..., axis=0)이 Vector끼리 더하려다(+
        # 연산자 미구현) TypeError를 던짐 — NULL 여부와 무관하게 이 함수는 애초에
        # 한 번도 정상 동작한 적이 없었던 것으로 보임(첫 수정에서 NULL 필터링만
        # 추가했을 때도 500은 없어졌지만 실제로는 여전히 이 지점에서 실패해서
        # 매번 빈 배열만 반환되고 있었음 — 실사용 재확인으로 발견).
        # Vector.to_numpy()로 진짜 numpy 배열(float32, 1024차원)로 변환한 뒤 쌓아야 함.
        # chunks.embedding에 NOT NULL 제약이 없어서(schema_tables.sql) 임베딩 누락 청크가
        # 섞여 있을 가능성은 여전히 있으므로 None 필터링은 유지.
        embeddings = [r["embedding"].to_numpy() for r in rows if r["embedding"] is not None]
        if not embeddings:
            return []  # 청크가 아예 없거나(파싱 실패 등) 전부 임베딩 누락 — 계산할 기준이 없음
        centroid = np.mean(np.stack(embeddings), axis=0)
        return await conn.fetch(_SIMILAR_SQL, centroid, document_id, limit)


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
