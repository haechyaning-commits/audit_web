# ------------------------------------------------------------------
# 원문 렌더링 구조 이상 전수조사 (Colab 실행용, 읽기 전용) — 2026-08-19
# ------------------------------------------------------------------
# 배경: 오늘 하루 사용자가 스크린샷으로 우연히 발견한 렌더링 버그 3건을 각각
# 원인 추적해서 고쳤음(로마숫자 오탐, 각주 공백 미인식, 각주 중 불릿 문단
# 스와핑). 매번 사람이 스크린샷을 찾아서 제보해야 하는 방식은 67,751건 규모
# 에서 지속 불가능하다는 지적 — 렌더링 로직 자체가 "구조를 잘못 흡수/유실"
# 하는 징후를 기계적으로 찾아내는 전수 스캐너로 전환.
#
# **로직 출처**: frontend/src/pages/DetailPage.jsx의 classifyLine()/
# splitIntoBlocks()을 Python으로 그대로 옮김(2026-08-19 시점 최신 버전 —
# 로마숫자 X 오탐 수정, FOOTNOTE_DEF_RE \s* 완화, 각주 중 불릿 흡수 3건 전부
# 반영된 상태). **주의: 저 파일이 나중에 또 바뀌면 이 포팅도 같이 갱신할 것**
# — 그래서 실행 맨 앞에서 실제 검증된 문서 2건(아래 SELF_TEST_DOCS)으로
# 자가 검증부터 하고, 기대한 각주 개수와 다르면 바로 멈춤(로직이 갈라졌다는
# 신호이므로 전수 스캔을 신뢰할 수 없음).
#
# **탐지하는 "구조 이상" 신호** (전부 휴리스틱 — 확정 버그가 아니라 "사람이
# 확인해볼 가치가 있는 후보"를 걸러내는 용도):
#   1) footnote/bullet/table 블록인데 비정상적으로 긺(길이 상한 초과) —
#      원래 각주/불릿은 한두 문장짜리가 많은데, 엉뚱한 문단을 잘못 흡수하면
#      한 블록이 통짜로 길어짐(오늘 발견한 버그들의 공통 증상).
#   2) 문서 안에 각주 참조 번호(footnoteNums)는 있는데 실제 footnote 타입
#      블록이 하나도 안 만들어진 경우 — 각주 인식이 통째로 실패했을 가능성.
#   3) 렌더링된 블록 텍스트 총 글자 수(공백 제외) vs 원본 raw_text 글자 수
#      (공백 제외)가 크게 다른 경우 — 블록화 과정에서 내용이 조용히
#      유실/중복됐을 가능성(정상이면 공백 정규화 차이 정도만 있어야 함).
#   4) 문서 길이가 꽤 되는데(예: 1500자+) heading 타입 블록이 하나도 없는
#      경우 — 구조 인식 자체가 이 문서 양식에서 전혀 안 먹힌 경우일 수 있음.
#
# **DB에 아무것도 안 씀** — 순수 읽기 전용 조사.
# ------------------------------------------------------------------

import json
import os
import re

import psycopg2

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
# DetailPage.jsx 로직 포팅 (2026-08-19 최신 버전)
# ------------------------------------------------------------------
TITLE_RE = re.compile(r"^[\[【]?제\s*목\s*[\]】]?\s*[:：]?\s")
LABEL_SEP = r"(?:[:：]\s*|\s+)"
PAREN_LABEL_RE = re.compile(r"^[(（][^()（）]{1,20}[)）]$")

