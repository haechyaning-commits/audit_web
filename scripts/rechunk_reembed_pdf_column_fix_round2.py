# ------------------------------------------------------------------
# PDF 2단 레이아웃 재추출 반영 — 2차 (순서만 바뀐 문서 구제) (Colab 실행용)
# ------------------------------------------------------------------
# 배경: rechunk_reembed_pdf_column_fix.py(1차) 실행 후 722건 자동반영 + 1,415건
# 수동검토로 갈렸음. 그런데 이 프로젝트의 원조 검증 기준 문서였던
# 한국철도공사 2020(dec56dc84bfe3a6c)조차 수동검토 큐에 남아있는 걸 발견해서
# 직접 재현 검증함(2026-08-18):
#
#   - 이 PDF를 실제로 재추출해보면 "◯1 음주관리...◯5 조작판..." 뒤섞인 목록이
#     정확히 1→2→3→4→5→6→7→8 순서로 완벽하게 고쳐짐(원하던 결과 그대로).
#   - 근데 이 새 텍스트를 DB의 옛(뒤섞인) 원문과 순서 기반 유사도(difflib)로 비교하면
#     0.535밖에 안 나옴 — 뒤섞인 걸 바로잡았으니 당연히 옛 텍스트와 순서가 많이
#     달라짐. 그래서 1차의 SIMILARITY_THRESHOLD(0.90) 게이트에 걸려 자동반영에서
#     제외됨.
#   - 직접 확인: 글자를 순서 무시하고 멀티셋으로 비교하면 유사도 1.0, 길이 비율도
#     1.013 — 즉 내용 손실/추가 없이 **순서만 고쳐진** 케이스였음이 수치로 확인됨.
#
# **핵심 문제**: 1차의 유사도 게이트는 "옛 텍스트와 얼마나 비슷한가"를 재는데, 이
# 프로젝트 목적 자체가 "뒤섞인 옛 텍스트를 순서대로 고치는 것"이라서, 가장
# 성공적으로 고쳐진 문서일수록(뒤섞임이 심했을수록) 옛 텍스트와 제일 달라져서
# 게이트에 걸리는 역설이 있었음. 표 뒤섞임/2단 리스트 뒤섞임이 심한 문서일수록
# 오히려 구제가 안 되는 구조였던 것.
#
# **이 스크립트의 추가 기준**: 1차의 순서 기반 유사도(SIMILARITY_THRESHOLD)를 통과
# 못 해도, 아래 둘 다 만족하면 "순서만 바뀐 안전한 케이스"로 보고 추가 반영:
#   1) 글자(공백 제외) 멀티셋 유사도(bag_similarity) >= REORDER_BAG_THRESHOLD
#      — 같은 글자들로 이뤄져 있는지(순서 무시). 표 뒤섞임/선행 상용구 문제는
#        글자 자체가 달라지므로(내용 추가/손실) 이 기준에서 자연히 걸러짐.
#   2) 길이 비율(new/old)이 REORDER_LEN_RATIO_LOW~HIGH 범위 안 — 혹시 모를
#      큰 폭의 내용 손실/추가를 한 번 더 방어(멀티셋 유사도만으로는 "같은
#      글자가 반씩 두 번 나오는" 것 같은 병적 케이스를 완전히 못 잡을 수 있어서
#      길이도 같이 봄).
#
# **실행 순서**: 1차(rechunk_reembed_pdf_column_fix.py)와 동일 —
#   1) DRY_RUN=True로 먼저 — 이번엔 몇 건이 추가로 구제되는지, 순서기반/멀티셋기반
#      중 어느 쪽으로 통과했는지 확인.
#   2) 이상 없으면 DRY_RUN=False로 재실행 — 백업 -> UPDATE -> 재청킹 -> 재임베딩.
# ------------------------------------------------------------------

# !pip install -q pymupdf psycopg2-binary requests FlagEmbedding pgvector

import datetime
import difflib
import hashlib
import json
import os
import re
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import psycopg2
import pymupdf
import requests
from psycopg2.extras import execute_values

DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로
SIMILARITY_THRESHOLD = 0.90  # 1차와 동일 — 순서 기반 유사도로 그냥 통과하는 기준
REORDER_BAG_THRESHOLD = 0.97  # 순서 무시 글자 멀티셋 유사도 — 이 이상이면 "같은 내용"
REORDER_LEN_RATIO_LOW = 0.95
REORDER_LEN_RATIO_HIGH = 1.05  # 길이 비율이 이 범위 안이어야 "순서만 바뀜"으로 인정
DOWNLOAD_WORKERS = 16

REVIEW_QUEUE_PATH = "/content/drive/MyDrive/audit_project/pdf_reextract_manual_review.jsonl"
REVIEW_QUEUE_PATH_ROUND2 = "/content/drive/MyDrive/audit_project/pdf_reextract_manual_review_round2.jsonl"
EMBED_CHECKPOINT_PATH = "/content/drive/MyDrive/audit_project/pdf_reextract_embed_checkpoint_round2.jsonl"
BATCH_SIZE = 64
MAX_LENGTH = 1024

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


# ------------------------------------------------------------------
# build_source_url / 재추출 로직 / split_into_chunks — 1차 스크립트와 동일
# (rechunk_reembed_pdf_column_fix.py 참고, 그대로 복사)
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


