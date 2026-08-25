# ------------------------------------------------------------------
# 구버전 HWP 표 내용 손실 실태 조사 — 전수(모집단 전체) 버전 (2026-08-24)
# ------------------------------------------------------------------
# 배경: audit_hwp_table_loss.py(8/18)가 표본 3,426건으로 규모를 확인했고,
# rechunk_reembed_hwp_table_fix.py(8/19)가 그 표본 중 affected=true 1,730건을
# 대상으로 실제로 1,559건 반영까지 끝냄(STATUS.md 8/19 참고). 표본 밖 나머지
# 모집단(.hwp 전체 약 33,089건 중 약 29,663건)은 아직 확인 안 된 상태 —
# 표본 영향률(50.5%)을 적용하면 추가로 1만 건 이상 영향받았을 것으로 추정됨.
#
# 이 스크립트는 원본 audit_hwp_table_loss.py와 로직은 완전히 동일하고 딱
# 두 가지만 다름:
#   1) RANDOM_SAMPLE_SIZE = None — 표본이 아니라 .hwp 전체를 스캔
#   2) CHECKPOINT_PATH가 새 파일(hwp_table_loss_full_checkpoint.jsonl) —
#      기존 8/18 체크포인트를 재사용하면 "이미 처리됨"으로 건너뛰면서, 그때
#      기록된 affected 판정을 그대로 믿게 됨. 그런데 그 판정은 8/19 수정
#      **이전**(DB raw_text에 아직 표 내용이 없던 시점)의 스냅샷이라, 이미
#      고쳐진 1,559건을 다시 "영향받음"으로 잘못 셀 위험이 있음. 새 체크포인트로
#      돌리면 db_has_table_trace를 지금(수정 후) DB 상태로 새로 판정하므로,
#      이미 고쳐진 문서는 raw_text에 "|" 흔적이 있어서 자동으로 affected=false로
#      나옴(별도 제외 로직 불필요 — 휴리스틱 자체가 이미 고쳐진 건 걸러줌).
#
# **실행 후**: 여기서 나온 새 체크포인트 파일을 `rechunk_reembed_hwp_table_fix.py`의
# CANDIDATE_CHECKPOINT_PATH로 지정해서 그대로 이어서 실행하면(DRY_RUN=True로
# 먼저) 표본 밖에서 새로 발견된 영향 문서들만 자동반영/수동검토로 갈림.
#
# 원본 스크립트 설명(문제 원인 등)은 audit_hwp_table_loss.py 상단 참고 —
# 전수조사 시 걸리는 시간만 다름(8/18 실측: 25분에 2,000건, 3만건 전체면
# 대략 5~6시간 예상 — Colab 런타임 연결 유지하고 오래 기다리거나, 체크포인트
# 이어쓰기를 활용해 여러 세션에 나눠 돌려도 됨).
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary requests

import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import requests


def _ensure_hwp5txt():
    # 2026-08-25: 진단 스크립트(audit_hwp5txt_env_check.py)로 hwp5txt 설치를
    # 확인했던 세션과 실제 이 전수조사를 돌린 세션이 서로 다른 Colab 런타임이라
    # pyhwp가 그 세션엔 없는 채로 33,089건 전부
    # "[Errno 2] No such file or directory: 'hwp5txt'"로 에러난 사고 이후 추가.
    # 진단 스크립트를 먼저 돌렸는지 여부와 무관하게 이 스크립트 자체가 매번
    # 스스로 확인/설치해서, 어느 세션에서 바로 실행해도 안전하게 함.
    if shutil.which("hwp5txt"):
        return
    print("hwp5txt가 PATH에 없음 — 설치 시도 중 (setuptools<60 → pyhwp → setuptools<82)...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "setuptools<60", "pyhwp"],
        check=False,
    )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-qU", "setuptools<82"],
        check=False,
    )
    if not shutil.which("hwp5txt"):
        raise SystemExit(
            "hwp5txt 자동 설치 실패 — audit_hwp5txt_env_check.py를 먼저 돌려서 "
            "pip 설치 로그를 확인할 것. 이 상태로 전수조사를 강행하면 8/25처럼 "
            "33,089건 전부가 에러로 새어 시간만 날리게 됨."
        )
    print("hwp5txt 설치 확인됨 — 이어서 진행.")


_ensure_hwp5txt()

