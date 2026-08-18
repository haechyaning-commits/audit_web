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
# **8/14 4차 추가 검증(24개 문서, 다단 후보 8건 + 임의 16건)**:
# - 크래시 0건. 기존 PyMuPDF 기본 추출(page.get_text())과 비교해 "15자 이상
#   붙어버린 한글" 개수를 세어보니, 기본 추출은 8/24 문서(33%)에서 최대
#   63개까지 발생했는데 새 로직은 24/24 전부 0개 — 띄어쓰기 손실이 애초
#   2,111건(다단 의심)보다 더 넓게 퍼져 있고, 이 재추출 로직이 다단 여부와
#   무관하게 일반적으로 더 안전하다는 뜻으로 해석됨.
# - 이 검증 중 새로운 버그를 하나 찾아 고침: PyMuPDF가 같은 시각적 줄도
#   폰트/서브셋 전환 경계에서 별도 line 객체로 쪼개는 경우가 있어서(예:
#   "【제 목】"이 "【제" / "목】"로 분리 — 문서 제목 인식 실패 원인이었던
#   바로 그 패턴), 같은 줄(y0 근접)이면서 가로로 인접한(x 간격 작음)
#   fragment를 합치는 _merge_same_row_fragments()를 추가함. 처음엔 y0만
#   보고 합쳤다가 2단 페이지에서 좌/우 컬럼의 첫 줄이 같은 y0라서 서로 다른
#   컬럼 내용이 한 줄로 잘못 합쳐지는 회귀를 직접 발견 — x 간격 조건(<=50pt,
#   컬럼 간격 최소치인 페이지폭 15%보다 훨씬 작음)을 추가해 해결. 한국철도
#   공사 문서의 "◯1 음주관리...◯5 조작판..." 5개 항목 순서가 여전히 정확한지,
#   8개 2단 후보 문서 전체에서 병합줄이 페이지 폭의 70%를 넘는 의심 사례가
#   없는지 재확인 완료.
#
# **8/14 8차 — DB 원문과 실제 9개 문서 글자 단위 비교(API 없이, 이전 세션이
# DetailPage.jsx 검증용으로 받아둔 문서 JSON과 로컬 PDF가 우연히 겹치는 9건
# 이용)**: 공백 정규화 후 유사도(difflib) 평균 **93.5%**, 7/9건 96%+ (2건은
# 99.9%대로 사실상 일치). 이 비교 중 DB 원문에는 있는데 재추출 결과에는
# 없는 체계적 차이 2가지를 발견해서 그중 하나는 이번에 고침:
# 1. **마스킹 기호 정규화 누락(고침)**: 일부 기관 PDF는 이름/부서명을
#    "○○○", "◎◎◎◎", "□□" 같은 기호 반복으로 표시하는데, DB 원문은 이미
#    이걸 통일된 "[부서]" 토큰으로 저장하고 있었음(이 저장소 스크립트 중
#    어디서 그 정규화를 하는지는 못 찾음 — 아마 커밋 안 된 1회성 스크립트로
#    보임). `normalize_masked_glyphs()`를 추가해 재현함(공백 없이 2개 이상
#    붙은 동일 기호 → "[부서]"). 페이지 번호 푸터("- 1 -")도 DB 원문엔 없어서
#    `strip_page_number_footers()`로 같이 제거.
# 2. **선행 상용구 미제거(아직 안 고침)**: 일부 문서는 "제 목 : ..." 줄
#    앞에 "권 고 사 항 1.", "지적연번 2017-", "한 국 소 비 자 원 주 의 요 구"
#    같은 문서분류/기관명 헤더가 있는데, DB 원문은 이게 빠져 있고(아마 원
#    파이프라인이 "제 목" 줄부터 시작하도록 자르거나, 반복되는 페이지
#    헤더로 인식해 걸러내는 듯) 이 재추출 로직은 페이지 전체를 그대로
#    포함시켜서 포함됨. 표(예: [표 107] 형태)가 있는 문서는 셀 순서/구조
#    차이로 유사도가 더 낮게 나옴(doc 0772c638aa51d7c6=76.6%, 위 두 상용구
#    문제 겹친 doc 3053fd66660671f3=78.5%) — 둘 다 이번 라운드의 핵심
#    타겟(2단 순서+띄어쓰기)과는 무관한 별개 이슈라 이번엔 손대지 않음.
#
# **아직 프로토타입 단계 — DB에 바로 반영하지 말 것**:
# - 이 세션은 Railway DB 쓰기 권한이 없어서 실제 반영 코드는 없음(추출 함수만).
# - 원문과 글자 단위로 직접 비교한 건 9개 문서뿐(전부 24개 문서 중, API 없이
#   우연히 겹치는 것만) — 2,111건 전체에 적용하기 전에 API/DB 접근이 되는
#   대로 더 넓은 무작위 샘플로 같은 방식 재검증 필요. 특히 위 "선행 상용구"
#   문제와 표 구조 차이는 아직 미해결이므로, 이 두 패턴이 있는 문서는
#   DB 반영 전 별도로 걸러내거나 추가로 고쳐야 함.
# - 임계값 gap_threshold=2.5pt가 다른 폰트/기관 문서에도 맞는지 폭넓게
#   확인 필요(폰트 크기가 다르면 이 값도 다시 튜닝해야 할 수 있음).
# - 줄바꿈 단위가 원래 라인 인식(get_text 기본 "blocks")과 다르게 세밀하게
#   쪼개지는 경우가 있음(예: 밑줄/강조 글자가 한 글자씩 별도 줄로 나오는 등) —
#   내용 손실은 없지만 프론트(DetailPage.jsx)의 문단 합치기 로직이 알아서
#   흡수하는지 실제 렌더링으로 확인 필요.
# - DB 반영 전 반드시: (1) 더 많은 2,111건 샘플로 사람이 직접 비교 검증,
#   (2) 백업(scripts/backup_before_fix.py류) 먼저, (3) 재임베딩 사이클 계획.
# ------------------------------------------------------------------
import re

