# ------------------------------------------------------------------
# 표 컬럼 뒤섞임(2단 표 텍스트 교차 오염) 실태 조사 — 2차 수정본 (2026-08-13, 읽기 전용)
# ------------------------------------------------------------------
# 1차 시도(줄 길이 번갈아 나오는 패턴 휴리스틱)는 실패함 — 정상적인 감사보고서
# 원문도 PDF 줄바꿈 특성상 긴 줄/짧은 줄이 흔하게 섞여서, 전체 문서의 상당수가
# 오탐으로 걸림(변별력 없음). 폐기.
#
# 대신 이번엔 통계적 추정 대신, 실제로 문제가 확인된 "특정 표 양식"을 정확히
# 겨냥함. c34d1181227f1d9f(서울대학교치과병원) 등에서 확인된 오염은 전부
# "감사결과 처분서" 문서의 "연번 지적사항 처분" 3단 표(지적사항/처분 컬럼이
# PDF 추출 시 한 줄씩 번갈아 뒤섞임) 양식에서만 나타남. 이 정확한 헤더
# 문자열을 가진 문서만 골라서 사람이 눈으로 확인할 수 있게 목록만 뽑음
# (자동 판정 없음 — 오탐 위험 있는 통계적 방법 대신 정확한 후보군만 좁혀줌).
# ------------------------------------------------------------------
import os
from collections import Counter

import psycopg2

# 지금까지 확인된 문제 양식의 헤더 문자열 후보(줄바꿈 유무 등 변형 대비 여러 개)
TEMPLATE_MARKERS = [
    "연번 지적사항 처분",
    "연번\n지적사항\n처분",
]

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
for doc_id, institution, year, audit_type, raw_text in rows:
    if any(marker in raw_text for marker in TEMPLATE_MARKERS):
        candidates.append((doc_id, institution, year, audit_type))

print(f"\n'감사결과 처분서(연번/지적사항/처분)' 양식 문서: {len(candidates)}건 / "
      f"전체 {len(rows)}건\n")

inst_counter = Counter((inst, yr) for _, inst, yr, _ in candidates)
print("기관/연도별 분포:")
for (inst, yr), cnt in inst_counter.most_common():
    print(f"  {inst} {yr}: {cnt}건")

print("\n전체 목록 (document_id | 기관 | 연도 | 감사종류) — 상세페이지에서 직접 눈으로 확인 권장:")
for doc_id, institution, year, audit_type in candidates:
    print(f"  {doc_id} | {institution} | {year} | {audit_type}")
