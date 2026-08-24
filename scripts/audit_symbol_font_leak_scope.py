# ------------------------------------------------------------------
# Wingdings류 심볼폰트 불릿 누출 — 전체 범위 조사 (2026-08-24, 읽기 전용, DB만)
# ------------------------------------------------------------------
# 배경: audit_v_bullet_font_check.py로 'v' 불릿이 한국수력원자력 PDF에서
# Wingdings-Regular 폰트로 확정 확인됨(문맥: "v (관련부서의견)", "v 사장은..."
# 등 — 감사보고서 표준 문구 바로 앞자리). 그런데 지금까지 잡은 건 raw_text에서
# 'v' 하나만 정규식으로 훑은 결과라, 같은 Wingdings류 폰트가 다른 불릿 스타일에서
# 다른 알파벳(예: l, o, u, !, ...)으로도 새고 있을 가능성이 아직 미확인.
#
# 이 스크립트는 PDF를 다운로드하지 않고(빠름, 전체 67,751건에 바로 돌릴 수 있음)
# DB의 raw_text만으로 범위를 넓혀 본다: "v" 사례로 이미 검증된 방법 — 감사보고서
# 표준 문구(의견/지적/조치 관련 boilerplate) 바로 앞자리 문자를 전수조사 —
# 를 앵커 문구를 여러 개로 늘리고, 대상도 한수원이 아니라 **전체 기관**으로
# 넓혀서 돌린다. 목적은 "v 말고 다른 글자도 같은 자리에서 새고 있는가"와
# "이 문제가 한수원만의 문제인가, 여러 기관이 공유하는 PDF 양식의 문제인가"를
# 확인하는 것. 아무것도 수정하지 않음.
#
# 주의: 앵커 바로 앞 글자가 항상 불릿이라는 보장은 없음(문장이 그 자리에서
# 끝났을 수도 있음) — 그래서 "이 글자가 A-Z/a-z 알파벳 단독 1글자인가"만 따로
# 집계하고, 실제 확정은 audit_v_bullet_font_check.py처럼 원본 PDF 폰트 확인이
# 필요함(이 스크립트는 그 다음 단계에서 뭘 확인해야 할지 후보를 추리는 용도).
# ------------------------------------------------------------------
import os
import re
from collections import Counter, defaultdict

import psycopg2

# 감사보고서에서 흔히 쓰이는 boilerplate 앵커 문구들 — 'v' 검증에 쓴
# "(관련부서의견)"/"(관계기관의견)" 외에 자주 보이는 것들을 추가
ANCHOR_PHRASES = [
    "관련부서의견", "관계기관의견", "관련직원의견", "관련기관의견",
    "지적요지", "조치할사항", "판단기준", "감사결과", "처리결과",
]
# 문구 사이에 낀 공백은 무시하고 매칭(원문에 "지 적 요 지"처럼 띄어써진 경우 대응)
def _spaced(phrase):
    return r"\s*".join(re.escape(ch) for ch in phrase)

ANCHOR_RE = re.compile(
    r"(\S)\s*(?:\(" + "|".join(_spaced(p) for p in ANCHOR_PHRASES) + r"\)"
    r"|" + "|".join(_spaced(p) for p in ANCHOR_PHRASES) + r")"
)
SINGLE_LATIN_RE = re.compile(r"^[A-Za-z]$")

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

print(f"전체 문서 {len(rows)}건 조사 중...\n")

# 앵커 직전 문자 전체 분포 (전체 기관, 전체 포맷)
bullet_counter = Counter()
# 알파벳 단독 1글자인 경우만 별도 — 기관별/확장자별로 세분화
letter_by_institution = defaultdict(Counter)
letter_by_ext = Counter()
letter_examples = defaultdict(list)

for doc_id, institution, year, source_file, raw_text in rows:
    for m in ANCHOR_RE.finditer(raw_text):
        ch = m.group(1)
        bullet_counter[ch] += 1
        if SINGLE_LATIN_RE.match(ch):
            letter_by_institution[ch][institution] += 1
            ext = (
                source_file.rsplit(".", 1)[-1].lower()
                if source_file and "." in source_file
                else "(확장자없음)"
            )
            letter_by_ext[(ch, ext)] += 1
            if len(letter_examples[ch]) < 3:
                letter_examples[ch].append(doc_id)

print("앵커 문구 직전 문자 전체 분포 (상위 30):")
for ch, cnt in bullet_counter.most_common(30):
    print(f"  {ch!r}: {cnt}건")

print("\n--- 알파벳 단독 1글자인 것만 (Wingdings류 불릿 누출 후보) ---")
alpha_total = Counter({ch: sum(insts.values()) for ch, insts in letter_by_institution.items()})
for ch, total in alpha_total.most_common():
    print(f"\n'{ch}': 총 {total}건")
    print(f"  확장자별: { {ext: cnt for (c, ext), cnt in letter_by_ext.items() if c == ch} }")
    print(f"  기관별(상위 5): {letter_by_institution[ch].most_common(5)}")
    print(f"  예시 문서 ID: {letter_examples[ch]}")

print("\n확인 포인트: 'v' 말고 다른 알파벳도 여기 상당수 나오면, 그 알파벳이 나온"
      " 문서 몇 건을 audit_v_bullet_font_check.py와 같은 방식(pymupdf로 원본 PDF"
      " 열어서 해당 스팬 폰트 확인)으로 검증할 것.")
