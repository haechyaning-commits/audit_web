# ------------------------------------------------------------------
# 임베딩+리랭커 동시 로드 메모리 실측 (architecture.md §3.5 — 2026-08-27 코드 준비,
# RERANKER_ENABLED를 켜기 전 배포 전 필수 확인 항목)
# ------------------------------------------------------------------
# §3.5: "확인 필요"로 남겨두지 않고 배포 전 실측 기반으로 확정 — 이 스크립트가 그 실측을
# 자동화함. Railway와 동일 스펙 컨테이너(또는 최소한 `docker run --memory=<플랜상한>`)에서
# 돌리는 게 이상적이지만, 로컬에서 돌려도 "두 모델을 동시에 올리면 대략 얼마나 쓰는지"
# 최소한의 근거는 얻을 수 있음.
#
# **이 세션은 torch/sentence-transformers 설치 + 실제 모델 다운로드(수백 MB~1GB대)를
# 해보지 않았음** — 디스크/시간 예산을 고려해 스크립트만 준비하고 실행은 안 함. DB 접근
# 세션(로컬 또는 CI)에서 실행해서 실측치를 §3.5 표에 반영할 것.
#
# 실행:
#   pip install --extra-index-url https://download.pytorch.org/whl/cpu -r backend/requirements.txt
#   python scripts/measure_model_memory.py
# ------------------------------------------------------------------
import resource
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


def _peak_rss_mb() -> float:
    # Linux: ru_maxrss는 KB 단위 (macOS는 byte 단위라 다름 — Railway는 Linux 컨테이너라
    # 여기선 KB 기준으로만 계산, macOS 로컬에서 돌리면 이 숫자가 1000배 부풀려 보일 수 있음)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> None:
    print(f"시작 시 RSS: {_peak_rss_mb():.0f} MB")

    from app import embedding

    embedding.load_model()
    print(f"임베딩(BGE-m3) 로드 후 RSS: {_peak_rss_mb():.0f} MB")

    from app import reranker

    reranker.load_model()
    print(f"+ 리랭커(bge-reranker-v2-m3) 로드 후 RSS: {_peak_rss_mb():.0f} MB")

    # 실제 요청 처리 흉내 — 추론 한 번씩 돌려서 워밍업 이후 RSS도 같이 확인
    # (모델 가중치만 올렸을 때보다 실제 추론 중 피크가 더 높을 수 있음)
    vec = embedding.encode_query("수의계약 특혜")
    reranker.score_pairs("수의계약 특혜", ["예시 청크 텍스트 " * 20] * 20)
    print(f"쿼리 인코딩 + 리랭커 추론(20쌍) 1회 후 RSS: {_peak_rss_mb():.0f} MB")

    print(
        "\n위 마지막 수치를 §3.5 '실사용 RSS 예상치'와 비교해서 Railway 플랜 메모리 상한"
        "(대시보드에서 최신 값 재확인)을 넘는지 판단할 것. 넘으면 §3.5의 대응 순서"
        "(1순위: 리랭커 int8 양자화, 2순위: 플랜 상향, 최후수단: 리랭커 lazy load)를 따를 것."
    )


if __name__ == "__main__":
    main()
