# ------------------------------------------------------------------
# 'v' 불릿 오염 가설 — 원본 PDF 폰트 직접 확인 (2026-08-24, 읽기 전용)
# ------------------------------------------------------------------
# 배경: audit_v_bullet_diagnose.py 실행 결과(사용자 제공)로 가설이 상당히 바뀜:
#   - 애초 "HWPX 태그 절단" 가설은 틀림 — 'v' 있는 한수원 문서 202건 전부
#     source_file 확장자가 .pdf (HWP/HWPX 아님!)
#   - "(관련부서의견)"/"(관계기관의견)" 앞에 오는 문자를 전수조사한 결과 64건 중
#     63건이 'v', 나머지 1건만 다른 문자('(') — 그리고 'v' 없는 문서들에서는 이
#     앵커 문구 자체가 아예 안 잡힘(0건). 즉 이 문구가 나오는 문서는 사실상 전부
#     그 앞이 'v'라는 뜻 — 우연이라기엔 너무 일관적
#   - 문서당 'v' 출현 1~16회(항목마다 반복되는 불릿 패턴과 일치)
# → 원본 PDF에 있는 심볼 폰트(Wingdings류) 체크마크/불릿 글리프가, 폰트를 고려
#   안 하는 텍스트 추출 과정에서 코드값 그대로 'v'로 뽑힌 것이라는 가설.
#
# 이 스크립트는 실제로 원본 PDF 몇 건을 pymupdf로 열어서, "v" 단독 텍스트가
# 나오는 스팬(span)의 실제 폰트 이름을 직접 확인한다 — Wingdings/Symbol/Marlett
# 등 심볼 폰트로 나오면 가설 확정, 일반 본문 폰트(맑은고딕 등)로 나오면 가설
# 재검토 필요. 아무것도 수정하지 않음(읽기 전용, DB 변경 없음).
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


V_TOKEN_RE = re.compile(r"(?<![A-Za-z])v(?![A-Za-z])")

# ------------------------------------------------------------------
# 1) 'v' 있는 한수원 문서 중 표본 몇 건 뽑기 (문서당 출현 1회짜리 위주 — 가장
#    흔한 케이스부터 확인)
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute(
        "SELECT id, year, source_file, raw_text FROM documents "
        "WHERE institution = '한국수력원자력' AND source_file ILIKE '%%.pdf'"
    )
    rows = cur.fetchall()
conn.close()

sample = []
for doc_id, year, source_file, raw_text in rows:
    n = len(V_TOKEN_RE.findall(raw_text))
    if n == 1 and source_file:
        sample.append((doc_id, year, source_file))
    if len(sample) >= 5:
        break

print(f"표본 {len(sample)}건: {[s[0] for s in sample]}\n")

# ------------------------------------------------------------------
# 2) 각 PDF 다운로드 → pymupdf로 열어서 텍스트 "v" 단독 스팬의 폰트 확인
# ------------------------------------------------------------------
for doc_id, year, source_file in sample:
    url = build_source_url(source_file)
    print(f"=== {doc_id} ({year}) — {source_file} ===")
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
                    if text.strip() == "v":
                        found_any = True
                        print(f"  page {page_num}: text={text!r} font={span.get('font')!r} "
                              f"size={span.get('size'):.1f} flags={span.get('flags')}")
                        # 같은 줄의 다른 스팬들도 같이 찍어서 문맥 확인
                        line_text = "".join(s.get("text", "") for s in line.get("spans", []))
                        print(f"      같은 줄 전체: {line_text!r}")
    if not found_any:
        print("  단독 'v' 스팬을 못 찾음 (get_text 방식이 raw_text 추출 파이프라인과"
              " 다를 수 있음 — 문맥 스니펫으로 페이지 눈으로 확인 필요)")
    doc.close()
    print()

print("확인 포인트: font 이름이 Wingdings/Symbol/Marlett/HYWingdings 등 심볼 계열이면"
      " 가설 확정. 본문 폰트(맑은고딕 등)면 재검토 필요.")
