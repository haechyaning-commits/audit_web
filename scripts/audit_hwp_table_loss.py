# ------------------------------------------------------------------
# 구버전 HWP 표 내용 손실 실태 조사 (2026-08-18, 읽기 전용, Colab 실행용)
# ------------------------------------------------------------------
# 배경: 한전KPS 2018(cb8dcfbd7983ba43) 실제 문서로 발견 — DB raw_text에서
# "3. 관련자 현황", "Ⅲ. 신분상 조치 요구" 같은 섹션 제목 다음에 내용이 아예
# 없음. 원인 확인: 이 문서의 원본은 .hwp(구버전 바이너리)이고, `hwp5txt`
# 명령을 직접 돌려보면 표가 있던 자리에 "<표>" placeholder만 남고 실제 셀
# 내용은 애초에 텍스트로 못 뽑음(hwp5txt 자체의 한계, 이 저장소 코드 문제
# 아님) — 근데 DB raw_text엔 그 "<표>" placeholder마저 없어서(어디선가
# 필터링됨) 표가 있었다는 흔적조차 안 남음.
#
# `hwp5html`로 같은 파일을 열어보면 표 내용이 실제로 복구됨(직급/성명/징계
# 양정/조치근거 등) — hwp5txt의 "<표>" 순서와 hwp5html의 <table> 순서가
# 1:1로 대응해서, 두 출력을 합치면 온전한 문서를 재구성할 수 있음을 직접
# 검증함(6개 표, 6개 마커 정확히 매칭).
#
# 이 스크립트는 아직 아무것도 고치지 않고, **얼마나 많은 문서가 이 문제를
# 겪고 있는지**만 조사함:
#   1) source_file이 .hwp로 끝나는 문서(.hwpx 아님 — .hwpx는 XML 기반이라
#      다른 파이프라인/다른 이슈, 이 조사 대상 아님) 전체 조회
#   2) 각 파일을 실제로 다운로드해서 hwp5txt로 "<표>" 개수를 세고, 현재 DB
#      raw_text에 표 내용으로 보이는 게 있는지(간단 휴리스틱: "<표>"/"[표]"
#      마커 존재 여부, 또는 "|" 구분자 존재 여부) 확인
#   3) "<표>"가 1개 이상 있는데 DB raw_text에는 표 흔적이 전혀 없는 문서를
#      "영향받음"으로 집계
# ------------------------------------------------------------------

# !pip install -q pyhwp psycopg2-binary requests

import os
import re
import subprocess
import tempfile
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import requests

DOWNLOAD_WORKERS = 8  # hwp5txt 서브프로세스 실행이 있어서 PDF 스크립트보다 낮게 잡음
CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/hwp_table_loss_checkpoint.jsonl"

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
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name
        try:
            proc = subprocess.run(
                ["hwp5txt", tmp_path], capture_output=True, text=True, timeout=60
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
print(f"대상 .hwp 문서: {len(doc_rows)}건")

done = {}
if os.path.exists(CHECKPOINT_PATH):
    import json
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            done[rec["id"]] = rec
    print(f"체크포인트에서 {len(done)}건 이미 처리된 것 발견 — 이어서 진행")

todo = [r for r in doc_rows if r[0] not in done]
print(f"남은 {len(todo)}건을 {DOWNLOAD_WORKERS}개 동시 처리로 진행")

import json as _json

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
print(f"\n=== 결과 ===")
print(f"전체 .hwp 문서: {len(doc_rows)}건")
print(f"표 손실 영향받음(표 있었는데 DB엔 흔적 없음): {len(affected)}건 "
      f"({len(affected)/len(doc_rows)*100:.1f}%)")

inst_counter = Counter(v.get("institution", "?") for v in affected)
print("\n기관별 상위 10:")
for inst, cnt in inst_counter.most_common(10):
    print(f"  {cnt:4d}건 | {inst}")

print("\n표 개수 분포:")
n_tables_counter = Counter(v["n_table_markers"] for v in affected)
for n, cnt in sorted(n_tables_counter.items()):
    print(f"  표 {n}개인 문서: {cnt}건")
