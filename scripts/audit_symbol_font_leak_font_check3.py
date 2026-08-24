# ------------------------------------------------------------------
# 'y'(한국에너지공단)/'r'(한국남부발전) 폰트 확인 재시도 — 문서 ID 직접 지정
# (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: audit_symbol_font_leak_font_check2.py에서 institution+letter로 표본을
# 찾는 쿼리가 y/한국에너지공단, r/한국남부발전에 대해 0건을 찾음(기관명 문자열이
# 정확히 안 맞았거나 다른 이유로 매칭 실패 — 원인 불명). audit_symbol_font_leak_
# scope.py가 이미 실제로 찾아낸 문서 ID(예시 목록)가 있으니, 그걸 그대로 써서
# 우회. m/q는 이미 Wingdings-Regular로 확정됐으므로 이번엔 y/r만 확인.
# 아무것도 수정하지 않음(읽기 전용, DB 변경 없음).
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


# audit_symbol_font_leak_scope.py 출력의 "예시 문서 ID" 목록을 그대로 사용
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
found_ids = {r[0] for r in rows}
missing = set(TARGET_IDS) - found_ids
if missing:
    print(f"[경고] DB에서 못 찾은 ID: {missing}\n")

for doc_id, institution, year, source_file in rows:
    letter = TARGET_IDS[doc_id]
    url = build_source_url(source_file)
    print(f"=== [{letter}] {institution} — {doc_id} ({year}) — {source_file} ===")
    if not url:
        print("  source_file 없음, 건너뜀")
        continue
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
      " m/q/v와 같은 부류의 버그로 확정.")
