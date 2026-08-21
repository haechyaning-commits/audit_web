# ------------------------------------------------------------------
# HWPX XML 태그 누출 재수정 (2026-08-14, HWP 원문 잘림 복구의 후속 수정)
# ------------------------------------------------------------------
# 배경: `audit_hwp_truncation_extract.py`의 .hwpx 추출 함수가 정규식
# (`<hp:t[^>]*>(.*?)</hp:t>`)으로만 텍스트를 뽑았는데, hp:t 요소 안에 중첩된
# 다른 태그(hp:fwSpace, hp:sz 등, 표/이미지 있는 문서에서 흔함)까지 텍스트로
# 같이 섞여 들어가는 버그가 있었음(예: e410c25742a07326은 진짜 본문 10,744자인데
# 정규식으로는 364,872자로 부풀려짐 — XML 마크업 대부분이 "텍스트"로 잘못 셈).
#
# 이미 DB에 반영된 5,389건 중 .hwpx 소스 2,616건이 영향받음(.hwp는 hwp5txt를
# 써서 이 버그와 무관, 2,773건 그대로 둠) — 이 스크립트가 lxml로 hp:t 요소의
# `.text`만 정확히 뽑아서(자식 요소 무시) 다시 교정함.
#
# **실행 순서**:
#   1) DRY_RUN=True로 먼저 — 지금 DB에 있는 값(버그 섞인 버전) 대비 얼마나 바뀌는지
#      확인.
#   2) 이상 없으면 DRY_RUN=False로 재실행.
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary lxml

import html
import io
import json
import os
import re
import subprocess
import urllib.parse
import zipfile

import psycopg2
from lxml import etree
from psycopg2.extras import execute_values

CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/hwpx_leak_fix_checkpoint.jsonl"
DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로

NS_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
PUA_RE = re.compile(
    "[\U0000E000-\U0000F8FF\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]+"
)

DATABASE_URL = None
try:
    from google.colab import userdata
    DATABASE_URL = userdata.get("DATABASE_PUBLIC_URL")
except Exception:
    pass
if not DATABASE_URL:
    DATABASE_URL = os.environ.get("DATABASE_URL")


def download(source_file: str) -> bytes:
    path = source_file[len("data_repo/"):] if source_file.startswith("data_repo/") else source_file
    encoded = urllib.parse.quote(path)
    url = f"https://cdn.jsdelivr.net/gh/haechyaning-commits/data@main/{encoded}"
    resp = subprocess.run(["curl", "-sS", "-m", "30", "-L", url], capture_output=True)
    if resp.returncode != 0 or not resp.stdout:
        raise RuntimeError(f"download failed rc={resp.returncode} stderr={resp.stderr[:200]}")
    return resp.stdout