HEADING_LABEL_PATTERNS = [
    TITLE_RE,
    re.compile(r"^징\s*계\s*(대\s*상\s*자|종\s*류|사\s*유)"),
    re.compile(rf"^(소\s*관|조\s*치|관\s*계)\s*(기\s*관|부\s*서)\s*{LABEL_SEP}\S"),
    re.compile(r"^조\s*치\s*기\s*한\s*[:：]?"),
    re.compile(rf"^감\s*사\s*명\s*{LABEL_SEP}\S"),
    re.compile(r"^관\s*련\s*자\s*[:：]\s*\S"),
    re.compile(rf"^일\s*련\s*번\s*호\s*{LABEL_SEP}\S"),
    re.compile(r"^내\s*용\s*$"),
    re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]?\s"),  # 2026-08-19: 라틴 IVX 제거된 버전
    re.compile(r"^\[(표|그림|별표|붙임|별첨|참고|서식|양식|사진)[\s-]*\d*\]"),
    re.compile(r"^【.+】"),
    re.compile(r"^<.+>$"),
    PAREN_LABEL_RE,
    re.compile(r"^\[[^\[\]]{1,20}\]$"),
    re.compile(
        r"^\[(소\s*관\s*부\s*점\s*의\s*견|통\s*보|관\s*련\s*자\s*의\s*견|관\s*련\s*자|"
        r"모\s*범\s*사\s*례|권\s*고|개\s*선\s*요\s*구|개\s*선|조\s*치\s*할\s*사\s*항|"
        r"현\s*지\s*조\s*치|행\s*정\s*상\s*조\s*치|부\s*서\s*주\s*의|부\s*서\s*명|"
        r"덧\s*붙\s*임|첨\s*부|신\s*분\s*상\s*조\s*치|관\s*련\s*부\s*서\s*의\s*견|"
        r"관\s*련\s*부\s*서|시\s*정\s*요\s*구|현\s*지\s*시\s*정|시\s*정)\s*\]"
    ),
]

BULLET_RE = re.compile(r"^(?:[-–—□○◦▪‣·❍※*]\s*\S|[①②③④⑤⑥⑦⑧⑨⑩]\s+\S)")
GLYPH_BULLET_RE = re.compile(r"^([qm])\s+(?=[^a-z\s])")
SOURCE_NOTE_RE = re.compile(r"^(자료|출처)\s*[:：]")
SECURITY_NOTICE_RE = re.compile(r"^본\s*문서의\s*감사요지\s*및\s*귀책내용이\s*누설되어")
FOOTNOTE_REF_RE = re.compile(r"[^\s\d](\d{1,2})\)")
FOOTNOTE_DEF_RE = re.compile(r"^(\d{1,2})\)\s*\S")
GANADA_HEADING_RE = re.compile(r"^[가나다라마바사아자차카타파하][.)]?\s+\S")
NUMBERED_HEADING_RE = re.compile(r"^\d{1,2}[.)]\s+\S")


def classify_line(line: str) -> str:
    trimmed = line.strip()
    if not trimmed:
        return "blank"
    if GANADA_HEADING_RE.match(trimmed) and len(trimmed) <= 24:
        return "heading"
    if NUMBERED_HEADING_RE.match(trimmed) and len(trimmed) <= 24:
        return "heading"
    if any(p.search(trimmed) for p in HEADING_LABEL_PATTERNS):
        return "heading"
    if SOURCE_NOTE_RE.match(trimmed) or SECURITY_NOTICE_RE.match(trimmed):
        return "caption"
    if BULLET_RE.match(trimmed) or GLYPH_BULLET_RE.match(trimmed):
        return "bullet"
    return "body"


