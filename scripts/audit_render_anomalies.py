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
# **알려진 버그(2026-08-20 발견, 2026-08-21 수정 — 실 DB로 최종 확인 완료)**:
# SELF_TEST_DOCS의 9ddc6393057cc532 문서는 실제로는 각주가 19개(6/7/8/15/16도
# 존재)인데 **포팅 문제가 아니라 DetailPage.jsx 자체의 실제 렌더링 버그**(Node로
# 실제 파일과 대조 확인함) 때문에 일부가 body/heading에 흡수됐었음 — Colab 디버그
# 추적으로 원인 3가지(불릿/표 문단 흡수, 그로 인한 헤딩 오분류 연쇄)를 특정해서
# effectivePrevType 허용 목록에 "bullet"/"table" 추가로 6~10을 고침(12→17건).
# 남은 15/16(짧은 숫자 헤딩 직후 각주가 막히는 문제)은 처음엔 effectivePrevType
# 허용 목록에 "heading" 추가로 우회 수정했으나(17→19건, 실 DB 확인), 같은 날
# 별도 세션(webpage-data-verification-w7o0qj)이 더 깊이 파서 "진짜" 근본 원인을
# 찾음 — 다른 문서(한국자산관리공사 2019, 65fc6662db4c8570)의 「인사규정」
# 열거항목 오분류를 조사하다가, classifyLine의 "80자 이내+문장종결없음" 헤딩
# 예외가 법령인용 힌트 없이도 발동해서 각주 14 문단이 중간의 마침표 나열 항목
# ("5. 공사의...")에서 끊기고 그 여파로 15/16까지 막히는 것임을 발견 —
# LAW_CITATION_HINT_RE로 그 예외를 좁혀서 근본 해결(이 문서 밖의 다른 나열식
# 목록 오탐까지 같이 고침). heading 허용은 범용 안전망으로 그대로 유지, 둘 다
# 반영돼 있음. 이 클래스의 버그(각주 참조는 있는데 일부만 인식)는 아래 4개
# 탐지 신호로 못 잡을 수 있다는 점을 감안하고 후보 목록을 볼 것.
#
# **탐지하는 "구조 이상" 신호** (전부 휴리스틱 — 확정 버그가 아니라 "사람이
# 확인해볼 가치가 있는 후보"를 걸러내는 용도):
#   1) footnote/bullet/table 블록인데 비정상적으로 긺(길이 상한 초과) —
#      원래 각주/불릿은 한두 문장짜리가 많은데, 엉뚱한 문단을 잘못 흡수하면
#      한 블록이 통짜로 길어짐(오늘 발견한 버그들의 공통 증상).
#   2) 문서 안에 각주 참조 번호(footnoteNums)는 있는데 실제 footnote 타입
#      블록이 하나도 안 만들어진 경우 — 각주 인식이 통째로 실패했을 가능성.
#      2026-08-21: strict_footnote_nums()로 조치유형 코드("(통보1)" 등) 오탐을
#      스캔 단계에서부터 걸러내고, 후보에는 classify_footnote_zero_signal()로
#      "①렌더링 버그 의심(정의 줄이 heading 아닌 다른 곳에 흡수됨)" / "②번호목록
#      헤딩 오탐 의심(정의 줄이 실제로는 heading으로 정상 렌더링됨 — 참조 탐지
#      자체의 오탐, 표본 5건으로 확인: 감사보고서 최상위 구조 헤딩 "1) 업무개요/
#      2) 판단근거/3) 감사결과 문제점"류가 무관한 각주 참조와 번호가 겹쳐서
#      후보로 잘못 뽑힌 것)" / "③원본 각주 유실 의심(정의 줄이 원문에 아예
#      없음)" 태그를 붙여서 사람이 표본 확인할 때 우선순위를 좁힐 수 있게 함.
#      ②로 판정되면 애초에 candidates에도 안 넣음(스캔 단계 오탐 제거).
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

# 2026-08-20: "ㅇ"(한글 자음 '이응', U+3147)를 불릿으로 쓰는 문서 발견(한국자산관리공사
# 2019, 65fc6662db4c8570) — "○"(원 기호, U+25CB)와 다른 코드포인트라 못 걸리고 있었음.
# DetailPage.jsx와 동일하게 반영.
BULLET_RE = re.compile(r"^(?:[-–—□○◦▪‣·❍※•*ㅇ]\s*\S|[①②③④⑤⑥⑦⑧⑨⑩]\s+\S)")
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


