# ------------------------------------------------------------------
# 원본 PDF 다단(2단) 레이아웃 실태 조사 — 읽기 전용 (2026-08-14)
# ------------------------------------------------------------------
# "표 컬럼 뒤섞임"/"2단 리스트 뒤섞임" 계열 문제(STATUS.md 8/13·8/14 항목 참고)의
# 근본 원인을 raw_text가 아니라 **원본 PDF 자체의 레이아웃**에서 직접 확인하는
# 스크립트. 지금까지 시도한 raw_text 기반 휴리스틱(숫자 패턴, 문장 잘림 등)은
# 이미 한 번 뒤섞인 결과물에서 역으로 패턴을 찾는 거라 오탐/누락이 많았음 —
# 대신 raw_text가 나오기 전 단계인 원본 PDF의 텍스트 블록 좌표를 직접 분석해서
# "이 페이지가 실제로 2단(또는 2-up)인가"를 판정함. 훨씬 정확하지만 문서마다
# PDF를 다운로드해서 열어봐야 해서 느림(전체 72,913건 돌리면 오래 걸릴 수 있음
# — 체크포인트 저장/재개 포함해둠).
#
# 실제로 확인된 두 가지 변종 (2026-08-14, 코드 샌드박스 세션에서 PyMuPDF로 직접
# 검증):
#   1) 한국철도공사 2020 복무감사(dec56dc84bfe3a6c) — 페이지 하나 안에 ①~④(왼쪽
#      칸)/⑤~⑧(오른쪽 칸) 번호 목차 리스트가 나란히 배치된 형태. raw_text엔
#      "◯1 음주관리... ◯5 조작판 취급..."처럼 줄 단위로 좌우가 번갈아 섞여 저장됨.
#   2) 한국공항공사 2023 특정감사(19)(125a97b031fd8fe9) — 더 심각한 변종. PDF 페이지
#      한 장이 실제 문서 2쪽(홀수쪽/짝수쪽)을 나란히 붙인 "2-up" 인쇄 형태라, 리스트
#      항목이 아니라 문단 전체가 좌우로 통째로 섞임(가독 불가 수준).
#
# 두 경우 다 PyMuPDF(`page.get_text()` 기본 동작)로 재추출하면 블록을 좌표 기반
# 으로 묶어서 왼쪽 칸 전체 → 오른쪽 칸 전체 순서로 정확히 읽어냄 — 단, 원본 PDF의
# 인코딩 품질에 따라 한글 단어 사이 띄어쓰기가 소실되는 문서도 있었음(철도공사는
# 띄어쓰기 깨짐, 공항공사는 멀쩡함) — 재추출 파이프라인을 실제로 적용하려면
# 문서별로 띄어쓰기 검증이 별도로 필요함(이 스크립트 범위 밖, 레이아웃 실태 조사만).
#
# 오탐 주의: 표(여러 컬럼이 폭넓게 퍼진 형태)도 왼쪽 서술 문단 + 오른쪽 표 셀처럼
# 감지되어 오탐할 수 있음(실제로 한국소비자원 "[공직기강 점검 2회 적발자 현황]"
# 표 문서에서 확인). 아래 detect_multicolumn_pages()는 폭·길이 임계값으로 표 셀
# 조각을 최대한 걸러내지만 완전하진 않음 — 결과는 "후보 목록"으로만 쓰고, 실제
# 재추출 전에는 사람이 몇 건 직접 확인 권장(이 저장소의 다른 조사 스크립트들과
# 같은 방침).
# ------------------------------------------------------------------
import json
import os
import time
import urllib.parse

import psycopg2
import requests

try:
    import pymupdf
except ImportError as e:
    # 2026-08-14: 노트북(Colab)에서 SystemExit을 쓰면 IPython 일부 버전에서
    # "Internal Python error in the inspect module" 같은 알아보기 힘든 트레이스백
    # 뭉치가 나오는 버그가 있어서(실제로 사용자가 겪음), 대신 평범한 예외로
    # 다시 던짐 — 이러면 "pymupdf가 필요합니다" 메시지가 트레이스백 맨 아래에
    # 깔끔하게 보임. 실행 전에 새 셀에서 아래를 먼저 돌리면 됨:
    #   !pip install -q pymupdf psycopg2-binary requests
    raise ImportError(
        "pymupdf가 설치되어 있지 않습니다. 이 셀을 실행하기 전에 새 셀에서 "
        "다음을 먼저 실행하세요: !pip install -q pymupdf psycopg2-binary requests"
    ) from e

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

