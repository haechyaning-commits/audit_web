# ------------------------------------------------------------------
# 원문 렌더링 구조 이상 전수조사 (Colab 실행용, 읽기 전용) — 2026-08-20 갱신
# ------------------------------------------------------------------
# 배경: 오늘 하루 사용자가 스크린샷으로 우연히 발견한 렌더링 버그 3건을 각각
# 원인 추적해서 고쳤음(로마숫자 오탐, 각주 공백 미인식, 각주 중 불릿 문단
# 스와핑). 매번 사람이 스크린샷을 찾아서 제보해야 하는 방식은 67,751건 규모
# 에서 지속 불가능하다는 지적 — 렌더링 로직 자체가 "구조를 잘못 흡수/유실"
# 하는 징후를 기계적으로 찾아내는 전수 스캐너로 전환.
#
# **2026-08-20 갱신**: PR #21(필드 라벨 분리/법령인용 헤딩 분리/◯N 헤딩/
# 장식 글리프/워터마크 노이즈/표 줄바꿈 보존 등)이 main에 병합되면서
# DetailPage.jsx가 크게 바뀜 — 이 포팅이 8/19 시점 버전에 멈춰 있어서
# 그대로 돌리면 두 가지 문제가 있었음: ①구조 오탐지 신호가 최신 로직과
# 안 맞음(예: "field" 타입 블록을 전혀 몰라서 그 블록들을 전부 "body"로
# 오분류) ②**"field" 블록에 "text" 키가 없어서 rendered_chars 계산에서
# `b["text"]`를 그대로 읽으면 KeyError로 크래시**(관계기관/조치기한/감사명
# /관련자/일련번호 필드가 있는 거의 모든 문서에서 터짐 — 실행 자체가
# 불가능한 상태였음). 아래 로직 전체를 origin/main 46fb5bb(PR #21 병합
# 커밋) 시점 DetailPage.jsx 기준으로 다시 포팅.
#
# **로직 출처**: frontend/src/pages/DetailPage.jsx의 classifyLine()/
# splitIntoBlocks()을 Python으로 그대로 옮김. **주의: 저 파일이 나중에 또
# 바뀌면 이 포팅도 같이 갱신할 것** — 그래서 실행 맨 앞에서 두 단계로
# 자가 검증부터 함: ①DB 없이도 바로 확인 가능한 합성 텍스트 케이스(PR #21/
# main이 최근에 고친 버그들을 그대로 재현) ②실제 검증된 문서 2건(아래
# SELF_TEST_DOCS)의 각주 개수. 둘 중 하나라도 기대와 다르면 바로 멈춤
# (로직이 갈라졌다는 신호이므로 전수 스캔을 신뢰할 수 없음).
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
#      field 블록은 label+value를 합친 길이로 계산(DetailPage.jsx의
#      renderRawText가 화면에 이 둘을 나란히 보여주는 것과 맞춤).
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
# DetailPage.jsx 로직 포팅 (2026-08-20, PR #21 병합 후 최신 버전 기준)
# ------------------------------------------------------------------
TITLE_RE = re.compile(r"""^[\[【]?제\s*목\s*[\]】"'‘’“”]?\s*[:：]?\s""")
LABEL_SEP = r"(?:[:：]\s*|\s+)"
PAREN_LABEL_RE = re.compile(r"^[(（][^()（）]{1,20}[)）]$")
ORNAMENT_GLYPH_LINE_RE = re.compile(r"^[◤◢◣◥]+$")

FIELD_LABEL_PATTERNS = [
    re.compile(rf"^((?:소\s*관|조\s*치|관\s*계)\s*(?:기\s*관|부\s*서))\s*{LABEL_SEP}"),
    re.compile(r"^(조\s*치\s*기\s*한)\s*[:：]?\s*"),
    re.compile(rf"^(감\s*사\s*명)\s*{LABEL_SEP}"),
    re.compile(r"^(관\s*련\s*자)\s*[:：]\s*"),
    re.compile(rf"^(일\s*련\s*번\s*호)\s*{LABEL_SEP}"),
]


