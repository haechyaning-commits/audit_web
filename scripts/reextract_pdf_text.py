# ------------------------------------------------------------------
# 원본 PDF 재추출 프로토타입 — 다단(2단) 순서 + 띄어쓰기 동시 복구 (2026-08-14)
# ------------------------------------------------------------------
# `scripts/audit_pdf_column_layout.py`로 찾은 2,111건(약 7%)의 다단 레이아웃
# 문서를 실제로 고치기 위한 재추출 로직. 8/14 3차에서 PyMuPDF 기본 추출이
# "컬럼 순서는 잘 잡지만 문서에 따라 띄어쓰기가 깨진다"는 트레이드오프를
# 발견했었는데(철도공사=깨짐, 공항공사=안 깨짐), 이번에 원인을 찾아서 둘 다
# 해결함:
#
# **띄어쓰기가 깨지는 이유**: PyMuPDF의 기본 단어(word) 인식이 쓰는 간격
# 임계값이 이 말뭉치의 정당화(justify)된 한글 본문 간격보다 느슨해서, 진짜
# 띄어쓰기 자리(문자 간 간격 ~4~6pt)를 못 잡고 여러 단어를 하나로 붙여버림.
# 실제로 문자 좌표(rawdict)를 직접 까보면 단어 내부 간격(~0pt, 종종 겹침)과
# 단어 경계 간격(~4~6pt)이 뚜렷하게 두 무리로 나뉘어 있어서(중간값 2~3pt는
# 거의 없음), 이 간격을 직접 재는 것만으로 복구 가능함을 확인함.
#
# **검증**: 한국철도공사 2020(dec56dc84bfe3a6c) 문서의 "1. 감사배경 및 목적"
# 문단을 이 로직으로 재추출한 결과가 현재 DB에 저장된 원문과 **글자 하나
# 안 틀리고 일치**함(직접 비교 확인). 다단 순서 문제였던 "◯1 음주관리...
# ◯5 조작판..." 구간도 1→2→3→4→5 순서로 완전히 정상화됨. 원래 띄어쓰기
# 문제가 없던 한국공항공사 문서로도 회귀 테스트(정상 유지 확인), 정상적인
# 단일 컬럼 문서(한국관광공사 등)로도 회귀 없음 확인.
#
# **아직 프로토타입 단계 — DB에 바로 반영하지 말 것**:
# - 이 세션은 Railway DB 쓰기 권한이 없어서 실제 반영 코드는 없음(추출 함수만).
# - 검증은 5개 문서로만 함 — 2,111건 전체에 적용하기 전에 더 넓은 샘플로
#   재검증 필요(특히 임계값 gap_threshold=2.5pt가 다른 폰트/기관 문서에도
#   맞는지 확인 필요, 폰트 크기가 다르면 이 값도 다시 튜닝해야 할 수 있음).
# - 줄바꿈 단위가 원래 라인 인식(get_text 기본 "blocks")과 다르게 세밀하게
#   쪼개지는 경우가 있음(예: 밑줄/강조 글자가 한 글자씩 별도 줄로 나오는 등) —
#   내용 손실은 없지만 프론트(DetailPage.jsx)의 문단 합치기 로직이 알아서
#   흡수하는지 실제 렌더링으로 확인 필요.
# - DB 반영 전 반드시: (1) 더 많은 2,111건 샘플로 사람이 직접 비교 검증,
#   (2) 백업(scripts/backup_before_fix.py류) 먼저, (3) 재임베딩 사이클 계획.
# ------------------------------------------------------------------
import pymupdf