# textutils.py의 build_source_url()과 동일한 변환 규칙 — 이 스크립트만 따로 돌리는
# 환경(Colab)에서는 백엔드 모듈을 import하기보다 규칙을 그대로 복붙하는 게 간단함.
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


def detect_multicolumn_pages(pdf_path):
    """PDF 파일 하나를 열어서 2단(또는 2-up) 레이아웃으로 보이는 페이지 인덱스
    목록을 반환. 표 셀 조각(짧고 좁은 블록)은 미리 걸러내고, 문단급 블록만
    가지고 좌우 클러스터의 x좌표 간격 + 세로 퍼짐을 확인함(2026-08-14, 실제
    PDF 3종 이상으로 반복 조정한 임계값)."""
    doc = pymupdf.open(pdf_path)
    flagged = []
    for i, page in enumerate(doc):
        blocks = page.get_text("blocks")
        # 표 셀 조각 제외 — 너비 150pt 이상 + 텍스트 15자 이상인 "문장급" 블록만
        blocks = [b for b in blocks if (b[2] - b[0]) > 150 and len(b[4].strip()) > 15]
        if len(blocks) < 5:
            continue
        xs = sorted(b[0] for b in blocks)
        gaps = [(xs[j + 1] - xs[j], j) for j in range(len(xs) - 1)]
        if not gaps:
            continue
        biggest_gap, idx = max(gaps)
        page_width = page.rect.width
        if biggest_gap <= page_width * 0.15:
            continue
        left = [b for b in blocks if b[0] <= xs[idx]]
        right = [b for b in blocks if b[0] > xs[idx]]
        if len(left) < 3 or len(right) < 3:
            continue
        # 표는 한 "행"이 세로로 안 퍼지고 촘촘히 쌓이는 경우가 많아서, 양쪽 다
        # 세로로 100pt 이상 퍼져 있어야(=진짜 문단 흐름) 인정
        left_yspan = max(b[1] for b in left) - min(b[1] for b in left)
        right_yspan = max(b[1] for b in right) - min(b[1] for b in right)
        if left_yspan > 100 and right_yspan > 100:
            flagged.append(i)
    doc.close()
    return flagged, len(doc)


CHECKPOINT_PATH = "column_layout_checkpoint.jsonl"


def load_checkpoint():
    done = {}
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH) as f:
            for line in f:
                row = json.loads(line)
                done[row["id"]] = row
    return done


def main(limit=None):
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        cur.execute(
            "SELECT id, institution, year, source_file FROM documents "
            "WHERE source_file IS NOT NULL AND source_file ILIKE '%%.pdf'"
        )
        rows = cur.fetchall()
    conn.close()

    if limit:
        rows = rows[:limit]

    done = load_checkpoint()
    print(f"대상 PDF 문서 {len(rows)}건 (이미 처리됨 {len(done)}건, 이어서 진행)")

    checkpoint_f = open(CHECKPOINT_PATH, "a")
    candidates = []
    errors = 0
    for n, (doc_id, institution, year, source_file) in enumerate(rows, 1):
        if doc_id in done:
            if done[doc_id].get("flagged"):
                candidates.append(done[doc_id])
            continue

        url = build_source_url(source_file)
        result = {"id": doc_id, "institution": institution, "year": year, "flagged": []}
        if url:
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                tmp_path = "/tmp/_col_check.pdf"
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
                flagged, npages = detect_multicolumn_pages(tmp_path)
                result["flagged"] = flagged
                result["npages"] = npages
            except Exception as e:  # 네트워크/손상 PDF 등 — 개별 실패는 건너뜀
                result["error"] = str(e)
                errors += 1

        checkpoint_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        checkpoint_f.flush()
        if result["flagged"]:
            candidates.append(result)

        if n % 200 == 0:
            print(f"  {n}/{len(rows)}건 처리, 후보 {len(candidates)}건, 에러 {errors}건")
        time.sleep(0.05)  # jsdelivr CDN 부담 줄이기

    checkpoint_f.close()

    print(f"\n2단/다단 레이아웃 의심 문서: {len(candidates)}건 / 전체 {len(rows)}건")
    print("\n목록 (document_id | 기관 | 연도 | 의심 페이지 인덱스) — 상세페이지·원본 파일에서 직접 확인 권장:")
    for c in candidates:
        print(f"  {c['id']} | {c['institution']} | {c['year']} | pages={c['flagged']}")


if __name__ == "__main__":
    main()
