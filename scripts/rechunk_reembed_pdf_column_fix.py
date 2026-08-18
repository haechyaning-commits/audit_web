# ------------------------------------------------------------------
# 2단 레이아웃 PDF 재추출 반영 + 재청킹 + 재임베딩 (Colab 실행용)
# ------------------------------------------------------------------
# 배경: scripts/audit_pdf_column_layout.py로 찾은 2단(다단) 레이아웃 의심 문서들의
# raw_text를 scripts/reextract_pdf_text.py의 재추출 로직(2단 순서 복구 + 좌표 기반
# 띄어쓰기 보정)으로 교체하고, 그 문서들의 청크를 재생성 + 재임베딩함.
#
# 이 스크립트는 새로 짠 게 아니라 이미 검증된 세 조각을 그대로 이어붙인 것:
#   1) extract_doc_text() 등 재추출 로직 — 이 저장소 scripts/reextract_pdf_text.py
#      그대로 복사(2026-08-14, 한국철도공사 문서 글자 단위 100% 일치 검증 +
#      24개 문서 확대 검증 완료된 버전).
#   2) split_into_chunks() / make_chunk_id() — claude/data-preprocessing-next-steps-wksl8h
#      브랜치의 scripts/rechunk_reembed_hwp_fix.py에서 그대로 복사. 기존 청크 분포
#      (평균 1,321자/중앙값 1,097자/최대 3,002자)에 맞춰 설계된 근사 함수(원본 파이프라인
#      알고리즘 복제 아님) — 실 데이터 검증 중 버그 2건 발견/수정된 이력 있음.
#   3) DELETE 옛 청크 -> INSERT 새 청크(embedding NULL) -> GPU 임베딩(체크포인트) 패턴
#      — 위 rechunk_reembed_hwp_fix.py와 동일 구조.
#
# ⚠️ reextract_pdf_text.py 자체 주석의 경고("아직 프로토타입 단계 — DB에 바로
# 반영하지 말 것", STATUS.md 8/14 8차 참고):
#   1) 선행 상용구("권고사항 1." 등 문서분류/기관명 헤더) 제거 로직이 아직 없음 —
#      일부 문서는 재추출 결과가 DB 원문보다 앞부분이 더 길게 나올 수 있음.
#   2) 표가 있는 문서는 셀 순서/구조 차이로 유사도가 낮게 나옴(실측 76~78%대).
#   3) 문자 단위 직접 비교 검증은 9개 문서에서만 이뤄짐 — gap_threshold=2.5pt가
#      다른 폰트/기관 문서 전반에 맞는지 폭넓게 확인된 상태가 아님.
# 위 이유로 이 스크립트는 전수 자동 반영이 아니라, 신구 raw_text 유사도(difflib,
# 공백 정규화 후)를 계산해서 SIMILARITY_THRESHOLD 이상인 문서만 자동 반영하고,
# 미달/에러 건은 DB를 건드리지 않은 채 REVIEW_QUEUE_PATH에 남겨서 사람이 직접
# 확인하도록 함.
#
# **실행 순서**:
#   1) DRY_RUN=True로 먼저 — 대상 문서 수, 유사도 분포, 자동반영/수동검토 갈림,
#      샘플 재추출 결과 확인.
#   2) 이상 없으면 DRY_RUN=False로 재실행 —
#      documents.raw_text UPDATE(자동반영분만) -> DELETE 옛 청크 -> INSERT 새 청크
#      (embedding NULL) -> GPU 임베딩(체크포인트) -> UPDATE.
# ------------------------------------------------------------------

# !pip install -q pymupdf psycopg2-binary requests FlagEmbedding pgvector

import difflib
import hashlib
import json
import os
import re
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import psycopg2
import pymupdf
import requests
from psycopg2.extras import execute_values

DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로
SIMILARITY_THRESHOLD = 0.90  # 이 밑이면 자동 반영 안 하고 수동검토 큐로 뺌
DOWNLOAD_WORKERS = 16  # PDF 다운로드+재추출 동시 처리 수 — audit_pdf_column_layout.py와 동일 값
                       # (I/O 바운드라 GIL 영향 적음, jsdelivr 공개 CDN이라 16 정도는 무리 없음)