def extract_hwpx_proper(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        section_names = sorted(
            n for n in z.namelist() if n.startswith("Contents/section") and n.endswith(".xml")
        )
        paragraphs = []
        for name in section_names:
            root = etree.fromstring(z.read(name))
            for p_elem in root.iter(f"{{{NS_HP}}}p"):
                # p_elem.iter()(재귀)로 하면 표가 hp:p 안에 중첩된 hp:p(셀 문단)들을
                # 포함해버려서, "표 전체가 한 문단으로 뭉친 버전" + "표 셀별로 제대로
                # 나뉜 버전"이 중복으로 다 잡힘(실제 문서로 검증 중 발견, 예:
                # e410c25742a07326에서 10,744자->7,792자로 중복 제거됨, 2,952자가 순수
                # 중복이었음). findall로 이 문단의 "직속" run/t만 가져오면 —
                # 표를 앵커링하는 바깥 문단은 직속 텍스트가 없어서 빈 채로 건너뛰고,
                # 안쪽 셀 문단들은 각자 순서대로 한 번씩만 잡힘. 1ca9faabf1df243f(첫
                # 검증 문서)로 대조해서 표/일반 문단 모두 정답과 정확히 일치함을 확인.
                texts = [
                    t.text for t in p_elem.findall(f"{{{NS_HP}}}run/{{{NS_HP}}}t") if t.text
                ]
                if texts:
                    paragraphs.append("".join(texts))
        return "\n".join(paragraphs)


def clean_text(t: str) -> str:
    t = html.unescape(t)
    t = PUA_RE.sub("[코드]", t)
    return t


# ------------------------------------------------------------------
# 1) 대상 조회 — 오늘 반영한 것 중 .hwpx 소스만
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("""
        SELECT id, source_file, raw_text
        FROM documents
        WHERE source_file ILIKE '%%.hwpx'
          AND (raw_text LIKE '%%<hp:%%' OR raw_text LIKE '%%</hp:%%')
    """)
    rows = cur.fetchall()
conn.close()
print(f"재수정 대상(태그 누출 확인된 것): {len(rows)}건")

done_ids = set()
if os.path.exists(CHECKPOINT_PATH):
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                done_ids.add(json.loads(line)["id"])
            except Exception:
                pass
print(f"이미 처리됨(체크포인트): {len(done_ids)}건")

todo = [(doc_id, sf, rt) for doc_id, sf, rt in rows if doc_id not in done_ids]
print(f"이번에 처리할 것: {len(todo)}건")

# ------------------------------------------------------------------
# 2) 재추출 (10개 동시 다운로드 병렬 처리, 체크포인트 append)
# ------------------------------------------------------------------
import concurrent.futures


def process_one(doc_id, source_file, current_db_text):
    try:
        data = download(source_file)
        new_text = clean_text(extract_hwpx_proper(data)).strip()
        return {
            "id": doc_id, "status": "ok",
            "old_raw_text": current_db_text,  # 지금 DB에 있는(버그 섞인) 값 기준
            "new_raw_text": new_text,
        }
    except Exception as e:
        return {"id": doc_id, "status": "error", "error": str(e)[:300]}


n_done, n_ok, n_err = 0, 0, 0
with open(CHECKPOINT_PATH, "a", encoding="utf-8") as ckpt:
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_one, *args): args[0] for args in todo}
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

print(f"\n추출 완료 — 이번 실행 {n_done}건 (성공 {n_ok}, 실패 {n_err})")

# ------------------------------------------------------------------
# 3) DB 반영
# ------------------------------------------------------------------
all_records = []
with open(CHECKPOINT_PATH, encoding="utf-8") as f:
    for line in f:
        all_records.append(json.loads(line))
ok_records = [r for r in all_records if r["status"] == "ok"]

conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '60s'")
        ids = [r["id"] for r in ok_records]
        cur.execute("SELECT id, raw_text FROM documents WHERE id = ANY(%s)", (ids,))
        current = dict(cur.fetchall())

        to_update = []
        mismatched = []
        for r in ok_records:
            cur_text = current.get(r["id"])
            if cur_text is None:
                mismatched.append((r["id"], "문서 없음"))
            elif cur_text != r["old_raw_text"]:
                mismatched.append((r["id"], "raw_text가 예상과 다름(건너뜀)"))
            else:
                to_update.append((r["id"], r["new_raw_text"]))

        print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}반영{'예정' if DRY_RUN else ''}: {len(to_update)}건")
        print(f"건너뜀: {len(mismatched)}건")
        for doc_id, reason in mismatched[:20]:
            print(f"  {doc_id}: {reason}")

        if DRY_RUN:
            raise SystemExit(
                "\nDRY_RUN=True라 여기서 멈춤. 결과 확인 후 DRY_RUN=False로 다시 실행하세요."
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

        # 반영 후 태그 누출 재검사
        cur.execute("""
            SELECT count(*) FROM documents
            WHERE source_file ILIKE '%%.hwpx'
              AND (raw_text LIKE '%%<hp:%%' OR raw_text LIKE '%%</hp:%%')
        """)
        print(f"\n반영 후 hwpx 태그 누출 남은 문서: {cur.fetchone()[0]}건 (0이어야 정상)")
finally:
    conn.close()

print(f"\n완료 — {len(to_update) if not DRY_RUN else 0}건 반영 끝")
