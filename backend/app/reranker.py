"""
리랭커 (architecture.md §3.4, 스트레치 목표 — 2026-08-27 코드 준비).

RRF로 뽑은 후보를 크로스인코더(bge-reranker-v2-m3)로 한 번 더 정밀 채점 — embedding.py와
같은 이유(요청마다 로드하면 지연시간 폭증)로 앱 시작 시 딱 한 번만 로드해서 재사용.

**기본값은 꺼짐(RERANKER_ENABLED=false)**: architecture.md §3.5에 따르면 임베딩
모델(BGE-m3)과 리랭커(bge-reranker-v2-m3)를 같은 프로세스에 동시 로드하면 FP16 기준
RSS가 ~2.5~3GB로 추정되는데, 이게 Railway 배포 티어 메모리 상한을 넘길 가능성이 있어
"배포 전 실측 기반으로 확정"하도록 설계돼 있음. 이 세션은 DB/Railway 접근이 없어 실측을
못 했으므로, 코드는 준비하되 명시적으로 환경변수를 켜기 전까지는 기존 배포에 아무
영향도 안 주게(모델 로드 자체를 안 함) 만들어둠 — §3.5의 1번 항목(실측)을 먼저 하고
켤 것.
"""
import logging
import os

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

_model: CrossEncoder | None = None

# RRF+dedup 결과 중 상위 몇 건까지만 리랭커로 재채점할지. architecture.md §3.4 원안은
# "20건 재채점 후 top 10"이었지만, 2026-08-12에 검색 결과가 2열 그리드+페이지네이션(최대
# 40건)으로 확장되면서 그 전제가 바뀜 — 지금 top 10으로 잘라버리면 페이지네이션에 보여줄
# 결과가 부족해짐. 그래서 상위 RERANK_TOP_N건만 리랭커로 재정렬하고 나머지는 원래
# RRF+dedup 순서 그대로 뒤에 이어붙이는 방식으로 절충함(repository.rerank 참고) —
# 리랭커 효과가 가장 중요한 "맨 위 몇 개"만 정밀화하고, 페이지네이션에 필요한 전체
# 후보 수는 그대로 유지.
RERANK_TOP_N = int(os.environ.get("RERANK_TOP_N", "20"))


def load_model() -> None:
    global _model
    if _model is not None:
        return
    import torch

    # embedding.py와 동일한 이유(컨테이너 CPU 코어 수 오탐지로 인한 스레드 경합 방지)
    torch.set_num_threads(int(os.environ.get("TORCH_NUM_THREADS", "2")))
    _model = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cpu", max_length=512)


def is_loaded() -> bool:
    return _model is not None


def score_pairs(query_text: str, texts: list[str]) -> list[float]:
    if _model is None:
        raise RuntimeError("리랭커가 로드되지 않았습니다 (startup에서 load_model 호출 필요)")
    pairs = [(query_text, t) for t in texts]
    scores = _model.predict(pairs)
    return [float(s) for s in scores]
