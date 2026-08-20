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
# **알려진 버그(2026-08-20, 전부 수정됨)**: SELF_TEST_DOCS의 9ddc6393057cc532
# 문서는 실제로는 각주가 19개(6/7/8도 존재)인데 **포팅 문제가 아니라
# DetailPage.jsx 자체의 실제 렌더링 버그**(Node로 실제 파일과 대조 확인함) 때문에
# 일부가 body/heading에 흡수됐었음 — Colab 디버그 추적으로 원인 3가지(불릿/표 문단
# 흡수, 그로 인한 헤딩 오분류 연쇄)를 실제로 특정해서 effectivePrevType 허용
# 목록에 "bullet"/"table" 추가로 6~10을 고침(12→17건, 실제 DB로 확인 완료). 남은
# 15/16도 같은 날 후속 세션에서 해결 — 각주 정의문이 인용한 법조항 번호("5. 공사의
# 여러 규정...")가 번호 헤딩 휴리스틱에 걸려 heading으로 잘못 승격되던 게 원인이라,
# 각주 문단 누적 중 나온 이런 줄을 흡수하도록 수정(17→19건, 실제 API로 확인).
# 이 클래스의 버그(각주 참조는 있는데 일부만 인식)는 아래 4개 탐지 신호로 못 잡을
# 수 있다는 점을 감안하고 후보 목록을 볼 것.
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


# 2026-08-14 10차: "[통보] ○○팀장은..." "[관련자 의견] 관련자는..."처럼 대괄호
# 라벨 뒤에 줄바꿈 없이 내용이 바로 이어지는 경우도 헤딩으로 인식시키려고 일부러
# 줄 끝 고정($) 없이 만든 패턴 — HEADING_LABEL_PATTERNS 맨 끝에서 쓰고,
# split_into_blocks의 split_bracket_label_heading에서 라벨/내용 분리에도 재사용
# 하므로 그 두 곳보다 앞에 선언해둠(DetailPage.jsx와 동일 반영, 동작 변경 없음).
BRACKET_LABEL_WITH_TRAILING_RE = re.compile(
    r"^\[(소\s*관\s*부\s*점\s*의\s*견|통\s*보|관\s*련\s*자\s*의\s*견|관\s*련\s*자|"
    r"모\s*범\s*사\s*례|권\s*고|개\s*선\s*요\s*구|개\s*선|조\s*치\s*할\s*사\s*항|"
    r"현\s*지\s*조\s*치|행\s*정\s*상\s*조\s*치|부\s*서\s*주\s*의|부\s*서\s*명|"
    r"덧\s*붙\s*임|첨\s*부|신\s*분\s*상\s*조\s*치|관\s*련\s*부\s*서\s*의\s*견|"
    r"관\s*련\s*부\s*서|시\s*정\s*요\s*구|현\s*지\s*시\s*정|시\s*정)\s*\]"
)

# 2026-08-20: "붙임 : 1. 관련자 문답서(2021. 3. 10.)\n2. 당시...개별면담 내용(...)"
# 처럼 문서 끝 첨부목록을 여는 "붙임"이 인식되는 라벨이 아니라서 앞 문장에 그대로
# 병합되고, 그 안 "2. ..." 항목은 번호 헤딩 휴리스틱에 걸려 혼자만 heading으로
# 튀는 문제(9ddc6393057cc532 실제 발췌) — HEADING_LABEL_PATTERNS와
# split_into_blocks의 split_attachment_label 둘 다에서 써서 그 두 곳보다 앞에
# 선언(DetailPage.jsx와 동일 반영).
ATTACHMENT_LABEL_RE = re.compile(rf"^(붙\s*임)\s*{LABEL_SEP}")

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
    BRACKET_LABEL_WITH_TRAILING_RE,
    ATTACHMENT_LABEL_RE,
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


