# ------------------------------------------------------------------
# HWPX 내부 태그 누출 재조사 2차 (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: audit_hwp_tag_leak.py(2026-08-13)가 hp:run/hp:linesegarray, hc:도형/차트
# 속성(hc:transMatrix 등), textpos=/vertpos=, linkListNextIDRef=, outlineS 계열을
# 잡아냈는데, 그 수정 이후에도 한국농어촌공사 2024년 복무감사(문서 328d072215a508c6)
# 상세페이지에서 여전히 그 어느 패턴에도 안 걸리는 새 종류의 누출 토큰이 육안으로
# 확인됨:
#   - "hp: run", "hp: p", "hp: subList" — 기존에 고쳤다는 hp:run/hp:p 계열이
#     콜론 뒤 공백이 낀 변형으로 재등장(표 셀 문단 쪽 hp:subList는 처음 확인)
#   - "col", "cha", "head", "v", "linkLis", "ubList", "paraPrI", "lineW" — 접두사
#     (hp:/hc:) 없이 잘린 것으로 보이는 단독 토큰들. hp:tbl의 열(col) 관련 속성,
#     hp:subList/paraPrIDRef(문단 속성 참조 attr), hc:lineWidth(선 굵기 attr),
#     hp:linkList 등 HWPX 표/문단 스키마 요소·속성명이 부분적으로만 잘려 텍스트에
#     섞인 것으로 추정 — 다만 원본 HWPX를 직접 열어 확인한 게 아니라 상세페이지에
#     노출된 결과만 보고 역추정한 가설임(공백 유무 차이는 브라우저 복사 시 줄바꿈
#     경계에서 생긴 아티팩트일 가능성도 배제 못 함).
#
# 이 세션은 DATABASE_URL이 없는 코드 샌드박스라 실행 못 함 — Colab(DB 자격증명
# 있는 세션)에서 먼저 돌려서 실제로 몇 건이나 해당하는지, 오탐(false positive)이
# 얼마나 섞이는지부터 확인할 것. 단독 토큰(col/cha/head/v 등)은 일반 텍스트에서도
# 우연히 나올 수 있어 word-boundary로 제한해도 오탐 위험이 있으므로, 건수만 세지
# 말고 매칭 주변 문맥(앞뒤 30자)을 같이 찍어서 육안으로 진짜 누출인지 확인해야 함.
# 328d072215a508c6은 반드시 대조군으로 포함해서 실제 raw_text가 여기 옮겨 적은
# 그대로인지부터 검증할 것.
# ------------------------------------------------------------------
import os
import re
from collections import Counter

import psycopg2

REFERENCE_DOC_ID = "328d072215a508c6"  # 한국농어촌공사 2024년 복무감사 — 이슈 발견 사례

# 접두사가 남아있는 것(공백 변형 포함)과, 접두사 없이 잘린 것으로 추정되는 단독
# 토큰을 분리해서 집계 — 후자는 오탐 위험이 높아 문맥 확인이 필수
TAG_PATTERNS = {
    "hp:run/p/subList (공백 변형 포함, 기존 수정 회귀 의심)": re.compile(
        r"hp:\s?(run|p|subList|linesegarray)\b"
    ),
    "col (접두사 없는 단독 토큰, 표 열 속성 추정)": re.compile(r"(?<![A-Za-z])col(?![A-Za-z])"),
    "cha (접두사 없는 단독 토큰)": re.compile(r"(?<![A-Za-z])cha(?![A-Za-z])"),
    "head (접두사 없는 단독 토큰)": re.compile(r"(?<![A-Za-z])head(?![A-Za-z])"),
    "linkLis (linkList 절단 추정)": re.compile(r"linkLis(?![A-Za-z])"),
    "ubList (subList 절단 추정)": re.compile(r"(?<![A-Za-z])ubList(?![A-Za-z])"),
    "paraPrI (paraPrIDRef 절단 추정)": re.compile(r"paraPrI(?![A-Za-z])"),
    "lineW (lineWidth 절단 추정)": re.compile(r"lineW(?![A-Za-z])"),
    "v (접두사 없는 단독 1글자 토큰, 오탐 위험 최고)": re.compile(r"(?<![A-Za-z])v(?![A-Za-z])"),
}
ANY_TAG_RE = re.compile("|".join(f"(?:{p.pattern})" for p in TAG_PATTERNS.values()))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute("SELECT id, institution, year, audit_type, raw_text FROM documents")
    rows = cur.fetchall()
conn.close()

print(f"전체 문서 {len(rows)}건 조사 중...")

# 대조군: 이슈를 발견한 문서가 실제로 뭘 갖고 있는지 먼저 확인
ref_row = next((r for r in rows if r[0] == REFERENCE_DOC_ID), None)
if ref_row is None:
    print(f"\n[경고] 대조군 문서 {REFERENCE_DOC_ID}를 DB에서 못 찾음 — id가 맞는지부터 확인할 것")
else:
    _, ref_inst, ref_year, ref_type, ref_text = ref_row
    ref_matched = [name for name, pat in TAG_PATTERNS.items() if pat.search(ref_text)]
    print(f"\n대조군 {REFERENCE_DOC_ID} ({ref_inst} {ref_year} {ref_type}) 매칭 결과: {ref_matched}")
    if not ref_matched:
        print("  → 패턴이 하나도 안 걸림. 위 정규식이 실제 raw_text 형태와 다르다는 뜻이므로,"
              " raw_text를 직접 찍어서 정규식부터 다시 맞출 것.")

candidates = []
pattern_counts = Counter()

for doc_id, institution, year, audit_type, raw_text in rows:
    if not ANY_TAG_RE.search(raw_text):
        continue
    matched = []
    contexts = {}
    for name, pat in TAG_PATTERNS.items():
        m = pat.search(raw_text)
        if m:
            matched.append(name)
            start = max(0, m.start() - 30)
            end = min(len(raw_text), m.end() + 30)
            contexts[name] = raw_text[start:end].replace("\n", " ")
    for name in matched:
        pattern_counts[name] += 1
    candidates.append((doc_id, institution, year, audit_type, matched, contexts))

print(f"\nHWPX 태그 누출(2차) 의심 문서: {len(candidates)}건 / 전체 {len(rows)}건 "
      f"({len(candidates) / len(rows) * 100:.2f}%)\n")

print("태그 계열별 건수 (오탐 위험 높은 패턴일수록 문맥 스니펫을 꼭 확인할 것):")
for name, cnt in pattern_counts.most_common():
    print(f"  {name}: {cnt}건")

inst_counter = Counter((inst, yr) for _, inst, yr, _, _, _ in candidates)
print("\n기관/연도별 분포 (2건 이상만):")
for (inst, yr), cnt in inst_counter.most_common():
    if cnt >= 2:
        print(f"  {inst} {yr}: {cnt}건")

print("\n샘플 20건 (document_id | 기관 | 연도 | 매칭된 패턴 | 문맥 스니펫) — 육안 오탐 확인용:")
for doc_id, institution, year, audit_type, matched, contexts in candidates[:20]:
    print(f"  {doc_id} | {institution} | {year} | {matched}")
    for name in matched:
        print(f"      [{name}] ...{contexts[name]}...")
