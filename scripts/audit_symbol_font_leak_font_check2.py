# ------------------------------------------------------------------
# 'v' 외 불릿 누출 후보(m/q/y/r) 원본 PDF 폰트 확인 (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: audit_symbol_font_leak_scope.py 실행 결과(사용자 제공, 전체 67,751건),
# boilerplate 앵커 문구 직전 알파벳 단독 1글자를 전수조사한 결과 대부분은
# 1~2건씩 여러 기관에 흩어져 있어 우연(실제 텍스트)으로 보이지만, 아래 4개는
# 'v'(한국수력원자력, Wingdings-Regular로 이미 확정)와 같은 시그니처(특정
# 기관 하나에 집중, .pdf 위주)를 보임 — 같은 부류의 버그(기관마다 쓰는 보고서
# 양식 폰트가 달라서 새는 글자도 다르게 고정)라는 가설:
#   - 'm': 서울대학교병원(15)/국립부산과학관(14)/한국수자원조사기술원(8)
#   - 'q': 한국원자력통제기술원(20/21)
#   - 'y': 한국에너지공단(11/11)
#   - 'r': 한국남부발전(7/7)
#
# audit_v_bullet_font_check.py와 동일한 방식(pymupdf로 원본 PDF 열어서 해당
# 알파벳 단독 스팬의 실제 폰트 이름 확인)을 기관/글자 후보별로 일반화해서 실행.
# 아무것도 수정하지 않음(읽기 전용, DB 변경 없음).
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


# (기관, 확인할 글자, 표본 건수)
CANDIDATES = [
    ("서울대학교병원", "m", 2),
    ("국립부산과학관", "m", 2),
    ("한국수자원조사기술원", "m", 1),
    ("한국원자력통제기술원", "q", 2),
    ("한국에너지공단", "y", 2),
    ("한국남부발전", "r", 2),
]

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    all_samples = []
    for institution, letter, n in CANDIDATES:
        letter_re = re.compile(r"(?<![A-Za-z])" + re.escape(letter) + r"(?![A-Za-z])")
        cur.execute(
            "SELECT id, year, source_file, raw_text FROM documents "
            "WHERE institution = %s AND source_file ILIKE '%%.pdf'",
            (institution,),
        )
        rows = cur.fetchall()
        found = 0
        for doc_id, year, source_file, raw_text in rows:
            if source_file and letter_re.search(raw_text):
                all_samples.append((institution, letter, doc_id, year, source_file))
                found += 1
            if found >= n:
                break
conn.close()

print(f"확인할 표본 {len(all_samples)}건\n")

for institution, letter, doc_id, year, source_file in all_samples:
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
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if text.strip() == letter:
                        found_any = True
                        print(f"  page {page_num}: text={text!r} font={span.get('font')!r} "
                              f"size={span.get('size'):.1f} flags={span.get('flags')}")
                        line_text = "".join(s.get("text", "") for s in line.get("spans", []))
                        print(f"      같은 줄 전체: {line_text!r}")
    if not found_any:
        print(f"  단독 {letter!r} 스팬을 못 찾음")
    doc.close()
    print()

print("확인 포인트: font 이름이 Wingdings/Symbol/Marlett/HYWingdings 등 심볼 계열이면"
      " 'v'와 같은 부류의 버그로 확정. 아니면(일반 본문 폰트) 진짜 텍스트일 가능성.")
