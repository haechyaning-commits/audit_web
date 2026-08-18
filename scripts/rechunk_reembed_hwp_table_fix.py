# ------------------------------------------------------------------
# 구버전 HWP 표 내용 손실 복구 — hwp5txt+hwp5html 병합 + 재청킹 + 재임베딩
# (Colab 실행용, 2026-08-18 설계)
# ------------------------------------------------------------------
# 배경: scripts/audit_hwp_table_loss.py로 규모 조사한 문제 — 구버전 .hwp(바이너리)
# 문서는 현재 파이프라인이 쓰는 hwp5txt가 표 자리에 "<표>" placeholder만 남기고
# 실제 셀 내용을 못 뽑는데(도구 자체 한계), DB raw_text엔 그 placeholder마저
# 어딘가에서 필터링돼 표가 있었다는 흔적조차 안 남아있음(한전KPS 2018
# cb8dcfbd7983ba43로 최초 발견).
#
# **검증된 복구 방법**(같은 문서로 직접 확인, STATUS.md 2026-08-18 참고): 같은 파일을
# hwp5html로 열면 표 내용이 <table>로 실제 복구됨(소속/직급/징계양정/조치근거 등).
# hwp5txt 출력의 "<표>" 등장 순서와 hwp5html 출력의 <table> 등장 순서가 1:1로 정확히
# 대응(6개 표, 6개 마커 정확히 매칭 확인) — 두 출력을 순서대로 병합하면 표 내용을
# 복구할 수 있음.
#
# **아직 실측 검증 안 된 부분(주의)**: 이 스크립트 자체는 이번 세션에서 새로 작성한
# 것으로, 6개 표짜리 문서 1건 수동 검증 외에 대량 데이터로 돌려본 적이 없음(이 저장소
# 실행 환경은 DB/외부 네트워크 접근이 없어 로컬 검증 불가). 아래 사항 특히 주의:
#   1) hwp5html --output 결과물의 실제 파일 구성(단일 xhtml인지 section별로 나뉘는지)이
#      pyhwp 버전에 따라 다를 수 있음 — _extract_tables_from_hwp5html()이 디렉터리 내
#      모든 *.xhtml/*.html을 파일명 정렬 순으로 훑어서 <table>을 모으는 방식이라, 파일이
#      여러 개로 나뉘어도 대체로 맞는 순서가 나올 것으로 예상하지만 실제로 하나의
#      기준 문서만 검증됐으므로 DRY_RUN 결과의 "표/마커 개수 불일치" 비율을 꼭 확인할 것.
#   2) <표> 개수와 <table> 개수가 다른 문서는 병합 신뢰 불가로 보고 자동 반영하지 않음
#      (review queue로 분리) — 표 안에 표가 중첩된 경우 등 엣지케이스 대비.
#   3) 안전장치로 "표 내용을 다시 제거한 병합 결과"와 "DB 옛 raw_text"의 유사도를
#      게이트로 씀(REMOVE_TABLE_SIMILARITY_THRESHOLD) — 표 내용을 뺀 나머지 부분까지
#      크게 달라지면(추출 로직이 이 문서에서 이상 동작했다는 신호) 자동 반영 안 함.
#
# **실행 순서**:
#   1) scripts/audit_hwp_table_loss.py를 먼저 끝까지 돌려서
#      hwp_table_loss_checkpoint.jsonl을 만들어 둘 것(이 스크립트가 그 결과에서
#      affected=true인 문서만 대상으로 삼음).
#   2) DRY_RUN=True로 이 스크립트 실행 — 대상 문서 수, 마커/표 개수 일치율,
#      자동반영/수동검토 갈림, 병합 샘플 확인.
#   3) 이상 없으면 DRY_RUN=False로 재실행 —
#      documents.raw_text UPDATE(자동반영분만) -> DELETE 옛 청크 -> INSERT 새 청크
#      (embedding NULL) -> GPU 임베딩(체크포인트) -> UPDATE.
# ------------------------------------------------------------------

# !pip install -q "setuptools<60" pyhwp
# !pip install -q psycopg2-binary requests FlagEmbedding pgvector

