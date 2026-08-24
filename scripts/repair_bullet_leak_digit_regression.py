# ------------------------------------------------------------------
# 긴급 복구: DRY_RUN=False 반영 시 캐시된 구버전 스크립트가 실행된 정황
# (2026-08-24)
# ------------------------------------------------------------------
# 배경: fix_symbol_font_bullet_leak.py에 숫자 바로 뒤는 제외하는 수정을
# 넣었고(정규식 (?<![A-Za-z]) -> (?<![A-Za-z0-9])) DRY_RUN 재확인에서
# documents 248건/chunks 444건으로 정확히 줄어든 걸 확인했는데, 실제
# DRY_RUN=False 반영 결과는 249건/446건 — 수정 전 숫자 그대로 나옴(한국수자원
# 조사기술원도 8건이 아니라 9건). raw.githubusercontent.com의 캐시 때문에
# curl이 방금 푸시한 최신 버전이 아니라 그 이전(숫자 제외 수정 전) 버전을
# 받아왔을 가능성이 높음 — 즉 실제 DB 반영에 구버전 정규식이 쓰였을 것으로
# 추정됨.
#
# 영향 범위는 정확히 알려져 있음: DRY_RUN 재확인 때 "한국수자원조사기술원이
# 9건 -> 8건으로 줄었다"는 것 자체가 그 차이가 문서 eb702631521fc699 딱 하나
# (그리고 그 문서의 유일한 매칭이 "약 2.0m에 위치" 오탐 하나)라는 뜻 —
# 이 문서는 그 오탐 말고 다른 진짜 불릿(m)이 하나도 없었으므로, 이 문서만
# 정확히 원상복구하면 됨(문서 전체를 백업값으로 되돌려도 안전 — 이 문서에서
# 바뀐 부분은 그 한 곳뿐이라는 게 이미 검증됨).
#
# 방금 직전에 실행한 backup_before_fix.py의 백업 jsonl을 그대로 사용해서
# documents.raw_text와 이 문서에 속한 chunks.text를 정확히 원래 값으로 되돌림.
# 되돌린 chunk는 임베딩도 원래 값 그대로 유효하므로 재임베딩 불필요 —
# reembed_input_bullet_fix.jsonl에서 이 chunk id들을 제거한 새 파일도 같이 만듦.
# ------------------------------------------------------------------
import json
import os

import psycopg2

AFFECTED_DOC_ID = "eb702631521fc699"  # 한국수자원조사기술원, "약 2.0m에 위치" 오탐

BACKUP_DIR = "/content/drive/MyDrive/audit_project/backups"
DOCS_BACKUP_PATH = f"{BACKUP_DIR}/documents_raw_text_20260813.jsonl"
CHUNKS_BACKUP_PATH = f"{BACKUP_DIR}/chunks_text_20260813.jsonl"
REEMBED_INPUT_PATH = "/content/drive/MyDrive/audit_project/reembed_input_bullet_fix.jsonl"
REEMBED_INPUT_FIXED_PATH = "/content/drive/MyDrive/audit_project/reembed_input_bullet_fix_v2.jsonl"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)