def split_into_blocks(text: str) -> list[dict]:
    footnote_nums = set(m.group(1) for m in FOOTNOTE_REF_RE.finditer(text))

    blocks: list[dict] = []
    para: list[str] = []
    para_type = "body"
    prev_type = None

    def flush_para():
        nonlocal para, para_type, prev_type
        if not para:
            return
        blocks.append({"type": para_type, "text": " ".join(para)})
        prev_type = para_type
        para = []
        para_type = "body"

    for raw_line in text.split("\n"):
        trimmed = raw_line.strip()
        if not trimmed:
            flush_para()
            continue

        effective_prev_type = para_type if para else prev_type
        footnote_match = FOOTNOTE_DEF_RE.match(trimmed)
        if (
            footnote_match
            and footnote_match.group(1) in footnote_nums
            and effective_prev_type in ("body", "footnote")
        ):
            flush_para()
            para_type = "footnote"
            para.append(trimmed)
            continue

        kind = classify_line(trimmed)
        if kind == "heading" and para_type == "table" and PAREN_LABEL_RE.match(trimmed):
            para.append(trimmed)
            continue
        if kind == "heading":
            flush_para()
            blocks.append({"type": "heading", "text": trimmed})
            prev_type = "heading"
            continue
        if kind == "caption":
            flush_para()
            blocks.append({"type": "caption", "text": trimmed})
            prev_type = "caption"
            continue
        if kind == "bullet" and para_type == "footnote":
            para.append(trimmed)
            continue
        if kind == "bullet":
            flush_para()
            para_type = "bullet"
            para.append(trimmed)
            continue
        para.append(trimmed)

    flush_para()
    return blocks


# ------------------------------------------------------------------
# 자가 검증 — 오늘 실제로 원인 특정·검증한 문서 2건으로 포팅이 맞는지 확인.
# 기대치와 다르면 포팅이 DetailPage.jsx와 갈라졌다는 뜻이므로 바로 중단.
# ------------------------------------------------------------------
SELF_TEST_DOCS = {
    # 한국자산관리공사 2021 — 로컬에서 실제 raw_text로 검증: footnote 블록 정확히 16건
    # (참조 번호는 1~19까지 있지만 6/7/8은 별도 각주 정의 없이 실제로 존재 안 함 — 정상).
    "9ddc6393057cc532": {"footnote_blocks": 16},
    # 한국부동산원 2024 — 각주 1~11 전부 분리돼야 함(오늘 세 번째로 고친 "각주 중 불릿
    # 흡수" 버그의 실제 재현 문서).
    "4df12939e14a66c3": {"footnote_blocks": 11},
}

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '30s'")
    cur.execute(
        "SELECT id, raw_text FROM documents WHERE id = ANY(%s)",
        (list(SELF_TEST_DOCS.keys()),),
    )
    self_test_rows = dict(cur.fetchall())
conn.close()

print("=== 자가 검증 ===")
self_test_ok = True
for doc_id, expect in SELF_TEST_DOCS.items():
    raw_text = self_test_rows.get(doc_id)
    if raw_text is None:
        print(f"  {doc_id}: DB에서 못 찾음 — 자가 검증 스킵(문서가 삭제/변경됐을 수 있음)")
        continue
    blocks = split_into_blocks(raw_text)
    n_footnote = sum(1 for b in blocks if b["type"] == "footnote")
    ok = n_footnote == expect["footnote_blocks"]
    print(f"  {doc_id}: footnote 블록 {n_footnote}건 (기대: {expect['footnote_blocks']}) -> {'OK' if ok else 'FAIL'}")
    self_test_ok = self_test_ok and ok

if not self_test_ok:
    raise SystemExit(
        "\n자가 검증 실패 — 이 스크립트의 split_into_blocks()가 지금 "
        "DetailPage.jsx의 실제 로직과 달라진 것으로 보입니다. "
        "frontend/src/pages/DetailPage.jsx 최신 버전 기준으로 포팅을 다시 맞춘 뒤 재실행하세요."
    )
print("자가 검증 통과 — 전수 스캔 진행\n")

# ------------------------------------------------------------------
# 전수 스캔
# ------------------------------------------------------------------
LONG_FOOTNOTE_THRESHOLD = 500   # 각주 하나가 이보다 길면 후보
LONG_BULLET_THRESHOLD = 800     # 불릿 문단이 이보다 길면 후보(불릿은 원래 더 길 수 있어 상한을 넉넉히)
LONG_TABLE_THRESHOLD = 3000     # 표 잔여 텍스트는 원래 길 수 있어 상한을 아주 넉넉히
CONTENT_LOSS_RATIO = 0.85       # 렌더링된 글자 수가 원본의 이 비율보다 적으면 후보
MIN_DOC_LEN_FOR_HEADING_CHECK = 1500  # 이 길이 이상인데 heading이 0개면 후보

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '300s'")
    cur.execute("SELECT id, institution, year, raw_text FROM documents")
    rows = cur.fetchall()
