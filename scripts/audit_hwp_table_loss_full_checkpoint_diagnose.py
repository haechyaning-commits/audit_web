# ------------------------------------------------------------------
# hwp_table_loss_full_checkpoint.jsonl 결과 재진단 (2026-08-25, 읽기 전용)
# ------------------------------------------------------------------
# 배경: audit_hwp_table_loss_full_population.py를 hwp5txt 정상화(진단
# 스크립트로 확인 완료) 이후 재실행했는데도 "영향받음 0건(0.0%)"이 또
# 나옴 — 8/24(17차) 사고와 똑같은 숫자. 그런데 그 스크립트의 마지막
# "=== 결과 ===" 출력엔 에러 총계가 안 찍히게 돼 있어서(진행 중 20건마다만
# 표시), 이번에도 "진짜 0건"인지 "또 대량 에러로 새는 중"인지 최종 요약만
# 봐서는 구분이 안 됨. 이 스크립트는 체크포인트 파일(JSONL, 매 건마다
# append됨)을 직접 읽어서 에러/판정/표 마커 분포를 다시 집계함 — DB나
# hwp5txt 재실행 필요 없이 몇 초면 끝남.
# ------------------------------------------------------------------

import json
from collections import Counter

CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/hwp_table_loss_full_checkpoint.jsonl"

records = []
with open(CHECKPOINT_PATH, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

print(f"총 레코드: {len(records)}건")

errors = [r for r in records if r.get("error")]
ok = [r for r in records if not r.get("error")]
print(f"에러: {len(errors)}건 ({len(errors) / len(records) * 100:.1f}%)")
print(f"정상 처리: {len(ok)}건")

if errors:
    print("\n에러 메시지 상위 10종 (앞 80자 기준으로 그룹핑):")
    err_msg_counter = Counter((r["error"] or "")[:80] for r in errors)
    for msg, cnt in err_msg_counter.most_common(10):
        print(f"  {cnt:5d}건 | {msg}")

if ok:
    print("\nn_table_markers 분포 (정상 처리된 건만):")
    n_tables_counter = Counter(r.get("n_table_markers", "?") for r in ok)
    for n, cnt in sorted(n_tables_counter.items(), key=lambda kv: str(kv[0])):
        print(f"  {n}: {cnt}건")

    print("\ndb_has_table_trace 분포 (정상 처리된 건만):")
    trace_counter = Counter(r.get("db_has_table_trace") for r in ok)
    for v, cnt in trace_counter.items():
        print(f"  {v}: {cnt}건")

    affected = [r for r in ok if r.get("affected")]
    print(f"\naffected=True: {len(affected)}건")

print("\n=== 해석 가이드 ===")
if len(errors) > len(records) * 0.5:
    print(
        "❌ 에러 비율이 절반 넘음 — hwp5txt 진단 스크립트는 1건짜리 테스트라 "
        "통과했지만, 대량 병렬 처리(48 워커) 상황에서 다른 문제(메모리, 파일 "
        "핸들, 레이트리밋 등)로 다시 새고 있을 가능성. 위 '에러 메시지 상위 "
        "10종'에서 실제 원인 확인 필요 — 특히 jsdelivr 403(레이트리밋, 무관한 "
        "소수여야 정상)인지, hwp5txt 자체 에러(returncode != 0, 심각)인지 구분할 것."
    )
elif ok and all(r.get("n_table_markers", 0) == 0 for r in ok):
    print(
        "❌ 정상 처리된 건 전부가 '<표>' 마커 0개 — 8/24(17차)와 완전히 같은 "
        "증상. hwp5txt 단일 파일 테스트는 통과했는데 이 결과라면, 병렬 실행 "
        "환경에서만 재현되는 문제(예: 워커별 임시 파일 경합, 서브프로세스 "
        "리소스 고갈)일 가능성 — audit_hwp5txt_env_check.py를 동시에 여러 개 "
        "(스레드로) 돌려서 재현되는지 먼저 확인해볼 것."
    )
else:
    print(
        "✅ n_table_markers 분포에 0 아닌 값이 섞여 있으면 정상 — 그 경우 "
        "'영향받음 0건'이 실제로 맞을 수도 있음(이미 8/19에 표본 기반으로 "
        "1,559건 반영해뒀으므로, 남은 모집단에서 우연히 0건이 나오는 것도 "
        "이론상 불가능하진 않음 — 다만 8/18 표본 영향률(50.5%)과 크게 어긋나므로 "
        "affected 판정 로직 자체를 한 번 더 의심해볼 것)."
    )
