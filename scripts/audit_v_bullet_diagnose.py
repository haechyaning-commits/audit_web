# ------------------------------------------------------------------
# 'v' 단독 토큰 = 불릿 기호 오염 가설 검증 (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: audit_hwpx_tag_leak_round2.py 실행 결과, "v (관련부서의견)" / "v 1." /
# "지 적 요 지 v독신자 숙소..." 처럼 'v'가 항상 항목 맨 앞(불릿 자리)에 나타남 —
# hp:val 같은 속성명 절단이 아니라, 심볼 폰트(Wingdings류) 체크마크(✓) 불릿이
# 폰트 정보 없이 문자코드만 뽑히면서 'v'로 오염된 것이라는 가설.
#
# raw_text만으로 검증 가능한 정황증거: "(관련부서의견)"/"(관계기관의견)" 앞에는
# 거의 항상 불릿 문자 하나가 온다(감사보고서 표준 서식). 이 스크립트는 그 기관
# 전체 문서(매칭 여부 무관)에서 그 앞 문자를 전부 모아 분포를 봄 —
#   - 대부분 문서에서 특정 문자(예: ○, ◆, 빈칸 등)가 나오는데 일부 문서만 'v'가
#     나온다면 → 불릿 기호가 원본/변환 경로에 따라 다르게 깨진다는 강한 정황
#   - 애초에 아무 규칙이 없다면 → 가설 재검토 필요
# 추가로 매칭 문서들의 source_file 확장자(.hwp/.hwpx) 분포도 같이 뽑아서, 어느
# 추출 경로(hwp5txt vs hwpx lxml)에서 나는 문제인지 단서를 잡음.
# 아무것도 수정하지 않음(읽기 전용).
# ------------------------------------------------------------------
import os
import re
from collections import Counter

import psycopg2

ANCHOR_RE = re.compile(r"(\S)\s*\((관련부서의견|관계기관의견)\)")
V_TOKEN_RE = re.compile(r"(?<![A-Za-z])v(?![A-Za-z])")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute(
        "SELECT id, institution, year, source_file, raw_text FROM documents "
        "WHERE institution = '한국수력원자력'"
    )
    rows = cur.fetchall()
conn.close()

print(f"한국수력원자력 문서 {len(rows)}건 조사 중...\n")

# 1) "(관련부서의견)"/"(관계기관의견)" 바로 앞 문자 분포 — 매칭 여부와 무관하게 전수
bullet_counter = Counter()
bullet_examples = {}
for doc_id, institution, year, source_file, raw_text in rows:
    for m in ANCHOR_RE.finditer(raw_text):
        ch = m.group(1)
        bullet_counter[ch] += 1
        bullet_examples.setdefault(ch, []).append(doc_id)

print("'(관련부서의견)' / '(관계기관의견)' 직전 문자 분포 (전체):")
for ch, cnt in bullet_counter.most_common(20):
    sample_ids = bullet_examples[ch][:3]
    print(f"  {ch!r}: {cnt}건  예: {sample_ids}")

# 2) 'v' 단독 토큰이 있는 문서만 따로 — source_file 확장자 분포 + 문서당 출현 횟수
v_docs = [(doc_id, year, source_file, raw_text) for doc_id, inst, year, source_file, raw_text in rows
          if V_TOKEN_RE.search(raw_text)]
print(f"\n'v' 단독 토큰 있는 한수원 문서: {len(v_docs)}건")

ext_counter = Counter()
for doc_id, year, source_file, raw_text in v_docs:
    ext = source_file.rsplit(".", 1)[-1].lower() if source_file and "." in source_file else "(확장자 없음)"
    ext_counter[ext] += 1
print("소스 파일 확장자 분포:")
for ext, cnt in ext_counter.most_common():
    print(f"  .{ext}: {cnt}건")

occ_counter = Counter()
for doc_id, year, source_file, raw_text in v_docs:
    occ_counter[len(V_TOKEN_RE.findall(raw_text))] += 1
print("\n문서당 'v' 출현 횟수 분포:")
for occ, cnt in sorted(occ_counter.items()):
    print(f"  {occ}회: {cnt}건")

# 3) 매칭 안 된(=='v' 없는) 문서들 중, "(관련부서의견)" 앞 문자가 뭔지 다시 확인
#    (위 1번과 대조해서, 'v'가 나오는 문서만 유독 그 자리가 다른지 교차검증)
v_ids = {doc_id for doc_id, *_ in v_docs}
bullet_in_v_docs = Counter()
bullet_in_nonv_docs = Counter()
for doc_id, institution, year, source_file, raw_text in rows:
    for m in ANCHOR_RE.finditer(raw_text):
        ch = m.group(1)
        if doc_id in v_ids:
            bullet_in_v_docs[ch] += 1
        else:
            bullet_in_nonv_docs[ch] += 1

print("\n'v' 있는 문서들만: '(관련부서의견)' 직전 문자 분포:")
for ch, cnt in bullet_in_v_docs.most_common(10):
    print(f"  {ch!r}: {cnt}건")

print("\n'v' 없는 문서들: '(관련부서의견)' 직전 문자 분포:")
for ch, cnt in bullet_in_nonv_docs.most_common(10):
    print(f"  {ch!r}: {cnt}건")
