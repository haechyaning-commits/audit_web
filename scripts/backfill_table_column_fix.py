# ------------------------------------------------------------------
# 표 컬럼 뒤섞임(서울대학교치과병원류 "연번/지적사항/처분" 3단 표 양식) 복구 (2026-08-14)
# ------------------------------------------------------------------
# backfill_source_file.py와 같은 패턴 — GPU/모델 필요 없음, 순수 텍스트 UPDATE만.
#
# 배경: `scripts/audit_table_column_interleave.py`로 찾은 49건 중, 원본 PDF를
# pdfplumber로 다시 읽어 표를 정확히 재추출한 뒤(코드 샌드박스 세션에서 수행),
# DB의 raw_text 안에서 뒤섞인 표 부분만 찾아 교체한 결과를 이 스크립트가 반영함.
# 이 스크립트 자체는 텍스트 재구성 로직을 담지 않음 — 이미 계산된 old/new 쌍을
# JSON에서 읽어 UPDATE만 함(재구성 로직/PDF는 이 세션 밖 별도 작업, STATUS.md 참고).
#
# 43건 확정(사용자가 diff 파일 직접 검토 후 전부 승인, 2026-08-14) — 매칭 안 된 나머지
# 6건(한국소비자원 3건, 한국세라믹기술원 3건, 다른 표 양식이라 이번 로직 미적용)은 별도.
#
# **실행 순서**:
#   1) table_fix_updates.json 파일을 Colab `/content/`에 업로드(왼쪽 파일 탐색기에
#      드래그, 또는 `files.upload()`) — doc_id별 {old_raw_text, new_raw_text} 쌍 포함,
#      old_raw_text가 DB의 현재 값과 다르면 그 문서는 건너뜀(안전장치 — 그 사이에 다른
#      수정이 들어갔을 가능성 대비).
#   2) 이 파일 내용을 Colab 셀에 그대로 붙여넣어 실행 — DRY_RUN=True로 먼저 돌려서
#      "DB의 현재 raw_text가 old_raw_text와 일치하는지" 확인, 이상 없으면 DRY_RUN=False로.
#   3) 43건뿐이라 WAL/디스크 부담 거의 없음 — 인덱스 DROP 같은 것 불필요.
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary

import json

import psycopg2

UPDATES_PATH = "/content/table_fix_updates.json"

DRY_RUN = True  # 먼저 True로 돌려서 old_raw_text 일치 여부 확인, 이상 없으면 False로

with open(UPDATES_PATH, encoding="utf-8") as f:
    updates = json.load(f)

print(f"반영 대상: {len(updates)}건")

DATABASE_URL = None
try:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_PUBLIC_URL")
except Exception:
    pass
if not DATABASE_URL:
    import os

    DATABASE_URL = os.environ.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '60s'")

        mismatched = []
        applied = 0
        for doc_id, rec in updates.items():
            cur.execute("SELECT raw_text FROM documents WHERE id = %s", (doc_id,))
            row = cur.fetchone()
            if row is None:
                mismatched.append((doc_id, "문서 없음"))
                continue
            current_raw_text = row[0]
            if current_raw_text != rec["old_raw_text"]:
                mismatched.append((doc_id, "raw_text가 예상과 다름(건너뜀)"))
                continue

            if DRY_RUN:
                applied += 1
                continue

            cur.execute(
                "UPDATE documents SET raw_text = %s WHERE id = %s",
                (rec["new_raw_text"], doc_id),
            )
            applied += 1

        if not DRY_RUN:
            conn.commit()

    print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}정상 반영{'예정' if DRY_RUN else '완료'}: {applied}건")
    if mismatched:
        print(f"건너뜀: {len(mismatched)}건")
        for doc_id, reason in mismatched:
            print(f"  {doc_id}: {reason}")

    if DRY_RUN:
        raise SystemExit(
            "\nDRY_RUN=True라 여기서 멈춤(실제 UPDATE 안 함). "
            "위 결과가 기대(43건 반영예정, 건너뜀 0건)와 같으면 DRY_RUN=False로 바꿔서 다시 실행하세요."
        )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, institution, year, raw_text FROM documents WHERE id = ANY(%s) LIMIT 3",
            (list(updates.keys())[:3],),
        )
        print("\n반영 확인 샘플 3건:")
        for doc_id, institution, year, raw_text in cur.fetchall():
            print(f"  {doc_id} | {institution} {year}")
            print(f"    {raw_text[:200]!r}")
finally:
    conn.close()

print(f"\n완료 — {applied}건 raw_text 반영 끝")
