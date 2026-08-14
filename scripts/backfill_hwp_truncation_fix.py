# ------------------------------------------------------------------
# HWP 원문 잘림(1,000자 캡) 복구 반영 (2026-08-14)
# ------------------------------------------------------------------
# 배경: documents 중 HWP류(.hwp/.hwpx) 37,631건 중 5,405건이 raw_text 길이
# 900~1020자 근처에 비정상적으로 몰려있던 것 확인(원래 파이프라인이 HWP "미리보기
# 텍스트" 길이 제한을 본문으로 잘못 쓴 것으로 추정) — `scripts/audit_hwp_truncation_extract.py`로
# 원본 HWP/HWPX 파일 재다운로드해서 전체 텍스트 재추출(5,389건 성공, 16건 실패는 그대로 둠),
# HTML 엔티티(&lt; 등) 복원 + HWP 전용 특수문자([코드]로 치환) 정리까지 마친
# `hwp_truncation_checkpoint_cleaned.jsonl`을 이 스크립트가 DB에 반영함.
#
# 순증가량 약 108MB(5.2MB -> 113.2MB) — documents.raw_text는 인덱스가 안 걸려있어서
# (인덱스는 chunks 테이블에만 있음, schema_indexes.sql 참고) 인덱스 재구축 부담 없음.
# 그래도 5,389건이라 batch + execute_values로 나눠서 반영(재임베딩 사고 이후 정착된
# "1건씩 왕복" 대신 "여러 건 한 왕복" 패턴, backfill_audit_type.py 등과 동일).
#
# **실행 순서**:
#   1) DRY_RUN=True로 먼저 돌려서 DB의 현재 raw_text가 old_raw_text와 일치하는지
#      전수 확인 (일치 안 하면 그 문서는 자동으로 건너뜀 — 안전장치).
#   2) 이상 없으면 DRY_RUN=False로 재실행.
#   3) chunks 재임베딩은 이 스크립트 범위 밖(별도 진행 — raw_text 길이가 완전히
#      달라져서 청크 재분할부터 다시 해야 함, 규모가 크므로 별도로 시간 잡고 진행할 것).
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary

import json
import os

import psycopg2
from psycopg2.extras import execute_values

CLEANED_PATH = "/content/drive/MyDrive/audit_project/hwp_truncation_checkpoint_cleaned.jsonl"

DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로

DATABASE_URL = None
try:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_PUBLIC_URL")
except Exception:
    pass
if not DATABASE_URL:
    DATABASE_URL = os.environ.get("DATABASE_URL")

records = []
with open(CLEANED_PATH, encoding="utf-8") as f:
    for line in f:
        records.append(json.loads(line))

ok_records = [r for r in records if r["status"] == "ok"]
print(f"반영 대상(성공한 것): {len(ok_records)}건")

conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '60s'")

        # 현재 DB의 raw_text를 한 번에 조회해서 old_raw_text와 일치하는지 확인
        ids = [r["id"] for r in ok_records]
        cur.execute("SELECT id, raw_text FROM documents WHERE id = ANY(%s)", (ids,))
        current = dict(cur.fetchall())

        to_update = []
        mismatched = []
        for r in ok_records:
            current_text = current.get(r["id"])
            if current_text is None:
                mismatched.append((r["id"], "문서 없음"))
            elif current_text != r["old_raw_text"]:
                mismatched.append((r["id"], "raw_text가 예상과 다름(건너뜀)"))
            else:
                to_update.append((r["id"], r["new_raw_text"]))

        print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}반영{'예정' if DRY_RUN else ''}: {len(to_update)}건")
        print(f"건너뜀: {len(mismatched)}건")
        for doc_id, reason in mismatched[:20]:
            print(f"  {doc_id}: {reason}")

        if DRY_RUN:
            raise SystemExit(
                "\nDRY_RUN=True라 여기서 멈춤(실제 UPDATE 안 함). "
                f"위 결과가 기대(반영예정 {len(ok_records)}건 근처, 건너뜀 적음)와 같으면 "
                "DRY_RUN=False로 바꿔서 다시 실행하세요."
            )

        batch_size = 500
        for i in range(0, len(to_update), batch_size):
            batch = to_update[i:i + batch_size]
            execute_values(
                cur,
                "UPDATE documents SET raw_text = data.new_text "
                "FROM (VALUES %s) AS data(id, new_text) "
                "WHERE documents.id = data.id",
                batch,
            )
            conn.commit()
            print(f"  DB 반영: {min(i + batch_size, len(to_update))}/{len(to_update)}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, institution, year, length(raw_text) FROM documents WHERE id = ANY(%s) LIMIT 3",
            (ids[:3],),
        )
        print("\n반영 확인 샘플 3건:")
        for doc_id, institution, year, length in cur.fetchall():
            print(f"  {doc_id} | {institution} {year} | 길이 {length}")
finally:
    conn.close()

print(f"\n완료 — {len(to_update)}건 raw_text 반영 끝")
