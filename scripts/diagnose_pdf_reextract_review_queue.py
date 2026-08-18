# ------------------------------------------------------------------
# pdf_reextract_manual_review.jsonl 진단 (Colab 실행용, 읽기 전용)
# ------------------------------------------------------------------
# rechunk_reembed_pdf_column_fix.py의 DRY_RUN 실행 결과, 수동검토 큐(1,463건,
# 전체 2,137건의 68.5%)가 자동반영(674건)보다 훨씬 큰 것을 보고 원인 파악을
# 위해 작성. DRY_RUN=False로 넘어가기 전에 이 탈락률이 "알려진 한계"(표 문서
# 오탐, 선행 상용구) 때문인지, 아니면 놓친 버그(예: 마스킹 기호 정규화 누락)
# 때문인지 구분하는 게 목적 — 아무것도 DB에 쓰지 않음.
# ------------------------------------------------------------------

import json
import statistics
from collections import Counter

REVIEW_QUEUE_PATH = "/content/drive/MyDrive/audit_project/pdf_reextract_manual_review.jsonl"

rows = []
with open(REVIEW_QUEUE_PATH, encoding="utf-8") as f:
    for line in f:
        rows.append(json.loads(line))

errors = [r for r in rows if "error" in r]
low_sim = [r for r in rows if "similarity" in r]

print(f"전체 수동검토 큐: {len(rows)}건")
print(f"  다운로드/파싱 에러: {len(errors)}건")
print(f"  유사도 미달(계산은 됐지만 임계값 밑): {len(low_sim)}건")

if errors:
    print("\n--- 에러 메시지 상위 10개 (패턴별) ---")
    # 에러 메시지가 URL/상세 내용까지 포함해 제각각일 수 있어서 앞 60자로 뭉뚱그려 카운트
    err_patterns = Counter(e["error"][:60] for e in errors)
    for msg, cnt in err_patterns.most_common(10):
        print(f"  {cnt:4d}건 | {msg}")

if low_sim:
    sims = [r["similarity"] for r in low_sim]
    print(f"\n--- 유사도 분포 (n={len(sims)}) ---")
    print(f"  평균 {statistics.mean(sims):.3f} / 중앙값 {statistics.median(sims):.3f} / 최소 {min(sims):.3f} / 최대 {max(sims):.3f}")
    buckets = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9)]
    for lo, hi in buckets:
        cnt = sum(1 for s in sims if lo <= s < hi)
        print(f"  [{lo:.1f}, {hi:.1f}): {cnt}건")

    # new_len/old_len 비율 — 1보다 많이 크면 재추출 결과가 원문보다 길어짐(선행
    # 상용구 등 원문엔 없는 내용이 섞여 들어갔을 가능성), 1보다 많이 작으면
    # 내용 손실(표 등) 가능성.
    ratios = [r["new_len"] / r["old_len"] for r in low_sim if r.get("old_len")]
    if ratios:
        print(f"\n--- new_len/old_len 비율 (재추출/원문 글자수) ---")
        print(f"  평균 {statistics.mean(ratios):.3f} / 중앙값 {statistics.median(ratios):.3f}")
        print(f"  1.1 이상(재추출이 원문보다 10%+ 김 — 선행 상용구 등 의심): "
              f"{sum(1 for r in ratios if r >= 1.1)}건")
        print(f"  0.9 이하(재추출이 원문보다 10%+ 짧음 — 내용 손실 의심): "
              f"{sum(1 for r in ratios if r <= 0.9)}건")

    print("\n--- 기관별 상위 10 (수동검토 큐에 많이 걸린 기관) ---")
    inst_counter = Counter(r.get("institution", "?") for r in low_sim)
    for inst, cnt in inst_counter.most_common(10):
        print(f"  {cnt:4d}건 | {inst}")

    print("\n--- 유사도 구간별 샘플 2건씩(id만, 상세페이지에서 직접 대조해볼 것) ---")
    for lo, hi in buckets + [(0.9, 1.01)]:
        band = [r for r in low_sim if lo <= r["similarity"] < hi]
        if band:
            sample = band[:2]
            ids = ", ".join(f"{r['id']}(sim={r['similarity']})" for r in sample)
            print(f"  [{lo:.1f}, {hi:.1f}): {ids}")
