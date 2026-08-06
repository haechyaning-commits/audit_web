# ------------------------------------------------------------------
# 요약 배치 스모크 테스트 스크립트
# ------------------------------------------------------------------
# 목적: 8만 건 전체 요약 배치(OpenAI 저비용 모델)를 돌리기 전에,
#       30~35건 샘플로 아래를 먼저 검증한다.
#   1) 프롬프트가 실제로 "정확히 4줄" 포맷을 지키는지
#   2) parsing_quality(partial/fallback)별로 이상한 요약(할루시네이션 등)이 없는지
#   3) 재시도/백오프 로직이 실제로 동작하는지
#   4) 8만 건 기준 실제 비용/소요시간을 실측치로 추정
#
# 실행 전 준비:
#   pip install openai
#   export OPENAI_API_KEY=...
#   INPUT_PATH는 documents_final.jsonl 기준으로 맞춰져 있음
#     (필드: id, institution, year, raw_text, parsing_quality —
#      중복/분할 문서 정리 + overview 레코드 제외까지 끝난 최종 파일)
#
# 비용 없이 먼저 돌려보기 (DRY_RUN):
#   DRY_RUN=1 python summary_smoke_test.py
#   -> 실제 API를 호출하지 않고 가짜 요약을 채워 넣어 파이프라인만 검증한다
#      (샘플링/동시실행/재시도 처리/포맷 체크/파일 저장/비용 계산 로직).
#      API 키 없이도 실행 가능. 단, 실제 요약 품질·토큰 수·응답시간은
#      검증되지 않으므로 최종 확인은 DRY_RUN 없이 최소 몇 건이라도 돌려봐야 한다.
# ------------------------------------------------------------------

import json
import os
import random
import time
import concurrent.futures
from datetime import datetime

import openai

# ------------------------------------------------------------------
# 0) 설정
# ------------------------------------------------------------------
# [수정] Anthropic Claude Haiku -> OpenAI로 교체. 모델명/가격은 실행 시점에
# 반드시 재확인할 것 (OpenAI 라인업/가격은 자주 바뀌고, 여기 적힌 값은
# 이 스크립트를 작성한 시점 기준 참고치일 뿐임).
MODEL = "gpt-4o-mini"  # 8만 건 1회성 배치라 저비용 모델로 충분 — 배치 직전 더 저렴/신모델 있는지 확인 권장
INPUT_PATH = "/content/drive/MyDrive/audit_project/documents_final.jsonl"  # Colab 기준 경로, 필요시 수정
OUTPUT_PATH = "smoke_test_results.jsonl"

# parsing_quality별 표본 크기 — overview/extraction_failed는 documents_final.jsonl 생성 시 이미 제외됨
SAMPLE_SIZE_PER_BUCKET = {
    "standard": 20,
    "partial": 10,
    "fallback": 5,
}

MAX_CONCURRENCY = 5           # 동시 요청 수 제한 (본 배치 때 이 값 자체를 튜닝하는 게 목적 중 하나)
MAX_RETRIES_PER_REQUEST = 4   # SDK가 429/5xx/네트워크 에러에 자동으로 exponential backoff 재시도
FULL_BATCH_SIZE = 72_913      # documents_final.jsonl 확정 건수 기준 (기존 "8만 건" 추정치 대신 실측치)

# gpt-4o-mini 가격: $0.15 / 1M input, $0.60 / 1M output (참고치 — OpenAI 가격 정책은
# 자주 바뀌므로 본 배치 실행 직전 platform.openai.com/pricing에서 반드시 재확인)
PRICE_PER_M_INPUT = 0.15
PRICE_PER_M_OUTPUT = 0.60

# DRY_RUN=1이면 실제 API를 전혀 호출하지 않음 → 비용 0원. 파이프라인 로직만 검증할 때 사용.
DRY_RUN = os.environ.get("DRY_RUN") == "1"

# dry-run에서는 API 키가 없어도 되므로 client를 필요할 때만 생성
client = None if DRY_RUN else openai.OpenAI()  # OPENAI_API_KEY 환경변수 사용