import pymupdf

# 일부 기관 PDF는 익명화된 이름/부서명을 '○○○', '◎◎◎◎', '□□' 같은 동일
# 기호 반복으로(글자 하나당 기호 하나씩) 표시함. 현재 DB의 raw_text는 이런
# 기호 반복을 이미 통일된 "[부서]" 토큰으로 정규화해서 저장하고 있음(어느
# 기호를 쓰든, 몇 글자든 상관없이 하나의 "[부서]"로) — 이 정규화가 정확히
# 어디서 이뤄졌는지는(원본 파이프라인/한 번성 스크립트) 이 저장소에서
# 찾지 못했지만, 재추출 결과를 DB 원문과 9개 문서로 직접 비교하며 발견함.
# 같은 기호가 공백 없이 2개 이상 붙어 나오면 마스킹으로 보고 하나의 "[부서]"
# 토큰으로 치환. 글머리 기호(◯ U+25EF 등)는 항상 단독 1개 + 뒤에 공백이
# 오는 형태라 이 패턴과 구분됨(예: "◯ 음주관리" 불릿 vs "○○본부" 마스킹,
# 서로 다른 코드포인트: ◯=U+25EF, ○=U+25CB).
# 2026-08-18: 2단 레이아웃 재추출분(PDF column-fix) 유사도 진단 중 ☆☆병원,
# ▽▽과 같이 원래 5종 밖의 기호로 마스킹된 문서를 발견 — 흔히 쓰이는 별/삼각형
# 계열 기호까지 넓힘(★☆는 짝, △▲▽▼도 짝이라 원래 5종과 같은 패턴으로 나옴).
_MASK_GLYPH_RE = re.compile(r"([○◎□●■☆★△▲▽▼◇◆])\1+")

