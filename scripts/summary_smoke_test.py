# ------------------------------------------------------------------
# 요약 배치 스모크 테스트 스크립트
# ------------------------------------------------------------------
# 목적: 8만 건 전체 요약 배치(Claude Haiku)를 돌리기 전에,
#       30~35건 샘플로 아래를 먼저 검증한다.
#   1) 프롬프트가 실제로 "정확히 4줄" 포맷을 지키는지
#   2) parsing_quality(partial/fallback)별로 이상한 요약(할루시네이션 등)이 없는지
#   3) 재시도/백오프 로직이 실제로 동작하는지
#   4) 8만 건 기준 실제 비용/소요시간을 실측치로 추정
#
# 실행 전 준비:
#   pip install anthropic
#   export ANTHROPIC_API_KEY=...   (또는 `ant auth login` 후 실행)
#   INPUT_PATH를 실제 문서 파일 경로로 변경
#     - 요약은 "문서(사례) 단위"이므로(architecture.md §4), chunk가 아니라
#       document 레코드가 필요함: document_id, raw_text(원문 전체),
#       parsing_quality, institution, year 등을 포함한 jsonl 가정.
#       실제 파이프라인의 필드명이 다르면 load_and_sample()만 맞춰 수정.
# ------------------------------------------------------------------

import json
import os
import random
import time
import concurrent.futures
from datetime import datetime

import anthropic

# ------------------------------------------------------------------
# 0) 설정
# ------------------------------------------------------------------
MODEL = "claude-haiku-4-5"  # architecture.md §4.4: 8만 건 1회성 배치라 저비용 모델로 충분
INPUT_PATH = "documents.jsonl"           # TODO: 실제 문서 파일 경로로 교체
OUTPUT_PATH = "smoke_test_results.jsonl"

# parsing_quality별 표본 크기 — extraction_failed는 요약 생성 대상에서 제외(§4.3)
SAMPLE_SIZE_PER_BUCKET = {
    "standard": 20,
    "partial": 10,
    "fallback": 5,
}

MAX_CONCURRENCY = 5           # 동시 요청 수 제한 (본 배치 때 이 값 자체를 튜닝하는 게 목적 중 하나)
MAX_RETRIES_PER_REQUEST = 4   # SDK가 429/5xx/네트워크 에러에 자동으로 exponential backoff 재시도
FULL_BATCH_SIZE = 80_000      # 최종 비용/시간 추정용

# Haiku 4.5 가격: $1.00 / 1M input, $5.00 / 1M output (2026-08 기준, 변동 가능 — 배치 직전 재확인 권장)
PRICE_PER_M_INPUT = 1.00
PRICE_PER_M_OUTPUT = 5.00

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 또는 `ant auth login` 프로필 사용

PROMPT_TEMPLATE = """아래 감사 사례 원문을 읽고 정확히 4줄로 요약해라.
1줄: 지적사항 한 문장
2줄: 원인/경위 한 문장
3줄: 조치사항 한 문장
4줄: 처리결과 한 문장 (원문에 결과 정보가 없으면 "처리결과 미기재"로 표시)
원문:
{raw_text}"""