# 2026-08-21: "(cid:148)(cid:44)(cid:53)..."처럼 PDF 폰트 임베딩이 깨져서 글자
# 코드가 그대로 텍스트로 뽑힌 줄 — DetailPage.jsx와 동일하게 반영(그 파일의
# CID_TOKEN_RE/isCidCorruption 주석 참고). WATERMARK_NOISE_RE와 같은 급으로
# caption 처리.
CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")


def is_cid_corruption(trimmed):
    matches = CID_TOKEN_RE.findall(trimmed)
    if not matches:
        return False
    cid_char_count = sum(len(m) for m in matches)
    return cid_char_count / len(trimmed) > 0.3


# 2026-08-21: "[표 N]" 캡션 없이 표 데이터가 bullet 문단으로 흡수되는 경우 —
# DetailPage.jsx와 동일하게 반영(그 파일의 looksLikeFlattenedTable 주석 참고).
EMBEDDED_BULLET_RE = re.compile(r"\s[-–—□○◦▪‣·❍※•*①②③④⑤⑥⑦⑧⑨⑩]\s")


def looks_like_flattened_table(text):
    if len(text) < 500:
        return False
    return len(EMBEDDED_BULLET_RE.findall(text)) >= 5


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

# 2026-08-21: 8/20 2차 스캔 표본 조사(18b48a4726dad247)로 새 오탐 유형 발견 —
# "(통보1)"/"(주의1)"처럼 조치유형을 분류하는 괄호 코드가 라벨(1~4글자, 전부
# 한글)+번호로 이루어져 있어서 FOOTNOTE_REF_STRICT_RE가 여전히 각주 참조로
# 오인함(라벨이 2글자 이상이면 "숫자) 바로 앞 한 글자"만 보는 걸로는 못 거름 —
# "통보1)"의 경우 "보1)"만 보면 그 앞 글자가 "통"이라 괄호가 있는 줄 자체를
# 놓침). 실제 각주 참조("87,818,181원1)", "위임2)")는 항상 문장 중간에 바로
# 붙는 형태로 앞에 여는 괄호가 없는 반면, 이 오탐들은 항상 "(라벨N)"처럼
# 통째로 괄호 하나에 들어있음 — 그 괄호 전체 스팬을 먼저 찾아서, 그 안에
# 들어가는 FOOTNOTE_REF_STRICT_RE 매치는 제외함(단일 글자 lookbehind로는
# 여러 글자 라벨을 못 걸러서 스팬 비교 방식으로 함).
ACTION_TYPE_CODE_RE = re.compile(r"\([가-힣]{1,4}\d{1,2}\)")


def strict_footnote_nums(raw_text):
    """FOOTNOTE_REF_STRICT_RE 매치 중 "(라벨N)" 조치유형 코드에 속한 것은 제외하고
    진짜 각주 참조 번호만 집합으로 반환."""
    excluded_spans = [m.span() for m in ACTION_TYPE_CODE_RE.finditer(raw_text)]
    nums = set()
    for m in FOOTNOTE_REF_STRICT_RE.finditer(raw_text):
        if any(s <= m.start() and m.end() <= e for s, e in excluded_spans):
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


