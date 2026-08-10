# ------------------------------------------------------------------
# table_placeholder_only 판정 급증 원인 조사 (2026-08-10)
# ------------------------------------------------------------------
# remove_unrecoverable_docs.py의 find_unrecoverable()이 예상(1,765건, 2026-08-07
# 진단 기준)보다 훨씬 많은 5,162건을 찾아냄 — 특히 table_placeholder_only가
# 1,674건 예상 대비 5,046건으로 급증.
#
# 가설: table_placeholder_only 판정 기준(strip_table_placeholder 적용 후
# 300자 미만)을 2026-08-07 원래 진단 때는 "수정 전(글자/숫자 중복이 그대로
# 남아있는) raw_text"로 쟀는데, 지금 find_unrecoverable()은 "1차+2차 수정까지
# 다 반영된(글자/숫자 중복이 collapse된) raw_text"로 재는 바람에, 중복 글자로
# 부풀려져 있던 문서들이 dedup 이후 실제 분량이 드러나면서 300자 밑으로 새로
# 떨어진 게 아닌가 하는 것.
#
# 검증 방법: 원래는 documents_backup_20260807(1차 수정 전 원본 백업)과 비교할
# 계획이었으나, 디스크 부족 해결 과정에서 백업 테이블을 이미 삭제함 (2026-08-10).
# 대신 documents_final.jsonl(load_to_postgres.py가 최초 적재 때 썼던 원본
# 파일, DB 적재 전이라 어떤 수정도 안 거친 상태 — 백업 테이블보다도 더 순수한
# 원본)로 대체. DB 접속 자체가 필요 없어서 지금 진행 중인 다른 DB 작업과
# 안 부딪힘.
# ------------------------------------------------------------------

import json
import re

# 원본 파일 경로 — load_to_postgres.py의 BASE와 동일 관례. 실제 Drive 구조가
# 다르면 이 경로만 맞게 수정할 것.
DOCUMENTS_FINAL_PATH = "/content/drive/MyDrive/audit_project/documents_final.jsonl"


def strip_table_placeholder(text: str) -> str:
    lines = [line for line in text.split("\n") if line.strip() != "표"]
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# 1) 방금 만든 manifest에서 table_placeholder_only인 id만 로드
now_ids = set()
with open("removed_unrecoverable_docs.jsonl", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if rec["reason"] == "table_placeholder_only":
            now_ids.add(rec["id"])
print(f"지금 table_placeholder_only로 잡힌 문서: {len(now_ids)}건")

# 2) documents_final.jsonl(수정 전 원본)에서 같은 id의 raw_text 찾기
orig_texts = {}
with open(DOCUMENTS_FINAL_PATH, encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        if d["id"] in now_ids:
            orig_texts[d["id"]] = d["raw_text"]

print(f"원본 파일에서 매칭된 문서: {len(orig_texts)}건 (전체 {len(now_ids)}건 중)")
if len(orig_texts) < len(now_ids):
    print(f"  [주의] {len(now_ids) - len(orig_texts)}건은 원본 파일에 없음 — 별도 확인 필요")

# 3) 원본(수정 전) 기준으로도 300자 미만이었을지 재계산해서 비교
already_flagged = 0          # 원본에서도 어차피 걸렸을 것 (가설과 무관, 진짜 문제)
newly_flagged_by_dedup = []  # 원본은 300자 이상이었는데 지금은 미만 (가설 확인 대상)

for doc_id, original_text in orig_texts.items():
    orig_len = len(strip_table_placeholder(original_text))
    if orig_len < 300:
        already_flagged += 1
    else:
        newly_flagged_by_dedup.append((doc_id, orig_len))

print(f"\n원본(수정 전) 기준으로도 300자 미만이었을 문서: {already_flagged}건 (진짜 문제)")
print(f"원본은 300자 이상이었는데 지금(수정 후)은 미만으로 떨어진 문서: "
      f"{len(newly_flagged_by_dedup)}건 (가설 확인 대상)")

print("\n가설 확인 대상 샘플 10건 (원본에서 표제거후 길이):")
for doc_id, orig_len in newly_flagged_by_dedup[:10]:
    print(f"  {doc_id}: {orig_len}자")