# audit_pdf_column_layout.py 실행 결과 체크포인트("flagged" 페이지가 있는 문서만
# 이 스크립트의 대상이 됨). 2026-08-18 이전 버전의 audit_pdf_column_layout.py는
# 이걸 Drive가 아니라 Colab 로컬(/content/)의 상대경로에 저장했었어서, 세션이
# 재시작되면 소실되는 문제가 있었음 — 지금은 audit_pdf_column_layout.py도 이
# Drive 경로로 저장하도록 고쳐뒀으니, 그 스크립트를 (다시) 돌려서 이 파일부터
# 만드세요. 옛 로컬 경로도 혹시 몰라 폴백으로 같이 확인함.
CANDIDATE_CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/column_layout_checkpoint.jsonl"
_CANDIDATE_CHECKPOINT_FALLBACK = "column_layout_checkpoint.jsonl"  # 옛 버전이 쓰던 로컬 경로
REVIEW_QUEUE_PATH = "/content/drive/MyDrive/audit_project/pdf_reextract_manual_review.jsonl"
EMBED_CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/pdf_reextract_embed_checkpoint.jsonl"
BATCH_SIZE = 64
MAX_LENGTH = 1024  # embed_chunks.py / reembed_changed_chunks.py / rechunk_reembed_hwp_fix.py와 동일 값

# 2026-08-18: audit_pdf_column_layout.py는 Colab Secret 이름을 "DATABASE_URL"로
# 쓰는데(실제로 이 사용자 환경에서 이 이름으로 성공적으로 연결됨), 이 스크립트는
# 원래 rechunk_reembed_hwp_fix.py(다른 브랜치)를 따라 "DATABASE_PUBLIC_URL"을
# 먼저 찾다가 실패 -> DATABASE_URL이 None으로 남아 psycopg2가 로컬 소켓에 연결을
# 시도하며 OperationalError가 난 적이 있음. 이 사용자 환경에서 실제로 동작하는
# "DATABASE_URL"을 먼저 찾고, "DATABASE_PUBLIC_URL"은 다른 브랜치 스크립트와의
# 호환을 위해 폴백으로만 남겨둠.
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
        "\"DATABASE_URL\" (또는 \"DATABASE_PUBLIC_URL\") 이름의 Secret이 등록돼 "
        "있고 이 노트북에 대해 '노트북 접근' 권한이 켜져 있는지 확인하세요."
    )


# ------------------------------------------------------------------
# scripts/audit_pdf_column_layout.py와 동일한 source_file -> PDF URL 변환
# (backend/app/textutils.py의 build_source_url()과 동일 규칙)
# ------------------------------------------------------------------
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
# 재추출 로직 — scripts/reextract_pdf_text.py 그대로 (2단 순서 + 띄어쓰기 복구).
# 상세 설계/검증 근거는 원본 파일 헤더 주석 참고, 여기선 함수만 그대로 복사.
# ------------------------------------------------------------------
_MASK_GLYPH_RE = re.compile(r"([○◎□●■])\1+")
_PAGE_NUMBER_RE = re.compile(r"^-\s*\d+\s*-$")


def normalize_masked_glyphs(text):
    return _MASK_GLYPH_RE.sub("[부서]", text)


def strip_page_number_footers(text):
    lines = [l for l in text.split("\n") if not _PAGE_NUMBER_RE.match(l.strip())]
    return "\n".join(lines)


def chars_to_text(chars, gap_threshold=2.5):
    if not chars:
        return ""
    out = [chars[0]["c"]]
    for prev, cur in zip(chars, chars[1:]):
        gap = cur["bbox"][0] - prev["bbox"][2]
        if gap >= gap_threshold and prev["c"] != " " and cur["c"] != " ":
            out.append(" ")
        out.append(cur["c"])
    return "".join(out).strip()


def line_text(line, gap_threshold=2.5):
    chars = []
    for span in line["spans"]:
        chars.extend(span.get("chars", []))
    return chars_to_text(chars, gap_threshold)


