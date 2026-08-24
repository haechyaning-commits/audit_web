# ------------------------------------------------------------------
# ③(원본 각주 유실 의심, 576건) 원본 PDF/HWP 직접 대조 (Colab 실행용, 읽기 전용)
# ------------------------------------------------------------------
# 배경: 2026-08-21 (11차) 조사 결론 — 기관/연도/parsing_quality 어디에도 상관관계가
# 없는, 코퍼스 전반에 낮은 비율(0.85%)로 퍼진 각주 정의 줄 유실(576건). raw_text만
# 봐서는 더 못 좁혀서 "다음 단계는 원본 PDF와 직접 대조 필요"로 결론 남(STATUS.md
# 8/21 11차 참고). 이 스크립트가 그 다음 단계 — 실제로 원본 파일을 다시 열어봐서:
#   ①원본 자체(재추출)에도 각주 설명이 없으면 → 진짜 원본 데이터 누락(저자가 안 씀,
#     또는 페이지 각주 영역이 이 코퍼스 추출 파이프라인이 못 뽑는 레이아웃)
#   ②원본을 다시 뽑아보니 각주 설명이 있으면 → 지금 DB의 추출 파이프라인이 놓친
#     것(재추출 파이프라인으로 복구 가능한 진짜 버그)
#
# 판별 방법: DetailPage.jsx/audit_render_anomalies.py와 같은 각주 참조 정규식
# (FOOTNOTE_REF_RE 상당)으로 raw_text에서 참조 번호(예: "...원1)")를 찾고, 그
# 번호로 시작하는 정의 줄("1) ...")이 raw_text 어디에도 없는 문서만 후보로 봄(이게
# audit_render_anomalies.py의 classify_footnote_zero_signal이 ③으로 태깅하는
# 핵심 조건과 동일). 후보 중 무작위 표본만 뽑아서 원본 파일을 재다운로드하고,
# PDF는 PyMuPDF 기본 추출, .hwp는 hwp5txt, .hwpx는 hp:t 직속 텍스트로 다시 뽑아서
# 같은 번호의 정의 줄이 있는지 확인.
#
# DB에 아무것도 쓰지 않음 — 순수 조사.
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary requests pymupdf lxml
# !apt-get install -qq -y python3-pyhwp 2>/dev/null || pip install -q "setuptools<60" pyhwp

import io
import os
import random
import re
import subprocess
import tempfile
import urllib.parse
import zipfile

import psycopg2
import requests

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

SAMPLE_SIZE = 10  # 원본 파일까지 실제로 열어볼 표본 수 — 규모조사가 아니라 원인
                  # 파악용이라 크게 잡을 필요 없음(11차 결론 참고: 규모는 이미 확정됨)

# DetailPage.jsx/audit_render_anomalies.py의 FOOTNOTE_REF_RE와 동일 —
# 숫자/공백이 아닌 글자 바로 뒤에 붙은 "숫자)"만 각주 참조로 인정.
FOOTNOTE_REF_RE = re.compile(r"[^\s\d](\d{1,2})\)")


def find_missing_footnote_nums(raw_text):
    """raw_text에서 참조된 각주 번호 중, 그 번호로 시작하는 정의 줄이 원문 어디에도
    없는 번호만 반환 — audit_render_anomalies.py의 classify_footnote_zero_signal이
    ③으로 태깅하는 핵심 조건(정의 줄 자체가 raw_text에 없음)과 동일."""
    ref_nums = {m.group(1) for m in FOOTNOTE_REF_RE.finditer(raw_text)}
    if not ref_nums:
        return []
    lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
    missing = []
    for num in ref_nums:
        def_re = re.compile(rf"^{num}\)\s*\S")
        if not any(def_re.match(ln) for ln in lines):
            missing.append(num)
    return missing


_SOURCE_REPO_RAW_BASE = "https://cdn.jsdelivr.net/gh/haechyaning-commits/data@main/"
_SOURCE_FILE_PREFIX = "data_repo/"


def build_source_url(source_file):
    path = source_file[len(_SOURCE_FILE_PREFIX):] if source_file.startswith(_SOURCE_FILE_PREFIX) else source_file
    encoded = "/".join(urllib.parse.quote(seg) for seg in path.strip("/").split("/"))
    return _SOURCE_REPO_RAW_BASE + encoded