# [수정] 1~3줄에도 4줄과 동일한 탈출구를 추가함 — 원래는 4줄(처리결과)만
# "없으면 이렇게 표시해라"가 있었고 1~3줄은 무조건 채우게 되어 있었음.
# 그러면 원문에 원인/조치가 불명확한 문서(특히 partial/fallback 등급)에서
# 모델이 없는 내용을 지어낼 위험이 있음.
# 다만 탈출구 기준을 "불분명하면"처럼 느슨하게 주면 반대로 있는 내용도
# 귀찮아서 미기재로 때우는 문제가 생길 수 있어서, "원문에 관련 내용이
# 전혀 없을 때만"으로 문턱을 높여서 균형을 잡음. 이게 실제로 잘 맞는지는
# 프롬프트만으로 보장 못 하므로, 아래 print_report()의 미기재 비율 집계로
# 스모크 테스트 결과를 보면서 확인해야 함.
PROMPT_TEMPLATE = """아래 감사 사례 원문을 읽고 정확히 4줄로 요약해라.
1줄: 지적사항 한 문장 (원문에 관련 내용이 전혀 없을 때만 "지적사항 불분명"으로 표시)
2줄: 원인/경위 한 문장 (원문에 관련 내용이 전혀 없을 때만 "원인 미기재"로 표시)
3줄: 조치사항 한 문장 (원문에 관련 내용이 전혀 없을 때만 "조치사항 미기재"로 표시)
4줄: 처리결과 한 문장 (원문에 관련 내용이 전혀 없을 때만 "처리결과 미기재"로 표시)
원문:
{raw_text}"""