def match_field_label(trimmed):
    """줄이 FIELD_LABEL_PATTERNS 중 하나에 매칭되고, 라벨 뒤에 실제 값이
    남아있으면 (label, value)를 반환(라벨만 있고 끝나는 줄은 필드가 아니라
    일반 heading으로 두려고 None 반환)."""
    for pattern in FIELD_LABEL_PATTERNS:
        m = pattern.match(trimmed)
        if m:
            value = trimmed[len(m.group(0)):]
            if value.strip():
                return (m.group(1), value)
    return None


HEADING_LABEL_PATTERNS = [
    TITLE_RE,
    re.compile(r"^징\s*계\s*(대\s*상\s*자|종\s*류|사\s*유)"),
    re.compile(r"^내\s*용\s*$"),
    re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]?\s"),  # 2026-08-19: 라틴 IVX 제거된 버전
    re.compile(r"^◯\d{1,2}\s+\S"),  # 2026-08-18: ◯1/◯2... 항목번호
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

BULLET_RE = re.compile(r"^(?:[-–—□○◦▪‣·❍※•*]\s*\S|[①②③④⑤⑥⑦⑧⑨⑩]\s+\S)")
LONE_BULLET_GLYPH_RE = re.compile(r"^[-–—□○◦▪‣·❍※•]$")
PERSON_LIST_ITEM_RE = re.compile(r"^[A-Z]{1,3}\s*[-–—]\s+\S")  # "C - .../D - ..." 인물목록
GLYPH_BULLET_RE = re.compile(r"^([qm])\s+(?=[^a-z\s])")
GLYPH_BULLET_MAP = {"q": "□", "m": "○"}


def normalize_glyph_bullet(trimmed):
    m = GLYPH_BULLET_RE.match(trimmed)
    if not m:
        return trimmed
    return GLYPH_BULLET_MAP[m.group(1)] + trimmed[len(m.group(1)):]


TABLE_CAPTION_RE = re.compile(
    r"^[【\[]\s*(표|그림|별표)[\s-]*\d*\s*[】\]]"
    r"|^[【\[][^【】\[\]]*(?:명세|현황|내역|명단|실태)\s*[】\]]$"
)
SOURCE_NOTE_RE = re.compile(r"^(자료|출처)\s*[:：]")
SECURITY_NOTICE_RE = re.compile(r"^본\s*문서의\s*감사요지\s*및\s*귀책내용이\s*누설되어")
WATERMARK_NOISE_RE = re.compile(r"^[A-Za-z0-9_:.\s-]{20,}$")


def is_watermark_noise(trimmed):
    return "_" in trimmed and bool(WATERMARK_NOISE_RE.match(trimmed))


FOOTNOTE_REF_RE = re.compile(r"[^\s\d](\d{1,2})\)")
FOOTNOTE_DEF_RE = re.compile(r"^(\d{1,2})\)\s*\S")  # 2026-08-19: \s* 완화된 버전
LIST_HEADING_NUM_RE = re.compile(r"^(\d{1,2})[.)]\s+\S")


def extract_list_num(text):
    m = LIST_HEADING_NUM_RE.match(text)
    return int(m.group(1)) if m else None


QUOTE_CHAR_RE = re.compile(r"""[‘’“”'"]""")


def split_law_citation_heading(trimmed):
    """번호목록 헤딩 줄에서 "법령/조항 인용 라벨 + 그 뒤에 줄바꿈 없이 붙은
    인용문" 경계를 찾아 (라벨, 인용문)으로 나눔. 조건을 만족 못 하면 None."""
    if not LIST_HEADING_NUM_RE.match(trimmed):
        return None
    m = QUOTE_CHAR_RE.search(trimmed)
    if not m or m.start() <= 0:
        return None
    quote_idx = m.start()
    before = trimmed[:quote_idx]
    if not re.search(r"[)）]", before):
        return None  # 조/항 인용 괄호가 하나도 없으면 라벨 아님
    label = before.rstrip()
    body = trimmed[quote_idx:]
    if not label or not body:
        return None
    return (label, body)