# 2026-08-18: 처음엔 서브프로세스 실행이 있어서 PDF 스크립트(16)보다 낮게(8) 잡았는데,
# 실측해보니 hwp5txt 1건 처리에 ~0.29초라 딱히 낮출 이유가 없었음(서브프로세스는 GIL을
# 안 잡고 있으니 동시성을 올려도 무방) — PDF 스크립트보다 오히려 살짝 높여서 24로 설정.
#
# 2026-08-18 추가: 실제 3만건 규모로 돌려보니 25분에 2,000건(진행률로 보면 완주까지
# 5시간 이상)으로 예상보다 훨씬 느렸음 — 워커 수 문제가 아니라 아래 requests.get()을
# 매 요청마다 새로 호출해서 스레드마다 jsdelivr CDN과 TCP+TLS 핸드셰이크를 새로 맺고
# 있었던 게 원인으로 추정(연결 재사용 안 됨). requests.Session + HTTPAdapter로 커넥션
# 풀을 공유하도록 고치고, 워커도 48로 상향.
DOWNLOAD_WORKERS = 48
# 2026-08-24: 8/18 표본조사 체크포인트와 다른 새 파일 — 위 상단 주석 참고
# (기존 체크포인트를 재사용하면 8/19 수정 이전 스냅샷의 affected 판정을 그대로
# 믿게 돼서, 이미 고쳐진 1,559건을 다시 "영향받음"으로 잘못 셀 위험이 있음).
CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/hwp_table_loss_full_checkpoint.jsonl"

_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(
    pool_connections=DOWNLOAD_WORKERS, pool_maxsize=DOWNLOAD_WORKERS, max_retries=2
)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    try:
        from google.colab import userdata
        DATABASE_URL = userdata.get("DATABASE_URL")
    except Exception:
        pass
if not DATABASE_URL:
    try:
        from google.colab import userdata
        DATABASE_URL = userdata.get("DATABASE_PUBLIC_URL")
    except Exception:
        pass
if not DATABASE_URL:
    raise SystemExit(
        "\nDATABASE_URL을 찾을 수 없습니다. Colab 좌측 열쇠(Secrets) 아이콘에서 "
        "\"DATABASE_URL\" Secret이 등록돼 있는지 확인하세요."
    )

_SOURCE_REPO_RAW_BASE = "https://cdn.jsdelivr.net/gh/haechyaning-commits/data@main/"
_SOURCE_FILE_PREFIX = "data_repo/"


def build_source_url(source_file):
    if not source_file:
        return None
    path = source_file.strip()
    if path.startswith(_SOURCE_FILE_PREFIX):
        path = path[len(_SOURCE_FILE_PREFIX):]
    path = path.strip("/")
    if not path:
        return None
    encoded = "/".join(urllib.parse.quote(seg) for seg in path.split("/"))
    return _SOURCE_REPO_RAW_BASE + encoded


def _check_one(doc_id, institution, year, source_file, raw_text):
    url = build_source_url(source_file)
    if not url:
        return {"id": doc_id, "error": "source_file 없음/URL 변환 실패"}
    try:
        resp = _session.get(url, timeout=30)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name
        try:
            proc = subprocess.run(
                ["hwp5txt", tmp_path], capture_output=True, text=True, timeout=60
            )
            # 2026-08-24: returncode를 체크 안 하면 hwp5txt가 내부에서 죽어도(예:
            # pkgutil.ImpImporter AttributeError — setuptools/Python 3.12 버전
            # 문제, STATUS.md 8/19 참고) stdout이 그냥 빈 문자열이라 예외 없이
            # "표 0개"로 조용히 기록됨. 실제로 이번 전수조사(8/24)에서 32,752건
            # 전부가 n_table_markers=0으로 나와서 발견 — 8/18 표본에선 같은
            # 로직으로 50.5%가 잡혔었으니 로직 버그가 아니라 이번 런타임에서
            # hwp5txt 자체가 매번 실패했던 것. 이제 실패 시 바로 에러로 잡히게 함.
            if proc.returncode != 0:
                raise RuntimeError(
                    f"hwp5txt exit={proc.returncode}: {(proc.stderr or '').strip()[:300]}"
                )
            fresh_text = proc.stdout
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        return {"id": doc_id, "institution": institution, "year": year, "error": str(e)}

    n_table_markers = fresh_text.count("<표>")
    n_pic_markers = fresh_text.count("<그림>")
    # DB raw_text에 표 흔적이 있는지 — 마커가 그대로 남아있거나(설계상 없어야
    # 정상이지만 혹시 몰라 체크), 표 형태로 보이는 "|" 구분자가 있으면 이미
    # 어떤 식으로든 표 내용이 반영된 것으로 봄
    db_has_table_trace = bool(raw_text) and (
        "<표>" in raw_text or "[표]" in raw_text or raw_text.count("|") >= 3
    )

    return {
        "id": doc_id,
        "institution": institution,
        "year": year,
        "n_table_markers": n_table_markers,
        "n_pic_markers": n_pic_markers,
        "db_has_table_trace": db_has_table_trace,
        "affected": n_table_markers > 0 and not db_has_table_trace,
    }


conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute(
        "SELECT id, institution, year, source_file, raw_text FROM documents "
        "WHERE source_file IS NOT NULL AND source_file ILIKE '%%.hwp' "
        "AND source_file NOT ILIKE '%%.hwpx'"
    )
    doc_rows = cur.fetchall()
