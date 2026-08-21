# ------------------------------------------------------------------
# 중복 문서 실태 조사 (2026-08-13, 읽기 전용 — DB에 아무것도 안 씀)
# ------------------------------------------------------------------
# 배경: 데이터 파이프라인 이력(STATUS.md)을 보면 여러 단계(청킹 대상 76,454건 ->
# 1차 정리 78,697건 -> 최종 67,751건)를 거치며 건수가 계속 바뀌었는데, 그 과정에서
# "같은 감사보고서가 원본 파일명만 다르게(오탈자, 재게시 등) 두 번 적재됐는지"는 한
# 번도 직접 검증된 적이 없음. 전체 규모를 파악하기 위한 조사 스크립트.
#
# 두 단계로 나눠서 봄:
#   1) 완전 중복 — raw_text가 글자 하나까지 똑같은 문서(institution 다를 수도 있어서
#      institution 기준으로는 안 묶고 raw_text 자체로만 묶음 — 정말 같은 파일이 두 번
#      들어간 경우만 여기 걸림).
#   2) 유사 중복(같은 기관+연도 + 본문 앞부분 거의 동일) — 완전히 똑같진 않지만
#      (여백/줄바꿈 차이, 재추출로 살짝 다르게 뽑힌 경우 등) 사실상 같은 문서로
#      보이는 경우. 앞부분 300자에서 공백을 다 지우고 비교 — 완전 일치가 아니라
#      "같은 기관+연도 그룹 안에서 정규화한 앞부분이 겹치는 것"만 후보로 올림
#      (통계적 유사도 점수 없음 — 지난번 표 뒤섞임 스캔 실패 교훈으로, 애매한 임계값
#      대신 명확한 조건만 사용. 최종 판단은 사람이 목록 보고 확인).
# ------------------------------------------------------------------
import os
import re
from collections import defaultdict

import psycopg2

# 본문 비교용 정규화 — 공백/개행 차이, 익명화 placeholder 개수 차이 정도는 무시하고
# "같은 문서인가"만 보고 싶어서 공백만 다 지움(단어 자체를 건드리진 않음)
NORMALIZE_RE = re.compile(r"\s+")


def normalize_head(raw_text: str, n: int = 300) -> str:
    return NORMALIZE_RE.sub("", raw_text)[:n]


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

print(f"전체 문서 {len(rows)}건 조사 중...\n")

# ------------------------------------------------------------------
# 1) 완전 중복 — raw_text 자체가 100% 동일
# ------------------------------------------------------------------
exact_groups = defaultdict(list)
for doc_id, institution, year, audit_type, raw_text in rows:
    exact_groups[raw_text].append((doc_id, institution, year, audit_type))

exact_dups = {text: ids for text, ids in exact_groups.items() if len(ids) > 1}
exact_dup_doc_count = sum(len(v) for v in exact_dups.values())

print(f"[완전 중복] {len(exact_dups)}개 그룹 / 총 {exact_dup_doc_count}건 문서 "
      f"(그룹당 평균 {exact_dup_doc_count / len(exact_dups):.1f}건)"
      if exact_dups else "[완전 중복] 0건")
print()
for text, ids in list(exact_dups.items())[:20]:
    print(f"  그룹({len(ids)}건):")
    for doc_id, institution, year, audit_type in ids:
        print(f"    {doc_id} | {institution} | {year} | {audit_type}")
print()

# ------------------------------------------------------------------
# 2) 유사 중복 — 같은 기관+연도 안에서 정규화한 본문 앞부분(300자)이 일치
#    (완전 중복으로 이미 잡힌 문서는 제외 — 중복 보고 방지)
# ------------------------------------------------------------------
exact_dup_ids = {doc_id for ids in exact_dups.values() for doc_id, *_ in ids}

near_groups = defaultdict(list)
for doc_id, institution, year, audit_type, raw_text in rows:
    if doc_id in exact_dup_ids:
        continue
    if not raw_text or len(raw_text) < 100:
        continue  # 너무 짧으면 앞부분 300자 비교가 의미 없음(우연 일치 위험)
    key = (institution, year, normalize_head(raw_text))
    near_groups[key].append((doc_id, audit_type, len(raw_text)))

near_dups = {k: v for k, v in near_groups.items() if len(v) > 1}
near_dup_doc_count = sum(len(v) for v in near_dups.values())

print(f"[유사 중복] {len(near_dups)}개 그룹 / 총 {near_dup_doc_count}건 문서 "
      f"(완전 중복 제외, 같은 기관+연도+본문 앞 300자 일치)"
      if near_dups else "[유사 중복] 0건")
print()
for (institution, year, _head), items in list(near_dups.items())[:20]:
    print(f"  그룹({len(items)}건) — {institution} {year}:")
    for doc_id, audit_type, length in items:
        print(f"    {doc_id} | {audit_type} | raw_text 길이 {length}")
print()

print("=== 요약 ===")
print(f"전체 문서: {len(rows)}건")
print(f"완전 중복: {exact_dup_doc_count}건 ({len(exact_dups)}개 그룹)")
print(f"유사 중복(완전 중복 제외): {near_dup_doc_count}건 ({len(near_dups)}개 그룹)")
