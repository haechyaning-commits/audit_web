# ------------------------------------------------------------------
# fix_symbol_font_bullet_leak.py 반영 전 안전장치 — 숫자 바로 뒤 매칭만 별도 확인
# (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: preview 스크립트 샘플은 전부 깔끔했지만, 문서당 매칭이 최대 83회까지
# 나오는 경우가 있어(한국수자원조사기술원) 표본 3개만으론 안심할 수 없음.
# 현재 정규식 (?<![A-Za-z])X(?![A-Za-z])는 "앞뒤가 알파벳만 아니면" 매칭이라
# 상당히 느슨함 — 특히 X가 단위 기호로 실제 쓰이는 경우(m=미터, v=볼트 등)
# **숫자 바로 뒤**에 올 수 있음(예: "폭 3m", "220v"). 이런 경우는 진짜 불릿이
# 아니라 지우면 안 되는 실제 내용.
#
# 지금까지 확인된 진짜 불릿은 전부 줄바꿈 직후나 항목기호(원문자 마스킹 등)
# 바로 뒤였음 — 숫자 바로 뒤에 오는 매칭이 있다면 그게 진짜 단위 표기인지
# 육안으로 확인해야 함. 이 스크립트는 매칭 전체를 훑어서 "직전 문자가
# 숫자인 것"만 따로 추려서 문맥과 함께 보여줌. 아무것도 수정하지 않음
# (읽기 전용, DB 변경 없음).
# ------------------------------------------------------------------
import os

import psycopg2

from fix_symbol_font_bullet_leak import RULES_BY_INSTITUTION, _BULLET_RES

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

total_matches = 0
digit_preceded = []  # (doc_id, institution, letter, context)
newline_preceded = 0
other_preceded = 0

for doc_id, institution, raw_text in doc_rows:
    for letter in RULES_BY_INSTITUTION.get(institution, []):
        for m in _BULLET_RES[letter].finditer(raw_text):
            total_matches += 1
            prev_char = raw_text[m.start() - 1] if m.start() > 0 else ""
            if prev_char.isdigit():
                s, e = max(0, m.start() - 30), min(len(raw_text), m.end() + 30)
                digit_preceded.append(
                    (doc_id, institution, letter, raw_text[s:e].replace("\n", "\\n"))
                )
            elif prev_char in ("\n", ""):
                newline_preceded += 1
            else:
                other_preceded += 1

print(f"전체 매칭 {total_matches}건")
print(f"  줄바꿈/문서 시작 직후: {newline_preceded}건")
print(f"  기타(공백/한글/기호 등) 직후: {other_preceded}건")
print(f"  **숫자 직후 (단위 표기 위험 — 육안 확인 필요)**: {len(digit_preceded)}건")

if digit_preceded:
    print("\n숫자 직후 매칭 전체 목록:")
    for doc_id, institution, letter, ctx in digit_preceded:
        print(f"  [{doc_id}] {institution} '{letter}': ...{ctx}...")
else:
    print("\n숫자 바로 뒤에 오는 매칭 없음 — 단위 표기 오탐 위험 없음.")

print("\n확인 포인트: 숫자 직후 목록이 비어 있으면 안심하고 DRY_RUN=False로 진행 가능."
      " 목록에 있는 게 진짜 '3m'(미터) 같은 단위 표기라면, fix_symbol_font_bullet_leak.py의"
      " 정규식에 '숫자 바로 뒤는 제외' 조건을 추가해야 함.")