def _merge_same_row_fragments(fragments, y_tol=1.0, max_x_gap=50.0):
    fragments = sorted(fragments, key=lambda f: (f["bbox"][1], f["bbox"][0]))
    y_clusters = []
    for frag in fragments:
        y0 = frag["bbox"][1]
        if y_clusters and abs(y_clusters[-1]["last_y0"] - y0) <= y_tol:
            y_clusters[-1]["frags"].append(frag)
            y_clusters[-1]["last_y0"] = y0
        else:
            y_clusters.append({"last_y0": y0, "frags": [frag]})

    rows = []
    for cluster in y_clusters:
        frags = sorted(cluster["frags"], key=lambda f: f["bbox"][0])
        cur = [frags[0]]
        for prev, f in zip(frags, frags[1:]):
            gap = f["bbox"][0] - prev["bbox"][2]
            if gap <= max_x_gap:
                cur.append(f)
            else:
                rows.append(cur)
                cur = [f]
        rows.append(cur)

    merged = []
    for frags in rows:
        chars = []
        for f in frags:
            chars.extend(f["chars"])
        x0 = min(f["bbox"][0] for f in frags)
        y0 = min(f["bbox"][1] for f in frags)
        x1 = max(f["bbox"][2] for f in frags)
        y1 = max(f["bbox"][3] for f in frags)
        merged.append({"bbox": (x0, y0, x1, y1), "chars": chars})
    return merged