TITLE_BLOCK_LEADING_NUM_RE = re.compile(r"^(\d{1,2})[.)]\s")


def fix_missing_title_number(blocks):
    """제목 블록에 번호가 없는데 바로 다음 헤딩이 "2."(이상)로 시작하면
    "1. "이 유실된 것으로 보고 표시용 text에만 보정."""
    title_idx = next(
        (i for i, b in enumerate(blocks) if b["type"] == "heading" and b.get("isTitle")),
        -1,
    )
    if title_idx == -1 or title_idx == len(blocks) - 1:
        return
    title_block = blocks[title_idx]
    if TITLE_BLOCK_LEADING_NUM_RE.match(title_block["text"]):
        return  # 이미 번호 있음
    nxt = blocks[title_idx + 1]
    if nxt["type"] != "heading":
        return
    m = TITLE_BLOCK_LEADING_NUM_RE.match(nxt["text"])
    if m and int(m.group(1)) >= 2:
        title_block["text"] = f"1. {title_block['text']}"


GANADA_HEADING_RE = re.compile(r"^[가나다라마바사아자차카타파하][.)]?\s+\S")
NUMBERED_HEADING_RE = re.compile(r"^\d{1,2}[.)]\s+\S")
SENTENCE_END_RE = re.compile(r"[가-힣][.!?](?:\s|$)")


def classify_line(line: str) -> str:
    trimmed = line.strip()
    if not trimmed:
        return "blank"

    if GANADA_HEADING_RE.match(trimmed) and len(trimmed) <= 24:
        return "heading"
    # 2026-08-18: "1. 2. 3." 번호 항목 — 24자 상한 + 두 가지 예외(법령인용 분리
    # 가능하거나, 80자 이내면서 문장 종결로 안 끝나는 경우)는 헤딩으로 인정.
    if NUMBERED_HEADING_RE.match(trimmed) and (
        len(trimmed) <= 24
        or split_law_citation_heading(trimmed)
        or (len(trimmed) <= 80 and not SENTENCE_END_RE.search(trimmed))
    ):
        return "heading"
    if any(p.match(trimmed) for p in HEADING_LABEL_PATTERNS):
        return "heading"
    if match_field_label(trimmed):
        return "field"
    if SOURCE_NOTE_RE.match(trimmed) or SECURITY_NOTICE_RE.match(trimmed) or is_watermark_noise(trimmed):
        return "caption"
    if BULLET_RE.match(trimmed) or GLYPH_BULLET_RE.match(trimmed) or PERSON_LIST_ITEM_RE.match(trimmed):
        return "bullet"
    return "body"


