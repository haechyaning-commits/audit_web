# ------------------------------------------------------------------
# 'y'(한국에너지공단)/'r'(한국남부발전) 폰트 확인 재시도 2 — 단어 단위 위치로
# 먼저 찾고 스팬과 겹치는 부분 폰트 역추적 (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: font_check3.py에서 "스팬 텍스트가 정확히 이 한 글자"라는 조건으로
# 찾았는데 y/r 문서 6건 전부 못 찾음 — m/q/v는 그 글자가 다른 폰트(Wingdings)라
# pymupdf가 자동으로 별도 스팬으로 쪼갰지만, y/r은 앞뒤 글자와 같은 폰트로
# 묶여서 하나의 스팬 안에 섞여 있을 가능성이 있음(그렇다면 Wingdings 가설과
# 다른 원인일 수도 있고, 혹은 그냥 폰트가 같아서 병합됐을 뿐일 수도 있음 —
# 폰트 이름을 봐야 구분 가능).
#
# 이번엔 페이지를 "words"(공백 기준 단어 단위, 폰트 무관하게 항상 쪼개짐)로
# 먼저 훑어서 정확히 그 글자 하나인 단어의 좌표를 찾고, 그 좌표와 겹치는
# "dict" 스팬을 찾아 폰트를 역추적한다. 이러면 병합 여부와 무관하게 폰트를
# 확인할 수 있음. 아무것도 수정하지 않음(읽기 전용, DB 변경 없음).
# ------------------------------------------------------------------
import os
import urllib.parse

import psycopg2
import requests

try:
    import pymupdf
except ImportError as e:
    raise ImportError(
        "pymupdf가 설치되어 있지 않습니다. 이 셀을 실행하기 전에 새 셀에서 "
        "다음을 먼저 실행하세요: !pip install -q pymupdf psycopg2-binary"
    ) from e

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

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


def rects_overlap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


TARGET_IDS = {
    "0bef15b819dc8977": "y",
    "94197135bdf82018": "y",
    "693e0a3357f87c57": "y",
    "20852e7e1b42a626": "r",
    "a8172c7a5703b84f": "r",
    "99d6aa4ad2d77da5": "r",
}

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute(
        "SELECT id, institution, year, source_file FROM documents WHERE id = ANY(%s)",
        (list(TARGET_IDS.keys()),),
    )
    rows = cur.fetchall()
conn.close()

print(f"조회된 문서 {len(rows)}건 / 요청한 {len(TARGET_IDS)}건\n")

for doc_id, institution, year, source_file in rows:
    letter = TARGET_IDS[doc_id]
    url = build_source_url(source_file)
    print(f"=== [{letter}] {institution} — {doc_id} ({year}) — {source_file} ===")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        doc = pymupdf.open(stream=resp.content, filetype="pdf")
    except Exception as e:
        print(f"  다운로드/열기 실패: {e}")
        continue

    found_any = False
    for page_num, page in enumerate(doc):
        words = page.get_text("words")  # (x0,y0,x1,y1,text,block,line,word_no)
        target_words = [w for w in words if w[4] == letter]
        if not target_words:
            continue
        d = page.get_text("dict")
        for w in target_words:
            w_rect = w[:4]
            for block in d.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if rects_overlap(w_rect, span.get("bbox", (0, 0, 0, 0))):
                            found_any = True
                            print(
                                f"  page {page_num}: word={letter!r} span_text={span.get('text')!r} "
                                f"font={span.get('font')!r} size={span.get('size'):.1f}"
                            )
                            line_text = "".join(s.get("text", "") for s in line.get("spans", []))
                            print(f"      같은 줄 전체: {line_text!r}")
    if not found_any:
        print(f"  단어 {letter!r}를 이 문서에서 못 찾음(다른 페이지/추출방식 차이 가능)")
    doc.close()
    print()

print("확인 포인트: font 이름이 Wingdings/Symbol/Marlett/HYWingdings 등 심볼 계열이면"
      " m/q/v와 같은 부류의 버그로 확정. 일반 본문 폰트(맑은고딕 등)라면 y/r은"
      " 다른 원인(혹은 실제 텍스트)일 가능성 — 그 경우 우선순위 낮춰도 됨.")
