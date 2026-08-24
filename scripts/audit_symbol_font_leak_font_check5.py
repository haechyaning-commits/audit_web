# ------------------------------------------------------------------
# 'y'(한국에너지공단)/'r'(한국남부발전) — DB raw_text 문맥 vs pymupdf 추출 결과
# 나란히 비교 (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: font_check4.py에서 pymupdf의 words/dict 추출 둘 다 'y'/'r'을 문서 전체
# 어디서도 못 찾음(6/6 전부). m/q/v는 Wingdings 폰트라 pymupdf가 별도 스팬으로
# 잘 잡아냈는데, y/r만 이러는 건 — pymupdf 자체 추출 결과가 DB raw_text와
# 다르다는 뜻일 가능성이 큼. 즉 pymupdf는 이 폰트의 ToUnicode CMap을 제대로
# 읽어서 'y'가 아닌 실제 글리프(진짜 불릿 기호 등)로 정확히 보여주고 있는데,
# raw_text를 만든 원래 추출 파이프라인(pymupdf가 아닐 수도 있음, 또는 다른
# 버전)은 그 매핑을 놓치고 코드값 그대로 'y'를 뽑았을 가능성.
#
# 이 스크립트는 DB raw_text에서 'y'/'r' 주변 문맥을 먼저 뽑고, 같은 문서를
# pymupdf로 열어 앞쪽 몇 페이지의 원문 텍스트(page.get_text())를 그대로 출력해서
# 두 결과를 사람이 직접 대조할 수 있게 한다. 아무것도 수정하지 않음(읽기 전용).
# ------------------------------------------------------------------
import os
import re
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


TARGET_IDS = {
    "0bef15b819dc8977": "y",
    "94197135bdf82018": "y",
    "693e0a3357f87c57": "y",
    "20852e7e1b42a626": "r",
    "a8172c7a5703b84f": "r",
    "99d6aa4ad2d77da5": "r",
}
N_PAGES_TO_DUMP = 2  # m/q 사례가 전부 page 0~1에 있었으니 우선 앞 2페이지만

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute(
        "SELECT id, institution, year, source_file, raw_text FROM documents WHERE id = ANY(%s)",
        (list(TARGET_IDS.keys()),),
    )
    rows = cur.fetchall()
conn.close()

print(f"조회된 문서 {len(rows)}건 / 요청한 {len(TARGET_IDS)}건\n")

for doc_id, institution, year, source_file, raw_text in rows:
    letter = TARGET_IDS[doc_id]
    print(f"========== [{letter}] {institution} — {doc_id} ({year}) ==========")

    # 1) DB raw_text 쪽 문맥 (처음 3개까지)
    letter_re = re.compile(r"(?<![A-Za-z])" + re.escape(letter) + r"(?![A-Za-z])")
    matches = list(letter_re.finditer(raw_text))
    print(f"-- DB raw_text: '{letter}' {len(matches)}회 출현, 앞 3개 문맥 --")
    for m in matches[:3]:
        start = max(0, m.start() - 40)
        end = min(len(raw_text), m.end() + 40)
        print(f"   ...{raw_text[start:end].replace(chr(10), ' ')}...")

    # 2) pymupdf 쪽 원문 그대로 (앞 N페이지)
    url = build_source_url(source_file)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        doc = pymupdf.open(stream=resp.content, filetype="pdf")
    except Exception as e:
        print(f"  다운로드/열기 실패: {e}\n")
        continue

    print(f"-- pymupdf page.get_text() 앞 {N_PAGES_TO_DUMP}페이지 원문 --")
    for page_num in range(min(N_PAGES_TO_DUMP, len(doc))):
        text = doc[page_num].get_text()
        print(f"  [page {page_num}]")
        print("  " + text.replace("\n", "\n  "))
    doc.close()
    print()

print("확인 포인트: pymupdf 원문 쪽에서 DB raw_text의 'y'/'r' 자리에 해당하는 부분에"
      " 다른 글자(불릿 기호, 다른 알파벳, 공백 등)가 있는지 대조. pymupdf 쪽에도"
      " 똑같이 'y'/'r'이 있는데 위치만 못 찾은 거라면 words 추출 방식 자체의 한계일"
      " 수 있음.")