def split_into_blocks(text: str) -> list[dict]:
    footnote_nums = set(m.group(1) for m in FOOTNOTE_REF_RE.finditer(text))

    blocks: list[dict] = []
    para: list[str] = []
    para_type = "body"
    next_is_table = False
    prev_type = None
    last_heading_list_num = None
    pending_glyph = None

    def flush_para():
        nonlocal para, para_type, prev_type
        if not para:
            return
        text_out = "\n".join(para) if para_type == "table" else " ".join(para)
        blocks.append({"type": para_type, "text": text_out})
        prev_type = para_type
        para = []
        para_type = "body"

    for raw_line in text.split("\n"):
        trimmed = raw_line.strip()

        if not trimmed or ORNAMENT_GLYPH_LINE_RE.match(trimmed):
            if pending_glyph:
                para.append(pending_glyph)
                pending_glyph = None
            flush_para()
            continue

        if LONE_BULLET_GLYPH_RE.match(trimmed):
            pending_glyph = trimmed
            continue
        if pending_glyph:
            trimmed = f"{pending_glyph} {trimmed}"
            pending_glyph = None

        effective_prev_type = para_type if para else prev_type
        footnote_match = FOOTNOTE_DEF_RE.match(trimmed)
        continues_heading_list = (
            last_heading_list_num is not None
            and footnote_match is not None
            and int(footnote_match.group(1)) == last_heading_list_num + 1
        )
        if (
            footnote_match
            and footnote_match.group(1) in footnote_nums
            and effective_prev_type in ("body", "footnote")
            and not continues_heading_list
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
            citation_split = split_law_citation_heading(trimmed)
            if citation_split:
                label, body = citation_split
                blocks.append({"type": "heading", "text": label, "isTitle": bool(TITLE_RE.match(label))})
                prev_type = "heading"
                last_heading_list_num = extract_list_num(label)
                next_is_table = False
                para_type = "body"
                para.append(body)
                continue
            blocks.append({"type": "heading", "text": trimmed, "isTitle": bool(TITLE_RE.match(trimmed))})
            prev_type = "heading"
            last_heading_list_num = extract_list_num(trimmed)
            next_is_table = bool(TABLE_CAPTION_RE.match(trimmed))
            continue
        if kind == "field":
            flush_para()
            label, value = match_field_label(trimmed)
            blocks.append({"type": "field", "label": label, "value": value})
            prev_type = "field"
            next_is_table = False
            continue
        if kind == "caption":
            flush_para()
            blocks.append({"type": "caption", "text": trimmed})
            prev_type = "caption"
            next_is_table = False
            continue
        if kind == "bullet" and para_type == "footnote":
            para.append(normalize_glyph_bullet(trimmed))
            continue
        if kind == "bullet":
            flush_para()
            para_type = "bullet"
            next_is_table = False
            para.append(normalize_glyph_bullet(trimmed))
            continue
        if not para and next_is_table:
            para_type = "table"
            next_is_table = False
        para.append(trimmed)

    if pending_glyph:
        para.append(pending_glyph)
    flush_para()
    fix_missing_title_number(blocks)
    return apply_dept_mask(blocks)


def mask_dept_placeholder(text: str) -> str:
    """"[부서]" 익명화 placeholder를 화면 표시용 "○○○"로 치환 — DetailPage.jsx가
    splitIntoBlocks 맨 끝에서 적용하는 것과 동일(원문 자체·구조 분류는 안 건드리고
    표시 단계에서만 적용되므로, 여기서도 분류가 다 끝난 뒤 블록 텍스트에만 적용)."""
    return text.replace("[부서]", "○○○")


def apply_dept_mask(blocks: list[dict]) -> list[dict]:
    for b in blocks:
        if b["type"] == "field":
            b["label"] = mask_dept_placeholder(b["label"])
            b["value"] = mask_dept_placeholder(b["value"])
        else:
            b["text"] = mask_dept_placeholder(b["text"])
    return blocks


def block_render_text(b: dict) -> str:
    """블록 하나가 화면에 보여주는 텍스트 — field는 label+value를 합침
    (renderRawText가 이 둘을 나란히 보여주는 것과 맞춤, DetailPage.jsx 참고)."""
    if b["type"] == "field":
        return f"{b['label']}{b['value']}"
    return b.get("text", "")


# ------------------------------------------------------------------
# 자가 검증 1단계 — DB 없이 바로 확인 가능한 합성 텍스트로, PR #21/main이
# 최근에 고친 버그들이 이 포팅에도 그대로 반영됐는지 확인.
# ------------------------------------------------------------------
def run_synthetic_self_tests():
    failures = []

    def check(name, cond):
        print(f"  {'OK' if cond else 'FAIL'}: {name}")
        if not cond:
            failures.append(name)

    # 각주가 괄호 뒤 공백 없어도 인식되는지(main, \s* 완화)
    text = "본문 문단에서 지적된 금액18)은 환수 조치됨\n\n18)「감사규정」제5조에 따라 처리함\n이어지는 각주 내용"
    blocks = split_into_blocks(text)
    check("각주: 괄호 뒤 공백 없어도 인식(\\s* 완화)", any(b["type"] == "footnote" for b in blocks))

    # 법령인용 헤딩 분리(PR #21)
    text = "1) 법령 「공직자윤리법」 제3조의2 제2항(공기업) '공직유관단체인 우리 공사는 ...'"
    blocks = split_into_blocks(text)
    heading = next((b for b in blocks if b["type"] == "heading"), None)
    body = next((b for b in blocks if b["type"] == "body"), None)
    check("법령인용 헤딩: 라벨만 분리", heading is not None and "공직유관단체" not in heading["text"])
    check("법령인용 헤딩: 인용문은 body로", body is not None and "공직유관단체" in body["text"])

    # 필드 라벨 분리(PR #21) — "field" 블록이 만들어지고 KeyError 없이 길이 계산되는지
    text = "소관부서 [부서]사업소\n본문 내용"
    blocks = split_into_blocks(text)
    field = next((b for b in blocks if b["type"] == "field"), None)
    check("필드 라벨: field 블록 생성", field is not None and field.get("label", "").strip() == "소관부서")
    check("필드 라벨: block_render_text가 KeyError 없이 동작", all(block_render_text(b) is not None for b in blocks))

    # 제목 번호 유실 보정(main, isTitle/fixMissingTitleNumber)
    text = "【제 목】 2026년 정기감사 결과\n2. 관계기관 : 한국공사\n3. 감사기간 : 2026.1.1.~2026.1.31."
    blocks = split_into_blocks(text)
    title_block = next((b for b in blocks if b["type"] == "heading" and b.get("isTitle")), None)
    check("제목 번호 보정: 제목 블록 인식 + '1. ' 보정", title_block is not None and title_block["text"].startswith("1. "))

    # ◯N 헤딩 패턴(PR #21)
    text = "◯1 음주관리 및 근무에 관한 사항 (신분상・행정상조치)"
    blocks = split_into_blocks(text)
    check("◯N 헤딩 패턴 인식", any(b["type"] == "heading" and b["text"].startswith("◯1") for b in blocks))

    # 로마숫자 오탐 제거(main) — 표 셀 값 "X"가 장 제목으로 오인되지 않는지
    text = "X 기능 개선시 별도 인증 필요"
    blocks = split_into_blocks(text)
    check("'X ...'는 로마숫자 헤딩으로 오탐되지 않음", not any(b["type"] == "heading" and b["text"].startswith("X ") for b in blocks))

    # 장식 글리프 줄(PR #21) — 빈 줄처럼 처리돼 독립 블록을 안 만드는지
    text = "Ⅰ 감사실시 개요\n◤\n1. 감사배경 및 목적"
    blocks = split_into_blocks(text)
    check("장식 글리프(◤) 단독 줄은 body에 안 섞임", not any("◤" in block_render_text(b) for b in blocks if b["type"] == "body"))

    if failures:
        raise SystemExit(
            f"\n합성 자가 검증 실패({len(failures)}건): {failures}\n"
            "이 스크립트의 split_into_blocks()가 지금 DetailPage.jsx의 실제 로직과 "
            "달라진 것으로 보입니다. frontend/src/pages/DetailPage.jsx 최신 버전 기준으로 "
            "포팅을 다시 맞춘 뒤 재실행하세요."
        )


print("=== 자가 검증 1단계 (합성 텍스트, DB 불필요) ===")
run_synthetic_self_tests()
print("합성 자가 검증 통과\n")

# ------------------------------------------------------------------
# 자가 검증 2단계 — 오늘 실제로 원인 특정·검증한 문서 2건으로 포팅이 맞는지 확인.
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

print("=== 자가 검증 2단계 (실제 문서, DB) ===")
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

    rendered_chars = sum(len(re.sub(r"\s+", "", block_render_text(b))) for b in blocks)
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
