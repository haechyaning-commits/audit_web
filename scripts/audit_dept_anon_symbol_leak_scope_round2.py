# ------------------------------------------------------------------
# 부서/기관명 익명화 심볼 누출 — 규모조사 2차 (2026-08-27, 읽기 전용, DB만)
# ------------------------------------------------------------------
# 1차(audit_dept_anon_symbol_leak_scope.py, 2026-08-26) 결과 요약:
#   - CURATED_SUSPECT_CHARS(♣♧▩▧♥♠⊗, 카드무늬 7종) 영향 문서 8,314건/67,751건(12.27%)
#   - 그중 6,142건(74%)은 같은 문서에 "[부서]"(정상 처리)도 같이 있음 — 익명화 로직이
#     이 문서를 "부분적으로만" 처리했다는 신호(같은 문서 안에서 어떤 마스킹 자리는
#     정상 변환되고 어떤 자리는 원본 심볼 그대로 새고 있음)
#   - "넓은 그물"(1번 그리드 밖 미확인 문자) 상위 40개에 카드무늬류 외에도 기하학무늬/
#     블록기호류가 대거 발견됨 — 이번 2차 조사 대상
#
# 이번 스크립트가 하는 일 (전체 67,751건, DB의 raw_text만으로 훑음):
#   A. 1차에서 새로 발견된 기하학무늬/블록기호 후보(GROUP_A) — 카드무늬와 같은 부류로 추정
#   B. 이미 확정된 ♥♠(카드무늬)와 짝을 이루는 outline 버전 ♡♤(GROUP_B) — 마스킹일 가능성 높음
#   C. 수식/화살표/문장부호로 보여 오탐(정상 기호)일 수 있는 후보 ×∼～→☞(GROUP_C) —
#      마스킹이 아니면 KNOWN_GOOD_CHARS로 옮겨야 함
# 각 문자에 대해: 영향 문서/총 출현 수, 연속반복 길이 분포(단독 1개 / 2개 연속 / 3개+
# 연속 — reextract_pdf_text.py의 _MASK_GLYPH_RE가 "2개 이상 연속"만 잡는 것과 비교
# 하기 위함, 1차 조사 중 발견한 "기관 자기 이름이 [부서]로 잘못 치환된" 사례가
# 힌트가 됨: 그 사례처럼 짧게 마스킹된 자리는 연속 2개 미만이라 애초에 안 걸릴 수
# 있음), 기관별 분포, 컨텍스트 샘플(최대 4건)까지 뽑음.
# 아무것도 수정하지 않음 — 규모 확정 전까지는 수정 스크립트를 만들지 않는 게 이 프로젝트 관례.
# ------------------------------------------------------------------
import os
import re
from collections import Counter, defaultdict

import psycopg2

# A. 1차 "넓은 그물" 상위 40개 중 카드무늬(♣♧▩▧♥♠⊗)와 같은 부류로 보이는
#    기하학무늬/블록기호. ■◎☆★●는 _MASK_GLYPH_RE가 원래 처리해야 하는 심볼(2개 이상
#    연속일 때만)인데도 "넓은 그물"에 걸렸다는 건 단독(1개)로 나온 자리가 있다는 뜻 —
#    아래 run_length_dist로 실제 그런지 확인.
GROUP_A = "◉▤◐◁▷◍■▥▨◎▢◈◒☆★●▣◌◧◊▒◕◫◑▶◩◷◨◰⊠◪◘▦"
# B. 이미 1차에서 확정된 ♥♠(카드무늬 채움형)의 outline(테두리만) 버전. 같은 폰트가
#    채움형/테두리형을 같이 쓰는 경우가 흔해서 마스킹일 가능성이 높다고 보고 별도 그룹.
GROUP_B = "♡♤"
# C. 수학 기호(×)·범위 표시(∼～)·화살표(→)·손가락 기호(☞)로 보여, 마스킹이 아니라
#    정상 문장부호/기호일 가능성이 있는 후보. 확인 후 아니라면 KNOWN_GOOD_CHARS로.
GROUP_C = "×∼～→☞"