conn.close()
TOTAL_HWP_DOCS = len(doc_rows)  # 표본추출 전 실제 모집단 크기 — 최종 리포트에서 사용
print(f"대상 .hwp 문서: {TOTAL_HWP_DOCS}건")

done = {}
if os.path.exists(CHECKPOINT_PATH):
    import json
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            done[rec["id"]] = rec
    print(f"체크포인트에서 {len(done)}건 이미 처리된 것 발견 — 이어서 진행")

# 2026-08-24: 이번엔 표본이 아니라 전수 확인이 목적이라 None — 위 상단 주석 참고.
RANDOM_SAMPLE_SIZE = None

if RANDOM_SAMPLE_SIZE and len(doc_rows) > RANDOM_SAMPLE_SIZE:
    random.seed(42)  # 재현 가능하도록 고정
    already = [r for r in doc_rows if r[0] in done]
    remaining_pool = [r for r in doc_rows if r[0] not in done]
    fill_n = max(0, RANDOM_SAMPLE_SIZE - len(already))
    sampled_remaining = random.sample(remaining_pool, min(fill_n, len(remaining_pool)))
    doc_rows = already + sampled_remaining
    print(
        f"무작위 표본 {len(doc_rows)}건으로 축소해서 조사(전수조사 아님 — 비율 추정용, "
        f"이미 처리된 {len(already)}건은 표본에 포함해 재사용)"
    )

todo = [r for r in doc_rows if r[0] not in done]
print(f"남은 {len(todo)}건을 {DOWNLOAD_WORKERS}개 동시 처리로 진행")

import json as _json

os.makedirs(os.path.dirname(CHECKPOINT_PATH), exist_ok=True)
checkpoint_f = open(CHECKPOINT_PATH, "a", encoding="utf-8")
print_lock = threading.Lock()
n_done = 0
errors = 0

with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
    futures = [pool.submit(_check_one, *row) for row in todo]
    for fut in as_completed(futures):
        result = fut.result()
        with print_lock:
            checkpoint_f.write(_json.dumps(result, ensure_ascii=False) + "\n")
            checkpoint_f.flush()
            done[result["id"]] = result
            n_done += 1
            if result.get("error"):
                errors += 1
            if n_done % 20 == 0 or n_done == len(todo):
                affected_so_far = sum(1 for v in done.values() if v.get("affected"))
                print(f"  {n_done}/{len(todo)}건 처리(누적 {len(done)}/{len(doc_rows)}), "
                      f"영향받음 {affected_so_far}건, 에러 {errors}건")

checkpoint_f.close()

affected = [v for v in done.values() if v.get("affected")]
sample_rate = len(affected) / len(doc_rows) * 100 if doc_rows else 0.0
print(f"\n=== 결과 ===")
if RANDOM_SAMPLE_SIZE and TOTAL_HWP_DOCS > RANDOM_SAMPLE_SIZE:
    print(f"표본 문서: {len(doc_rows)}건 (전체 .hwp {TOTAL_HWP_DOCS}건 중 무작위 표본 — 전수조사 아님)")
    print(f"표 손실 영향받음(표본 내): {len(affected)}건 ({sample_rate:.1f}%)")
    print(f"=> 전체 {TOTAL_HWP_DOCS}건으로 환산 추정: 약 {round(TOTAL_HWP_DOCS * sample_rate / 100):,}건 "
          f"(오차범위 대략 ±2%p, 95% 신뢰수준)")
else:
    print(f"전체 .hwp 문서: {len(doc_rows)}건")
    print(f"표 손실 영향받음(표 있었는데 DB엔 흔적 없음): {len(affected)}건 ({sample_rate:.1f}%)")

# 2026-08-25: 이 줄이 없어서 "영향받음 0건"이 진짜 0건인지 대량 에러로 새는
# 중인지 최종 요약만으로 구분이 안 됐던 사고 이후 추가(진행 중 20건마다는
# 원래도 찍혔지만, 스크롤을 놓치면 최종 요약에 안 남아있었음).
n_errors = sum(1 for v in done.values() if v.get("error"))
print(f"에러: {n_errors}건 ({n_errors / len(doc_rows) * 100:.1f}%)"
      if doc_rows else "에러: 0건")
if n_errors > len(doc_rows) * 0.1:
    print(
        "⚠️ 에러 비율이 10% 넘음 — '영향받음' 수치를 그대로 믿지 말 것. "
        "audit_hwp_table_loss_full_checkpoint_diagnose.py로 에러 메시지 확인 필요."
    )

inst_counter = Counter(v.get("institution", "?") for v in affected)
print("\n기관별 상위 10:")
for inst, cnt in inst_counter.most_common(10):
    print(f"  {cnt:4d}건 | {inst}")

print("\n표 개수 분포:")
n_tables_counter = Counter(v["n_table_markers"] for v in affected)
for n, cnt in sorted(n_tables_counter.items()):
    print(f"  표 {n}개인 문서: {cnt}건")
