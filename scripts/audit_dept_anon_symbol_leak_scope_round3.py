# ------------------------------------------------------------------
# 부서/기관명 익명화 심볼 누출 — 3차: 합집합 규모 확정 (2026-08-27, 읽기 전용, DB만)
# ------------------------------------------------------------------
# 1차(audit_dept_anon_symbol_leak_scope.py)에서 카드무늬 7종(♣♧▩▧♥♠⊗) 영향 8,314건
# (12.27%)을 확인했고, 2차(_round2.py)에서 컨텍스트 샘플 전수 확인으로 추가 35종
# (기하학무늬/블록기호 33종 + ♥♠의 outline 짝 ♡♤)을 마스킹으로 확정했음(회신 결과
# 참고, 2026-08-27 STATUS.md 9차). 이번 3차는 그 42종의 **합집합** 기준 전체 영향
# 규모(중복 제거)를 확정하는 마지막 단계 — 개별 문자 최대치(◉ 5,084건)보다 훨씬 클
# 것으로 예상되고, 이 숫자가 최종 "규모조사" 결론이 됨. 이후 대응(수정 스크립트) 여부는
# 이 숫자를 보고 판단.
# 아무것도 수정하지 않음 — 규모 확정 전까지는 수정 스크립트를 만들지 않는 게 이 프로젝트 관례.
# ------------------------------------------------------------------
import os
import re
from collections import Counter

import psycopg2

# 1차 카드무늬 7종
CURATED_ROUND1 = "♣♧▩▧♥♠⊗"
# 2차 A그룹(기하학무늬/블록기호) 33종 — 컨텍스트 전수 마스킹 확정
CONFIRMED_ROUND2_A = "◉▤◐◁▷◍■▥▨◎▢◈◒☆★●▣◌◧◊▒◕◫◑▶◩◷◨◰⊠◪◘▦"
# 2차 B그룹(♥♠의 outline 짝) 2종 — 마스킹 확정
CONFIRMED_ROUND2_B = "♡♤"

ALL_CONFIRMED = CURATED_ROUND1 + CONFIRMED_ROUND2_A + CONFIRMED_ROUND2_B
assert len(set(ALL_CONFIRMED)) == len(ALL_CONFIRMED), "후보 문자 목록에 중복이 있음"
print(f"확정된 마스킹 문자 {len(ALL_CONFIRMED)}종으로 합집합 규모 계산\n")

UNION_RE = re.compile("[" + re.escape(ALL_CONFIRMED) + "]")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '300s'")
    cur.execute("SELECT id, institution, year, source_file, raw_text FROM documents")
    rows = cur.fetchall()
conn.close()

total_docs = len(rows)
print(f"전체 문서 {total_docs}건 조사 중...\n")

affected_doc_ids = set()
institution_count = Counter()
year_count = Counter()
mixed_with_placeholder = 0
chars_per_doc_dist = Counter()  # 한 문서 안에 확정 문자가 몇 종류나 섞여 나오는지

for doc_id, institution, year, source_file, raw_text in rows:
    if not raw_text:
        continue
    found_chars = set(UNION_RE.findall(raw_text))
    if not found_chars:
        continue
    affected_doc_ids.add(doc_id)
    institution_count[institution] += 1
    year_count[year] += 1
    chars_per_doc_dist[len(found_chars)] += 1
    if "[부서]" in raw_text:
        mixed_with_placeholder += 1

print("=== 합집합 규모 (최종) ===")
print(
    f"영향받은 문서: {len(affected_doc_ids)}건 / {total_docs}건"
    f" ({len(affected_doc_ids) / total_docs:.2%})"
)
if affected_doc_ids:
    print(
        f"  같은 문서 안에 '[부서]' placeholder도 같이 있는 경우: {mixed_with_placeholder}건"
        f" ({mixed_with_placeholder / len(affected_doc_ids):.1%}) — 부분 처리 신호(1차와 같은 지표)"
    )

print("\n한 문서 안에 섞여 나오는 확정 문자 '종류 수' 분포(1종만 새는 문서 vs 여러 종 혼합):")
for k in sorted(chars_per_doc_dist):
    print(f"  {k}종: {chars_per_doc_dist[k]}건")

print("\n기관별 영향 문서 수 (상위 15):")
for inst, cnt in institution_count.most_common(15):
    print(f"  {inst}: {cnt}건")

print("\n연도별 영향 문서 수:")
for yr, cnt in sorted(year_count.items(), key=lambda x: (x[0] is None, x[0])):
    print(f"  {yr}: {cnt}건")

print("\n확인 포인트:")
print("  - 이 숫자가 '규모조사' 최종 결론. 대응(수정) 여부·범위를 이 규모로 판단할 것.")
print("  - 대응한다면 두 갈래 문제를 구분해서 접근: ① 아직 [부서]로도 전혀 안 바뀌고")
print("    원본 심볼이 그대로 새는 경우(이 42종 자체가 대상) ② 이미 [부서]로 바뀌었지만")
print("    실제로는 부서가 아닌 다른 개체(기관 자기이름·직위·숫자 등)를 가린 경우")
print("    (2026-08-27 STATUS.md 9차, 한국문화예술위원회 사례) — 서로 다른 수정이 필요함")
