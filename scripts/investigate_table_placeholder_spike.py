# ------------------------------------------------------------------
# table_placeholder_only 판정 급증 원인 조사 (2026-08-10)
# ------------------------------------------------------------------
# remove_unrecoverable_docs.py의 find_unrecoverable()이 예상(1,765건, 2026-08-07
# 진단 기준)보다 훨씬 많은 5,162건을 찾아냄 — 특히 table_placeholder_only가
# 1,674건 예상 대비 5,046건으로 급증.
#
# 가설: table_placeholder_only 판정 기준(strip_table_placeholder 적용 후
# 300자 미만)을 2026-08-07 원래 진단 때는 "1차 수정 반영 전(글자/숫자 중복이
# 그대로 남아있는) raw_text"로 쟀는데, 지금 find_unrecoverable()은 "2차 수정까지
# 다 반영된(글자/숫자 중복이 collapse된) raw_text"로 재는 바람에, 중복 글자로
# 부풀려져 있던 문서들이 dedup 이후 실제 분량이 드러나면서 300자 밑으로 새로
# 떨어진 게 아닌가 하는 것.
#
# 검증 방법: documents(현재, 2차 수정 반영됨)와 documents_backup_20260807(1차
# 수정 반영 전 원본)의 같은 id에 대해 raw_text를 둘 다 가져와서, 각각에
# strip_table_placeholder를 적용한 길이를 비교. "원본은 300자 이상인데 지금은
# 미만"인 문서 수가 급증분(약 3,372건)과 비슷하면 가설 확인.
#
# 읽기 전용 — DB에 아무것도 안 씀. 다른 스크립트와 동시에 돌려도 안전.
# ------------------------------------------------------------------

import json
import re

import psycopg2
from google.colab import userdata


def strip_table_placeholder(text: str) -> str:
    lines = [line for line in text.split("\n") if line.strip() != "표"]
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# 1) 방금 만든 manifest에서 table_placeholder_only인 id만 로드
now_ids = []
with open("removed_unrecoverable_docs.jsonl", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if rec["reason"] == "table_placeholder_only":
            now_ids.append(rec["id"])
print(f"지금 table_placeholder_only로 잡힌 문서: {len(now_ids)}건")

# 2) 같은 id에 대해 현재 raw_text와 원본(백업) raw_text를 함께 조회
DATABASE_URL = userdata.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute(
        "SELECT d.id, d.raw_text, b.raw_text "
        "FROM documents d "
        "JOIN documents_backup_20260807 b ON d.id = b.id "
        "WHERE d.id = ANY(%s)",
        (now_ids,),
    )
    rows = cur.fetchall()
conn.close()

print(f"백업 테이블에서 매칭된 문서: {len(rows)}건 (전체 {len(now_ids)}건 중)")
if len(rows) < len(now_ids):
    print(f"  [주의] {len(now_ids) - len(rows)}건은 백업 테이블에 없음 — 별도 확인 필요")

# 3) 원본(1차 수정 전) 기준으로도 300자 미만이었을지 재계산해서 비교
already_flagged = 0        # 원본에서도 어차피 걸렸을 것 (가설과 무관, 진짜 문제)
newly_flagged_by_dedup = []  # 원본은 300자 이상이었는데 지금은 미만 (가설 확인 대상)

for doc_id, current_text, original_text in rows:
    orig_len = len(strip_table_placeholder(original_text))
    if orig_len < 300:
        already_flagged += 1
    else:
        cur_len = len(strip_table_placeholder(current_text))
        newly_flagged_by_dedup.append((doc_id, orig_len, cur_len))

print(f"\n원본(1차 수정 전) 기준으로도 300자 미만이었을 문서: {already_flagged}건 (진짜 문제)")
print(f"원본은 300자 이상이었는데 지금(2차 수정 후)은 미만으로 떨어진 문서: "
      f"{len(newly_flagged_by_dedup)}건 (가설 확인 대상)")

print("\n가설 확인 대상 샘플 10건 (원본 표제거후길이 -> 지금 표제거후길이):")
for doc_id, orig_len, cur_len in newly_flagged_by_dedup[:10]:
    print(f"  {doc_id}: {orig_len}자 -> {cur_len}자")
