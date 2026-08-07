"""
검색어를 벡터로 변환 (architecture.md §3.3 쿼리 임베딩, 온라인 추론).

배치(Colab GPU)와 달리 검색 시점엔 실시간으로 인코딩해야 함. 모델을 요청마다 새로 불러오면
지연시간이 폭증하므로, 앱 시작 시 딱 한 번만 로드해서 재사용.
"""
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def load_model() -> None:
    global _model
    if _model is not None:
        return
    # Railway는 보통 GPU 없는 CPU 인스턴스 — device 명시 안 하면 자동으로 CPU 씀
    _model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    _model.max_seq_length = 512


def encode_query(text: str) -> list[float]:
    if _model is None:
        raise RuntimeError("임베딩 모델이 로드되지 않았습니다 (startup에서 load_model 호출 필요)")
    # normalize_embeddings=True — 배치 임베딩(embed_chunks.py)도 정규화된 벡터를 저장했으므로
    # 같은 벡터공간 기준을 맞춰야 코사인 유사도 비교가 의미 있음 (STATUS.md 6차 실측: norm≈1.0 확인)
    vec = _model.encode([text], normalize_embeddings=True)[0]
    return vec.tolist()
