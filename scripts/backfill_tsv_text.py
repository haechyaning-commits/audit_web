# ------------------------------------------------------------------
# chunks.tsv_text 배치 백필 — 한국어 형태소 토큰화 (architecture.md §3.6, 2026-08-27)
# ------------------------------------------------------------------
# backfill_source_file.py와 같은 패턴(DRY_RUN 우선 확인 → 반영)이지만, 그쪽은
# Drive jsonl에서 값을 읽어오는 데 비해 이 스크립트는 DB에 이미 있는 chunks.text를
# 직접 읽어서 형태소 분석 후 같은 DB에 다시 써넣음 — 별도 원본 파일이 필요 없음.
#
# **실행 전제**: scripts/tsv_text_migration.sql의 STEP 1(ALTER TABLE ... ADD COLUMN
# tsv_text)이 먼저 실행돼 있어야 함. 이 스크립트가 끝난 뒤에는 같은 파일의 STEP 2를
# 실행해서 tsv 생성 컬럼/GIN 인덱스를 tsv_text 기준으로 교체할 것.
#
# **실행 위치**: 이 저장소(backend/app/tokenizer.py)를 그대로 import해서 쓰므로,
# generate_sitemap.py와 마찬가지로 이 저장소 클론 루트에서 실행하는 걸 전제로 함
# (Colab이면 이 repo를 클론해두고 그 경로에서 실행 — Drive 경로 기준이 아님).
# kiwipiepy는 backend/requirements.txt에 이미 있음(2026-08-27 추가, pip install kiwipiepy).
#
# 실행:
#   DATABASE_URL=postgresql://... python scripts/backfill_tsv_text.py            # DRY_RUN(기본)
#   DRY_RUN=false DATABASE_URL=postgresql://... python scripts/backfill_tsv_text.py  # 실제 반영
# ------------------------------------------------------------------
import os
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from app import tokenizer  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"
SAMPLE_SIZE = 20  # DRY_RUN일 때 몇 건 보여줄지
BATCH_SIZE = 2000  # kiwipiepy 배치 토큰화 + DB UPDATE 배치 크기 (실측: 2,000건 약 3초, num_workers=2 기준)

if not DATABASE_URL:
    raise SystemExit("DATABASE_URL 환경변수가 필요합니다.")

tokenizer.load_model()

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False

try:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks;")
        total = cur.fetchone()[0]
    print(f"chunks 전체: {total}건")

    if DRY_RUN:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id, text FROM chunks ORDER BY id LIMIT {SAMPLE_SIZE};")
            rows = cur.fetchall()
        sample_texts = [text for _, text in rows]
        sample_tokens = tokenizer.tokenize_batch(sample_texts)
        print(f"\n[DRY RUN] 샘플 {len(rows)}건 (원문 앞부분 → 토큰화 결과)")
        for (chunk_id, text), tokens in zip(rows, sample_tokens):
            print(f"  {chunk_id}")
            print(f"    원문: {text[:80]!r}")
            print(f"    토큰: {tokens[:120]!r}")
        raise SystemExit(
            "\nDRY_RUN=True라 여기서 멈춤. 위 샘플이 말이 되면(조사/어미가 빠지고 의미어만 "
            "남았는지) DRY_RUN=False로 바꿔서 다시 실행하세요."
        )

    # ------------------------------------------------------------------
    # 실제 반영 — 먼저 (id, text) 전체를 한 번에 읽어옴(96,355건 × 청크 하나당 수백 바이트
    # 수준이라 메모리 부담 적음, backfill_source_file.py가 jsonl 전체를 dict로 읽어들이는
    # 것과 같은 수준). Postgres named cursor(서버 사이드 스트리밍)는 기본적으로
    # WITHOUT HOLD라 트랜잭션 commit 시 커서가 닫혀버려서, 배치마다 commit하는 이
    # 스크립트 구조와는 안 맞음 — 그래서 안 씀. 토큰화·UPDATE·commit만 BATCH_SIZE
    # 단위로 반복.
    # ------------------------------------------------------------------
    with conn.cursor() as setup_cur:
        setup_cur.execute("SET statement_timeout = '300s'")
    with conn.cursor() as read_cur:
        read_cur.execute("SELECT id, text FROM chunks ORDER BY id;")
        rows = read_cur.fetchall()
    conn.commit()  # 읽기 트랜잭션 정리
    print(f"조회 완료: {len(rows)}건 (메모리에 적재)")

    done = 0
    failed = 0
    t_start = time.time()
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        ids = [r[0] for r in batch]
        texts = [r[1] or "" for r in batch]
        try:
            tokens_list = tokenizer.tokenize_batch(texts)
        except Exception as e:
            # 배치 전체가 실패하면(예: 특정 텍스트가 kiwipiepy를 죽이는 극단적 케이스)
            # 한 건씩 재시도해서 그 문제 청크만 건너뜀 — build_final_dataset.py의
            # "실패 건만 스킵 + 카운트 로그" 관례와 동일.
            print(f"  배치 토큰화 실패, 건별 재시도: {e}")
            tokens_list = []
            for cid, t in zip(ids, texts):
                try:
                    tokens_list.append(tokenizer.tokenize(t))
                except Exception:
                    tokens_list.append(None)
                    failed += 1
                    print(f"    실패(스킵): chunk_id={cid}")

        update_rows = [(tok, cid) for cid, tok in zip(ids, tokens_list) if tok is not None]
        with conn.cursor() as write_cur:
            psycopg2.extras.execute_batch(
                write_cur, "UPDATE chunks SET tsv_text = %s WHERE id = %s;", update_rows
            )
        conn.commit()
        done += len(batch)
        elapsed = time.time() - t_start
        print(f"  진행: {done}/{total} (실패 {failed}건 누적, {elapsed:.0f}s 경과)")

    print(f"\n완료: {done}건 처리, {failed}건 실패(tsv_text NULL로 남음 — 마이그레이션 SQL의 "
          f"COALESCE(tsv_text, text) 안전망으로 원문 기준 색인은 유지됨)")
finally:
    conn.close()