# ------------------------------------------------------------------
# 1) 층화 샘플링
#    — parsing_quality 비율대로, 원문 길이도 짧은/중간/긴 문서를 섞어서 추출
#      (앞에서부터 N개만 뽑으면 특정 기관/연도로 편향될 위험이 있음)
# ------------------------------------------------------------------
def load_and_sample(path: str) -> list[dict]:
    by_quality: dict[str, list[dict]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            q = rec.get("parsing_quality")
            if q == "extraction_failed":
                continue  # §4.3: 요약 생성 대상에서 이미 제외
            by_quality.setdefault(q, []).append(rec)

    sample = []
    for quality, n in SAMPLE_SIZE_PER_BUCKET.items():
        pool = by_quality.get(quality, [])
        if not pool:
            print(f"[경고] parsing_quality={quality} 문서가 입력 파일에 없음 — 건너뜀")
            continue
        # 길이순 정렬 후 균등 간격으로 뽑아서 짧은/중간/긴 문서를 골고루 포함
        pool_sorted = sorted(pool, key=lambda r: len(r.get("raw_text", "")))
        step = max(1, len(pool_sorted) // n)
        picked = pool_sorted[::step][:n]
        sample.extend(picked)

    random.shuffle(sample)
    return sample


# ------------------------------------------------------------------
# 2) 4줄 포맷 검증 (자동 체크로 걸러내고, 나머지는 사람이 눈으로 확인)
# ------------------------------------------------------------------
def validate_format(summary_text: str) -> list[str]:
    lines = [l for l in summary_text.strip().split("\n") if l.strip()]
    issues = []
    if len(lines) != 4:
        issues.append(f"줄 수 불일치: {len(lines)}줄 (4줄이어야 함)")
    return issues


# ------------------------------------------------------------------
# 3) 요청 1건 실행 — 실패해도 예외를 던지지 않고 결과 dict로 기록
#    (동시 실행 중 하나 실패했다고 전체가 죽으면 스모크 테스트 의미가 없음)
# ------------------------------------------------------------------
def summarize_one(doc: dict) -> dict:
    base = {
        "document_id": doc.get("document_id"),
        "parsing_quality": doc.get("parsing_quality"),
        "raw_text_len": len(doc.get("raw_text", "")),
    }
    prompt = PROMPT_TEMPLATE.format(raw_text=doc.get("raw_text", ""))
    start = time.time()
    try:
        resp = client.with_options(max_retries=MAX_RETRIES_PER_REQUEST).messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - start
        summary = "".join(b.text for b in resp.content if b.type == "text")
        return {
            **base,
            "summary": summary,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "elapsed_sec": round(elapsed, 2),
            "format_issues": validate_format(summary),
            "error": None,
        }
    except anthropic.APIStatusError as e:
        return {**base, "error": f"{type(e).__name__}: {e.status_code} {e.message}"}
    except anthropic.APIConnectionError as e:
        return {**base, "error": f"APIConnectionError: {e}"}


# ------------------------------------------------------------------
# 4) 동시 실행
# ------------------------------------------------------------------
def run_smoke_test(samples: list[dict]) -> list[dict]:
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        futures = {executor.submit(summarize_one, doc): doc for doc in samples}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            status = "OK" if not result.get("error") else f"FAIL: {result['error']}"
            print(f"[{i}/{len(samples)}] {result.get('document_id')} ({result.get('parsing_quality')}) — {status}")
            results.append(result)
    return results


# ------------------------------------------------------------------
# 5) 결과 저장 + 요약 통계 + 8만 건 기준 비용/시간 추정
# ------------------------------------------------------------------
def save_results(results: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n결과 저장: {path}")
    print("-> summary 필드를 직접 눈으로 열어보고 확인할 것: 정확히 4줄인지, "
          "처리결과 미기재 처리가 맞는지, partial/fallback 문서에서 이상한 내용을 지어내지 않는지")


def print_report(results: list[dict]) -> None:
    ok = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]
    format_bad = [r for r in ok if r.get("format_issues")]

    print("\n" + "=" * 60)
    print(f"실행 시각: {datetime.now().isoformat(timespec='seconds')}")
    print(f"전체 {len(results)}건 | 성공 {len(ok)}건 | 실패 {len(failed)}건 "
          f"(실패율 {len(failed) / len(results) * 100:.1f}%)")

    if failed:
        print("\n[실패 목록] — 재시도 로직이 흡수 못한 케이스, 원인 확인 필요")
        for r in failed:
            print(f"  - {r['document_id']} ({r['parsing_quality']}): {r['error']}")

    if format_bad:
        print(f"\n[4줄 포맷 위반] {len(format_bad)}건 — 프롬프트 조정 필요할 수 있음")
        for r in format_bad:
            print(f"  - {r['document_id']} ({r['parsing_quality']}): {r['format_issues']}")

    if not ok:
        print("\n성공한 요청이 없어 비용/시간 추정 불가")
        return

    avg_in = sum(r["input_tokens"] for r in ok) / len(ok)
    avg_out = sum(r["output_tokens"] for r in ok) / len(ok)
    avg_time = sum(r["elapsed_sec"] for r in ok) / len(ok)

    cost_per_doc = (avg_in / 1_000_000) * PRICE_PER_M_INPUT + (avg_out / 1_000_000) * PRICE_PER_M_OUTPUT
    total_cost = cost_per_doc * FULL_BATCH_SIZE
    total_time_serial_hr = (avg_time * FULL_BATCH_SIZE) / 3600
    total_time_concurrent_hr = total_time_serial_hr / MAX_CONCURRENCY

    print(f"\n--- 8만 건 본 배치 추정치 ({MODEL} 기준) ---")
    print(f"건당 평균: 입력 {avg_in:.0f}토큰 / 출력 {avg_out:.0f}토큰 / {avg_time:.2f}초")
    print(f"예상 총 비용: ${total_cost:.2f}")
    print(f"예상 총 소요시간 (동시 {MAX_CONCURRENCY}건 기준, 대략치): 약 {total_time_concurrent_hr:.1f}시간")
    print("주의: 이 추정치는 표본 30~35건 기준 — 본 배치는 이 스크립트에 "
          "resume/checkpoint 로직(embedding 스크립트처럼)을 추가해서 돌릴 것")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY 환경변수를 설정하거나 `ant auth login`을 먼저 실행하세요")

    samples = load_and_sample(INPUT_PATH)
    print(f"스모크 테스트 대상: {len(samples)}건 (parsing_quality별 층화 추출, extraction_failed 제외)")

    results = run_smoke_test(samples)
    save_results(results, OUTPUT_PATH)
    print_report(results)