# 2026-08-20: 이 정규식(DetailPage.jsx 원본 그대로) 자체가 오탐이 많다는 걸 실제
# 전수 스캔에서 발견함 — "공백/숫자가 아닌 아무 문자"가 너무 느슨해서 날짜 표기
# ('24.06.24)"의 "."), 괄호 열거번호("(10) 그런데..."의 "("), 익명화 마스킹
# ("+0+0+0)"의 "+") 뒤에 오는 숫자+")"까지 전부 "각주 참조"로 잡아버림(실제
# 감사보고서 5건을 직접 원문으로 확인, 전부 각주가 아예 없는 정상 문서였음).
# **split_into_blocks() 안의 footnote_nums 계산은 DetailPage.jsx를 그대로 미러링
# 해야 하므로 이 느슨한 버전을 그대로 둠** — 대신 아래 전수 스캔의 "각주 참조는
# 있는데 블록 0건" 신호(신호 ②)를 만들 때만 FOOTNOTE_REF_STRICT_RE를 따로 씀
# (신호 정확도만 개선, DetailPage.jsx가 실제로 쓰는 판별 로직 자체는 안 건드림 —
# 오늘은 프로덕션 수정 없이 스캔만 진행하기로 한 결정 유지, STATUS.md 참고).
FOOTNOTE_REF_RE = re.compile(r"[^\s\d](\d{1,2})\)")

# "각주 참조는 있는데 블록 0건" 신호(②) 전용 — 실제 각주 참조는 항상 한글 글자
# 바로 뒤에 붙음(원 주석 예시: "87,818,181원1)", "위임2)" — "원"/"임" 모두 한글).
# 한글 글자로 좁히면 위 날짜/괄호열거/마스킹 오탐이 전부 사라짐(5건 실제 확인).
FOOTNOTE_REF_STRICT_RE = re.compile(r"[가-힣](\d{1,2})\)")

# 2026-08-20: 신호② 표본 재조사(18b48a4726dad247)에서 발견한 추가 오탐 —
# "(통보1)"/"(주의1)"처럼 감사보고서 조치유형을 순번으로 분류한 코드가
# "통보"/"주의" 둘 다 한글이라 FOOTNOTE_REF_STRICT_RE를 그대로 통과함(각주가
# 아님). 감사원/공공기관 감사보고서에서 표준적으로 쓰이는 조치요구 유형
# 명칭만 좁게 나열 — "괄호로 감싼 조치유형+번호" 형태([조치유형N)] 전체가
# 아니라 "(조치유형N)"처럼 여닫는 괄호가 다 있는 경우만)로 한정해서, 실제
# 각주 참조(예: "감사원에 통보18)")처럼 괄호 없이 문장 중간에 나오는 경우는
# 오히려 걸러내지 않도록 함(오탐 필터가 진짜 각주까지 지우는 역효과 방지).
ACTION_TYPE_KEYWORDS = (
    "통보", "주의", "시정", "개선", "권고", "문책", "징계", "고발", "훈계", "경고", "변상",
)
ACTION_TYPE_CODE_RE = re.compile(
    r"\((" + "|".join(ACTION_TYPE_KEYWORDS) + r")(\d{1,2})\)"
)


def strict_footnote_nums(text):
    """FOOTNOTE_REF_STRICT_RE로 잡히는 각주 참조 번호 집합 — 조치유형 분류
    코드(ACTION_TYPE_CODE_RE와 겹치는 매치)는 제외."""
    action_spans = [m.span() for m in ACTION_TYPE_CODE_RE.finditer(text)]
    nums = set()
    for m in FOOTNOTE_REF_STRICT_RE.finditer(text):
        if any(a_start <= m.start() and m.end() <= a_end for a_start, a_end in action_spans):
            continue
        nums.add(m.group(1))
    return nums