ALL_CANDIDATES = GROUP_A + GROUP_B + GROUP_C
GROUPS = [
    ("A. 마스킹 추정 — 기하학무늬/블록기호", GROUP_A),
    ("B. ♥♠ 짝(outline) — 마스킹 추정", GROUP_B),
    ("C. 오탐 의심 — 정상 기호일 가능성", GROUP_C),
]

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
print(f"전체 문서 {total_docs}건 조사 중 (후보 문자 {len(ALL_CANDIDATES)}종)...\n")

char_doc_count = Counter()
char_occurrence_count = Counter()
institution_count = defaultdict(Counter)
run_length_dist = defaultdict(Counter)  # char -> {1: n, 2: n, "3+": n}
examples = defaultdict(list)

find_re = {ch: re.compile(re.escape(ch)) for ch in ALL_CANDIDATES}
run_re = {ch: re.compile(re.escape(ch) + "+") for ch in ALL_CANDIDATES}

for doc_id, institution, year, source_file, raw_text in rows:
    if not raw_text:
        continue
    for ch in ALL_CANDIDATES:
        if ch not in raw_text:
            continue
        occ = len(find_re[ch].findall(raw_text))
        if occ == 0:
            continue
        char_doc_count[ch] += 1
        char_occurrence_count[ch] += occ
        institution_count[ch][institution] += 1
        for run in run_re[ch].findall(raw_text):
            length = len(run)
            key = length if length <= 2 else "3+"
            run_length_dist[ch][key] += 1
        if len(examples[ch]) < 4:
            m = find_re[ch].search(raw_text)
            start = max(0, m.start() - 20)
            end = min(len(raw_text), m.end() + 40)
            context = raw_text[start:end].replace("\n", " ")
            examples[ch].append((doc_id, institution, year, source_file, context))

for group_name, group_chars in GROUPS:
    print(f"\n{'=' * 70}\n{group_name}\n{'=' * 70}")
    for ch in group_chars:
        if char_doc_count[ch] == 0:
            print(f"\n'{ch}' (U+{ord(ch):04X}): 이 코퍼스에 없음")
            continue
        dist = run_length_dist[ch]
        print(f"\n'{ch}' (U+{ord(ch):04X}): 문서 {char_doc_count[ch]}건 / 총 {char_occurrence_count[ch]}회 출현")
        print(
            f"  연속반복 길이: 단독(1개) {dist.get(1, 0)}회 / 2개 연속 {dist.get(2, 0)}회"
            f" / 3개 이상 연속 {dist.get('3+', 0)}회"
        )
        print(f"  기관별(상위 5): {institution_count[ch].most_common(5)}")
        print("  컨텍스트 샘플:")
        for doc_id, institution, year, source_file, context in examples[ch]:
            print(f"    [{doc_id}] {institution}·{year}: ...{context}...")

print("\n" + "=" * 70)
print("확인 포인트")
print("=" * 70)
print("  - A/B 그룹: 컨텍스트 샘플이 실제로 이름/부서/기관명이 있어야 할 자리인지 확인")
print("    → 맞으면 CURATED_SUSPECT_CHARS(1차 스크립트)에 추가해서 규모를 재확정")
print("  - '단독(1개)' 비율이 높게 나온 문자(특히 ■◎☆★● — 원래 _MASK_GLYPH_RE가")
print("    2개 이상 연속일 때만 처리하는 심볼)는, 짧게(1글자) 마스킹된 이름/기관명이")
print("    새는 것으로 추정됨(1차 조사에서 실제로 '한국■■■■위원회'→'한국[부서]위원회'처럼")
print("    기관 자기 이름 일부가 [부서]로 잘못 치환된 사례를 발견한 것과 같은 근본 원인)")
print("    — 단, 단독 1개는 정상 불릿(예: ● 목록 항목 맨 앞)과 구분이 안 되니 컨텍스트로")
print("    반드시 확인. 문장/단어 중간에 끼어있으면 마스킹, 줄 맨 앞에 있고 뒤에 공백이")
print("    오면 불릿일 가능성이 높음.")
print("  - C 그룹: 컨텍스트 샘플이 수식/범위/화살표 등 정상 문장부호로 보이면 마스킹이")
print("    아니므로 이후 조사에서 제외, KNOWN_GOOD_CHARS에 추가해 노이즈를 줄일 것")
