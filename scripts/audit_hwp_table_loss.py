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
import random
import re
import subprocess
import tempfile
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import requests

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
CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/hwp_table_loss_checkpoint.jsonl"

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

# 2026-08-18: 3만건 전수조사가 예상보다 훨씬 느려서(25분에 2,000건, 완주까지 5시간+
# 추정) — 이 조사의 목적 자체가 "영향받는 비율"을 파악해서 복구 스크립트를 만들
# 가치가 있는지 판단하는 것이라, 전수조사 대신 무작위 표본으로 축소함(표본 3,000건이면
# 모집단 3만 기준 비율 추정 오차범위 대략 ±2%p, 95% 신뢰수준 — 규모 판단용으로 충분).
# 이미 체크포인트에 쌓인 문서는 버리지 않고 표본에 우선 포함시켜 재사용함. 정확한
# 전수 집계가 필요해지면 RANDOM_SAMPLE_SIZE = None으로 바꿔서 다시 돌리면 됨.
RANDOM_SAMPLE_SIZE = 3000

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

inst_counter = Counter(v.get("institution", "?") for v in affected)
print("\n기관별 상위 10:")
for inst, cnt in inst_counter.most_common(10):
    print(f"  {cnt:4d}건 | {inst}")

print("\n표 개수 분포:")
n_tables_counter = Counter(v["n_table_markers"] for v in affected)
for n, cnt in sorted(n_tables_counter.items()):
    print(f"  표 {n}개인 문서: {cnt}건")
