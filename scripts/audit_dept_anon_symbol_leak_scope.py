# ------------------------------------------------------------------
# 부서/기관명 익명화 자리에 사설 심볼 폰트 문자가 새는 버그 — 규모조사 (2026-08-26, 읽기 전용, DB만)
# ------------------------------------------------------------------
# 배경: 실제 배포 사이트를 브라우저로 렌더링해서 눈으로 확인하던 중 발견(API JSON 응답만
# 봐서는 유효한 유니코드 문자라 그냥 지나치기 쉬움). 검색결과 카드에 "관 련 부 서 [부서]
# ♣부, ▩부" 처럼 부서명이 정상적으로 "[부서]"로 익명화된 자리 옆에 카드무늬/기하학무늬류
# 기호(♣♧▩▧♥♠⊗ 등)가 그대로 노출되는 문서를 확인함. 같은 문서 안에서 "[부서]"로 정상
# 치환된 경우와 기호로 새는 경우가 섞여 있는 사례도 있어서(예: db132cd6f1819aa8,
# 한국수력원자력·2026 — "관 련 부 서 [부서] ♣부, ▩부 / 조 치 부 서 [부서] ♧팀, ♣부, ▩부"),
# 기존 익명화 로직이 이 케이스를 부분적으로만 처리하고 있는 것으로 보임.
#
# 원인 추정(아직 미확정): DetailPage.jsx의 GLYPH_BULLET_MAP(q→□, m→○)이나
# scripts/audit_symbol_font_leak_*·fix_symbol_font_bullet_leak*.py가 다뤄온 "원문 HWP가
# 사설 심볼 폰트(Wingdings류)를 쓴 자리를, 폰트 매핑 정보 없이 코드포인트만 그대로 뽑아내면
# 엉뚱한 문자로 보인다"는 것과 같은 부류의 문제로 추정되나, 그 조사들은 "원문자 불릿(①②③,
# 목록 항목 맨 앞)"이 중심이었고 이번 건은 "부서/기관명 익명화 자리(문장 중간, 여러 글자가
# 연달아 나옴)"라는 별개 위치라 기존 조사의 매칭 범위에 포함돼 있었는지 확인 안 됨.
#
# 이 스크립트가 하는 일 (PDF/HWP 재다운로드 없이, DB의 raw_text만으로 전체 67,751건 빠르게 훑음):
#   1. 실제로 관찰된 의심 문자(CURATED_SUSPECT_CHARS)의 전체 규모 — 영향 문서 수/비율,
#      기관별 분포, "[부서]"와 같은 문서에 섞여 있는지(부분 처리 신호), 컨텍스트 샘플
#   2. 아직 못 찾은 같은 부류의 문자가 더 있는지 — Hangul/ASCII/이미 알려진 정상 불릿
#      기호(DetailPage.jsx BULLET_RE 기준)를 뺀 "이 문서군에서 흔치 않은 문자"를 빈도순으로
#      나열해서 다음 확인 후보를 추림
# 아무것도 수정하지 않음 — 규모 확정 전까지는 수정 스크립트를 만들지 않는 게 이 프로젝트 관례.
# ------------------------------------------------------------------
import os
import re
import unicodedata
from collections import Counter, defaultdict

import psycopg2

# 실제로 화면에서 관찰된 의심 문자 (browser 스크린샷으로 확인된 것들)
CURATED_SUSPECT_CHARS = "♣♧▩▧♥♠⊗"

# "정상"으로 이미 알려진 문자군 — 이 문서 코퍼스에서 흔하고 실제로 정상 콘텐츠인 것들.
# DetailPage.jsx의 BULLET_RE/원문자/GLYPH_BULLET_MAP 및 흔한 문장부호를 기준으로 구성.
KNOWN_GOOD_CHARS = set(
    "-–—□○◦▪‣·❍※•*ㅇ◯"  # 불릿류 (BULLET_RE, LONE_BULLET_GLYPH_RE)
    "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"  # 원문자 번호
    "「」『』〈〉《》【】〔〕（）()[]{}"  # 괄호류
    "·ㆍ‧、。,.!?:;'\"“”‘’"  # 문장부호
    "㈜%℃㎡㎢㎞㎏₩원※△▲▽▼◇◆☎☏"  # 문서에서 흔한 단위/기호
    "\n\r\t "
)