# 페이지 하단에 "- 1 -" 형태로 반복되는 페이지 번호 푸터. DB 원문에는 없어서
# (페이지마다 반복되는 걸 걸러내는 로직이 원 파이프라인에 있는 듯) 같이 제거.
_PAGE_NUMBER_RE = re.compile(r"^-\s*\d+\s*-$")


def normalize_masked_glyphs(text):
    """공백 없이 2개 이상 붙어 나오는 동일 마스킹 기호를 "[부서]" 토큰으로
    치환(위 _MASK_GLYPH_RE 설명 참고)."""
    return _MASK_GLYPH_RE.sub("[부서]", text)


def strip_page_number_footers(text):
    """"- 1 -" 같은 페이지 번호 전용 줄을 제거."""
    lines = [l for l in text.split("\n") if not _PAGE_NUMBER_RE.match(l.strip())]
    return "\n".join(lines)


def chars_to_text(chars, gap_threshold=2.5):
    """문자(char) 목록(이미 읽기 순서로 정렬됨)을 좌표 기반으로 이어붙이되,
    문자 간 간격이 임계값 이상이면 공백을 삽입. PyMuPDF의 기본 단어 인식이
    놓치는 좁은 간격(이 말뭉치 기준 ~4~6pt)을 직접 재서 보정함(위 모듈 설명
    참고)."""
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


def line_text(line, gap_threshold=2.5):
    """줄 하나(PyMuPDF rawdict의 line)를 문자 좌표 기반으로 이어붙임."""
    chars = []
    for span in line["spans"]:
        chars.extend(span.get("chars", []))
    return chars_to_text(chars, gap_threshold)


def _merge_same_row_fragments(fragments, y_tol=2.0, max_x_gap=50.0):
    """PyMuPDF는 같은 시각적 줄(row)도 폰트/서브셋 전환(예: 문장부호용
    임베딩 폰트 vs 한글 본문 폰트) 경계에서 별도의 block/line으로 쪼개는
    경우가 있음 — 특히 "제    목】" 처럼 글자 사이 간격이 아주 넓은 라벨성
    텍스트에서 자주 발생(간격이 너무 넓어 PyMuPDF 자체가 줄바꿈으로 오인).
    같은 페이지 안에서 y0(세로 시작 좌표)가 거의 동일한(허용오차 y_tol)
    fragment들은 실제로는 한 줄일 가능성이 높다.

    2026-08-18: y_tol을 1.0 -> 2.0으로 늘림 — 원문자 목록("◯1", "◯2"...)에서
    원(◯) 안에 작게 겹쳐 그려지는 숫자가 폰트 크기 차이(9.2pt vs 6.5pt) 때문에
    베이스라인이 살짝(실측 1.7pt) 어긋나 있어서, y_tol=1.0으로는 다른 줄로
    분리되어 "◯ 음주관리...(조치)" 다음 줄에 숫자만 "1" 덜렁 나오는 문제가
    있었음(한국철도공사 2020 dec56dc84bfe3a6c 실사용 중 발견). 1.7pt까지
    합쳐지게 2.0으로 올림 — 본문 줄간격(9.2pt 폰트 기준 통상 11pt 이상)보다는
    훨씬 작아서 서로 다른 줄이 잘못 합쳐질 위험은 낮음.

    주의: 2단 레이아웃 페이지는 좌/우 컬럼의 첫 줄이 y0가 서로 거의 같은
    경우가 흔함(둘 다 컬럼 맨 위에서 시작) — 이런 경우 y0만 보고 합치면
    서로 다른 컬럼의 내용이 한 줄로 잘못 이어붙여져서 컬럼 분리 로직 자체가
    무력화됨(합쳐진 줄의 bbox가 페이지 폭 전체로 넓어져 좌우 판정 불가).
    그래서 y0 근접뿐 아니라 x 간격도 함께 봐서, 가로로 "붙어있는"
    fragment끼리만(간격 <= max_x_gap) 합친다 — 이 값은 실제 관측된 줄바꿈
    오분류 간격(~30pt 이하)보다는 넉넉히 크고, 2단 컬럼 판정에 쓰는 최소
    컬럼 간격(페이지 폭의 15%, 보통 90pt 이상)보다는 훨씬 작게 잡아
    컬럼 간 간격은 항상 걸러지도록 함."""
    fragments = sorted(fragments, key=lambda f: (f["bbox"][1], f["bbox"][0]))
    y_clusters = []
    for frag in fragments:
        y0 = frag["bbox"][1]
        if y_clusters and abs(y_clusters[-1]["last_y0"] - y0) <= y_tol:
            y_clusters[-1]["frags"].append(frag)
            y_clusters[-1]["last_y0"] = y0
        else:
            y_clusters.append({"last_y0": y0, "frags": [frag]})

    rows = []
    for cluster in y_clusters:
        frags = sorted(cluster["frags"], key=lambda f: f["bbox"][0])
        cur = [frags[0]]
        for prev, f in zip(frags, frags[1:]):
            gap = f["bbox"][0] - prev["bbox"][2]
            if gap <= max_x_gap:
                cur.append(f)
            else:
                rows.append(cur)
                cur = [f]
        rows.append(cur)

    merged = []
    for frags in rows:
        chars = []
        for f in frags:
            chars.extend(f["chars"])
        x0 = min(f["bbox"][0] for f in frags)
        y0 = min(f["bbox"][1] for f in frags)
        x1 = max(f["bbox"][2] for f in frags)
        y1 = max(f["bbox"][3] for f in frags)
        merged.append({"bbox": (x0, y0, x1, y1), "chars": chars})
    return merged


