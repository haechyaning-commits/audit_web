# ------------------------------------------------------------------
# HWP 원문 잘림(1,000자 근처 캡) 복구 — 전체 추출 (2026-08-14)
# ------------------------------------------------------------------
# 배경: documents 중 source_file이 .hwp/.hwpx인 문서 37,631건 중 5,405건이
# raw_text 길이 900~1020자 근처에 비정상적으로 몰려있음(길이 분포 스파이크+절벽
# 패턴으로 확인) — 원래 파이프라인이 HWP 파일의 "미리보기 텍스트"(길이 제한 있음)를
# 본문으로 잘못 쓴 것으로 추정. 실제 원본은 8,664~364,872자까지 있음(샘플 10건 검증).
#
# 이 스크립트는 그 5,405건의 원본 HWP/HWPX 파일을 jsdelivr CDN에서 받아서 전체
# 텍스트를 다시 뽑아냄. .hwpx는 zip+XML이라 직접 파싱, .hwp(구버전 바이너리)는
# pyhwp의 hwp5txt로 추출(5/5 샘플 검증 완료, 2,262~2,421자 복구 확인됨).
#
# **알려진 한계**: hwp5txt는 표가 있으면 내용을 "<표>" 자리표시자로 뭉갬(표 셀
# 내용 손실) — 이번 패스에서는 받아들이고 넘어감(이미 이 프로젝트가 감수해온
# 종류의 손실), 필요하면 다음에 hwp5html로 개선 검토.
#
# 체크포인트: Drive에 결과를 한 줄씩(JSONL) 즉시 append — 중간에 끊겨도 이어서
# 실행하면 이미 처리된 건 자동으로 건너뜀 (재임베딩 사고 교훈 — 노트북 셀에 직접
# 붙여넣어서 실행할 것, !python 서브프로세스로 돌리지 말 것).
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary
# !pip install -q pyhwp six lxml olefile

import concurrent.futures
import io
import json
import os
import re
import subprocess
import urllib.parse
import zipfile

import psycopg2

CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/hwp_truncation_checkpoint.jsonl"
os.makedirs(os.path.dirname(CHECKPOINT_PATH), exist_ok=True)

DATABASE_URL = None
try:
    from google.colab import userdata
    DATABASE_URL = userdata.get("DATABASE_PUBLIC_URL")
except Exception:
    pass
if not DATABASE_URL:
    DATABASE_URL = os.environ.get("DATABASE_URL")

# ------------------------------------------------------------------
# 1) 이미 처리된 문서 확인(재시작 대비)
# ------------------------------------------------------------------
done_ids = set()
if os.path.exists(CHECKPOINT_PATH):
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                done_ids.add(json.loads(line)["id"])
            except Exception:
                pass
print(f"이미 처리됨(체크포인트): {len(done_ids)}건")

# ------------------------------------------------------------------
# 2) 대상 문서 조회
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '60s'")
    cur.execute("""
        SELECT id, source_file, raw_text
        FROM documents
        WHERE (source_file ILIKE '%.hwp' OR source_file ILIKE '%.hwpx')
          AND length(raw_text) BETWEEN 900 AND 1020
    """)
    rows = cur.fetchall()
conn.close()
print(f"대상 문서: {len(rows)}건")

todo = [(doc_id, sf, rt) for doc_id, sf, rt in rows if doc_id not in done_ids]
print(f"이번에 처리할 것: {len(todo)}건")


# ------------------------------------------------------------------
# 3) 다운로드 + 추출
# ------------------------------------------------------------------
def download(source_file: str) -> bytes:
    path = source_file[len("data_repo/"):] if source_file.startswith("data_repo/") else source_file
    encoded = urllib.parse.quote(path)
    url = f"https://cdn.jsdelivr.net/gh/haechyaning-commits/data@main/{encoded}"
    resp = subprocess.run(["curl", "-sS", "-m", "30", "-L", url], capture_output=True)
    if resp.returncode != 0 or not resp.stdout:
        raise RuntimeError(f"download failed rc={resp.returncode} stderr={resp.stderr[:200]}")
    return resp.stdout


def extract_hwpx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n))
        texts = []
        for n in names:
            content = z.read(n).decode("utf-8", errors="replace")
            texts.append("".join(re.findall(r"<hp:t[^>]*>(.*?)</hp:t>", content, re.DOTALL)))
        return "\n".join(texts)


def extract_hwp(data: bytes, tmp_path: str) -> str:
    with open(tmp_path, "wb") as f:
        f.write(data)
    result = subprocess.run(["hwp5txt", tmp_path], capture_output=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[:300])
    return result.stdout.decode("utf-8", errors="replace")


def process_one(doc_id, source_file, old_raw_text):
    try:
        data = download(source_file)
        if source_file.lower().endswith(".hwpx"):
            new_text = extract_hwpx(data)
        else:
            new_text = extract_hwp(data, f"/tmp/_hwp_{doc_id}.hwp")
        new_text = new_text.strip()
        return {
            "id": doc_id, "status": "ok",
            "old_len": len(old_raw_text), "new_len": len(new_text),
            "old_raw_text": old_raw_text, "new_raw_text": new_text,
        }
    except Exception as e:
        return {"id": doc_id, "status": "error", "error": str(e)[:300]}


n_done = 0
n_ok = 0
n_err = 0
with open(CHECKPOINT_PATH, "a", encoding="utf-8") as ckpt:
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_one, doc_id, sf, rt): doc_id for doc_id, sf, rt in todo}
        for future in concurrent.futures.as_completed(futures):
            rec = future.result()
            ckpt.write(json.dumps(rec, ensure_ascii=False) + "\n")
            ckpt.flush()
            n_done += 1
            if rec["status"] == "ok":
                n_ok += 1
            else:
                n_err += 1
            if n_done % 100 == 0:
                print(f"진행: {n_done}/{len(todo)} (성공 {n_ok}, 실패 {n_err})")

print(f"\n완료 — 이번 실행 {n_done}건 (성공 {n_ok}, 실패 {n_err})")
print(f"체크포인트 파일: {CHECKPOINT_PATH}")