# 2026-08-21: STATUS.md 8/20 항목 — 남은 신호②(각주 참조는 있는데 블록 0건)가
# 최소 3가지 다른 원인이 섞여 있다고 정리했음:
#   ①아직 못 고친 렌더링 버그(정의 줄은 원문에 있는데 흡수/오분류돼서 인식 실패)
#   ②스캐너 신호 자체의 오탐(위 strict_footnote_nums로 이미 상당수 걸러짐)
#   ③원본 데이터 자체에 각주 설명이 없음(텍스트 추출 단계에서 유실 — 프론트
#     수정으로는 해결 불가, 988fef1135220d92에서 실제 확인)
#
# 2026-08-21(2차, ① 표본 5건 실 DB 디버그로 확인): 처음엔 "정의 줄이 원문에
# 있으면 무조건 ①"로 단순 판정했는데, 실제 표본(한국광해광업공단 2023,
# 6b06a312a8a35d5a)을 보니 "1) 업무개요 / 2) 판단근거 / 3) 감사결과 문제점"처럼
# **각주가 아니라 감사보고서의 진짜 최상위 구조 헤딩**인 경우가 있었음 —
# continuesHeadingList가 의도대로 정확히 작동해서 이 번호목록을 각주로
# 오분류하지 않게 막은 것이고, DetailPage.jsx는 이 경우 heading으로 올바르게
# 렌더링하고 있었음(5표본 전부 이 패턴). 즉 버그는 DetailPage.jsx가 아니라
# 이 분류 함수 자체에 있었음 — "정의 줄이 실제로 heading 블록으로 렌더링됐는지"
# 까지 확인해서, heading으로 잘 렌더링된 경우는 ②(스캐너의 참조 탐지 자체가
# 오탐 — 어딘가의 "한글N)" 패턴을 이 헤딩과 무관하게 각주 참조로 오인한 것)로
# 재분류함. heading이 아닌 다른 타입(body/bullet/table 등)에 흡수된 경우만
# 여전히 ①(진짜 렌더링 버그 의심)로 남김. 한 문서에 여러 참조 번호가 섞여 있을
# 수 있어 우선순위는 ①(하나라도 있으면 사람이 확인할 가치 있음) > ②(전부
# heading으로 설명됨) > ③(정의 줄 자체가 없음).
def classify_footnote_zero_signal(raw_text, footnote_nums_in_text, blocks):
    lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
    heading_texts = [b["text"] for b in blocks if b["type"] == "heading"]

    any_absorbed_elsewhere = False
    any_explained_by_heading = False

    for num in footnote_nums_in_text:
        def_re = re.compile(rf"^{num}\)\s*\S")
        if not any(def_re.match(ln) for ln in lines):
            continue
        heading_re = re.compile(rf"^{num}\)\s")
        if any(heading_re.match(ht) for ht in heading_texts):
            any_explained_by_heading = True
        else:
            any_absorbed_elsewhere = True

    if any_absorbed_elsewhere:
        return "① 렌더링 버그 의심(정의 줄이 heading 아닌 다른 곳에 흡수됨)"
    if any_explained_by_heading:
        return "② 번호목록 헤딩 오탐 의심(정의 줄이 실제로는 heading으로 정상 렌더링됨)"
    return "③ 원본 각주 유실 의심(정의 줄이 원문에 없음)"


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
# 2026-08-20: "80자 이내+문장종결없음" 예외가 마침표 없이 끝나는 흔한 나열식 목록
# 항목("1. 법령, 관계규정 또는 감독기관 등의 지시·명령·처분 등을 위반한 사람")까지
# 헤딩으로 오탐하던 문제를 실제 문서로 확인함(한국자산관리공사 2019,
# 65fc6662db4c8570). 이 예외가 실제로 노리는 케이스는 항상 「법령명」 인용이나
# "제N조/항/호" 조항 참조를 포함하므로, 그 힌트가 있을 때만 인정하도록 좁힘
# (DetailPage.jsx와 동일하게 반영).
LAW_CITATION_HINT_RE = re.compile(r"「|제\s*\d+\s*(?:조|항|호)")