FOOTNOTE_DEF_RE = re.compile(r"^(\d{1,2})\)\s*\S")  # 2026-08-19: \s* 완화된 버전
# 2026-08-20: 원래 "[.)]"로 마침표/괄호 둘 다 받았는데, 이 번호가 각주 오판별
# 방지(continuesHeadingList)에 쓰이면서 실제 문서(한국조폐공사 2016,
# f35fdc468543c358 / 한국자산관리공사 2021, 9ddc6393057cc532)로 확인된 버그가
# 있었음 — "1. 업무개요 / 2. 관계규정..." 같은 마침표 최상위 섹션 번호(거의
# 모든 감사보고서에 있는 흔한 구조)까지 이 카운터를 오염시켜서, 뒤에 나오는
# 진짜 각주("1)"/"2)")가 "목록 연속"으로 오판별돼 인식이 안 되던 문제. 실제
# "N) 법령 「...」..." 인용 목록은 지금까지 확인된 사례 전부 괄호만 썼음 —
# 괄호만 받게 좁힘(DetailPage.jsx와 동일하게 반영).
LIST_HEADING_NUM_RE = re.compile(r"^(\d{1,2})\)\s+\S")


def extract_list_num(text):
    m = LIST_HEADING_NUM_RE.match(text)
    return int(m.group(1)) if m else None


QUOTE_CHAR_RE = re.compile(r"""[‘’“”'"]""")


LEADING_NUM_PREFIX_RE = re.compile(r"^\d{1,2}\)\s*")


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
    # 2026-08-20: "7) 2021. 1. 30. 모바일 익명 커뮤니티 앱인 '블라인드'의..."처럼
    # 각주 정의 줄 자체가 우연히 비공식 인용부호(속어/앱 이름 등)를 포함하면,
    # 번호 접두어 자체의 괄호("7)"의 ")")까지 "조/항 인용 괄호"로 오인해서 각주가
    # 헤딩으로 잘못 쪼개지는 버그를 실제 문서(9ddc6393057cc532)로 확인함 —
    # 번호 접두어는 제외하고 그 "뒤"에 별도의 조/항 인용 괄호가 있는지만 봄.
    leading_num = LEADING_NUM_PREFIX_RE.match(before)
    after_leading_num = before[leading_num.end():] if leading_num else before
    if not re.search(r"[)）]", after_leading_num):
        return None  # 조/항 인용 괄호가 없으면 라벨 아님
    label = before.rstrip()
    body = trimmed[quote_idx:]
    if not label or not body:
        return None
    return (label, body)


def split_bracket_label_heading(trimmed):
    """BRACKET_LABEL_WITH_TRAILING_RE("[통보]"/"[관련자 의견]" 등)에 매칭되고
    "]" 뒤에 실제 내용이 남아있으면 (라벨, 내용)으로 나눔(split_law_citation_heading과
    같은 목적·같은 방식) — DetailPage.jsx의 splitBracketLabelHeading과 동일 반영.
    라벨 하나로 줄이 끝나면(내용 없음) None(그 경우는 이미 위 "줄 전체가 라벨뿐"
    패턴이 먼저 걸러서 실제로는 거의 안 옴)."""
    m = BRACKET_LABEL_WITH_TRAILING_RE.match(trimmed)
    if not m:
        return None
    label = m.group(0).strip()
    body = trimmed[len(m.group(0)):].strip()
    if not label or not body:
        return None
    return (label, body)


def split_attachment_label(trimmed):
    """ATTACHMENT_LABEL_RE에 매칭되면 (라벨, 나머지내용)으로 나눔(내용이 없으면
    빈 문자열 — "붙임" 혼자 나오고 다음 줄부터 목록이 시작하는 문서도 있을 수
    있어서 위 두 split_*_heading과 달리 None을 반환 안 함). DetailPage.jsx의
    splitAttachmentLabel과 동일 반영."""
    m = ATTACHMENT_LABEL_RE.match(trimmed)
    if not m:
        return None
    label = m.group(1)
    body = trimmed[len(m.group(0)):].strip()
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