# 위 탈출구 문구들 — print_report()에서 줄 번호별로 이 표현이 얼마나
# 등장했는지 세어서, "모델이 게으르게 답하고 있는지" 신호로 사용
FALLBACK_PHRASES = ["지적사항 불분명", "원인 미기재", "조치사항 미기재", "처리결과 미기재"]


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
            if q in ("extraction_failed", "overview"):
                continue  # 이미 documents_final.jsonl 생성 시 제외됐어야 하지만 방어적으로 한 번 더 체크
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
# 2-1) DRY_RUN용 가짜 응답 — 실제 API를 타지 않고 파이프라인만 검증
#      (토큰 수는 원문 길이에서 대략 흉내만 낸 값이라 실제 비용 추정치로 쓰면 안 됨)
# ------------------------------------------------------------------
def fake_summarize_one(doc: dict, base: dict) -> dict:
    time.sleep(0.05)  # 네트워크 왕복을 흉내내는 정도 (동시성 로직 테스트용)
    fake_summary = (
        "[DRY_RUN] 지적사항 예시 문장\n"
        "[DRY_RUN] 원인/경위 예시 문장\n"
        "[DRY_RUN] 조치사항 예시 문장\n"
        "[DRY_RUN] 처리결과 미기재"
    )
    approx_in = max(1, base["raw_text_len"] // 2)  # 대략적인 근사치일 뿐, 실측 아님
    return {
        **base,
        "summary": fake_summary,
        "input_tokens": approx_in,
        "output_tokens": 40,
        "elapsed_sec": 0.05,
        "format_issues": validate_format(fake_summary),
        "error": None,
    }


# ------------------------------------------------------------------
# 3) 요청 1건 실행 — 실패해도 예외를 던지지 않고 결과 dict로 기록
#    (동시 실행 중 하나 실패했다고 전체가 죽으면 스모크 테스트 의미가 없음)
# ------------------------------------------------------------------
def summarize_one(doc: dict) -> dict:
    base = {
        "document_id": doc.get("id"),  # documents_final.jsonl은 id 필드 사용 (document_id 아님)
        "parsing_quality": doc.get("parsing_quality"),
        "raw_text_len": len(doc.get("raw_text", "")),
    }

    if DRY_RUN:
        return fake_summarize_one(doc, base)

    prompt = PROMPT_TEMPLATE.format(raw_text=doc.get("raw_text", ""))
    start = time.time()
    try:
        resp = client.with_options(max_retries=MAX_RETRIES_PER_REQUEST).chat.completions.create(
            model=MODEL,
            max_completion_tokens=512,  # max_tokens는 OpenAI SDK에서 deprecated, 이걸로 대체됨
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - start
        summary = resp.choices[0].message.content or ""
        return {
            **base,
            "summary": summary,
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
            "elapsed_sec": round(elapsed, 2),
            "format_issues": validate_format(summary),
            "error": None,
        }
    except openai.APIStatusError as e:
        return {**base, "error": f"{type(e).__name__}: {e.status_code} {e.message}"}
    except openai.APIConnectionError as e:
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
          "미기재/불분명 처리가 맞는지, partial/fallback 문서에서 이상한 내용을 지어내지 않는지 "
          "(아래 '줄별 미기재/불분명 사용 비율' 리포트로 어느 등급을 우선 확인할지 가늠 가능)")


# ------------------------------------------------------------------
# 5-1) 탈출구 문구("불분명"/"미기재") 남용 여부 체크
#      — 1~3줄에 탈출구를 열어주면서 생긴 반대쪽 위험(있는 정보도
#        귀찮아서 미기재로 때우는 것)을 35건 다 눈으로 읽지 않고도
#        parsing_quality별 비율로 미리 감지하기 위한 자동 집계
# ------------------------------------------------------------------
def print_fallback_usage_report(results: list[dict]) -> None:
    ok = [r for r in results if not r.get("error") and not r.get("format_issues")]
    if not ok:
        return

    by_quality: dict[str, list[dict]] = {}
    for r in ok:
        by_quality.setdefault(r["parsing_quality"], []).append(r)

    line_labels = ["1줄(지적사항)", "2줄(원인)", "3줄(조치사항)", "4줄(처리결과)"]

    print("\n--- 줄별 '미기재/불분명' 사용 비율 (parsing_quality별) ---")
    print("standard 등급인데 비율이 높으면 모델이 있는 정보도 귀찮아서 미기재로 때우고 있다는 신호.")
    print("partial/fallback 등급에서 비율이 높은 건 원문 자체가 부실해서 그런 것일 수 있어 정상 범위로 볼 수 있음.")
    for quality in sorted(by_quality):
        items = by_quality[quality]
        counts = [0, 0, 0, 0]
        for r in items:
            lines = [l for l in r["summary"].strip().split("\n") if l.strip()]
            for i, phrase in enumerate(FALLBACK_PHRASES):
                if i < len(lines) and phrase in lines[i]:
                    counts[i] += 1
        n = len(items)
        rates = " / ".join(f"{label} {c}건({c / n * 100:.0f}%)" for label, c in zip(line_labels, counts))
        print(f"  [{quality}, {n}건] {rates}")


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

    print_fallback_usage_report(results)

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
    if DRY_RUN:
        print("[DRY_RUN] 아래 수치는 실제 토큰이 아니라 근사치이므로 참고만 할 것 — "
              "실제 비용 추정은 DRY_RUN 없이 다시 돌려야 함")
    print(f"건당 평균: 입력 {avg_in:.0f}토큰 / 출력 {avg_out:.0f}토큰 / {avg_time:.2f}초")
    print(f"예상 총 비용: ${total_cost:.2f}")
    print(f"예상 총 소요시간 (동시 {MAX_CONCURRENCY}건 기준, 대략치): 약 {total_time_concurrent_hr:.1f}시간")
    print("주의: 이 추정치는 표본 30~35건 기준 — 본 배치는 이 스크립트에 "
          "resume/checkpoint 로직(embedding 스크립트처럼)을 추가해서 돌릴 것")


if __name__ == "__main__":
    if DRY_RUN:
        print("[DRY_RUN 모드] 실제 API 호출 없음 — 비용 0원, 파이프라인 로직만 검증합니다.\n")
    elif not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY 환경변수를 설정하세요")

    samples = load_and_sample(INPUT_PATH)
    print(f"스모크 테스트 대상: {len(samples)}건 (parsing_quality별 층화 추출, extraction_failed 제외)")

    results = run_smoke_test(samples)
    save_results(results, OUTPUT_PATH)
    print_report(results)