def extract_page_text(page, gap_threshold=2.5):
    """페이지 하나를 컬럼(좌/우) 인식 + 줄 단위 간격 보정 문자 재구성으로
    추출. 2단이면 왼쪽 칼럼 전체(위→아래) 후 오른쪽 칼럼 전체(위→아래)
    순서로, 단일 컬럼이면 그냥 위→아래 순서로 반환.
    컬럼 분리 판정 로직은 scripts/audit_pdf_column_layout.py의
    detect_multicolumn_pages()와 동일한 임계값(문장급 줄 5개+, 최대 간격이
    페이지 폭의 15% 초과, 좌우 각 3줄+, 세로 퍼짐 100pt+)을 씀 — 이미 그
    스크립트로 다단 판정된 문서에만 이 재추출을 적용하는 걸 전제로 함."""
    d = page.get_text("rawdict")
    fragments = []
    for block in d["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            chars = []
            for span in line["spans"]:
                chars.extend(span.get("chars", []))
            if chars:
                fragments.append({"bbox": line["bbox"], "chars": chars})

    if not fragments:
        return ""

    rows = _merge_same_row_fragments(fragments)
    lines = []
    for row in rows:
        text = chars_to_text(row["chars"], gap_threshold)
        if text:
            lines.append({"bbox": row["bbox"], "text": text})

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
    """PDF 파일 경로 또는 바이트를 받아 전체 문서를 페이지 순서대로 재추출.
    마스킹 기호 정규화("[부서]") + 페이지 번호 푸터 제거까지 적용한 최종
    결과를 반환함(DB의 현재 raw_text와 비교 검증한 후처리, 위 상수 설명
    참고)."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        doc = pymupdf.open(stream=path_or_bytes, filetype="pdf")
    else:
        doc = pymupdf.open(path_or_bytes)
    pages = [extract_page_text(p, gap_threshold) for p in doc]
    doc.close()
    text = "\n".join(pages)
    text = strip_page_number_footers(text)
    text = normalize_masked_glyphs(text)
    return text


if __name__ == "__main__":
    # 사용법: python3 reextract_pdf_text.py 파일.pdf
    # (또는 audit_pdf_column_layout.py의 build_source_url()로 받은 PDF를
    # 대상으로 사람이 눈으로 원문과 비교하며 검증하는 용도)
    import sys

    print(extract_doc_text(sys.argv[1]))