def extract_page_text(page, gap_threshold=2.5):
    d = page.get_text("rawdict")
    fragments = []
    for block in d["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            chars = []
            for span in line["spans"]:
                chars.extend(span.get("chars", []))
            if chars:
                fragments.append({"bbox": line["bbox"], "chars": chars})

    if not fragments:
        return ""

    rows = _merge_same_row_fragments(fragments)
    lines = []
    for row in rows:
        text = chars_to_text(row["chars"], gap_threshold)
        if text:
            lines.append({"bbox": row["bbox"], "text": text})

    if not lines:
        return ""

    wide_lines = [l for l in lines if (l["bbox"][2] - l["bbox"][0]) > 100]
    is_two_col = False
    split_x = None
    if len(wide_lines) >= 5:
        xs = sorted(l["bbox"][0] for l in wide_lines)
        gaps = [(xs[j + 1] - xs[j], j) for j in range(len(xs) - 1)]
        if gaps:
            biggest_gap, idx = max(gaps)
            if biggest_gap > page.rect.width * 0.15:
                left = [l for l in wide_lines if l["bbox"][0] <= xs[idx]]
                right = [l for l in wide_lines if l["bbox"][0] > xs[idx]]
                if len(left) >= 3 and len(right) >= 3:
                    left_yspan = max(l["bbox"][1] for l in left) - min(l["bbox"][1] for l in left)
                    right_yspan = max(l["bbox"][1] for l in right) - min(l["bbox"][1] for l in right)
                    if left_yspan > 100 and right_yspan > 100:
                        is_two_col = True
                        split_x = xs[idx]

    if is_two_col:
        left = sorted([l for l in lines if l["bbox"][0] <= split_x], key=lambda l: l["bbox"][1])
        right = sorted([l for l in lines if l["bbox"][0] > split_x], key=lambda l: l["bbox"][1])
        ordered = left + right
    else:
        ordered = sorted(lines, key=lambda l: l["bbox"][1])

    return "\n".join(l["text"] for l in ordered)


def extract_doc_text(path_or_bytes, gap_threshold=2.5):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        doc = pymupdf.open(stream=path_or_bytes, filetype="pdf")
    else:
        doc = pymupdf.open(path_or_bytes)
    pages = [extract_page_text(p, gap_threshold) for p in doc]
    doc.close()
    text = "\n".join(pages)
    text = strip_page_number_footers(text)
    text = normalize_masked_glyphs(text)
    return text


# ------------------------------------------------------------------
# 청킹 함수 — claude/data-preprocessing-next-steps-wksl8h 브랜치의
# scripts/rechunk_reembed_hwp_fix.py에서 그대로 가져옴. 기존 청크 분포(평균
# 1,321자/중앙값 1,097자/최대 3,002자)에 맞춰 설계된 근사 함수(원본 파이프라인
# 알고리즘 복제 아님) — 실 데이터로 검증하며 버그 2건(문장부호 없는 텍스트에서
# 39,337자짜리 청크, 잔여 3,670자짜리 청크) 발견/수정된 이력 있는 버전.
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
# 1) 대상 문서 조회 — audit_pdf_column_layout.py가 2단 레이아웃으로 플래그한 문서
# ------------------------------------------------------------------
_checkpoint_path = None
for _candidate in (CANDIDATE_CHECKPOINT_PATH, _CANDIDATE_CHECKPOINT_FALLBACK):
    if os.path.exists(_candidate):
        _checkpoint_path = _candidate
        break

if _checkpoint_path is None:
    raise SystemExit(
        f"\n{CANDIDATE_CHECKPOINT_PATH} (또는 로컬 {_CANDIDATE_CHECKPOINT_FALLBACK})를 "
        "찾을 수 없습니다.\n"
        "scripts/audit_pdf_column_layout.py를 먼저 실행해서 2단 레이아웃 후보 목록부터 "
        "만드세요(이제 Drive에 저장하도록 고쳐져 있어서, 실행해두면 세션이 끊겨도 "
        "이 경로에 남습니다). 이미 후보 목록을 다른 이름/경로로 갖고 계시면 "
        "CANDIDATE_CHECKPOINT_PATH를 그 경로로 바꿔서 다시 실행하세요."
    )

target_ids = []
with open(_checkpoint_path, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        if rec.get("flagged"):
            target_ids.append(rec["id"])
print(f"2단 레이아웃 후보: {len(target_ids)}건 (출처: {_checkpoint_path})")

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
# 2) PDF 다운로드 + 재추출 + 신구 유사도 비교 (자동반영 / 수동검토 분리)
# ------------------------------------------------------------------
# audit_pdf_column_layout.py와 동일하게 ThreadPoolExecutor로 병렬 다운로드
# (2,137건을 순차로 돌리면 네트워크 대기 때문에 느림 — I/O 바운드라 스레드로 충분).


def _process_one(doc_id, institution, year, source_file, old_text):
    """문서 1건 다운로드+재추출+유사도 비교 — 스레드 풀에서 병렬 호출됨.
    결과 dict만 반환하고 공유 리스트는 안 건드림(스레드 안전)."""
    url = build_source_url(source_file)
    if not url:
        return {"id": doc_id, "ok": False, "error": "source_file 없음/URL 변환 실패"}
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        new_text = extract_doc_text(resp.content)
    except Exception as e:
        return {
            "id": doc_id, "ok": False, "institution": institution, "year": year,
            "error": str(e),
        }

    old_norm = re.sub(r"\s+", " ", (old_text or "")).strip()
    new_norm = re.sub(r"\s+", " ", new_text).strip()
    sim = difflib.SequenceMatcher(None, old_norm, new_norm).ratio()

    if sim >= SIMILARITY_THRESHOLD:
        return {"id": doc_id, "ok": True, "apply": True, "new_text": new_text}
    return {
        "id": doc_id, "ok": True, "apply": False,
        "institution": institution, "year": year,
        "similarity": round(sim, 4), "old_len": len(old_norm), "new_len": len(new_norm),
    }


apply_list = []  # (doc_id, new_text)
review_list = []  # dict — DB 미반영, 사람 확인용

print_lock = threading.Lock()
n_done = 0

with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
    futures = [pool.submit(_process_one, *row) for row in doc_rows]
    for fut in as_completed(futures):
        result = fut.result()
        if result["ok"] and result["apply"]:
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

print(f"\n자동 반영 대상(유사도 >= {SIMILARITY_THRESHOLD}): {len(apply_list)}건")
print(f"수동 검토 필요(유사도 미달/에러): {len(review_list)}건")

if review_list:
    with open(REVIEW_QUEUE_PATH, "w", encoding="utf-8") as f:
        for r in review_list:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"수동 검토 목록 저장: {REVIEW_QUEUE_PATH} (이 문서들은 DB에 반영 안 됨)")

print("\n자동 반영 대상 샘플 3건:")
for doc_id, new_text in apply_list[:3]:
    print(f"  {doc_id} (len={len(new_text)}): {new_text[:100]!r}")

if DRY_RUN:
    raise SystemExit(
        "\nDRY_RUN=True라 여기서 멈춤(DB 변경 없음). "
        "위 유사도 분포/수동검토 건수가 말이 되면 DRY_RUN=False로 바꿔서 다시 실행하세요."
    )

# ------------------------------------------------------------------
# 3) documents.raw_text UPDATE (자동 반영분만 — 수동검토 큐는 건드리지 않음)
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
# 4) 재청킹 (split_into_chunks 재사용) — 신구 raw_text가 바뀐 문서만 대상
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
# 5) GPU 임베딩 (체크포인트 지원) — 이 아래는 별도 셀로 나눠서 실행 권장
#    (재청킹까지 CPU로 끝내고, 여기부터는 GPU 런타임 전환 후 이어서)
#    rechunk_reembed_hwp_fix.py와 동일 패턴.
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

print("\n완료 — PDF 재추출 반영 + 재청킹 + 재임베딩 끝")
print(f"참고: 수동 검토 큐 {len(review_list)}건은 이번에 반영 안 됐음 — {REVIEW_QUEUE_PATH} 확인 필요")
