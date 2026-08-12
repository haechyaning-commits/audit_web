# ------------------------------------------------------------------
# 기존 DB에 이미 적재된 documents에 audit_type(감사종류) 소급 반영 (2026-08-12)
# ------------------------------------------------------------------
# 재임베딩과 달리 GPU/모델 필요 없음 — embed_ready_v2.jsonl(Drive)에서 document_id별
# source_file을 읽어 textparse.parse_source_file로 감사종류만 뽑은 뒤 UPDATE 한 번씩.
# 몇 분이면 끝남.
#
# **실행 순서**:
#   1) Railway Query 탭에서 먼저 컬럼 추가(한 번만):
#        ALTER TABLE documents ADD COLUMN IF NOT EXISTS audit_type TEXT;
#   2) 이 파일 내용을 Colab 셀에 그대로 붙여넣어 실행 — DRY_RUN=True로 먼저 돌려서
#      샘플 파싱 결과가 말이 되는지 꼭 확인한 뒤, DRY_RUN=False로 바꿔서 다시 실행
#      (재임베딩 사고 교훈 — DB 반영 전 로컬 검증 먼저).
#   3) 이 스크립트는 이 레포(audit_web) 클론 안에서 실행되는 걸 전제로 함
#      (%cd audit_web 상태에서 scripts.textparse를 import) — 아니면 textparse.py
#      내용을 같은 셀에 그대로 붙여넣어도 됨.
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary

import json
import os

import psycopg2
from scripts.textparse import parse_source_file

BASE = "/content/drive/MyDrive/audit_project/"
EMBED_READY_PATH = BASE + "embed_ready_v2.jsonl"

DRY_RUN = True  # 먼저 True로 돌려서 샘플 확인, 이상 없으면 False로 바꿔서 재실행
SAMPLE_SIZE = 20  # DRY_RUN일 때 몇 건 보여줄지

# ------------------------------------------------------------------
# 1) document_id -> source_file 매핑 (한 문서에 청크가 여러 개라 첫 값만 사용 —
#    build_final_dataset.py의 match_with_chunks()와 동일한 가정)
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

# ------------------------------------------------------------------
# 2) 파싱
# ------------------------------------------------------------------
doc_audit_type: dict[str, str] = {}
parse_failed = 0
for doc_id, sf in doc_source_file.items():
    _, _, audit_type = parse_source_file(sf)
    if audit_type:
        doc_audit_type[doc_id] = audit_type
    else:
        parse_failed += 1

print(f"감사종류 파싱 성공: {len(doc_audit_type)}건 / 실패(패턴 안 맞음): {parse_failed}건")

if DRY_RUN:
    print(f"\n[DRY RUN] 샘플 {SAMPLE_SIZE}건 — source_file -> 파싱 결과")
    for doc_id, sf in list(doc_source_file.items())[:SAMPLE_SIZE]:
        print(f"  {sf!r} -> {parse_source_file(sf)}")
    raise SystemExit(
        "\nDRY_RUN=True라 여기서 멈춤. 위 샘플이 말이 되면 DRY_RUN=False로 바꿔서 다시 실행하세요."
    )

# ------------------------------------------------------------------
# 3) DB UPDATE — 컬럼이 없으면 여기서 에러남(먼저 ALTER TABLE 실행 필요)
# ------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        rows = list(doc_audit_type.items())
        batch_size = 1000
        for i in range(0, len(rows), batch_size):
            batch = [(audit_type, doc_id) for doc_id, audit_type in rows[i:i + batch_size]]
            cur.executemany("UPDATE documents SET audit_type = %s WHERE id = %s", batch)
            conn.commit()
            print(f"  DB 반영: {min(i + batch_size, len(rows))}/{len(rows)}")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents WHERE audit_type IS NOT NULL")
        print(f"\n반영 확인 — audit_type 채워진 문서: {cur.fetchone()[0]}건")
        cur.execute(
            "SELECT audit_type, count(*) FROM documents WHERE audit_type IS NOT NULL "
            "GROUP BY audit_type ORDER BY count(*) DESC LIMIT 20"
        )
        print("감사종류별 상위 20개 분포:")
        for audit_type, cnt in cur.fetchall():
            print(f"  {audit_type}: {cnt}건")
finally:
    conn.close()

print(f"\n완료 — {len(doc_audit_type)}건 audit_type 반영 끝")
