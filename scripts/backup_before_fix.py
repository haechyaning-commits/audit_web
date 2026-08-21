# ------------------------------------------------------------------
# fix_text_corruption.py 실행 전 백업 (2026-08-13, 경량판)
# ------------------------------------------------------------------
# 원래는 `CREATE TABLE ... AS SELECT * FROM chunks`로 테이블째 통째로 복사했는데,
# chunks 테이블에 벡터(임베딩) 컬럼까지 같이 복사되면서 Postgres 볼륨 용량을 거의
# 2배로 잡아먹어 실제로 DiskFull 에러가 났음(Railway Postgres 볼륨 한계 도달).
#
# fix_text_corruption.py가 실제로 건드리는 건 documents.raw_text / chunks.text
# 딱 두 컬럼뿐이라 벡터까지 백업할 필요가 없음 — DB 안에 새 테이블을 만드는 대신
# 그 두 컬럼만 Drive에 jsonl로 스트리밍해서 뺌. Postgres 디스크는 전혀 안 씀(읽기만
# 하고 새로 쓰는 게 없음).
# ------------------------------------------------------------------
import json
import os

import psycopg2

BACKUP_DIR = "/content/drive/MyDrive/audit_project/backups"


def export_column(conn, table: str, col: str, out_path: str) -> int:
    """서버사이드 커서로 한 줄씩 스트리밍 — 전체를 메모리에 한 번에 안 올림."""
    n = 0
    with conn.cursor(name=f"backup_{table}_{col}") as cur:
        cur.itersize = 2000
        cur.execute(f"SELECT id, {col} FROM {table}")
        with open(out_path, "w", encoding="utf-8") as f:
            for row_id, val in cur:
                f.write(json.dumps({"id": row_id, col: val}, ensure_ascii=False) + "\n")
                n += 1
    return n


if __name__ == "__main__":
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        from google.colab import userdata

        DATABASE_URL = userdata.get("DATABASE_URL")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        for table, col in [("documents", "raw_text"), ("chunks", "text")]:
            out_path = f"{BACKUP_DIR}/{table}_{col}_20260813.jsonl"
            n = export_column(conn, table, col, out_path)
            print(f"{table}.{col} 백업 완료: {n}건 -> {out_path}")
    finally:
        conn.close()
    print("\n백업 완료 — Postgres 디스크는 전혀 안 썼습니다(읽기만 함, 새 테이블 없음)")