conn.close()
print(f"전체 문서 {len(rows)}건 스캔 시작...\n")

candidates = []
for i, (doc_id, institution, year, raw_text) in enumerate(rows):
    if not raw_text:
        continue
    blocks = split_into_blocks(raw_text)

    reasons = []

    long_footnote = [b for b in blocks if b["type"] == "footnote" and len(b["text"]) > LONG_FOOTNOTE_THRESHOLD]
    if long_footnote:
        reasons.append(f"긴 각주 {len(long_footnote)}건(최대 {max(len(b['text']) for b in long_footnote)}자)")

    long_bullet = [b for b in blocks if b["type"] == "bullet" and len(b["text"]) > LONG_BULLET_THRESHOLD]
    if long_bullet:
        reasons.append(f"긴 불릿문단 {len(long_bullet)}건(최대 {max(len(b['text']) for b in long_bullet)}자)")

    long_table = [b for b in blocks if b["type"] == "table" and len(b["text"]) > LONG_TABLE_THRESHOLD]
    if long_table:
        reasons.append(f"긴 표잔여 {len(long_table)}건(최대 {max(len(b['text']) for b in long_table)}자)")

    footnote_nums_in_text = set(m.group(1) for m in FOOTNOTE_REF_RE.finditer(raw_text))
    n_footnote_blocks = sum(1 for b in blocks if b["type"] == "footnote")
    if footnote_nums_in_text and n_footnote_blocks == 0:
        reasons.append(f"각주 참조({len(footnote_nums_in_text)}개) 있는데 각주 블록 0건")

    rendered_chars = sum(len(re.sub(r"\s+", "", b["text"])) for b in blocks)
    orig_chars = len(re.sub(r"\s+", "", raw_text))
    if orig_chars > 0 and rendered_chars / orig_chars < CONTENT_LOSS_RATIO:
        reasons.append(f"렌더링 글자수 {rendered_chars}/{orig_chars}({rendered_chars/orig_chars*100:.0f}%) — 내용 유실 의심")

    n_heading = sum(1 for b in blocks if b["type"] == "heading")
    if len(raw_text) >= MIN_DOC_LEN_FOR_HEADING_CHECK and n_heading == 0:
        reasons.append(f"문서 {len(raw_text)}자인데 heading 0건")

    if reasons:
        candidates.append({
            "id": doc_id, "institution": institution, "year": year,
            "reasons": reasons, "doc_len": len(raw_text),
        })

    if (i + 1) % 5000 == 0:
        print(f"  {i+1}/{len(rows)}건 처리, 후보 {len(candidates)}건 누적")

print(f"\n스캔 완료 — 전체 {len(rows)}건 중 후보 {len(candidates)}건 "
      f"({len(candidates)/len(rows)*100:.2f}%)")

OUT_PATH = "/content/drive/MyDrive/audit_project/render_anomaly_candidates.jsonl"
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
with open(OUT_PATH, "w", encoding="utf-8") as f:
    for c in candidates:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")
print(f"후보 목록 저장: {OUT_PATH}")

print("\n기관별 후보 분포 (상위 15):")
from collections import Counter
inst_counter = Counter(c["institution"] for c in candidates)
for inst, cnt in inst_counter.most_common(15):
    print(f"  {cnt:4d}건 | {inst}")

print("\n샘플 10건:")
for c in candidates[:10]:
    print(f"  {c['id']} | {c['institution']} {c['year']} | {'; '.join(c['reasons'])}")
