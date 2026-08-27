# ------------------------------------------------------------------
# 검색 품질 오프라인 평가 (architecture.md §5.3, §3.6 검증 근거 — 2026-08-27 코드 준비)
# ------------------------------------------------------------------
# RRF(하이브리드) vs 벡터 단독 vs 키워드 단독 vs (RRF+리랭커) vs (형태소 토큰화 적용
# 전/후)를 같은 eval set(쿼리-정답 문서 쌍)으로 돌려서 Recall@10/MRR을 비교표로 뽑음.
#
# **이 세션은 DB 접근이 없어 실행/검증을 못 했음** — generate_sitemap.py와 같은 이유로
# 이 저장소 클론 루트에서, 실제 DATABASE_URL로 실행하는 걸 전제로 작성함. 문법 검사
# (py_compile)만 통과 확인.
#
# **eval set 준비**: scripts/eval_set_template.jsonl 참고 — 이 세션은 실제 데이터를
# 볼 수 없어서 진짜 쿼리-정답 쌍을 채울 수 없었음. DB 접근 있는 사람이 검색 UI(또는
# /search API)로 실제 검색해보면서 "이 결과는 진짜 관련 있다"고 판단한 document_id를
# 20~30개 쿼리에 대해 채워야 함(§5.3 "수작업으로 구성").
#
# 실행:
#   DATABASE_URL=postgresql://... python scripts/eval_search_quality.py \
#       --eval-set scripts/eval_set.jsonl
#
# 리랭커까지 비교하려면 먼저 RERANKER_ENABLED=true로 이 스크립트를 실행(모델을 이
# 프로세스에 직접 로드함 — 별도 서버 필요 없음). 형태소 토큰화 전/후 비교는
# chunks.tsv_text가 이미 백필돼 있어야 "적용 후" 항목이 의미가 있음(scripts/
# backfill_tsv_text.py, scripts/tsv_text_migration.sql 먼저 실행).
# ------------------------------------------------------------------
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from app import db, embedding, repository, reranker, tokenizer  # noqa: E402

RERANKER_ENABLED = os.environ.get("RERANKER_ENABLED", "false").lower() == "true"
TOKENIZER_ENABLED = os.environ.get("TOKENIZER_ENABLED", "false").lower() == "true"

# 비교할 검색 모드 목록 — 아래 run_mode()에서 이 이름으로 분기
MODES = ["vector_only", "text_only", "rrf_hybrid"]

# 벡터/키워드 단독 검색 — repository._SEARCH_SQL과 같은 document 단위 dedup을
# 적용하되 한쪽 leg만 사용(공정한 비교를 위해 dedup 방식은 동일하게 맞춤).
_VECTOR_ONLY_SQL = """
WITH ranked AS (
    SELECT id AS chunk_id, document_id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank
    FROM chunks
    ORDER BY embedding <=> $1
    LIMIT 200
)
SELECT DISTINCT ON (document_id) document_id, rank
FROM ranked
ORDER BY document_id, rank ASC;
"""

_TEXT_ONLY_SQL = """
WITH ranked AS (
    SELECT id AS chunk_id, document_id,
           ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, plainto_tsquery('simple', $1)) DESC) AS rank
    FROM chunks
    WHERE tsv @@ plainto_tsquery('simple', $1)
    LIMIT 200
)
SELECT DISTINCT ON (document_id) document_id, rank
FROM ranked
ORDER BY document_id, rank ASC;
"""


async def _vector_only(pool, query_vector: list[float]) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(_VECTOR_ONLY_SQL, query_vector)
    return [r["document_id"] for r in sorted(rows, key=lambda r: r["rank"])]


async def _text_only(pool, query_text: str) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(_TEXT_ONLY_SQL, query_text)
    return [r["document_id"] for r in sorted(rows, key=lambda r: r["rank"])]


async def run_mode(pool, mode: str, query: str, query_vector: list[float]) -> list[str]:
    """모드 이름 → document_id 랭킹 리스트(위가 1등)."""
    if mode == "vector_only":
        return await _vector_only(pool, query_vector)
    if mode == "text_only":
        return await _text_only(pool, query)
    if mode == "text_only_tokenized":
        query_tokens = tokenizer.tokenize(query)
        return await _text_only(pool, query_tokens or query)
    if mode == "rrf_hybrid":
        candidates = await repository.search_candidates(pool, query_vector, query, limit=40)
        return [c["document_id"] for c in candidates]
    if mode == "rrf_hybrid_tokenized":
        query_tokens = tokenizer.tokenize(query)
        candidates = await repository.search_candidates(
            pool, query_vector, query_tokens or query, limit=40
        )
        return [c["document_id"] for c in candidates]
    if mode == "rrf_plus_rerank":
        candidates = await repository.search_candidates(pool, query_vector, query, limit=40)
        reranked = repository.rerank(candidates, query)
        return [c["document_id"] for c in reranked]
    raise ValueError(f"알 수 없는 모드: {mode}")


def recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    return 1.0 if set(ranked_ids[:k]) & relevant_ids else 0.0


def reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    for i, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / i
    return 0.0


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", default=str(REPO_ROOT / "scripts" / "eval_set.jsonl"))
    parser.add_argument(
        "--modes",
        default=",".join(MODES),
        help="쉼표로 구분된 모드 목록. 사용 가능: vector_only,text_only,text_only_tokenized,"
        "rrf_hybrid,rrf_hybrid_tokenized,rrf_plus_rerank",
    )
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    eval_path = Path(args.eval_set)
    if not eval_path.exists():
        raise SystemExit(
            f"eval set 파일이 없습니다: {eval_path}\n"
            "scripts/eval_set_template.jsonl을 scripts/eval_set.jsonl로 복사해서 실제 "
            "쿼리-정답 문서 쌍을 채운 뒤 다시 실행하세요."
        )
    eval_cases = []
    with open(eval_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            eval_cases.append(json.loads(line))
    if not eval_cases:
        raise SystemExit(f"{eval_path}에 eval 케이스가 없습니다.")
    print(f"eval set: {len(eval_cases)}개 쿼리")

    any_tokenized_index_mode = any("tokenized" in m for m in modes if m != "rrf_plus_rerank")
    if any_tokenized_index_mode and not TOKENIZER_ENABLED:
        print(
            "경고: *_tokenized 모드가 포함돼 있는데 TOKENIZER_ENABLED가 꺼져 있습니다 — "
            "형태소 분석기를 이 프로세스에도 로드해야 하므로 TOKENIZER_ENABLED=true로 "
            "다시 실행하세요(단, chunks.tsv_text 백필이 아직 안 끝났다면 이 모드의 결과는 "
            "'적용 후' 효과를 보여주지 못함 — tokenizer.py 모듈 docstring 참고)."
        )
        return
    if "rrf_plus_rerank" in modes and not RERANKER_ENABLED:
        print(
            "경고: rrf_plus_rerank 모드가 포함돼 있는데 RERANKER_ENABLED가 꺼져 있습니다 — "
            "RERANKER_ENABLED=true로 다시 실행하세요(리랭커 모델을 이 프로세스에 로드함, "
            "메모리 여유가 있는 환경에서 실행할 것 — architecture.md §3.5)."
        )
        return

    await db.init_pool()
    embedding.load_model()
    if TOKENIZER_ENABLED:
        tokenizer.load_model()
    if RERANKER_ENABLED:
        reranker.load_model()
    pool = db.get_pool()

    # {mode: {"recall10": [...], "recall40": [...], "mrr": [...]}}
    results: dict[str, dict[str, list[float]]] = {
        m: {"recall10": [], "recall40": [], "mrr": []} for m in modes
    }
    per_query_log = []

    try:
        for case in eval_cases:
            query = case["query"]
            relevant_ids = set(case["relevant_document_ids"])
            query_vector = embedding.encode_query(query)

            row = {"query": query}
            for mode in modes:
                t0 = time.time()
                ranked_ids = await run_mode(pool, mode, query, query_vector)
                elapsed_ms = (time.time() - t0) * 1000
                r10 = recall_at_k(ranked_ids, relevant_ids, 10)
                r40 = recall_at_k(ranked_ids, relevant_ids, 40)
                mrr = reciprocal_rank(ranked_ids, relevant_ids)
                results[mode]["recall10"].append(r10)
                results[mode]["recall40"].append(r40)
                results[mode]["mrr"].append(mrr)
                row[mode] = f"R@10={r10:.0f} R@40={r40:.0f} MRR={mrr:.2f} ({elapsed_ms:.0f}ms)"
            per_query_log.append(row)
            print(f"  [{query}] " + " | ".join(f"{m}: {row[m]}" for m in modes))
    finally:
        await db.close_pool()

    def avg(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    print("\n=== 요약 (평균, 쿼리 수 = %d) ===" % len(eval_cases))
    header = f"{'모드':<24}{'Recall@10':>12}{'Recall@40':>12}{'MRR':>10}"
    print(header)
    print("-" * len(header))
    for mode in modes:
        r10 = avg(results[mode]["recall10"])
        r40 = avg(results[mode]["recall40"])
        mrr = avg(results[mode]["mrr"])
        print(f"{mode:<24}{r10:>12.2%}{r40:>12.2%}{mrr:>10.3f}")


if __name__ == "__main__":
    asyncio.run(main())