import datetime
import difflib
import glob
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser

import numpy as np
import psycopg2
import requests
from psycopg2.extras import execute_values

DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로
# 표 내용을 다시 빼낸 병합 결과 vs DB 옛 raw_text 유사도 게이트 — 이 밑이면
# 자동 반영 안 하고 수동검토 큐로 뺌 (표 이외의 부분까지 달라졌다는 신호).
REMOVE_TABLE_SIMILARITY_THRESHOLD = 0.90
DOWNLOAD_WORKERS = 12  # hwp5txt+hwp5html 두 번의 서브프로세스를 도는 만큼
                       # audit_hwp_table_loss.py(24)보다 낮춰서 시작 — 실측 후 조정 권장

CANDIDATE_CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/hwp_table_loss_checkpoint.jsonl"
REVIEW_QUEUE_PATH = "/content/drive/MyDrive/audit_project/hwp_table_fix_manual_review.jsonl"
EMBED_CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/hwp_table_fix_embed_checkpoint.jsonl"
BATCH_SIZE = 64
MAX_LENGTH = 1024  # embed_chunks.py / rechunk_reembed_hwp_fix.py / *_pdf_column_fix*.py와 동일 값

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


# ------------------------------------------------------------------
# hwp5html 결과(xhtml)에서 <table>들을 문서 순서대로 뽑아 "셀 | 셀 | 셀" 텍스트로
# 변환. 파이프(" | ") 구분은 audit_hwp_table_loss.py의 db_has_table_trace 휴리스틱
# ("|" 3개 이상이면 표 흔적으로 간주)과 일부러 맞춤 — 이미 이 프로젝트 다른 곳에서
# 표를 파이프로 표현한 전례가 있다는 가정에 맞춘 것(정착된 컨벤션은 아직 없어서
# 근거는 약함 — 실제 반영 전에 웹 상세페이지 렌더링과 어울리는지 확인 권장).
# ------------------------------------------------------------------
class _TableExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []          # list[list[list[str]]] — table -> rows -> cells
        self._in_table = 0
        self._cur_table = None
        self._cur_row = None
        self._cur_cell_chunks = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table += 1
            if self._in_table == 1:
                self._cur_table = []
        elif tag == "tr" and self._in_table:
            self._cur_row = []
        elif tag in ("td", "th") and self._in_table:
            self._in_cell = True
            self._cur_cell_chunks = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            text = "".join(self._cur_cell_chunks).strip()
            text = re.sub(r"\s+", " ", text)
            if self._cur_row is not None:
                self._cur_row.append(text)
            self._in_cell = False
            self._cur_cell_chunks = None
        elif tag == "tr" and self._cur_row is not None:
            if self._cur_table is not None:
                self._cur_table.append(self._cur_row)
            self._cur_row = None
        elif tag == "table" and self._in_table:
            self._in_table -= 1
            if self._in_table == 0 and self._cur_table is not None:
                self.tables.append(self._cur_table)
                self._cur_table = None

    def handle_data(self, data):
        if self._in_cell and self._cur_cell_chunks is not None:
            self._cur_cell_chunks.append(data)


def _flatten_table(rows):
    lines = [" | ".join(cell for cell in row if cell) for row in rows if any(row)]
    return "\n".join(lines)


def _extract_tables_from_hwp5html_dir(out_dir):
    """hwp5html --output 결과 디렉터리에서 모든 xhtml/html 파일을 파일명 순으로
    훑어 <table>들을 문서 등장 순서로 모음. pyhwp 버전에 따라 index.xhtml 하나로
    나올 수도, section별로 나뉠 수도 있어 둘 다 대응."""
    html_files = sorted(
        glob.glob(os.path.join(out_dir, "**", "*.xhtml"), recursive=True)
        + glob.glob(os.path.join(out_dir, "**", "*.html"), recursive=True)
    )
    tables = []
    for path in html_files:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        parser = _TableExtractor()
        parser.feed(content)
        tables.extend(parser.tables)
    return [_flatten_table(t) for t in tables]


