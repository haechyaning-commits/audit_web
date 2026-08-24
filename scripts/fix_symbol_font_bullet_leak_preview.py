# ------------------------------------------------------------------
# fix_symbol_font_bullet_leak.py 반영 전 확장 샘플 확인용 (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: DRY_RUN 결과(documents 249건/chunks 446건, 5개 기관)를 확인했는데,
# 반영 전 특히 m/q 쪽 샘플을 더 보고 싶다는 요청 — fix_symbol_font_bullet_leak.py
# 는 전체 기관 통틀어 5건만 찍어서 한수원(v)에 쏠려 있었음(리스트 앞쪽이라).
# 이 스크립트는 fix_symbol_font_bullet_leak.py와 동일한 로직으로 대상을 찾되,
# (기관, 글자) 조합별로 골고루 샘플을 뽑아서 출력. 아무것도 수정하지 않음
# (읽기 전용, DB 변경 없음) — fix_symbol_font_bullet_leak.py 자체를 import해서
# 같은 규칙/정규식을 그대로 재사용(로직 중복 방지).
# ------------------------------------------------------------------
import os

import psycopg2

# fix_symbol_font_bullet_leak.py를 같은 디렉터리에서 불러옴 (Colab에서 같은 폴더에
# 두고 실행할 것 — 없으면 아래 import가 실패함)
from fix_symbol_font_bullet_leak import (
    CONFIRMED_BULLET_RULES,
    RULES_BY_INSTITUTION,
    _BULLET_RES,
    fix_bullet_leak,
)

SAMPLES_PER_RULE = 4

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

institutions = list(RULES_BY_INSTITUTION.keys())
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute(
        "SELECT id, institution, raw_text FROM documents WHERE institution = ANY(%s)",
        (institutions,),
    )
    doc_rows = cur.fetchall()
conn.close()

# (기관, 글자)별로 수정 대상 문서를 그룹핑
by_rule = {rule: [] for rule in CONFIRMED_BULLET_RULES}
for doc_id, institution, raw_text in doc_rows:
    fixed = fix_bullet_leak(raw_text, institution)
    if fixed == raw_text:
        continue
    for letter in RULES_BY_INSTITUTION[institution]:
        if _BULLET_RES[letter].search(raw_text):
            by_rule[(institution, letter)].append((doc_id, raw_text))

for (institution, letter), docs in by_rule.items():
    print(f"\n========== ({institution}, '{letter}') — 수정 대상 {len(docs)}건 ==========")
    for doc_id, raw_text in docs[:SAMPLES_PER_RULE]:
        matches = list(_BULLET_RES[letter].finditer(raw_text))
        print(f"  [{doc_id}] 이 글자 {len(matches)}회 출현, 앞 3개 문맥(전 -> 후):")
        for m in matches[:3]:
            s, e = max(0, m.start() - 25), min(len(raw_text), m.end() + 35)
            before_snip = raw_text[s:e].replace("\n", "\\n")
            after_snip = (raw_text[s:m.start()] + raw_text[m.end():e]).replace("\n", "\\n")
            print(f"     전: ...{before_snip}...")
            print(f"     후: ...{after_snip}...")

print("\n확인 포인트: '후' 쪽에서 불릿 글자만 깔끔히 사라지고 나머지 문장은 그대로인지,"
      " 이중공백/단어 일부 삭제 같은 부작용이 없는지 눈으로 확인.")