def reextract_fresh_text(source_file, content):
    """확장자별로 아주 단순한(재청킹 파이프라인의 정교한 보정 없는) 재추출만 함 —
    "각주 정의 줄이 원본에 존재하는가" 여부만 보면 되므로 정밀한 레이아웃 복원은
    불필요."""
    lower = source_file.lower()
    if lower.endswith(".pdf"):
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    if lower.endswith(".hwpx"):
        from lxml import etree
        NS_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = sorted(n for n in z.namelist() if n.startswith("Contents/section") and n.endswith(".xml"))
            paras = []
            for name in names:
                root = etree.fromstring(z.read(name))
                for p_elem in root.iter(f"{{{NS_HP}}}p"):
                    texts = [t.text for t in p_elem.findall(f"{{{NS_HP}}}run/{{{NS_HP}}}t") if t.text]
                    if texts:
                        paras.append("".join(texts))
            return "\n".join(paras)
    if lower.endswith(".hwp"):
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            proc = subprocess.run(["hwp5txt", path], capture_output=True, text=True, timeout=60)
            return proc.stdout
        finally:
            os.unlink(path)
    return None  # 알 수 없는 확장자


# ------------------------------------------------------------------
# 1) 후보 조회(전체 스캔 — raw_text가 있는 문서만, Python에서 정규식으로 판정)
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '300s'")
    cur.execute(
        "SELECT id, institution, year, source_file, raw_text FROM documents "
        "WHERE raw_text IS NOT NULL AND source_file IS NOT NULL"
    )
    rows = cur.fetchall()
conn.close()
print(f"전체 문서: {len(rows)}건 스캔")

candidates = []
for doc_id, institution, year, source_file, raw_text in rows:
    missing = find_missing_footnote_nums(raw_text)
    if missing:
        candidates.append((doc_id, institution, year, source_file, raw_text, missing))

print(f"후보(참조는 있는데 정의 줄이 raw_text에 전혀 없음): {len(candidates)}건")
print("(11차 조사의 576건과 정확히 같은 수는 아닐 수 있음 — 그때는 heading 오탐 등")
print(" 추가 필터를 거쳤고, 이건 핵심 조건만 다시 재현한 것이라 근사치임)\n")

random.seed(42)
sample = random.sample(candidates, min(SAMPLE_SIZE, len(candidates)))

# ------------------------------------------------------------------
# 2) 표본만 원본 재다운로드 + 재추출 + 대조
# ------------------------------------------------------------------
genuinely_missing = 0
recoverable = 0
download_failed = 0

for doc_id, institution, year, source_file, raw_text, missing_nums in sample:
    url = build_source_url(source_file)
    print(f"--- {doc_id} | {institution} {year} | {source_file} ---")
    print(f"  raw_text에 정의 줄 없는 각주 번호: {missing_nums}")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        fresh_text = reextract_fresh_text(source_file, resp.content)
    except Exception as e:
        print(f"  [에러] 원본 재다운로드/재추출 실패: {e}")
        download_failed += 1
        continue

    if fresh_text is None:
        print(f"  [건너뜀] 알 수 없는 확장자: {source_file}")
        continue

    fresh_lines = [ln.strip() for ln in fresh_text.split("\n") if ln.strip()]
    found_in_fresh = []
    still_missing = []
    for num in missing_nums:
        def_re = re.compile(rf"^{num}\)\s*\S")
        if any(def_re.match(ln) for ln in fresh_lines):
            found_in_fresh.append(num)
        else:
            still_missing.append(num)

    if found_in_fresh:
        recoverable += 1
        print(f"  ✅ 재추출본엔 있음(파이프라인이 놓친 것): {found_in_fresh}")
    if still_missing:
        genuinely_missing += 1
        print(f"  ⚠️ 재추출해도 없음(원본 자체에 없거나 이 방식으론 추출 불가): {still_missing}")
    print()

print("=== 요약 ===")
print(f"표본 {len(sample)}건 중:")
print(f"  재추출본에서 최소 1개 이상 발견(파이프라인이 놓쳤을 가능성) — {recoverable}건")
print(f"  재추출해도 전부 없음(원본 자체 문제일 가능성) — {genuinely_missing}건")
print(f"  다운로드/재추출 실패 — {download_failed}건")