def classify_line(line: str) -> str:
    trimmed = line.strip()
    if not trimmed:
        return "blank"

    if GANADA_HEADING_RE.match(trimmed) and len(trimmed) <= 24:
        return "heading"
    # 2026-08-18: "1. 2. 3." 번호 항목 — 24자 상한 + 두 가지 예외(법령인용 분리
    # 가능하거나, 80자 이내+문장종결없음+법령인용 힌트가 있는 경우)는 헤딩으로 인정.
    if NUMBERED_HEADING_RE.match(trimmed) and (
        len(trimmed) <= 24
        or split_law_citation_heading(trimmed)
        or (
            len(trimmed) <= 80
            and not SENTENCE_END_RE.search(trimmed)
            and LAW_CITATION_HINT_RE.search(trimmed)
        )
    ):
        return "heading"
    if any(p.match(trimmed) for p in HEADING_LABEL_PATTERNS):
        return "heading"
    if match_field_label(trimmed):
        return "field"
    if (
        SOURCE_NOTE_RE.match(trimmed)
        or SECURITY_NOTICE_RE.match(trimmed)
        or is_watermark_noise(trimmed)
        or is_cid_corruption(trimmed)
    ):
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
#
# 2026-08-21(각주 15/16, 8/20에 특정한 원인 기반): "15) 과잉금지의 원칙..."처럼 각주 본문 자체가
# 24자 이하로 짧으면 classify_line의 "짧은 번호 헤딩" 규칙에 걸려 heading으로
# 잘못 승격됨 — 그 직후엔 heading 자체가 각주 인식 허용 목록에 없어서 정작 진짜
# 각주였던 그 줄이 인식 안 되고 heading으로 새어버렸음(그 뒤로 이어지는 각주도
# 직전이 "heading"이라 연쇄로 계속 heading이 됨). bullet/table을 인정한 것과
# 같은 이유로 heading 직후도 허용(DetailPage.jsx와 동일하게 반영).
#
# 2026-08-21(2차, 신호② 표본 5건 실 DB 디버그로 확인): "자료: ○○ 제출자료
# 재구성"(caption) 바로 다음, 또는 "관계부서 의견"류 필드(field) 바로 다음에
# 각주 정의 줄이 곧장 이어지는 문서가 실제로 다수 있었음(한국가스공사 2025/
# 한국에너지공단 2024/한국수자원공사 2025/한국석유공사 2020 — caption 케이스,
# 한국수자원공사 2025 — field 케이스, 5건 표본 전부 이 패턴). caption/field
# 둘 다 허용 목록에 없어서 정작 각주 자신이 인식 안 되고 heading으로 샜고,
# 그 결과 last_heading_list_num이 오염돼 다음 각주 번호까지 continues_
# heading_list에 걸려 연쇄로 실패함(한국농어촌공사 2024, a728ba6793fbd689에서
# 각주 1·2 둘 다 이 경로로 실패하는 것 확인). bullet/table/heading을 인정한
# 것과 같은 이유로 caption/field 직후도 인정함(DetailPage.jsx와 동일하게 반영).
FOOTNOTE_ALLOWED_PREV_TYPES = frozenset(
    {"body", "footnote", "bullet", "table", "heading", "caption", "field"}
)


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
        # 2026-08-21: 캡션 없는 표 데이터가 bullet로 흘러들어온 경우 재분류
        # (DetailPage.jsx와 동일하게 반영 — looks_like_flattened_table 주석 참고).
        block_type = (
            "table"
            if para_type == "bullet" and looks_like_flattened_table(" ".join(para))
            else para_type
        )
        text_out = "\n".join(para) if block_type == "table" else " ".join(para)
        blocks.append({"type": block_type, "text": text_out})
        prev_type = block_type
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

    # FOOTNOTE_REF_STRICT_RE — 2026-08-20 전수 스캔에서 발견한 신호②(각주 0건)
    # 오탐 5종이 이 정규식으로는 각주 참조로 안 잡히는지(진짜 각주 참조는 여전히 잡는지).
    check("날짜 표기('24.06.24)는 각주 참조로 안 잡힘", not FOOTNOTE_REF_STRICT_RE.search("계약체결 기한('24.06.10)을 안내"))
    check("괄호 열거번호((10))는 각주 참조로 안 잡힘", not FOOTNOTE_REF_STRICT_RE.search("주의\n(10) ㅇ 그런데 2021"))
    check("익명화 마스킹(+0+0+0))은 각주 참조로 안 잡힘", not FOOTNOTE_REF_STRICT_RE.search("압류재산(+0+0+0+0-+0+0+0)의 경우"))
    check("한글 뒤 진짜 각주 참조('금액18)')는 여전히 잡힘", bool(FOOTNOTE_REF_STRICT_RE.search("지적된 금액18)은 환수")))
    # 2026-08-21: 조치유형 분류 코드("(통보1)"/"(주의1)")가 각주 참조로 오인되지
    # 않는지(strict_footnote_nums, ACTION_TYPE_CODE_RE 스팬 제외 적용) —
    # 18b48a4726dad247 실제 사례. 라벨이 2글자라 단순 lookbehind로는 못 거르는
    # 케이스라 FOOTNOTE_REF_STRICT_RE.search 직접 호출이 아니라 helper로 확인.
    check("조치유형 코드('(통보1)')는 각주 참조로 안 잡힘", strict_footnote_nums("점검 결과 (통보1) 조치함") == set())
    check("조치유형 코드('(주의1)')는 각주 참조로 안 잡힘", strict_footnote_nums("관련자에게 (주의1) 처분") == set())
    check(
        "같은 줄에 조치유형 코드와 진짜 각주가 같이 있어도 진짜 각주는 여전히 잡힘",
        strict_footnote_nums("(통보1) 지적된 금액18)은 환수") == {"18"},
    )

    # 2026-08-21: classify_footnote_zero_signal — 신호②(각주 참조는 있는데 블록
    # 0건) 후보를 ①렌더링 버그 의심/②번호목록 헤딩 오탐 의심/③원본 각주 유실
    # 의심으로 가르는 로직. 988fef1135220d92류(원문에 각주 정의 자체가 없는
    # 문서)의 최소 재현.
    check(
        "정의 줄이 원문에 전혀 없으면 '원본 각주 유실 의심'(③)",
        classify_footnote_zero_signal(
            "수송요율1)이 적용됨. 수송요율2)도 마찬가지",
            {"1", "2"},
            [],
        )
        == "③ 원본 각주 유실 의심(정의 줄이 원문에 없음)",
    )
    # 정의 줄은 원문에 있는데 heading이 아닌 다른 블록(body 등)에 흡수된 경우 —
    # 진짜 렌더링 버그 의심(①)으로 분류돼야 함.
    check(
        "정의 줄이 heading 아닌 다른 블록에 흡수되면 '렌더링 버그 의심'(①)",
        classify_footnote_zero_signal(
            "본문에서 언급된 위원회6)를 참고\n6) 위원회 규정 제41조에 따라 구성된 기구임",
            {"6"},
            [{"type": "body", "text": "본문에서 언급된 위원회6)를 참고 6) 위원회 규정 제41조에 따라 구성된 기구임"}],
        )
        == "① 렌더링 버그 의심(정의 줄이 heading 아닌 다른 곳에 흡수됨)",
    )
    # 2026-08-21(2차, 실 DB 표본 5건으로 발견): 정의 줄이 실제로는 heading 블록
    # 으로 정상 렌더링된 경우(진짜 최상위 구조 헤딩, 각주가 아님) — 한국광해광업
    # 공단 2023(6b06a312a8a35d5a) "1) 업무개요 / 2) 판단근거 / 3) 감사결과
    # 문제점" 재현. 이건 렌더링 버그가 아니라 참조 탐지(strict_footnote_nums)
    # 자체의 오탐이므로 ②로 분류돼야 함.
    check(
        "정의 줄이 실제로는 heading으로 정상 렌더링되면 '번호목록 헤딩 오탐 의심'(②)",
        classify_footnote_zero_signal(
            "1) 업무개요\n2) 판단근거\n3) 감사결과 문제점",
            {"2", "3"},
            [
                {"type": "heading", "text": "1) 업무개요"},
                {"type": "heading", "text": "2) 판단근거"},
                {"type": "heading", "text": "3) 감사결과 문제점"},
            ],
        )
        == "② 번호목록 헤딩 오탐 의심(정의 줄이 실제로는 heading으로 정상 렌더링됨)",
    )
    # 통합 재현 — split_into_blocks 실제 결과로도 "1)/2)/3)" 번호목록이 heading
    # 으로 정상 렌더링되는지, 그 결과를 classify_footnote_zero_signal에 그대로
    # 먹였을 때도 ②로 판정되는지(스캐너 오탐이지 DetailPage.jsx 버그가 아님을
    # 통합 레벨에서도 확인).
    text = "1) 업무개요\n관련 규정 검토 결과\n2) 판단근거\n적격심사 시행세칙에 따라 판단함\n3) 감사결과 문제점\n문제점이 확인됨"
    blocks = split_into_blocks(text)
    check(
        "번호목록 헤딩 통합 재현: 1)/2)/3) 전부 heading으로 정상 렌더링",
        all(
            any(b["type"] == "heading" and b["text"].startswith(f"{n})") for b in blocks)
            for n in ("1", "2", "3")
        ),
    )
    check(
        "번호목록 헤딩 통합 재현: classify_footnote_zero_signal이 ②로 판정(스캐너 오탐, 버그 아님)",
        classify_footnote_zero_signal(text, {"2", "3"}, blocks)
        == "② 번호목록 헤딩 오탐 의심(정의 줄이 실제로는 heading으로 정상 렌더링됨)",
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

    # 2026-08-21: 각주 15/16 — 짧은(24자 이하) 각주 정의가 heading 바로 다음에
    # 오면, classify_line의 "짧은 번호 헤딩" 규칙 때문에 그 각주 줄 자신이
    # heading으로 잘못 승격돼서 각주로 아예 인식이 안 되던 버그(그 뒤로 이어지는
    # 각주도 직전이 "heading"이라 연쇄로 계속 heading이 됨). 최소 재현.
    text = (
        "본문에서 지적된 사항15)과 비례원칙16)을 위반함\n"
        "다. 위법성 판단\n"
        "15) 과잉금지의 원칙 위반\n"
        "16) 비례의 원칙 위반"
    )
    blocks = split_into_blocks(text)
    footnote_texts = [b["text"] for b in blocks if b["type"] == "footnote"]
    check(
        "heading 직후 짧은 각주 15/16 둘 다 인식(수정 전엔 둘 다 heading으로 샘)",
        any(t.startswith("15)") for t in footnote_texts)
        and any(t.startswith("16)") for t in footnote_texts),
    )
    # 회귀 없음: 진짜 번호목록(연속 번호)이 heading 뒤에 와도 각주로 안 새고
    # 여전히 heading으로 남는지(continuesHeadingList가 여전히 이 케이스를 막음).
    text = (
        "관련 법령은 아래와 같음\n"
        "1) 법령 「공직자윤리법」 제3조\n"
        "2) 법령 「국가공무원법」 제63조"
    )
    blocks = split_into_blocks(text)
    heading_texts = [b["text"] for b in blocks if b["type"] == "heading"]
    check(
        "연속 번호목록은 heading 뒤에 와도 여전히 heading 유지(회귀 없음)",
        any(t.startswith("1)") for t in heading_texts)
        and any(t.startswith("2)") for t in heading_texts),
    )

    # 2026-08-21(2차): caption("자료:") 직후 각주 정의 — 한국가스공사 2025 등
    # 실 DB 표본 5건으로 확인한 최소 재현.
    text = (
        "그룹회계매뉴얼 상 유형자산군별 내용연수1)를 그대로 적용하고 있었다\n"
        "자료: 제출자료 재구성\n"
        "1) 생산기지와 공급 관리소 유형자산 관련 관리부서 인터뷰를 고려하여 해당 자산의 내용연수 설정"
    )
    blocks = split_into_blocks(text)
    check(
        "caption(자료:) 직후 각주 1 인식",
        any(b["type"] == "footnote" and b["text"].startswith("1)") for b in blocks),
    )

    # field("관계부서 의견") 직후 각주 정의 — 한국수자원공사 2025 실 DB 표본 재현.
    text = (
        "산업안전보건법에 따라 교반기1)를 제조하거나 수입하는 자는 확인해야 한다\n"
        "관계부서 의견 사업단은 감사의견을 수용하며 조속히 조치하겠다는 의견을 제시하였다\n"
        "1) 서로 다른 물질이 잘 섞이도록 물리적인 힘을 가해 휘젓거나 유동을 일으키는 장치"
    )
    blocks = split_into_blocks(text)
    check(
        "field(관계부서 의견) 직후 각주 1 인식",
        any(b["type"] == "footnote" and b["text"].startswith("1)") for b in blocks),
    )

    # caption 직후 연쇄 — 한국농어촌공사 2024(a728ba6793fbd689) 재현: 각주 1이
    # caption 직후 실패하면 last_heading_list_num이 오염돼 각주 2도 연쇄로
    # 실패하던 것까지 같이 고쳐지는지 확인.
    text = (
        "공사는 유형자산1)을 건설공사로 취득하게 될 때 건설중인자산2)으로 관리하고 있다\n"
        "자료: 재무본부 제출자료 재구성\n"
        "1) 판매를 목적으로 하지 않고 장기간에 걸쳐 영업활동에 사용하기 위하여 소유하고 있는 자산으로 토지 건물 등\n"
        "2) 유형자산의 건설 등의 과정에서 지출한 금액으로 미완성을 임시적으로 처리하는 계정"
    )
    blocks = split_into_blocks(text)
    footnote_texts = [b["text"] for b in blocks if b["type"] == "footnote"]
    check("caption 직후 연쇄 각주 1 인식", any(t.startswith("1)") for t in footnote_texts))
    check("caption 직후 연쇄 각주 2 인식(연쇄 실패 없음)", any(t.startswith("2)") for t in footnote_texts))

    # 회귀 없음: caption 뒤에 오는 진짜(각주 아닌) 번호목록 헤딩은 여전히 heading
    text = "표 데이터 요약\n자료: 각 부서 제출자료 재구성\n1) 첫 번째 개선 과제\n2) 두 번째 개선 과제"
    blocks = split_into_blocks(text)
    heading_texts = [b["text"] for b in blocks if b["type"] == "heading"]
    check(
        "caption 뒤 연속 번호목록은 여전히 heading 유지(회귀 없음)",
        any(t.startswith("1)") for t in heading_texts) and any(t.startswith("2)") for t in heading_texts),
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

    # 2026-08-21: cid 오염 감지 — "긴 각주"/"긴 불릿문단"/"heading 0건" 표본 조사
    # 중 실제로 확인한 PDF 폰트 임베딩 깨짐(86건).
    check(
        "cid 토큰이 대부분인 줄은 오염으로 판단",
        is_cid_corruption(
            "7)(cid:148)(cid:44)(cid:53)(cid:1)(cid:5)(cid:259)(cid:48)(cid:125)(cid:1)(cid:160)(cid:81)(cid:79)(cid:249)(cid:71)"
        ),
    )
    check(
        "정상 한국어 문장은 cid 오염 아님",
        not is_cid_corruption("이번 감사에서는 자재관리 및 예산집행 실태를 중점적으로 점검하였다."),
    )
    text = (
        "정상적인 본문 문단입니다.\n"
        "7)(cid:148)(cid:44)(cid:53)(cid:1)(cid:5)(cid:259)(cid:48)(cid:125)(cid:1)(cid:160)(cid:81)(cid:79)(cid:249)(cid:71)(cid:1)(cid:311)\n"
        "다시 정상적인 본문이 이어집니다."
    )
    blocks = split_into_blocks(text)
    check(
        "cid 오염 줄이 caption 타입으로 분리됨(회귀 없음, body에 안 섞임)",
        any(b["type"] == "caption" and "(cid:" in b["text"] for b in blocks),
    )
    check(
        "cid 오염 줄 앞뒤 정상 문단은 그대로 body 2개",
        sum(1 for b in blocks if b["type"] == "body") == 2,
    )

    # 2026-08-21: 캡션 없는 표 데이터가 bullet로 흡수되던 문제(885건 중 84건 확인) —
    # 한국무역보험공사 2019 스타일 최소 재현.
    rows = [
        f"코드{i} - 부적정 코드통합 {100 + i}-{200 + i} R {2019}{10 + i} 코드통합불필요" for i in range(1, 21)
    ]
    text = "- " + " ".join(rows)
    blocks = split_into_blocks(text)
    check(
        "캡션 없는 표 데이터가 table로 재분류됨(불릿으로 안 남음)",
        any(b["type"] == "table" for b in blocks) and not any(b["type"] == "bullet" for b in blocks),
    )
    # 회귀 없음: 짧은 불릿/정상적으로 긴 서술형 불릿 문단(불릿기호 재등장 없음)은
    # 여전히 bullet로 남아야 함.
    text = "- 짧은 불릿 항목 하나"
    blocks = split_into_blocks(text)
    check("짧은 불릿은 여전히 bullet 유지(회귀 없음)", any(b["type"] == "bullet" for b in blocks))
    sentence = (
        "관련 법령에 따라 해당 업무를 처리함에 있어 세부 기준을 명확히 하고 관계자에 대한 교육을 강화하며 "
        "재발방지대책을 마련하여 향후 유사 사례가 발생하지 않도록 철저히 관리할 필요가 있다는 지적이 있었으며 "
    )
    text = "* " + sentence * 6
    blocks = split_into_blocks(text)
    check(
        "정상적으로 긴 불릿 문단(불릿기호 재등장 없음)은 여전히 bullet 유지(회귀 없음)",
        any(b["type"] == "bullet" and len(b["text"]) > 500 for b in blocks)
        and not any(b["type"] == "table" for b in blocks),
    )

    # 2026-08-20: 아래 3건 — 한국자산관리공사 2019(65fc6662db4c8570) 실제 발췌로
    # 재현한 버그 3종.

    # ①"ㅇ"(한글 자음)을 불릿으로 인식하는지 — "○"(원 기호)만 걸리던 문제.
    text = "CMS 전용통신망으로 연결하여 처리하는 방식\nㅇ 또한, 「기록물관리세칙」에 따르면 인장을 관리하게 되어 있음"
    blocks = split_into_blocks(text)
    check(
        "한글 자음 'ㅇ'도 불릿으로 인식됨(원 기호 '○'와 별개 코드포인트)",
        any(b["type"] == "bullet" and b["text"].startswith("ㅇ") for b in blocks),
    )

    # ②"(징계)" 같은 괄호 라벨 바로 다음의 진짜 각주가 인식되는지. footnote_nums는
    # 문서 전체에서 "한글 뒤 숫자)" 참조를 스캔해서 채워지므로, 정의 줄만으로는
    # 재현이 안 되고 실제 문서처럼 앞쪽에 참조("횡령하였고9)"/"있음10)")가 있어야 함.
    text = (
        "위 사람은 대출금을 횡령하였고9) 이를 은폐하고자 회계사고를 발생시킨 사실이 있음10)\n"
        "ㅇ 「인사규정」 제52조에 따라 중징계(면직) 처분하시기 바람.\n"
        "(징계)\n"
        "9) 또한, 2018. 10. 25. 당일 지급하여야 할 위탁개발 필요자금 지급을 위한 대출금 455백만 원 중"
        " 100백만 원을 횡령하여 회계사고를 은폐하고자 한 사실이 있음\n"
        "10) 제44조(징계대상) 다음 각 호의 어느 하나에 해당하는 직원을 징계대상으로 한다."
    )
    blocks = split_into_blocks(text)
    footnote_blocks = [b for b in blocks if b["type"] == "footnote"]
    check(
        "괄호 라벨('(징계)') 바로 다음 각주 9)/10) 둘 다 인식됨(수정 전엔 헤딩으로 오분류)",
        any(b["text"].startswith("9)") for b in footnote_blocks)
        and any(b["text"].startswith("10)") for b in footnote_blocks),
    )

    # ③마침표로 끝나는 법령인용 없는 나열식 목록 항목("1. 법령... 위반한 사람")이
    # 더 이상 개별 헤딩으로 안 쪼개지는지.
    text = (
        "10) 제44조(징계대상) 다음 각 호의 어느 하나에 해당하는 직원을 징계대상으로 한다.\n"
        "1. 법령, 관계규정 또는 감독기관 등의 지시ㆍ명령ㆍ처분 등을 위반한 사람\n"
        "2. 배임, 횡령, 수뢰, 그 밖에 업무와 관련하여 금품을 수수한 사람"
    )
    blocks = split_into_blocks(text)
    check(
        "법령인용 힌트 없는 나열식 목록 항목은 더 이상 헤딩으로 안 쪼개짐(수정 전엔 오분류)",
        not any(b["type"] == "heading" and b["text"].startswith("1.") for b in blocks),
    )
    # 회귀 없음: 진짜 법령인용 라벨("제12조...제3항" 포함)은 여전히 헤딩으로 인정됨.
    text = "1) 공사 「행동강령」 제12조(알선ㆍ청탁 등의 금지) 제3항"
    blocks = split_into_blocks(text)
    check(
        "「법령명」/제N조 힌트가 있는 진짜 법령인용 라벨은 여전히 헤딩으로 인정됨(회귀 없음)",
        any(b["type"] == "heading" and b["text"] == text for b in blocks),
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
    # 남은 15/16(짧은 숫자 헤딩이 연달아 나오면 그 사이 각주가
    # effectivePrevType==="heading"에 막힘, continuesHeadingList와 무관)도
    # 2026-08-21에 같은 방식(effectivePrevType 허용 목록에 "heading" 추가)으로
    # 수정 — 실제 문서 총 각주 19개 중 남은 2개라 17→19로 기대치를 갱신했고,
    # **같은 날 Colab에서 실제로 19건 나오는 것 확인 완료**(자가 검증 2단계 통과).
    # 2026-08-20(별도 세션, webpage-data-verification-w7o0qj 병합): "진짜" 근본
    # 원인은 따로 있었음 — 각주 14 문단 안에 인용된 "5. 공사의 여러 규정, 서약사항
    # 및 지시명령을 위반하여"(마침표 나열식 목록, 법령인용 힌트 없음)가 classifyLine의
    # "80자 이내+문장종결없음" 헤딩 예외에 걸려 각주 14 문단을 중간에 끊어버렸던 것
    # (한국자산관리공사 2019, 65fc6662db4c8570의 「인사규정」 제44조 열거항목 오분류를
    # 조사하다가 발견). LAW_CITATION_HINT_RE로 그 예외를 좁혀서 각주 14가 안 끊기고
    # 15/16까지 정상 인식됨을 별도로 확인 — heading 허용(위)은 범용 안전망으로 유지,
    # LAW_CITATION_HINT_RE는 이 문서 밖 다른 나열식 목록 오탐까지 같이 잡는 더 근본적인
    # 수정이라 둘 다 반영. 어느 쪽만으로도 이 문서는 17→19가 되지만 두 원인이 실제로
    # 같이 존재했으므로 방어적으로 둘 다 유지함.
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
        tag = classify_footnote_zero_signal(raw_text, footnote_nums_in_text, blocks)
        # ②(번호목록 헤딩 오탐 의심)는 실제로는 정상 렌더링이라 후보 목록에 넣을
        # 이유가 없음 — strict_footnote_nums와 같은 급의 "스캔 단계 오탐 제거".
        if not tag.startswith("②"):
            reasons.append(f"각주 참조({len(footnote_nums_in_text)}개) 있는데 각주 블록 0건 — {tag}")

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