# 2026-08-20: classify_line의 "가/나/다" 및 "1. 2. 3." 번호 헤딩 휴리스틱을 별도
# 함수로 뽑아냄(DetailPage.jsx의 isGenericListHeading과 동일한 이유·동일한 분리) —
# split_into_blocks에서 각주 문단 흡수 여부를 판단할 때도 재사용(아래 각주15/16 버그
# 수정 참고). 동작 변경 없는 순수 리팩터링.
def is_generic_list_heading(trimmed: str) -> bool:
    if GANADA_HEADING_RE.match(trimmed) and len(trimmed) <= 24:
        return True
    # 2026-08-18: "1. 2. 3." 번호 항목 — 24자 상한 + 두 가지 예외(법령인용 분리
    # 가능하거나, 80자 이내면서 문장 종결로 안 끝나는 경우)는 헤딩으로 인정.
    if NUMBERED_HEADING_RE.match(trimmed) and (
        len(trimmed) <= 24
        or split_law_citation_heading(trimmed)
        or (len(trimmed) <= 80 and not SENTENCE_END_RE.search(trimmed))
    ):
        return True
    return False


def classify_line(line: str) -> str:
    trimmed = line.strip()
    if not trimmed:
        return "blank"

    if is_generic_list_heading(trimmed):
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


# 2026-08-20: 각주 판별 조건에서 허용하는 "직전 문단 타입" — 실제 문서(한국자산관리공사
# 2021, 9ddc6393057cc532)를 디버그 추적해서 확인함. "*" 불릿이 먼저 나와서 그 뒤
# 평문들을 "bullet" 문단으로 계속 흡수하다가 진짜 각주 정의 줄까지 삼키는 경우, 그리고
# "[표 N]" 캡션 뒤 표 데이터를 흡수하는 중에 각주 정의 줄이 나오는 경우 둘 다 원래
# ("body", "footnote")만 허용하던 조건에 안 걸려서 각주 인식이 통째로 실패하고 있었음.
# SOURCE_NOTE_RE("자료:"/"출처:")가 표 블록을 강제로 끝내는 경계로 이미 쓰이는 것과
# 같은 이유로, 진짜 각주 정의 줄(번호가 footnoteNums에 있음)도 불릿/표 문단을 끝내는
# 경계로 인정함(DetailPage.jsx와 동일하게 반영).
FOOTNOTE_ALLOWED_PREV_TYPES = frozenset({"body", "footnote", "bullet", "table"})


