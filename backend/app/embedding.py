"""
검색어를 벡터로 변환 (architecture.md §3.3 쿼리 임베딩, 온라인 추론).

배치(Colab GPU)와 달리 검색 시점엔 실시간으로 인코딩해야 함. 모델을 요청마다 새로 불러오면
지연시간이 폭증하므로, 앱 시작 시 딱 한 번만 로드해서 재사용.
"""
import os
from functools import lru_cache

import torch
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def load_model() -> None:
    global _model
    if _model is not None:
        return
    # 2026-08-25(성능 조사): 실사용 중 처음 보는 검색어 인코딩이 15~17초씩 걸리는 게
    # 확인됨(동일 검색어 재요청은 lru_cache 히트로 ~1초). 컨테이너 환경(Railway 등)에서
    # PyTorch가 기본으로 "호스트가 보고하는 논리 CPU 코어 수"만큼 스레드를 켜는데,
    # 실제 컨테이너에 할당된 CPU가 그보다 훨씬 적으면(흔한 상황) 스레드가 서로
    # 컨텍스트 스위칭만 하느라 오히려 더 느려지는 경우가 있음 — 특히 배치 크기 1(검색어
    # 한 문장)처럼 원래 병렬화 이득이 크지 않은 연산에서 두드러짐. 이게 실측된 지연의
    # 원인인지는 아직 배포 후 실측으로 검증 전(가설) — 인프라/모델 교체 없이 시도해볼
    # 수 있는 가장 저렴한 변경이라 먼저 시도함. TORCH_NUM_THREADS 환경변수로 조절
    # 가능하게 해서, 실측 후 다른 값이 낫다고 나오면 재배포 없이 바로 바꿀 수 있게 함.
    torch.set_num_threads(int(os.environ.get("TORCH_NUM_THREADS", "2")))
    # Railway는 보통 GPU 없는 CPU 인스턴스 — device 명시 안 하면 자동으로 CPU 씀
    _model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    _model.max_seq_length = 512


def _encode_query_uncached(text: str) -> list[float]:
    if _model is None:
        raise RuntimeError("임베딩 모델이 로드되지 않았습니다 (startup에서 load_model 호출 필요)")
    # normalize_embeddings=True — 배치 임베딩(embed_chunks.py)도 정규화된 벡터를 저장했으므로
    # 같은 벡터공간 기준을 맞춰야 코사인 유사도 비교가 의미 있음 (STATUS.md 6차 실측: norm≈1.0 확인)
    vec = _model.encode([text], normalize_embeddings=True)[0]
    return vec.tolist()


# 2026-08-24(피드백 반영): 같은 검색어로 필터(기관/연도/감사유형)만 바꿔서 재검색하면
# main.py가 매번 새 /search 요청을 보내는데(필터가 랭킹 전에 걸려야 해서 이 자체는
# 맞는 설계, repository.py 참고) — 그때마다 이 함수가 같은 텍스트를 다시 인코딩하고
# 있었음. 검색어 자체는 그대로인데 CPU를 쓰는 인코딩(이 앱에서 검색 지연시간의 상당
# 부분을 차지하는 부분, §3.3)만 반복하는 건 순수 낭비 — encode_query가 텍스트 하나에
# 항상 같은 벡터를 내는 순수 함수라는 점을 이용해 결과를 캐싱함. lru_cache는 스레드
# 세이프(내부 락 있음)라 asyncio.to_thread로 여러 요청이 동시에 들어와도 안전.
# tuple로 캐싱하는 이유: 호출부(main.py→repository.py)가 이 반환값을 안 건드리긴
# 하지만, 캐시된 리스트를 그대로 공유하면 나중에 어디선가 실수로 mutate했을 때 다른
# 요청까지 오염될 위험이 있음 — 매 호출마다 새 list로 복사해서 내보내 그 위험을 원천
# 차단함(비용은 float 1024개 복사, 무시할 수준).
# maxsize=256: 세션 몇 개가 동시에 필터를 이것저것 눌러봐도 캐시가 다 담을 만한
# 크기(벡터 하나당 1024차원 float64 ≈ 8KB, 256개 캐싱해도 ~2MB).
@lru_cache(maxsize=256)
def _encode_query_cached(text: str) -> tuple[float, ...]:
    return tuple(_encode_query_uncached(text))


def encode_query(text: str) -> list[float]:
    return list(_encode_query_cached(text))


# 2026-08-25(성능 개선): 홈 화면 예시 검색어(frontend/src/pages/SearchPage.jsx의
# EXAMPLE_QUERIES와 동일한 문구 — 실사용자가 클릭할 확률이 특히 높음)를 서버 시작 시
# 미리 인코딩해서 lru_cache를 예열해둠. 처음 보는 검색어는 여전히 15초 안팎 걸리지만,
# 최소한 이 케이스는 첫 클릭도 캐시 히트로 빠르게 응답됨.
# main.py가 이 함수를 asyncio.create_task(asyncio.to_thread(...))로 백그라운드에서
# 돌림(await 안 함) — load_model()과 달리 이건 앱이 요청을 받기 시작하는 걸 지연시킬
# 이유가 없고(예열 안 된 검색어는 어차피 느린 채로 정상 동작), 문구 4개 * ~15초로
# 배포 직후 헬스체크/시작 시간이 1분 가까이 늘어나면 오히려 배포 자체가 불안정해질
# 위험이 있어서(Railway 헬스체크 타임아웃) 블로킹시키지 않음.
_PREWARM_QUERIES = [
    "수의계약 특혜",
    "출장비를 부풀려 청구한 사례",
    "보조금 부정수급",
    "직장 상사가 부하직원을 괴롭힌 사례",
]


def prewarm_cache() -> None:
    for text in _PREWARM_QUERIES:
        encode_query(text)