_TABLE_MARKER_RE = re.compile(r"<표>")
_PICTURE_MARKER_RE = re.compile(r"<그림>")


def merge_hwp_text_and_tables(hwp_bytes):
    """(병합된 텍스트, 마커제거 기준텍스트, 표 마커 개수, 실제 뽑힌 표 개수,
    병합 성공 여부) 반환.
    - 병합된 텍스트: <표> 자리에 실제 표 내용을 끼워 넣은 최종 후보(DB 반영용).
    - 마커제거 기준텍스트: <표>를 그냥 제거만 한 버전 — 기존 파이프라인이 DB에
      저장해온 방식(placeholder까지 필터링되어 흔적이 안 남음, audit_hwp_table_loss.py
      조사로 확인)을 그대로 재현해서, DB 옛 raw_text와 사과 대 사과로 비교하기 위함
      (안전장치 유사도 게이트에서 사용).
    병합 실패(개수 불일치 등)면 병합 텍스트는 마커제거 기준텍스트와 동일(표 내용 없이)."""
    with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
        f.write(hwp_bytes)
        hwp_path = f.name

    try:
        txt_proc = subprocess.run(
            ["hwp5txt", hwp_path], capture_output=True, text=True, timeout=60
        )
        raw_text = txt_proc.stdout

        n_markers = len(_TABLE_MARKER_RE.findall(raw_text))
        # <그림>은 기존 DB 컨벤션과 맞춰 괄호만 벗겨 "그림"으로 남김
        raw_text_no_pic = _PICTURE_MARKER_RE.sub("그림", raw_text)
        baseline_text = _TABLE_MARKER_RE.sub("", raw_text_no_pic)

        if n_markers == 0:
            return raw_text_no_pic, baseline_text, 0, 0, True  # 표 자체가 없는 문서

        with tempfile.TemporaryDirectory() as out_dir:
            html_proc = subprocess.run(
                ["hwp5html", hwp_path, "--output", out_dir],
                capture_output=True, text=True, timeout=90,
            )
            if html_proc.returncode != 0:
                return baseline_text, baseline_text, n_markers, 0, False
            table_texts = _extract_tables_from_hwp5html_dir(out_dir)

        if len(table_texts) != n_markers:
            return baseline_text, baseline_text, n_markers, len(table_texts), False

        parts = _TABLE_MARKER_RE.split(raw_text_no_pic)
        merged = parts[0]
        for table_text, rest in zip(table_texts, parts[1:]):
            merged += f"\n{table_text}\n" + rest
        return merged, baseline_text, n_markers, len(table_texts), True
    finally:
        os.unlink(hwp_path)


# ------------------------------------------------------------------
# 청킹 함수 — scripts/rechunk_reembed_pdf_column_fix*.py와 동일(그 원출처는
# claude/data-preprocessing-next-steps-wksl8h 브랜치의 rechunk_reembed_hwp_fix.py).
# 이 저장소 다른 재청킹 스크립트들과 마찬가지로 그대로 복사해서 씀(Colab 노트북
# 셀에 통째로 붙여넣어 실행하는 구조라 각 스크립트가 독립적으로 완결돼야 함).
# ------------------------------------------------------------------
def split_into_chunks(text: str, target_size: int = 1300, max_size: int = 3000) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        stripped = text.strip()
        return [stripped] if stripped else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current))
        current, current_len = [], 0

    for p in paragraphs:
        if len(p) > max_size:
            flush()
            sentences = re.split(r"(?<=[.!?。])\s+", p)
            sub: list[str] = []
            sub_len = 0
            for s in sentences:
                if len(s) > max_size:
                    if sub:
                        chunks.append(" ".join(sub))
                        sub, sub_len = [], 0
                    for i in range(0, len(s), max_size):
                        chunks.append(s[i:i + max_size])
                    continue
                if sub_len + len(s) > max_size and sub:
                    chunks.append(" ".join(sub))
                    sub, sub_len = [], 0
                sub.append(s)
                sub_len += len(s)
            if sub:
                chunks.append(" ".join(sub))
            continue

        if current_len + len(p) > target_size and current:
            flush()
        current.append(p)
        current_len += len(p)

    flush()
    final_chunks = []
    for c in chunks:
        if len(c) > max_size:
            for i in range(0, len(c), max_size):
                final_chunks.append(c[i:i + max_size])
        else:
            final_chunks.append(c)
    return [c for c in final_chunks if c]


