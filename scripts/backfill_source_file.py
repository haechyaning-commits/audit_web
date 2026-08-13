# ------------------------------------------------------------------
# 기존 DB에 이미 적재된 documents에 source_file 소급 반영 (2026-08-13)
# ------------------------------------------------------------------
# backfill_audit_type.py와 완전히 같은 패턴 — GPU/모델 필요 없음. embed_ready_v2.jsonl
# (Drive)에서 document_id별 source_file을 읽어 UPDATE 한 번씩만 하면 됨(파싱 불필요,
# 원본 경로 그대로 저장 — GitHub raw 링크로 바꾸는 건 backend/app/textutils.py의
# build_source_url()이 응답 내려줄 때 함). 몇 분이면 끝남.
#
# 이 컬럼이 채워지면 상세페이지에 "원본 파일 보기"(GitHub raw PDF/HWP) 링크 버튼이 뜸
# (STATUS.md "원본 파일(GitHub) 하이퍼링크" 항목).
#
# **실행 순서**:
#   1) Railway Query 탭에서 먼저 컬럼 추가(한 번만, 이미 schema_tables.sql에도 반영해둠):
#        ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_file TEXT;
#      -> 이 ALTER가 끝나기 전에는 backend를 재배포하면 안 됨(상세페이지 API가 이
#         컬럼을 SELECT하므로, 컬럼 없이 배포하면 /documents/{id}가 전부 500 남).
#   2) 이 파일 내용을 Colab 셀에 그대로 붙여넣어 실행 — DRY_RUN=True로 먼저 돌려서
#      샘플이 말이 되는지 꼭 확인한 뒤, DRY_RUN=False로 바꿔서 다시 실행(재임베딩 사고
#      교훈 — DB 반영 전 로컬 검증 먼저).
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary

import json
import os

import psycopg2

BASE = "/content/drive/MyDrive/audit_project/"
EMBED_READY_PATH = BASE + "embed_ready_v2.jsonl"

DRY_RUN = True  # 먼저 True로 돌려서 샘플 확인, 이상 없으면 False로 바꿔서 재실행
SAMPLE_SIZE = 20  # DRY_RUN일 때 몇 건 보여줄지

# ------------------------------------------------------------------
# 1) document_id -> source_file 매핑 (한 문서에 청크가 여러 개라 첫 값만 사용 —
#    build_final_dataset.py의 match_with_chunks()와 동일한 가정, backfill_audit_type.py와 동일)
# ------------------------------------------------------------------
doc_source_file: dict[str, str] = {}
with open(EMBED_READY_PATH, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        doc_id = rec["document_id"]
        if doc_id not in doc_source_file:
            sf = rec.get("source_file")
            if sf:
                doc_source_file[doc_id] = sf

print(f"source_file 있는 문서: {len(doc_source_file)}건")

if DRY_RUN:
    print(f"\n[DRY RUN] 샘플 {SAMPLE_SIZE}건")
    for doc_id, sf in list(doc_source_file.items())[:SAMPLE_SIZE]:
        print(f"  {doc_id} -> {sf!r}")
    raise SystemExit(
        "\nDRY_RUN=True라 여기서 멈춤. 위 샘플이 말이 되면 DRY_RUN=False로 바꿔서 다시 실행하세요."
    )

# ------------------------------------------------------------------
# 2) DB UPDATE — 컬럼이 없으면 여기서 에러남(먼저 ALTER TABLE 실행 필요)
# ------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        rows = list(doc_source_file.items())
        batch_size = 1000
        for i in range(0, len(rows), batch_size):
            batch = [(sf, doc_id) for doc_id, sf in rows[i:i + batch_size]]
            cur.executemany("UPDATE documents SET source_file = %s WHERE id = %s", batch)
            conn.commit()
            print(f"  DB 반영: {min(i + batch_size, len(rows))}/{len(rows)}")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents WHERE source_file IS NOT NULL")
        print(f"\n반영 확인 — source_file 채워진 문서: {cur.fetchone()[0]}건")
        cur.execute("SELECT id, source_file FROM documents WHERE source_file IS NOT NULL LIMIT 3")
        print("샘플 3건:")
        for doc_id, sf in cur.fetchall():
            print(f"  {doc_id} -> {sf!r}")
finally:
    conn.close()

print(f"\n완료 — {len(doc_source_file)}건 source_file 반영 끝")
