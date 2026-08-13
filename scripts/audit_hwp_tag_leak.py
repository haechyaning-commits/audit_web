# ------------------------------------------------------------------
# HWP 내부 태그 누출 실태 재조사 (2026-08-13, 읽기 전용)
# ------------------------------------------------------------------
# 기존(2026-08-07~10) strip_hwpml_leak 수정은 hp:run/hp:linesegarray 계열(문단/
# 텍스트런 태그)만 다뤘음. 2026-08-13 상세페이지 오탐 조사 중, 표가 복잡한 문서에서
# hc: 계열(도형/차트 속성 태그 — hc:transMatrix, hc:scaMatrix, hc:rotMatrix,
# hc:fillBrush, hc:winBrush, hc:pt0~3 등)과 linkListNextIDRef=, outlineS 같은 다른
# HWPX 내부 마크업이 별도로 텍스트에 새고 있는 걸 발견함(예: 한국수목원정원관리원,
# 한국농어촌공사, 대구교통공사, 사립학교교직원연금공단 문서). 기존 수정 범위 밖의
# 새로운 잔존 케이스라 규모 파악용 조사 스크립트. 아무것도 수정 안 함(읽기 전용).
# ------------------------------------------------------------------
import os
import re
from collections import Counter

import psycopg2

# 발견된 각 태그 계열을 개별적으로 집계 — 어느 패턴이 제일 흔한지 확인용
TAG_PATTERNS = {
    "hp:run/linesegarray (기존에 고쳤다고 알던 것)": re.compile(r"hp:run|hp:linesegarray"),
    "hc:도형/차트 속성 (신규 발견)": re.compile(r"hc:\w+"),
    "textpos=/vertpos=": re.compile(r"textpos=|vertpos="),
    "linkListNextIDRef=": re.compile(r"linkListNextIDRef="),
    "outlineS (개요 구조 태그)": re.compile(r"outlineS"),
}
ANY_TAG_RE = re.compile("|".join(p.pattern for p in TAG_PATTERNS.values()))

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

candidates = []
pattern_counts = Counter()

for doc_id, institution, year, audit_type, raw_text in rows:
    if not ANY_TAG_RE.search(raw_text):
        continue
    matched = [name for name, pat in TAG_PATTERNS.items() if pat.search(raw_text)]
    for name in matched:
        pattern_counts[name] += 1
    candidates.append((doc_id, institution, year, audit_type, matched))

print(f"\nHWP 태그 누출 의심 문서: {len(candidates)}건 / 전체 {len(rows)}건 "
      f"({len(candidates) / len(rows) * 100:.2f}%)\n")

print("태그 계열별 건수:")
for name, cnt in pattern_counts.most_common():
    print(f"  {name}: {cnt}건")

inst_counter = Counter((inst, yr) for _, inst, yr, _, _ in candidates)
print("\n기관/연도별 분포 (2건 이상만):")
for (inst, yr), cnt in inst_counter.most_common():
    if cnt >= 2:
        print(f"  {inst} {yr}: {cnt}건")

print("\n전체 목록 (document_id | 기관 | 연도 | 감사종류 | 매칭된 태그계열):")
for doc_id, institution, year, audit_type, matched in candidates:
    print(f"  {doc_id} | {institution} | {year} | {audit_type} | {matched}")