def make_chunk_id(document_id: str, index: int, text: str) -> str:
    h = hashlib.md5(f"{document_id}_{index}_{text[:30]}".encode("utf-8")).hexdigest()[:8]
    return f"{document_id}_{h}"


# ------------------------------------------------------------------
# 1) 대상 문서 조회 — audit_hwp_table_loss.py가 affected=true로 표시한 문서
# ------------------------------------------------------------------
if not os.path.exists(CANDIDATE_CHECKPOINT_PATH):
    raise SystemExit(
        f"\n{CANDIDATE_CHECKPOINT_PATH}를 찾을 수 없습니다.\n"
        "scripts/audit_hwp_table_loss.py를 먼저 끝까지 실행해서 규모조사 체크포인트부터 "
        "만드세요."
    )

target_ids = []
with open(CANDIDATE_CHECKPOINT_PATH, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if rec.get("affected"):
            target_ids.append(rec["id"])
print(f"표 손실 영향받음(affected=true) 후보: {len(target_ids)}건 (출처: {CANDIDATE_CHECKPOINT_PATH})")

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '60s'")
    cur.execute(
        "SELECT id, institution, year, source_file, raw_text FROM documents WHERE id = ANY(%s)",
        (target_ids,),
    )
    doc_rows = cur.fetchall()
conn.close()
print(f"실제 조회된 문서: {len(doc_rows)}건")

# ------------------------------------------------------------------
# 2) 다운로드 + hwp5txt/hwp5html 병합 + 안전장치(유사도) 비교
# ------------------------------------------------------------------


def _process_one(doc_id, institution, year, source_file, old_text):
    url = build_source_url(source_file)
    if not url:
        return {"id": doc_id, "ok": False, "error": "source_file 없음/URL 변환 실패"}
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        merged_text, baseline_text, n_markers, n_tables, merge_ok = merge_hwp_text_and_tables(
            resp.content
        )
    except Exception as e:
        return {
            "id": doc_id, "ok": False, "institution": institution, "year": year,
            "error": str(e),
        }

    if not merge_ok:
        return {
            "id": doc_id, "ok": True, "apply": False,
            "institution": institution, "year": year,
            "reason": "marker_table_count_mismatch",
            "n_markers": n_markers, "n_tables": n_tables,
        }

    # 안전장치: <표>를 그냥 제거만 한 기준텍스트(baseline_text, 기존 파이프라인이
    # DB에 저장해온 방식과 동일한 변환) vs DB 옛 raw_text 유사도. 표 내용 자체가
    # 아니라 "표 이외의 부분까지 이 재추출 로직이 원본과 다르게 뽑았는가"만 검사함
    # — rechunk_reembed_pdf_column_fix.py의 SIMILARITY_THRESHOLD 게이트와 동일 발상.
    old_norm = re.sub(r"\s+", " ", (old_text or "")).strip()
    baseline_norm = re.sub(r"\s+", " ", baseline_text).strip()
    if not old_norm:
        sim = 0.0
    else:
        sim = difflib.SequenceMatcher(None, old_norm, baseline_norm).ratio()

    if sim >= REMOVE_TABLE_SIMILARITY_THRESHOLD:
        return {
            "id": doc_id, "ok": True, "apply": True,
            "new_text": merged_text, "n_markers": n_markers, "n_tables": n_tables,
        }
    return {
        "id": doc_id, "ok": True, "apply": False,
        "institution": institution, "year": year,
        "reason": "low_similarity_after_merge",
        "similarity": round(sim, 4), "n_markers": n_markers, "n_tables": n_tables,
    }


apply_list = []  # (doc_id, new_text)
review_list = []

print_lock = threading.Lock()
n_done = 0

with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
    futures = [pool.submit(_process_one, *row) for row in doc_rows]
    for fut in as_completed(futures):
        result = fut.result()
        if result.get("ok") and result.get("apply"):
            apply_list.append((result["id"], result["new_text"]))
        else:
            review_list.append({k: v for k, v in result.items() if k not in ("ok", "apply")})
        with print_lock:
            n_done += 1
            if n_done % 20 == 0 or n_done == len(doc_rows):
                print(
                    f"  {n_done}/{len(doc_rows)}건 처리, "
                    f"자동반영 {len(apply_list)}건, 수동검토 {len(review_list)}건"
                )

print(f"\n자동 반영 대상: {len(apply_list)}건")
print(f"수동 검토 필요: {len(review_list)}건")

if review_list:
    with open(REVIEW_QUEUE_PATH, "w", encoding="utf-8") as f:
        for r in review_list:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"수동 검토 목록 저장: {REVIEW_QUEUE_PATH} (이 문서들은 DB에 반영 안 됨)")