def _is_known_good(ch: str) -> bool:
    if ch in KNOWN_GOOD_CHARS:
        return True
    cat = unicodedata.category(ch)
    cp = ord(ch)
    # 한글(음절/자모), ASCII 문자/숫자, 일반 문장부호(P*)·구분자(Z*)는 정상으로 간주
    if 0xAC00 <= cp <= 0xD7A3:  # 한글 음절
        return True
    if 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:  # 한글 자모
        return True
    if cp < 0x80:  # ASCII
        return True
    if cat.startswith("P") or cat.startswith("Z") or cat.startswith("N"):
        return True
    if cat.startswith("L"):  # 다른 언어 문자(한자 등) — 이 코퍼스에 흔함, 오탐 방지
        return True
    return False


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

# --- 1. 커스텀 의심 문자 규모조사 ---
suspect_re = re.compile(f"[{re.escape(CURATED_SUSPECT_CHARS)}]")
affected_doc_ids = set()
char_doc_count = Counter()  # 문자별 영향 문서 수(중복 제거)
char_occurrence_count = Counter()  # 문자별 총 출현 횟수
institution_count = defaultdict(Counter)  # 문자 -> 기관 -> 문서 수
mixed_with_placeholder = 0  # 같은 문서에 "[부서]"도 같이 있는 경우(부분 처리 신호)
examples = []

for doc_id, institution, year, source_file, raw_text in rows:
    if not raw_text:
        continue
    matches = suspect_re.findall(raw_text)
    if not matches:
        continue
    affected_doc_ids.add(doc_id)
    seen_chars_in_doc = set(matches)
    for ch in seen_chars_in_doc:
        char_doc_count[ch] += 1
        institution_count[ch][institution] += 1
    for ch in matches:
        char_occurrence_count[ch] += 1
    if "[부서]" in raw_text:
        mixed_with_placeholder += 1
    if len(examples) < 15:
        m = suspect_re.search(raw_text)
        start = max(0, m.start() - 20)
        end = min(len(raw_text), m.end() + 40)
        context = raw_text[start:end].replace("\n", " ")
        examples.append((doc_id, institution, year, source_file, context))

print("=== 1. 의심 문자 규모조사 ===")
print(f"영향받은 문서: {len(affected_doc_ids)}건 / {total_docs}건 ({len(affected_doc_ids)/total_docs:.2%})")
print(f"  (참고) 같은 문서 안에 '[부서]' placeholder도 같이 있는 경우: {mixed_with_placeholder}건"
      " — 익명화 로직이 이 문서를 부분적으로만 처리했다는 신호")
print()
for ch in CURATED_SUSPECT_CHARS:
    if char_doc_count[ch] == 0:
        continue
    print(f"'{ch}' (U+{ord(ch):04X}): 문서 {char_doc_count[ch]}건 / 총 {char_occurrence_count[ch]}회 출현")
    print(f"  기관별(상위 5): {institution_count[ch].most_common(5)}")

print("\n--- 컨텍스트 샘플 (최대 15건) ---")
for doc_id, institution, year, source_file, context in examples:
    print(f"  [{doc_id}] {institution}·{year} ({source_file}): ...{context}...")

# --- 2. 아직 못 찾은 같은 부류 문자 넓혀 찾기 ---
print("\n=== 2. 넓은 그물: 이 코퍼스에서 흔치 않은 문자 빈도 (다음 확인 후보) ===")
unknown_char_counter = Counter()
unknown_char_doc_count = Counter()
for doc_id, institution, year, source_file, raw_text in rows:
    if not raw_text:
        continue
    doc_unknown_chars = set()
    for ch in raw_text:
        if _is_known_good(ch) or ch in CURATED_SUSPECT_CHARS:
            continue
        unknown_char_counter[ch] += 1
        doc_unknown_chars.add(ch)
    for ch in doc_unknown_chars:
        unknown_char_doc_count[ch] += 1

print("상위 40개 (문자 / U+코드 / 총 출현 / 영향 문서 수) — 기존 커버리지 밖의 후보들:")
for ch, cnt in unknown_char_counter.most_common(40):
    print(f"  {ch!r} (U+{ord(ch):04X}): 총 {cnt}회, 문서 {unknown_char_doc_count[ch]}건")

print("\n확인 포인트:")
print("  - 1번 결과로 실제 영향 규모(문서 수/기관 분포)를 확정하고, 컨텍스트 샘플로")
print("    전부 '부서/기관명 익명화 자리'인지(다른 정상 용도로 쓰인 오탐은 없는지) 확인.")
print("  - 2번 결과 상위권에 1번과 같은 성격(카드무늬/기하학무늬/드문 기호류)이 더 보이면")
print("    CURATED_SUSPECT_CHARS에 추가해서 재실행 — 원인(어느 폰트/추출 경로에서 새는지)")
print("    확정은 audit_v_bullet_font_check.py처럼 원본 HWP/PDF를 열어 실제 폰트를 확인해야 함")
print("    (이 스크립트는 그 전 단계, 확인할 후보를 추리는 용도).")
