# ------------------------------------------------------------------
# 표 컬럼 뒤섞임(2단 표 텍스트 교차 오염) 실태 조사 (2026-08-13, 읽기 전용)
# ------------------------------------------------------------------
# 서울대학교치과병원 "감사결과 처분서" 문서(c34d1181227f1d9f 등)에서 발견: 2단 표
# (지적사항/처분 컬럼)를 PDF에서 추출할 때 두 컬럼의 텍스트가 한 줄씩 번갈아 섞여서
# 저장됨(예: 긴 줄=지적사항 컬럼, 짧은 줄=처분 컬럼 조각이 교대로 나옴). 정규식으로
# 복구 불가능한 근본적 추출 순서 오류라 규모 파악용 조사 스크립트.
#
# 판정 방식(휴리스틱): 줄 길이가 "길다/짧다"로 번갈아 6번 이상 연속되면 의심 후보로
# 분류. 단, HWP 내부 태그 누출(audit_hwp_tag_leak.py가 다루는 별개 문제)이 섞여
# 있으면 같은 신호(불규칙한 짧은 줄 다수)를 내서 오탐이 생기므로, 태그 패턴이
# 있는 문서는 여기서 제외(따로 집계해서 태그 누출 쪽 문제로 분류).
#
# 완벽한 판정은 아니라서(자연스러운 문장도 길이가 들쭉날쭉할 수 있음), 사람이
# 최종 확인하는 걸 전제로 함. 아무것도 수정 안 함(읽기 전용).
# ------------------------------------------------------------------
import os
import re
from collections import Counter

import psycopg2

# audit_truncated_documents.py에서 이미 확인된 HWP 태그 누출 신호 + 이번에 추가로
# 발견된 도형/차트 속성 태그(hc: 계열) — 이 신호가 있으면 표 뒤섞임이 아니라 태그
# 누출 문제로 따로 집계
HWP_TAG_RE = re.compile(
    r"hp:run|hp:linesegarray|hc:\w+|textpos=|vertpos=|linkListNextIDRef|outlineS"
)

SHORT_THRESH = 14
LONG_THRESH = 22
MIN_RUN = 6


def line_kind(n: int) -> str:
    if n >= LONG_THRESH:
        return "L"
    if n <= SHORT_THRESH:
        return "S"
    return "?"


def longest_alternating_run(raw_text: str) -> int:
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    kinds = [line_kind(len(l)) for l in lines]
    best = 0
    i = 0
    while i < len(kinds) - 1:
        if kinds[i] in "LS" and kinds[i + 1] in "LS" and kinds[i] != kinds[i + 1]:
            run = 2
            j = i + 1
            while j + 1 < len(kinds) and kinds[j + 1] in "LS" and kinds[j + 1] != kinds[j]:
                run += 1
                j += 1
            best = max(best, run)
            i = j
        else:
            i += 1
    return best


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

interleave_candidates = []
tag_leak_only = []

for doc_id, institution, year, audit_type, raw_text in rows:
    has_tag = bool(HWP_TAG_RE.search(raw_text))
    run = longest_alternating_run(raw_text)
    if run >= MIN_RUN:
        if has_tag:
            tag_leak_only.append((doc_id, institution, year, audit_type, run))
        else:
            interleave_candidates.append((doc_id, institution, year, audit_type, run))

print(f"\n표 컬럼 뒤섞임 의심(태그 누출 아님): {len(interleave_candidates)}건")
print(f"참고: 같은 신호였지만 실제론 HWP 태그 누출로 보이는 것: {len(tag_leak_only)}건\n")

inst_counter = Counter((inst, yr) for _, inst, yr, _, _ in interleave_candidates)
print("기관/연도별 분포 (표 컬럼 뒤섞임 의심, 2건 이상만):")
for (inst, yr), cnt in inst_counter.most_common():
    if cnt >= 2:
        print(f"  {inst} {yr}: {cnt}건")

print("\n전체 후보 목록 (document_id | 기관 | 연도 | 감사종류 | 교차런길이):")
for doc_id, institution, year, audit_type, run in sorted(
    interleave_candidates, key=lambda r: -r[4]
):
    print(f"  {doc_id} | {institution} | {year} | {audit_type} | run={run}")
