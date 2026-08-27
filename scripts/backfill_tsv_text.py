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
# **재개(resume) 가능**(2026-08-27 2차 추가): 진행 상황을 별도 체크포인트 파일 없이
# tsv_text 컬럼 자체로 추적함 — tsv_text가 NULL인 행만 골라서 처리하므로, 코랩이
# 끊기거나 중간에 중단해도 다시 실행하면 이미 끝난 행은 건너뛰고 남은 것부터 이어감
# (실패해서 스킵된 행도 tsv_text가 NULL로 남아있어서 다음 실행 때 자동으로 재시도됨).
# 처리 순서가 항상 "성공하면 값을 채움, 실패/미처리는 NULL"이라 이 방식이 안전하게 동작함.
#
# **속도를 미리 가늠하고 싶으면**(2026-08-27, "얼마나 걸릴지 미리 재보고 싶다" 피드백
# 반영) TEST_LIMIT으로 소량만 먼저 돌려서 실측 처리율(코랩↔DB 네트워크 왕복까지 포함한
# 실제 종단간 속도 — 순수 kiwipiepy 연산 속도만으로는 이 왕복 비용을 알 수 없음)을 잰
# 뒤, 그 실측치로 전체 소요 시간을 계산할 것. TEST_LIMIT으로 처리된 행도 정상적으로
# tsv_text가 채워지므로(테스트용 임시 데이터가 아님) 그다음 TEST_LIMIT 없이 다시
# 실행하면 이어서 진행됨 — 낭비되는 시간이 없음.
#
# 실행:
#   DATABASE_URL=postgresql://... python scripts/backfill_tsv_text.py            # DRY_RUN(기본)
#   DRY_RUN=false DATABASE_URL=postgresql://... python scripts/backfill_tsv_text.py  # 실제 반영
#   DRY_RUN=false TEST_LIMIT=5000 DATABASE_URL=... python scripts/backfill_tsv_text.py  # 속도 실측용 소량 실행
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
BATCH_SIZE = 2000  # kiwipiepy 배치 토큰화 + DB UPDATE 배치 크기 (실측: 2,000건 약 3초, num_workers=2 기준 — 순수 연산만, 네트워크 왕복 별도)
TEST_LIMIT = os.environ.get("TEST_LIMIT")  # 설정하면 이번 실행에서 이 건수만 처리(속도 실측용)

if not DATABASE_URL:
    raise SystemExit("DATABASE_URL 환경변수가 필요합니다.")

tokenizer.load_model()

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False

try:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks;")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM chunks WHERE tsv_text IS NULL;")
        remaining = cur.fetchone()[0]
    already_done = total - remaining
    print(f"chunks 전체: {total}건 (이미 처리됨: {already_done}건, 남음: {remaining}건)")
    if already_done:
        print("  → 이전 실행에서 이어감(재개) — tsv_text가 채워진 행은 건너뜀")

    if DRY_RUN:
        if remaining == 0:
            raise SystemExit("\n남은 행이 없습니다 — 이미 전부 처리됨. STEP 2(재색인)로 넘어가면 됩니다.")
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, text FROM chunks WHERE tsv_text IS NULL ORDER BY id LIMIT {SAMPLE_SIZE};"
            )
            rows = cur.fetchall()
        sample_texts = [text for _, text in rows]
        sample_tokens = tokenizer.tokenize_batch(sample_texts)
        print(f"\n[DRY RUN] 샘플 {len(rows)}건 (원문 앞부분 → 토큰화 결과, 아직 처리 안 된 행 기준)")
        for (chunk_id, text), tokens in zip(rows, sample_tokens):
            print(f"  {chunk_id}")
            print(f"    원문: {text[:80]!r}")
            print(f"    토큰: {tokens[:120]!r}")
        raise SystemExit(
            "\nDRY_RUN=True라 여기서 멈춤. 위 샘플이 말이 되면(조사/어미가 빠지고 의미어만 "
            "남았는지) DRY_RUN=False로 바꿔서 다시 실행하세요. 전체 속도가 궁금하면 먼저 "
            "TEST_LIMIT=5000 DRY_RUN=false로 소량만 실행해서 실측 처리율을 재보는 걸 추천."
        )

    if remaining == 0:
        raise SystemExit("\n남은 행이 없습니다 — 이미 전부 처리됨. STEP 2(재색인)로 넘어가면 됩니다.")

    # ------------------------------------------------------------------
    # 실제 반영 — 아직 처리 안 된(tsv_text IS NULL) 행만 한 번에 읽어옴. 재개 실행이면
    # 이미 끝난 행은 SELECT 대상에서 아예 빠지므로 그만큼 이번 실행이 짧아짐(단순히
    # UPDATE만 건너뛰는 게 아니라 조회·토큰화 자체를 안 함).
    # 텍스트 전체를 한 번에 메모리에 올리는 이유(96,355건 규모 × 청크당 수백 바이트
    # 수준이라 메모리 부담 적음, backfill_source_file.py가 jsonl 전체를 dict로 읽어들이는
    # 것과 같은 수준)와 named cursor를 안 쓰는 이유(WITHOUT HOLD라 배치마다 commit하는
    # 구조와 안 맞음)는 이전과 동일.
    # ------------------------------------------------------------------
    with conn.cursor() as setup_cur:
        setup_cur.execute("SET statement_timeout = '300s'")
    select_sql = "SELECT id, text FROM chunks WHERE tsv_text IS NULL ORDER BY id"
    if TEST_LIMIT:
        select_sql += f" LIMIT {int(TEST_LIMIT)}"
        print(f"TEST_LIMIT={TEST_LIMIT} — 속도 실측용으로 이번 실행은 이 건수만 처리함")
    with conn.cursor() as read_cur:
        read_cur.execute(select_sql + ";")
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
        rate = done / elapsed if elapsed > 0 else 0
        print(
            f"  진행: {done}/{len(rows)} (이번 실행 기준, 전체는 {already_done + done}/{total}) "
            f"— 실패 {failed}건 누적, {elapsed:.0f}s 경과, {rate:.0f}건/초"
        )

    elapsed = time.time() - t_start
    rate = done / elapsed if elapsed > 0 else 0
    print(f"\n완료: {done}건 처리, {failed}건 실패(tsv_text NULL로 남음 — 마이그레이션 SQL의 "
          f"COALESCE(tsv_text, text) 안전망으로 원문 기준 색인은 유지됨)")
    # remaining(이번 실행 시작 시점 NULL 개수) - done(이번 실행에서 시도한 개수) +
    # failed(그중 실패해서 여전히 NULL로 남은 개수) — done에는 실패 건도 포함돼 있으므로
    # 그냥 remaining - done만 하면 failed만큼 남은 개수를 실제보다 적게 계산하게 됨.
    still_remaining = remaining - done + failed
    if TEST_LIMIT and still_remaining > 0 and rate > 0:
        eta_min = still_remaining / rate / 60
        print(
            f"\n[TEST_LIMIT 실측] 처리율 {rate:.0f}건/초 — 남은 {still_remaining}건 예상 소요 "
            f"약 {eta_min:.0f}분. TEST_LIMIT 없이 다시 실행하면 방금 처리한 {done}건은 "
            "건너뛰고 이어서 진행됩니다."
        )
    elif still_remaining > 0:
        print(f"\n{still_remaining}건이 아직 안 끝났습니다(중단됐거나 TEST_LIMIT 사용) — 다시 실행하면 이어서 진행됩니다.")
finally:
    conn.close()