print("\n자동 반영 대상 샘플 3건:")
for doc_id, new_text in apply_list[:3]:
    print(f"  {doc_id} (len={len(new_text)}): {new_text[:150]!r}")

if DRY_RUN:
    raise SystemExit(
        "\nDRY_RUN=True라 여기서 멈춤(DB 변경 없음). "
        "위 자동반영/수동검토 갈림과 병합 샘플이 말이 되면 DRY_RUN=False로 바꿔서 "
        "다시 실행하세요. 특히 수동검토 사유(marker_table_count_mismatch vs "
        "low_similarity_after_merge) 비율을 확인해서 병합 로직 자체에 문제가 있는지 "
        "판단할 것."
    )

# ------------------------------------------------------------------
# 2.5) 백업 — scripts/rechunk_reembed_pdf_column_fix.py와 동일 패턴
# ------------------------------------------------------------------
BACKUP_PATH = (
    f"/content/drive/MyDrive/audit_project/"
    f"hwp_table_fix_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.jsonl"
)
_apply_ids = [doc_id for doc_id, _ in apply_list]

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '60s'")
    cur.execute("SELECT id, raw_text FROM documents WHERE id = ANY(%s)", (_apply_ids,))
    _old_docs = dict(cur.fetchall())
    cur.execute(
        "SELECT id, document_id, text FROM chunks WHERE document_id = ANY(%s)",
        (_apply_ids,),
    )
    _old_chunks_by_doc: dict[str, list] = {}
    for cid, did, text in cur.fetchall():
        _old_chunks_by_doc.setdefault(did, []).append({"id": cid, "text": text})
conn.close()

with open(BACKUP_PATH, "w", encoding="utf-8") as f:
    for doc_id in _apply_ids:
        f.write(json.dumps({
            "id": doc_id,
            "raw_text": _old_docs.get(doc_id),
            "chunks": _old_chunks_by_doc.get(doc_id, []),
        }, ensure_ascii=False) + "\n")
print(f"백업 저장 완료: {BACKUP_PATH} ({len(_apply_ids)}건)")

# ------------------------------------------------------------------
# 3) documents.raw_text UPDATE
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '120s'")
        for doc_id, new_text in apply_list:
            cur.execute("UPDATE documents SET raw_text = %s WHERE id = %s", (new_text, doc_id))
        conn.commit()
    print(f"documents.raw_text 갱신: {len(apply_list)}건")
finally:
    conn.close()

# ------------------------------------------------------------------
# 4) 재청킹
# ------------------------------------------------------------------
new_chunks = []  # (chunk_id, document_id, text)
for doc_id, new_text in apply_list:
    pieces = split_into_chunks(new_text)
    for i, piece in enumerate(pieces):
        new_chunks.append((make_chunk_id(doc_id, i, piece), doc_id, piece))

print(f"신규 청크 수: {len(new_chunks)}건")
lens = [len(c[2]) for c in new_chunks]
if lens:
    print(f"청크 길이 — 평균 {sum(lens)/len(lens):.0f}, 최소 {min(lens)}, 최대 {max(lens)}")

conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '120s'")
        target_id_list = [doc_id for doc_id, _ in apply_list]
        cur.execute("DELETE FROM chunks WHERE document_id = ANY(%s)", (target_id_list,))
        print(f"옛 청크 삭제: {cur.rowcount}건")
        conn.commit()

        insert_rows = [(cid, did, text) for cid, did, text in new_chunks]
        for i in range(0, len(insert_rows), 500):
            batch = insert_rows[i:i + 500]
            execute_values(cur, "INSERT INTO chunks (id, document_id, text) VALUES %s", batch)
            conn.commit()
            print(f"  새 청크 INSERT: {min(i + 500, len(insert_rows))}/{len(insert_rows)}")
finally:
    conn.close()

print("\n재청킹 완료 — 이제 임베딩 계산 단계로 넘어가세요 (GPU 런타임 필요, 아래 5번).")

# ------------------------------------------------------------------
# 5) GPU 임베딩 (체크포인트 지원) — 별도 셀로 나눠서 실행 권장
# ------------------------------------------------------------------
from FlagEmbedding import BGEM3FlagModel  # noqa: E402
from pgvector.psycopg2 import register_vector  # noqa: E402

chunk_ids = [c[0] for c in new_chunks]
texts = [c[2] for c in new_chunks]

done: dict[str, list] = {}
if os.path.exists(EMBED_CHECKPOINT_PATH):
    with open(EMBED_CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            done[rec["chunk_id"]] = rec["embedding"]
    print(f"임베딩 체크포인트에서 {len(done)}건 이미 완료된 것 발견")

remaining_idx = [i for i, cid in enumerate(chunk_ids) if cid not in done]
print(f"임베딩 남은 것: {len(remaining_idx)}건")

if remaining_idx:
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    with open(EMBED_CHECKPOINT_PATH, "a", encoding="utf-8") as ckpt_f:
        for start in range(0, len(remaining_idx), BATCH_SIZE):
            batch_idx = remaining_idx[start:start + BATCH_SIZE]
            batch_texts = [texts[i] for i in batch_idx]
            output = model.encode(
                batch_texts, batch_size=BATCH_SIZE, max_length=MAX_LENGTH,
                return_dense=True, return_sparse=False, return_colbert_vecs=False,
            )
            for idx, vec in zip(batch_idx, output["dense_vecs"]):
                cid = chunk_ids[idx]
                emb_list = [round(float(x), 5) for x in vec]
                done[cid] = emb_list
                ckpt_f.write(json.dumps({"chunk_id": cid, "embedding": emb_list}) + "\n")
            ckpt_f.flush()
            print(f"  임베딩 진행: {min(start + BATCH_SIZE, len(remaining_idx))}/{len(remaining_idx)}")

print("임베딩 계산 완료 — DB 반영으로 넘어감")

vectors = np.array([done[cid] for cid in chunk_ids], dtype=np.float16)
norms = np.linalg.norm(vectors.astype(np.float32), axis=1)
print(f"벡터 norm 평균/표준편차: {norms.mean():.6f} / {norms.std():.6f}")
if abs(norms.mean() - 1.0) > 0.01:
    raise SystemExit("벡터 norm이 1.0에서 크게 벗어남 — DB 반영 전에 원인 확인 필요")

conn = psycopg2.connect(DATABASE_URL)
register_vector(conn)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        rows = list(zip(vectors, chunk_ids))
        for i in range(0, len(rows), 500):
            batch = rows[i:i + 500]
            cur.executemany("UPDATE chunks SET embedding = %s WHERE id = %s", batch)
            conn.commit()
            print(f"  임베딩 DB 반영: {min(i + 500, len(rows))}/{len(rows)}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chunks WHERE embedding IS NULL AND document_id = ANY(%s)",
            ([doc_id for doc_id, _ in apply_list],),
        )
        print(f"\n임베딩 안 된 청크(0이어야 정상): {cur.fetchone()[0]}건")
finally:
    conn.close()

print("\n완료 — HWP 표 손실 복구 + 재청킹 + 재임베딩 끝")
print(f"참고: 수동 검토 큐 {len(review_list)}건은 이번에 반영 안 됐음 — {REVIEW_QUEUE_PATH} 확인 필요")