def split_into_blocks(text: str) -> list[dict]:
    footnote_nums = set(m.group(1) for m in FOOTNOTE_REF_RE.finditer(text))

    blocks: list[dict] = []
    para: list[str] = []
    para_type = "body"
    next_is_table = False
    prev_type = None
    last_heading_list_num = None
    pending_glyph = None
    # 2026-08-20: "붙임" 라벨 바로 뒤 첨부목록 문단을 누적하는 중인지 — split_attachment_label
    # 주석 참고. DetailPage.jsx의 inAttachmentList와 동일 반영 — flush_para()에서 매번
    # False로 리셋되므로 "같은 문단이 이어지는 동안만" true로 유지됨.
    in_attachment_list = False

    def flush_para():
        nonlocal para, para_type, prev_type, in_attachment_list
        in_attachment_list = False
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
            and effective_prev_type in FOOTNOTE_ALLOWED_PREV_TYPES
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
        # 2026-08-20: 각주 15/16 미인식 버그 수정(DetailPage.jsx와 동일 반영) — 각주
        # 정의문이 법조항을 그대로 인용하면서 다음 줄이 "5. ..."처럼 번호로 시작하면
        # is_generic_list_heading(번호 헤딩 휴리스틱)에 걸려 heading으로 잘못 승격되고,
        # 그 순간 flush_para()로 각주 문단이 끊겨 prev_type이 "heading"이 됨 — 바로
        # 다음에 오는 진짜 각주가 FOOTNOTE_ALLOWED_PREV_TYPES에 "heading"이 없어서
        # 아예 인식 실패로 이어지던 연쇄(실제 문서 9ddc6393057cc532, 각주 17개→19개로
        # 검증 — 위 PAREN_LABEL_RE 표 흡수와 같은 이유). split_law_citation_heading으로
        # 분리되는 진짜 법령인용 헤딩은 명확한 구조 신호라 이 흡수에서 제외.
        if (
            kind == "heading"
            and para_type == "footnote"
            and is_generic_list_heading(trimmed)
            and not split_law_citation_heading(trimmed)
        ):
            para.append(trimmed)
            continue
        # 2026-08-20: "붙임" 첨부목록 문단을 누적하는 중(in_attachment_list)에 나온
        # 번호 헤딩 휴리스틱 매칭 줄("2. 당시...")은 새 목록 항목(원래 첨부 캡션
        # 나열이지 새 섹션 헤딩이 아님)일 뿐인데 heading으로 잘못 승격되던 문제 —
        # split_attachment_label 주석 참고. 위 각주 흡수와 같은 패턴으로 heading
        # 승격을 막고 그대로 흡수시킴.
        if (
            kind == "heading"
            and in_attachment_list
            and is_generic_list_heading(trimmed)
            and not split_law_citation_heading(trimmed)
        ):
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
            # 2026-08-20: "[통보] ○○팀장은..." 류(BRACKET_LABEL_WITH_TRAILING_RE) 라벨도
            # 위 법령인용 라벨과 똑같은 문제(줄 전체가 통째로 볼드돼 다음 줄과 뒤죽박죽)라
            # 같은 방식으로 라벨/내용 분리(split_bracket_label_heading, DetailPage.jsx 동일).
            bracket_split = split_bracket_label_heading(trimmed)
            if bracket_split:
                label, body = bracket_split
                blocks.append({"type": "heading", "text": label, "isTitle": False})
                prev_type = "heading"
                last_heading_list_num = extract_list_num(label)  # 항상 None
                next_is_table = False
                para_type = "body"
                para.append(body)
                continue
            # 2026-08-20: "붙임 : 1. ..." 라벨도 같은 이유로 라벨/내용 분리
            # (split_attachment_label 주석 참고) — 뒤이은 번호 항목들은 위
            # in_attachment_list 흡수 분기가 계속 처리.
            attachment_split = split_attachment_label(trimmed)
            if attachment_split:
                label, body = attachment_split
                blocks.append({"type": "heading", "text": label, "isTitle": False})
                prev_type = "heading"
                last_heading_list_num = None
                next_is_table = False
                para_type = "body"
                if body:
                    para.append(body)
                in_attachment_list = True
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

    # FOOTNOTE_REF_STRICT_RE — 2026-08-20 전수 스캔에서 발견한 신호②(각주 0건)
    # 오탐 5종이 이 정규식으로는 각주 참조로 안 잡히는지(진짜 각주 참조는 여전히 잡는지).
    check("날짜 표기('24.06.24)는 각주 참조로 안 잡힘", not FOOTNOTE_REF_STRICT_RE.search("계약체결 기한('24.06.10)을 안내"))
    check("괄호 열거번호((10))는 각주 참조로 안 잡힘", not FOOTNOTE_REF_STRICT_RE.search("주의\n(10) ㅇ 그런데 2021"))
    check("익명화 마스킹(+0+0+0))은 각주 참조로 안 잡힘", not FOOTNOTE_REF_STRICT_RE.search("압류재산(+0+0+0+0-+0+0+0)의 경우"))
    check("한글 뒤 진짜 각주 참조('금액18)')는 여전히 잡힘", bool(FOOTNOTE_REF_STRICT_RE.search("지적된 금액18)은 환수")))

    # ACTION_TYPE_CODE_RE — 2026-08-20 신호② 표본 재조사(18b48a4726dad247)에서
    # 발견한 조치유형 분류 코드("(통보1)"/"(주의1)") 오탐 필터.
    check(
        "조치유형 코드('(통보1)')는 strict_footnote_nums에서 제외됨",
        "1" not in strict_footnote_nums("처분요구 사항\n(통보1) ㅇ 그런데 예산집행이"),
    )
    check(
        "조치유형 코드('(주의1)')는 strict_footnote_nums에서 제외됨",
        "1" not in strict_footnote_nums("(주의1) ㅇ 관련자에게 주의를 촉구"),
    )
    check(
        "괄호 없는 진짜 각주 참조('통보18)')는 여전히 strict_footnote_nums에 잡힘",
        "18" in strict_footnote_nums("감사원에 통보18)하였다"),
    )
    check(
        "한글 뒤 일반 각주 참조('금액18)')는 strict_footnote_nums에도 여전히 잡힘",
        "18" in strict_footnote_nums("지적된 금액18)은 환수"),
    )

    # 2026-08-20: 헤딩/각주 번호 충돌 버그 수정(LIST_HEADING_NUM_RE 괄호 전용화 +
    # split_law_citation_heading 번호 접두어 괄호 제외) — 실제 문서로 재현한 케이스들.
    check(
        "마침표 섹션번호('5. ...')는 이제 목록 연속 판정에 안 걸림",
        extract_list_num("5. 공사의 여러 규정, 서약사항 및 지시명령을 위반하여") is None,
    )
    check("괄호 목록번호('1) ...')는 여전히 걸림", extract_list_num("1) 법령 「...」") == 1)
    check(
        "각주 정의 줄 자체의 괄호('7)')는 법령인용 괄호로 오인 안 됨",
        split_law_citation_heading(
            "7) 2021. 1. 30. 모바일 익명 커뮤니티 앱인 '블라인드'의 공사 전용 게시판에"
        )
        is None,
    )
    check(
        "진짜 법령인용(번호 뒤 별도 조/항 괄호)은 여전히 분리됨",
        split_law_citation_heading(
            "1) 법령 「공직자윤리법」 제3조의2 제2항(공기업) '공직유관단체인 우리 공사는 ...'"
        )
        is not None,
    )
    # 한국조폐공사 2016(f35fdc468543c358) 실제 발췌 — "회계정책1)"/"적용2)" 각주
    # 정의가 둘 다 인식되는지(수정 전엔 헤딩/각주 번호 충돌로 실패했음).
    text = (
        "기업회계기준에 따르면 최초 채택한 회계정책1)은 합당한 사유가 없는 한 동일한\n"
        "방식으로 일관성 있게 적용2)하여야 하므로, 유형자산 또한\n\n"
        "1) 기업회계기준서 제1008호 「회계정책, 회계추정의 변경 및 오류」 문단 5에 따름\n"
        "2) 일관성 있게 적용하여야 함을 의미함"
    )
    blocks = split_into_blocks(text)
    n_footnote = sum(1 for b in blocks if b["type"] == "footnote")
    check("한국조폐공사 스타일: 각주 1),2) 둘 다 인식됨", n_footnote == 2)

    # 2026-08-20: 각주가 불릿/표 문단에 흡수돼 인식이 통째로 실패하던 버그 수정 —
    # 한국자산관리공사 2021(9ddc6393057cc532)을 실제 디버그 추적해서 확인한 최소 재현.
    text = (
        "본문에서 언급된 판단 내용9)을 참고\n"
        "[표 1] 구제위원회 판단 내용\n"
        "위원 성명 의견\n"
        "AAA 인정\n"
        "BBB 불인정\n"
        "9) 위 인정된 사실 외 직장 내 괴롭힘 여부 판단 대상 중 발언은 판단요건에 부합하지 않음"
    )
    blocks = split_into_blocks(text)
    check(
        "표 데이터 흡수 중이던 각주 9 인식(수정 전엔 실패)",
        any(b["type"] == "footnote" and b["text"].startswith("9)") for b in blocks),
    )
    text = (
        "본문에서 언급된 위원회6)를 참고\n"
        "* 당시 관련자는 처장실 문 앞에 서서 발언\n"
        "이에 대해 소관부점이 사건을 인지하고 절차를 진행함\n"
        "6) 위원회 규정 제41조에 따라 구성된 기구임"
    )
    blocks = split_into_blocks(text)
    check(
        "불릿 문단에 흡수되던 각주 6 인식(수정 전엔 실패)",
        any(b["type"] == "footnote" and b["text"].startswith("6)") for b in blocks),
    )
    # 회귀 없음: 각주 아닌 일반 표/불릿은 여전히 하나로 흡수됨
    text = "[표 1] 인원 현황\n부서 인원 비고\n총무팀 5 -\n기획팀 3 -\n자료: 각 부서 제출자료 재구성"
    blocks = split_into_blocks(text)
    table_block = next((b for b in blocks if b["type"] == "table"), None)
    check(
        "일반 표 데이터는 여전히 하나의 table 블록으로 흡수됨(회귀 없음)",
        table_block is not None and "총무팀" in table_block["text"] and "기획팀" in table_block["text"],
    )
    text = "* 폭행 피해사실 : C - B가 휘드른 손에 머리를 2회 맞음\n계속되는 설명 문장"
    blocks = split_into_blocks(text)
    bullet_block = next((b for b in blocks if b["type"] == "bullet"), None)
    check(
        "일반 불릿 문단은 여전히 정상 흡수됨(회귀 없음)",
        bullet_block is not None and "계속되는 설명 문장" in bullet_block["text"],
    )

    # 2026-08-20: 각주 15/16 미인식 버그 수정 — 한국자산관리공사 2021
    # (9ddc6393057cc532)을 실제 API로 다시 확인해서 진짜 원인을 찾은 최소 재현.
    # 각주 14 정의문이 인용한 법조항 번호("5. 공사의...")가 번호 헤딩 휴리스틱에
    # 걸려 heading으로 잘못 승격되면서 그 다음 각주(15)가 막히던 연쇄.
    text = (
        "관련 규정14)을 위반한 직원15)에 대해 조치함\n"
        "14)「인사규정」제44조(징계대상)\n"
        "5. 공사의 여러 규정, 서약사항 및 지시명령을 위반하여 공사 내의 질서를 문란케 한 직원\n"
        "15) 과잉금지의 원칙 또는 비례의 원칙을 고려"
    )
    blocks = split_into_blocks(text)
    check(
        "각주 정의문이 인용한 법조항 번호('5. ...')는 헤딩으로 안 끊김(수정 전엔 실패)",
        any(
            b["type"] == "footnote" and b["text"].startswith("14)") and "5. 공사의" in b["text"]
            for b in blocks
        ),
    )
    check(
        "그 뒤 진짜 각주 15는 여전히 인식됨(수정 전엔 각주14가 heading으로 끊겨서 막혔음)",
        any(b["type"] == "footnote" and b["text"].startswith("15)") for b in blocks),
    )

    # 2026-08-20: "[관련자 의견] 관련자는..." 류 대괄호 라벨이 뒤에 오는 긴 문장까지
    # 통째로 heading(볼드)이 되던 버그 수정 — 한국자산관리공사 2021(9ddc6393057cc532)
    # 실제 발췌로 재현.
    text = (
        "[관련자 의견] 관련자는 감사 결과에 이견을 제기하지 않았고, 모범을\n"
        "보여야 할 관리자의 위치에도 불구하고 감정에 치우친 행동을 하였다."
    )
    blocks = split_into_blocks(text)
    check(
        "'[관련자 의견]' 라벨만 heading으로 분리됨(수정 전엔 첫 줄 전체가 heading)",
        any(b["type"] == "heading" and b["text"] == "[관련자 의견]" for b in blocks),
    )
    check(
        "라벨 뒤 문장은 다음 줄과 하나의 body 문단으로 합쳐짐(수정 전엔 뒤죽박죽)",
        any(
            b["type"] == "body"
            and "관련자는 감사 결과에" in b["text"]
            and "보여야 할 관리자의 위치" in b["text"]
            for b in blocks
        ),
    )
    # 회귀 없음: 줄 전체가 라벨뿐(내용 없음)이면 여전히 그 라벨만 heading으로 남음
    blocks = split_into_blocks("[통보]")
    check(
        "내용 없는 '[통보]' 단독 줄은 여전히 그대로 heading(회귀 없음)",
        any(b["type"] == "heading" and b["text"] == "[통보]" for b in blocks),
    )

    # 2026-08-20: "붙임" 첨부목록 라벨 뒤 "1./2." 번호 항목이 뒤죽박죽 볼드되던 버그
    # 수정 — 한국자산관리공사 2021(9ddc6393057cc532) 실제 발췌로 재현.
    text = (
        "엄중 주의 촉구하시기 바랍니다. (주의)\n"
        "붙임 : 1. 관련자 문답서(2021. 3. 10.)\n"
        "2. 당시 직원(XX명) 개별면담 내용(2021. 3. 10.~16.)"
    )
    blocks = split_into_blocks(text)
    check(
        "'붙임'이 앞 문장과 분리돼 별도 heading 라벨이 됨(수정 전엔 앞 문장에 병합)",
        any(b["type"] == "heading" and b["text"] == "붙임" for b in blocks),
    )
    check(
        "'(주의)' 문장은 '붙임' 이하와 분리된 별도 body 문단(수정 전엔 붙임까지 한 문단)",
        any(b["type"] == "body" and b["text"].endswith("(주의)") for b in blocks),
    )
    check(
        "'1./2.' 첨부 항목은 하나의 body 문단으로 합쳐지고 heading으로 안 승격됨"
        "(수정 전엔 '2.'만 heading으로 튐)",
        any(
            b["type"] == "body"
            and "1. 관련자 문답서" in b["text"]
            and "2. 당시 직원" in b["text"]
            for b in blocks
        )
        and not any(b["type"] == "heading" and b["text"].startswith("2.") for b in blocks),
    )
    # 회귀 없음: 빈 줄로 문단이 끊기면 그 뒤엔 in_attachment_list 흡수가 더 이상
    # 적용되지 않고(일반 번호 헤딩 휴리스틱이 정상 동작) 다음 섹션이 정상 인식됨
    text = "붙임 : 1. 결과보고서\n\n2. 새로운 섹션"
    blocks = split_into_blocks(text)
    check(
        "빈 줄 뒤엔 attachment 흡수가 안 걸리고 새 heading이 정상 인식됨(회귀 없음)",
        any(b["type"] == "heading" and b["text"] == "2. 새로운 섹션" for b in blocks),
    )

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
    # 한국자산관리공사 2021 — 2026-08-20: 8/19 시점 주석의 "6/7/8은 별도 각주 정의
    # 없이 실제로 존재 안 함"은 틀린 설명이었음(실제로는 각주 1~19가 전부 원문에
    # 존재). Colab 디버그 추적(effectivePrevType 실제 값을 매 줄 출력)으로 원인을
    # 정확히 특정 — ①"*" 불릿이 먼저 나오면 그 뒤 평문이 계속 "bullet" 문단으로
    # 흡수되다 각주 6/7까지 삼킴 ②"[표 N]" 캡션 뒤 표 데이터 흡수 중 각주 9가
    # 나오면 마찬가지로 흡수됨 ③6/9가 실패하며 잘못 heading으로 승격돼
    # lastHeadingListNum을 오염시켜 8/10이 연쇄로 실패. effectivePrevType 허용
    # 목록에 "bullet"/"table" 추가로 6~10 전부 해결(12→17건, 실제 DB로 확인 완료).
    # 남은 15/16도 이어서 해결(같은 날 후속 세션) — 원인은 각주 14 정의문이 인용한
    # 법조항 번호("5. 공사의 여러 규정...") 자체가 is_generic_list_heading(번호 헤딩
    # 휴리스틱)에 걸려 heading으로 승격되고, 그 여파로 prev_type이 "heading"이 돼서
    # 바로 다음 각주(15)가 FOOTNOTE_ALLOWED_PREV_TYPES를 못 만족해 막히는 연쇄였음
    # (continuesHeadingList와는 무관, 위 PAREN_LABEL_RE 표 흡수와 같은 종류의 문제).
    # 각주 문단 누적 중 나온 번호 헤딩 휴리스틱 매칭 줄을 그대로 흡수하도록 수정해서
    # 15/16까지 전부 해결(17→19건, 실제 API로 가져온 문서로 확인 완료).
    "9ddc6393057cc532": {"footnote_blocks": 19},
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

    footnote_nums_in_text = strict_footnote_nums(raw_text)
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