def line_text(line, gap_threshold=2.5):
    """줄 하나(PyMuPDF rawdict의 line)를 문자 좌표 기반으로 이어붙이되, 문자
    간 간격이 임계값 이상이면 공백을 삽입. PyMuPDF의 기본 단어 인식이 놓치는
    좁은 간격(이 말뭉치 기준 ~4~6pt)을 직접 재서 보정함(위 모듈 설명 참고)."""
    chars = []
    for span in line["spans"]:
        chars.extend(span.get("chars", []))
    if not chars:
        return ""
    out = [chars[0]["c"]]
    for prev, cur in zip(chars, chars[1:]):
        gap = cur["bbox"][0] - prev["bbox"][2]
        # 이미 명시적 공백 문자(prev/cur 자체가 ' ')인 경우 간격 기반 삽입을
        # 또 하면 공백이 두 번 들어감(양쪽 정당화로 벌어진 간격 + 실제 공백
        # 문자가 겹치는 경우, 정직(신입) 채용... 같은 완전정당화 줄에서 발견) —
        # 그럴 땐 건너뜀.
        if gap >= gap_threshold and prev["c"] != " " and cur["c"] != " ":
            out.append(" ")
        out.append(cur["c"])
    return "".join(out).strip()


def extract_page_text(page, gap_threshold=2.5):
    """페이지 하나를 컬럼(좌/우) 인식 + 줄 단위 간격 보정 문자 재구성으로
    추출. 2단이면 왼쪽 칼럼 전체(위→아래) 후 오른쪽 칼럼 전체(위→아래)
    순서로, 단일 컬럼이면 그냥 위→아래 순서로 반환.
    컬럼 분리 판정 로직은 scripts/audit_pdf_column_layout.py의
    detect_multicolumn_pages()와 동일한 임계값(문장급 줄 5개+, 최대 간격이
    페이지 폭의 15% 초과, 좌우 각 3줄+, 세로 퍼짐 100pt+)을 씀 — 이미 그
    스크립트로 다단 판정된 문서에만 이 재추출을 적용하는 걸 전제로 함."""
    d = page.get_text("rawdict")
    lines = []
    for block in d["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            text = line_text(line, gap_threshold)
            if text:
                lines.append({"bbox": line["bbox"], "text": text})

    if not lines:
        return ""

    wide_lines = [l for l in lines if (l["bbox"][2] - l["bbox"][0]) > 100]
    is_two_col = False
    split_x = None
    if len(wide_lines) >= 5:
        xs = sorted(l["bbox"][0] for l in wide_lines)
        gaps = [(xs[j + 1] - xs[j], j) for j in range(len(xs) - 1)]
        if gaps:
            biggest_gap, idx = max(gaps)
            if biggest_gap > page.rect.width * 0.15:
                left = [l for l in wide_lines if l["bbox"][0] <= xs[idx]]
                right = [l for l in wide_lines if l["bbox"][0] > xs[idx]]
                if len(left) >= 3 and len(right) >= 3:
                    left_yspan = max(l["bbox"][1] for l in left) - min(l["bbox"][1] for l in left)
                    right_yspan = max(l["bbox"][1] for l in right) - min(l["bbox"][1] for l in right)
                    if left_yspan > 100 and right_yspan > 100:
                        is_two_col = True
                        split_x = xs[idx]

    if is_two_col:
        left = sorted([l for l in lines if l["bbox"][0] <= split_x], key=lambda l: l["bbox"][1])
        right = sorted([l for l in lines if l["bbox"][0] > split_x], key=lambda l: l["bbox"][1])
        ordered = left + right
    else:
        ordered = sorted(lines, key=lambda l: l["bbox"][1])

    return "\n".join(l["text"] for l in ordered)


def extract_doc_text(path_or_bytes, gap_threshold=2.5):
    """PDF 파일 경로 또는 바이트를 받아 전체 문서를 페이지 순서대로 재추출."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        doc = pymupdf.open(stream=path_or_bytes, filetype="pdf")
    else:
        doc = pymupdf.open(path_or_bytes)
    pages = [extract_page_text(p, gap_threshold) for p in doc]
    doc.close()
    return "\n".join(pages)


if __name__ == "__main__":
    # 사용법: python3 reextract_pdf_text.py 파일.pdf
    # (또는 audit_pdf_column_layout.py의 build_source_url()로 받은 PDF를
    # 대상으로 사람이 눈으로 원문과 비교하며 검증하는 용도)
    import sys

    print(extract_doc_text(sys.argv[1]))