_MASK_GLYPH_RE = re.compile(r"([○◎□●■☆★△▲▽▼◇◆])\1+")
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
# 순서 무시 글자 멀티셋 유사도 — 이 스크립트에서 새로 추가된 부분
# ------------------------------------------------------------------
def bag_similarity(a: str, b: str) -> float:
    """공백 제외 글자 멀티셋(Counter) 기준 유사도. 순서는 완전히 무시하고
    "같은 글자들로 이뤄져 있는가"만 봄 — 표 뒤섞임/선행 상용구처럼 실제
    내용이 추가/손실된 경우엔 자연히 낮게 나오고, 순서만 바뀐 경우엔 1.0에
    가깝게 나옴(위 헤더 주석의 한국철도공사 문서 실측: 1.0)."""
    ca, cb = Counter(a.replace(" ", "")), Counter(b.replace(" ", ""))
    common = sum((ca & cb).values())
    total = max(sum(ca.values()), sum(cb.values()))
    return common / total if total else 1.0


# ------------------------------------------------------------------
# 1) 대상 문서 조회 — 1차의 수동검토 큐에 남은 문서만 (에러 건 포함, 재시도)
# ------------------------------------------------------------------
if not os.path.exists(REVIEW_QUEUE_PATH):
    raise SystemExit(
        f"\n{REVIEW_QUEUE_PATH}를 찾을 수 없습니다. "
        "rechunk_reembed_pdf_column_fix.py(1차)를 먼저 실행해서 수동검토 큐부터 만드세요."
    )

target_ids = []
with open(REVIEW_QUEUE_PATH, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        target_ids.append(rec["id"])
print(f"1차 수동검토 큐: {len(target_ids)}건 — 이번엔 순서 무시 유사도까지 재검사")

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
# 2) PDF 다운로드 + 재추출 + 이중 게이트(순서기반 OR 순서무시+길이비율) 판정
# ------------------------------------------------------------------
def _process_one(doc_id, institution, year, source_file, old_text):
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
        return {"id": doc_id, "ok": True, "apply": True, "reason": "sequence", "new_text": new_text}

    bag_sim = bag_similarity(old_norm, new_norm)
    len_ratio = len(new_norm) / len(old_norm) if old_norm else 0
    if bag_sim >= REORDER_BAG_THRESHOLD and REORDER_LEN_RATIO_LOW <= len_ratio <= REORDER_LEN_RATIO_HIGH:
        return {"id": doc_id, "ok": True, "apply": True, "reason": "reorder", "new_text": new_text}

    return {
        "id": doc_id, "ok": True, "apply": False,
        "institution": institution, "year": year,
        "similarity": round(sim, 4), "bag_similarity": round(bag_sim, 4),
        "len_ratio": round(len_ratio, 4),
        "old_len": len(old_norm), "new_len": len(new_norm),
    }


apply_list = []  # (doc_id, new_text, reason)
review_list = []  # dict — DB 미반영, 사람 확인용

print_lock = threading.Lock()
n_done = 0

with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
    futures = [pool.submit(_process_one, *row) for row in doc_rows]
    for fut in as_completed(futures):
        result = fut.result()
        if result["ok"] and result["apply"]:
            apply_list.append((result["id"], result["new_text"], result["reason"]))
        else:
            review_list.append({k: v for k, v in result.items() if k not in ("ok", "apply")})
        with print_lock:
            n_done += 1
            if n_done % 20 == 0 or n_done == len(doc_rows):
                print(f"  {n_done}/{len(doc_rows)}건 처리, 추가반영 {len(apply_list)}건, 여전히 검토필요 {len(review_list)}건")

n_by_reason = Counter(r for _, _, r in apply_list)
print(f"\n추가 반영 대상: {len(apply_list)}건 (순서기반 {n_by_reason['sequence']}건 + 순서무시/재정렬 {n_by_reason['reorder']}건)")
print(f"여전히 수동검토 필요: {len(review_list)}건")

if review_list:
    with open(REVIEW_QUEUE_PATH_ROUND2, "w", encoding="utf-8") as f:
        for r in review_list:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"남은 수동검토 목록 저장: {REVIEW_QUEUE_PATH_ROUND2}")

print("\n'reorder'로 통과한 샘플 3건:")
for doc_id, new_text, reason in [x for x in apply_list if x[2] == "reorder"][:3]:
    print(f"  {doc_id}: {new_text[:100]!r}")

if DRY_RUN:
    raise SystemExit(
        "\nDRY_RUN=True라 여기서 멈춤(DB 변경 없음). "
        "위 결과가 말이 되면 DRY_RUN=False로 바꿔서 다시 실행하세요."
    )

# ------------------------------------------------------------------
# 2.5) 백업 (1차와 동일 패턴)
# ------------------------------------------------------------------
BACKUP_PATH = (
    f"/content/drive/MyDrive/audit_project/"
    f"pdf_reextract_backup_round2_{datetime.datetime.now():%Y%m%d_%H%M%S}.jsonl"
)
_apply_ids = [doc_id for doc_id, _, _ in apply_list]

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
        for doc_id, new_text, _ in apply_list:
            cur.execute("UPDATE documents SET raw_text = %s WHERE id = %s", (new_text, doc_id))
        conn.commit()
    print(f"documents.raw_text 갱신: {len(apply_list)}건")
finally:
    conn.close()

# ------------------------------------------------------------------
# 4) 재청킹
# ------------------------------------------------------------------
new_chunks = []
for doc_id, new_text, _ in apply_list:
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
        target_id_list = [doc_id for doc_id, _, _ in apply_list]
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
# 5) GPU 임베딩 (1차와 동일 패턴)
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
            ([doc_id for doc_id, _, _ in apply_list],),
        )
        print(f"\n임베딩 안 된 청크(0이어야 정상): {cur.fetchone()[0]}건")
finally:
    conn.close()

print("\n완료 — PDF 재추출 2차(순서 구제) 반영 + 재청킹 + 재임베딩 끝")
print(f"참고: 여전히 수동검토 필요한 {len(review_list)}건은 {REVIEW_QUEUE_PATH_ROUND2} 확인")