# ------------------------------------------------------------------
# 1) 방금 뜬 백업에서 이 문서의 원본 raw_text 찾기
# ------------------------------------------------------------------
backup_raw_text = None
with open(DOCS_BACKUP_PATH, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if rec["id"] == AFFECTED_DOC_ID:
            backup_raw_text = rec["raw_text"]
            break

if backup_raw_text is None:
    raise SystemExit(
        f"백업 파일에서 {AFFECTED_DOC_ID}를 못 찾음 — 백업 경로가 맞는지 확인:"
        f" {DOCS_BACKUP_PATH}"
    )

with conn.cursor() as cur:
    cur.execute("SELECT raw_text FROM documents WHERE id = %s", (AFFECTED_DOC_ID,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"documents에서 {AFFECTED_DOC_ID}를 못 찾음")
    current_raw_text = row[0]

print(f"문서 {AFFECTED_DOC_ID}")
print(f"  백업(원본) 길이: {len(backup_raw_text)}자")
print(f"  현재(반영후) 길이: {len(current_raw_text)}자")
if backup_raw_text == current_raw_text:
    print("  -> 이미 동일함(피해 없었던 것으로 보임) — documents는 손댈 필요 없음")
    need_doc_fix = False
else:
    diff = len(backup_raw_text) - len(current_raw_text)
    print(f"  -> 길이 차이 {diff}자 (양수면 현재가 더 짧음 = 뭔가 지워졌다는 뜻)")
    idx = next((i for i in range(min(len(backup_raw_text), len(current_raw_text)))
                if backup_raw_text[i] != current_raw_text[i]), None)
    if idx is not None:
        s, e = max(0, idx - 30), idx + 30
        print(f"  최초로 달라지는 지점 문맥(백업 기준): ...{backup_raw_text[s:e]!r}...")
    need_doc_fix = True

# ------------------------------------------------------------------
# 2) 이 문서에 속한 chunk id 목록 조회 + 백업에서 원본 text 찾기
# ------------------------------------------------------------------
with conn.cursor() as cur:
    cur.execute("SELECT id, text FROM chunks WHERE document_id = %s", (AFFECTED_DOC_ID,))
    current_chunks = dict(cur.fetchall())

chunk_ids = set(current_chunks.keys())
backup_chunk_text = {}
with open(CHUNKS_BACKUP_PATH, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if rec["id"] in chunk_ids:
            backup_chunk_text[rec["id"]] = rec["text"]

chunks_to_fix = [
    (chunk_id, backup_chunk_text[chunk_id])
    for chunk_id in chunk_ids
    if chunk_id in backup_chunk_text and backup_chunk_text[chunk_id] != current_chunks[chunk_id]
]
print(f"\n이 문서에 속한 chunk {len(chunk_ids)}건 중 되돌려야 할 chunk {len(chunks_to_fix)}건")

# ------------------------------------------------------------------
# 3) 실제 복구 (documents.raw_text, chunks.text를 백업값으로 UPDATE)
# ------------------------------------------------------------------
with conn.cursor() as cur:
    if need_doc_fix:
        cur.execute(
            "UPDATE documents SET raw_text = %s WHERE id = %s",
            (backup_raw_text, AFFECTED_DOC_ID),
        )
        print(f"documents.raw_text 복구 완료: {AFFECTED_DOC_ID}")
    for chunk_id, old_text in chunks_to_fix:
        cur.execute("UPDATE chunks SET text = %s WHERE id = %s", (old_text, chunk_id))
    conn.commit()
    print(f"chunks.text 복구 완료: {len(chunks_to_fix)}건")

conn.close()

# ------------------------------------------------------------------
# 4) 재임베딩 목록에서 이 chunk들 제외한 새 파일 생성
#    (텍스트를 원본으로 되돌렸으니 기존 임베딩이 여전히 유효 — 재임베딩 불필요)
# ------------------------------------------------------------------
reverted_chunk_ids = {c for c, _ in chunks_to_fix}
if os.path.exists(REEMBED_INPUT_PATH) and reverted_chunk_ids:
    kept = 0
    removed = 0
    with open(REEMBED_INPUT_PATH, encoding="utf-8") as fin, \
         open(REEMBED_INPUT_FIXED_PATH, "w", encoding="utf-8") as fout:
        for line in fin:
            rec = json.loads(line)
            if rec["chunk_id"] in reverted_chunk_ids:
                removed += 1
                continue
            fout.write(line if line.endswith("\n") else line + "\n")
            kept += 1
    print(f"\n재임베딩 목록 재작성: {REEMBED_INPUT_FIXED_PATH} "
          f"(유지 {kept}건, 제외 {removed}건 — 원본으로 되돌아간 chunk는 재임베딩 불필요)")
    print("-> 이제부터는 reembed_input_bullet_fix.jsonl 대신 "
          "reembed_input_bullet_fix_v2.jsonl을 재임베딩에 사용할 것")
else:
    print("\n재임베딩 목록 파일이 없거나 되돌릴 chunk가 없음 — 건너뜀")

print("\n복구 완료. 반드시 아래 검증도 해볼 것:")
print(f"  SELECT raw_text FROM documents WHERE id = '{AFFECTED_DOC_ID}';")
print("  -> '약 2.0m에 위치하여 부딪힘' 처럼 m이 살아있는지 육안 확인")
