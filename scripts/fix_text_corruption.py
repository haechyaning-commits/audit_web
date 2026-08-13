# ------------------------------------------------------------------
# 텍스트 전처리 오염 수정 스크립트 (2026-08-07 발견된 데이터 품질 문제 대응)
# ------------------------------------------------------------------
# 배경: 검색 결과 미리보기에서 "제목목목목", "관관관관계계계계" 처럼 글자가
# 반복되는 문서, 그리고 "hp:run hp:linesegarray ..." 처럼 HWP(한글) 파일의
# 내부 XML 마크업이 텍스트로 그대로 새어 들어온 문서가 다수 발견됨.
# raw_text를 만든 파싱 단계(Colab 노트북, 이 레포 밖)의 버그로 추정되며,
# 이미 Postgres에 적재된 documents.raw_text / chunks.text에 반영돼 있었음.
#
# 두 가지 버그를 정규식으로 후처리해서 고침:
#
# 1) 글자 중복 (bold_dup) — 원본 PDF/HWP에서 볼드체로 강조된 텍스트가
#    획을 겹쳐 그리는 방식으로 렌더링된 경우, 텍스트 추출기가 겹친 획을
#    각각 별개 글자로 읽어서 "제목" -> "제제목목" 처럼 2~4배 중복 추출됨.
#    - 헤더 라벨은 글자 하나하나를 띄어써서("소 관 부 서") 스타일링하는
#      경우가 많아, 중복되면 "소소 관관 부부 서서"처럼 블록 사이에 공백이
#      낌 -> 정규식에 공백 허용 필요.
#    - 중복 배수가 홀수 나머지를 남기는 경우(예: 13배) 한 번의 collapse로
#      끝까지 안 줄어들고 2배로 남는 경우가 있어 -> 더 이상 안 바뀔 때까지
#      반복 적용 필요 (fix_duplicated_chars의 max_passes).
#
# 2) HWP XML 누출 (hwp_leak) — 표(테이블) 부분에서만 발생. 표 파싱이 실패해
#    HWPX 내부 마크업(hp:run, hp:tc, hp:sz 등)이 그대로 텍스트로 남음.
#    다행히 hp:t 뒤에 표 셀의 실제 내용이 남아있어서, 태그/속성만 정규식으로
#    벗겨내면 내용은 상당 부분 복원 가능 (표의 행/열 구조는 잃지만 검색
#    가능한 텍스트로는 충분).
#    - hp: 태그가 아예 없는 문서는 절대 건드리지 않음 (처음 버전은 이 가드가
#      없어서 전체 문서의 공백/줄바꿈을 몽땅 눌러버리는 사고가 있었음 —
#      DB 반영 전 로컬 검증에서 잡아냄, verify_and_apply()의 존재 이유).
#
# 3) 숫자 중복(bold_dup의 숫자 버전) — 1)과 같은 원인인데, 한글만 collapse
#    대상이었어서 "22002244" 같은 연도 숫자 중복은 처음엔 일부러 안 고쳤음
#    (숫자를 넣으면 "0000년", "000000" 같은 생년월일/주민번호 익명화
#    마스킹까지 다 지워버리는 오탐이 있었기 때문 — 처음 시도 때 발견).
#    구분법: 마스킹은 항상 "같은 숫자 하나"만 반복(0000, 000000)되는 반면,
#    진짜 버그는 "서로 다른 숫자가 섞여서" 반복됨(2,2,0,0,2,2,4,4).
#    -> 매칭된 구간 안에 서로 다른 숫자가 2개 이상 있을 때만 collapse.
#
# 4) 표 placeholder 잡음 제거 — 표가 있던 자리에 "표"라는 단어 한 줄만
#    남는 경우(27,128건, §"별도 문제" 참고), 검색 화면에서 표를 이미지로
#    보여줄 방법이 없으니 이 한 단어는 정보 없는 잡음일 뿐. 줄 전체가
#    "표" 하나뿐인 라인만 제거 (문장 중간의 "[표 14]" 같은 정상적인
#    "표" 언급은 안 건드림).
#
# 이 네 가지로도 못 고치는 별개 문제(재추출 필요, 이 스크립트 범위 밖):
#   - raw_text가 50자 미만인데 parsing_quality가 fallback이 아닌 문서
#   - 인코딩이 깨져 치환문자(U+FFFD)가 섞인 문서
#   - 표 placeholder를 빼면 전체 300자도 안 되는 문서 (표 파싱 실패로
#     내용 자체가 없어진 경우 — 4)번은 잡음만 치울 뿐 내용을 만들어내진
#     못하므로 이 문서들은 여전히 내용이 빈 채로 남음)
#   -> 총 1,765건 (2026-08-07 기준), 별도 재추출 워크스트림으로 분리.
#      텍스트 치환으로 복구 불가능하므로 이 스크립트로는 처리 안 함.
#
# 5) HWP XML 누출 2차 (2026-08-13) — 1)의 hp:run류 수정 이후에도 표가 복잡한 문서에서
#    hc:(도형/차트 속성: transMatrix/scaMatrix/rotMatrix/fillBrush/winBrush/pt0~3 등)
#    계열과 linkListNextIDRef=/textpos=/vertpos=/outlineS가 별도로 새고 있는 걸
#    audit_hwp_tag_leak.py로 확인(97건, 전체의 0.14%, 한국토지주택공사 2025에 집중).
#    hc: 태그명은 hp:처럼 단독 토큰으로 떠다니고, 속성 형태(linkListNextIDRef= 등)는
#    "=" 뒤에 줄바꿈이 끼어 기존 TAG_ATTR_RE가 못 잡던 경우가 있어서 정규식을 확장.
#    남은 한계: "fff"/"head"/"cha"/"vert"/"col"/"borderFill"/"rowSpan" 같은 영문 조각도
#    같은 문서들에 섞여 나오지만, 정상 영문 약어와 구분이 애매해 이번엔 손대지 않음
#    (오탐 위험 > 실익 판단 — 필요해지면 각 조각의 등장 문맥을 더 모아서 별도 검토).
#
# 실행 순서:
#   1) documents_backup_<날짜>, chunks_backup_<날짜> 테이블로 백업
#   2) 이 스크립트로 documents.raw_text, chunks.text 수정
#   3) 라이브 DB에서 재검증 (CHAIN_RE / HWP_LEAK_MARKER 둘 다 0건이어야 함)
#   4) 바뀐 chunk만 골라 BGE-m3로 재임베딩 (Colab, GPU 필요) 후
#      chunks.embedding UPDATE — 텍스트만 고치고 벡터를 안 바꾸면 검색은
#      여전히 옛날 텍스트 기준으로 동작하므로 필수 단계.
# ------------------------------------------------------------------

import html
import json
import os
import re

import psycopg2

CHAIN_RE = re.compile(r"(?:([가-힣])\1{1,3} ?){2,}")
DIGIT_CHAIN_RE = re.compile(r"(?:(\d)\1{1,3} ?){2,}")
# 2026-08-13 추가: hp:run류 수정(08-07~10) 이후에도, 표가 복잡한 문서에서 hc:(도형/차트
# 속성) 계열과 linkListNextIDRef=/textpos=/vertpos= 속성이 별도로 새고 있는 게 추가로
# 발견됨(97건/전체 0.14%, audit_hwp_tag_leak.py로 규모 확인). 실제 오염 샘플을 떠보니
# "속성=\n"값"" 처럼 = 뒤에 줄바꿈이 끼어 들어오는 경우가 있어서 기존 TAG_ATTR_RE(=
# 바로 뒤에 따옴표를 요구)가 이걸 못 잡고 있었음 -> \s* 로 완화.
TAG_ATTR_RE = re.compile(r'\b[\w:]+=\s*"[^"]*"')
TAG_NAME_RE = re.compile(r"/?\b(?:hp|hc):[A-Za-z0-9]+\b")
# outlineS(hp:outlineShape 계열로 추정)는 hp:/hc: 접두어 없이 단독 토큰으로 새는 경우가
# 있어서 TAG_NAME_RE로는 안 잡힘 -> 별도 패턴.
BARE_LEAK_TOKEN_RE = re.compile(r"\boutlineS(?:hape)?\b")
HWP_LEAK_MARKER = re.compile(
    r"hp:run|hp:lineseg|hp:sz|hp:pos|hc:\w+|linkListNextIDRef=|textpos=|vertpos=|outlineS"
)

# 2026-08-12 추가: 같은 bold_dup 렌더링 버그가 괄호/인용부호에도 나타남
# ("｢｢업무용 차량...｣｣"처럼 여는/닫는 괄호가 겹쳐 나옴). 한글 글자 중복(CHAIN_RE)과
# 달리 괄호는 "각각/종종" 같은 정상적으로 반복되는 단어가 있을 수 없어서, 단독으로
# 나와도(연속 2회 이상 조건 없이) 항상 안전하게 1개로 줄여도 됨.
BRACKET_DUP_RE = re.compile(r"([「」『』｢｣【】〔〕])\1+")

# 2026-08-12 추가: "제목"/"제 목" 라벨 뒤에 콜론 없이 바로 내용이 이어지는 문서가
# 있음(예: "제목 장애인 전용 주차구획 표기 부적정", "제 목 장애인화장실..."). 다른
# 문서 대부분은 "제 목 : ..."처럼 콜론이 붙어있어서 일관성이 없음 — 문서 맨 앞의
# "제목"/"제 목" 라벨(본문 중간에 우연히 나오는 "제목"은 안 건드림, ^ 앵커로 문서
# 시작 위치에서만 매칭)에 콜론이 없으면 추가.
TITLE_LABEL_RE = re.compile(r"^(제\s*목)\s+(?![:：])")


def _collapse_pass(text: str) -> str:
    def collapse(m: re.Match) -> str:
        return re.sub(r"([가-힣])\1+", r"\1", m.group(0))
    return CHAIN_RE.sub(collapse, text)


def fix_duplicated_chars(text: str, max_passes: int = 5) -> str:
    """글자 중복(bold_dup) 수정. 중복 배수가 애매하게 안 떨어지면(예: 13배)
    한 번에 안 끝나고 2배로 남는 경우가 있어 안정될 때까지 반복 적용."""
    for _ in range(max_passes):
        new_text = _collapse_pass(text)
        if new_text == text:
            break
        text = new_text
    return text


def _collapse_digit_pass(text: str) -> str:
    def collapse(m: re.Match) -> str:
        span = m.group(0)
        # 익명화 마스킹("0000년", "000000")은 같은 숫자 하나만 반복되므로
        # 구분해서 보호 — 서로 다른 숫자가 2개 이상 섞여 있을 때만 진짜
        # 중복 버그로 판단 (예: "22002244" -> 2,0,4 세 종류 -> collapse)
        if len(set(c for c in span if c.isdigit())) < 2:
            return span
        return re.sub(r"(\d)\1+", r"\1", span)
    return DIGIT_CHAIN_RE.sub(collapse, text)


def fix_duplicated_digits(text: str, max_passes: int = 5) -> str:
    """숫자 중복(bold_dup의 숫자 버전, 예: 연도 "22002244" -> "2024") 수정.
    생년월일/주민번호 익명화 마스킹("0000년", "000000")은 안 건드림."""
    for _ in range(max_passes):
        new_text = _collapse_digit_pass(text)
        if new_text == text:
            break
        text = new_text
    return text


def fix_duplicated_brackets(text: str) -> str:
    """괄호/인용부호 중복(bold_dup의 괄호 버전) 수정 — "｢｢...｣｣"처럼 여는/닫는 괄호가
    겹쳐 나오는 경우. 괄호는 절대 의미상 반복될 일이 없어 한글 글자 중복(CHAIN_RE)과
    달리 "연속 2회 이상" 같은 안전장치 없이도 항상 1개로 줄여도 안전함."""
    return BRACKET_DUP_RE.sub(r"\1", text)


def normalize_title_colon(text: str) -> str:
    """문서 맨 앞 '제목'/'제 목' 라벨 뒤에 콜론이 없으면 추가해서 표기를 통일함.
    예: '제목 장애인 전용...' -> '제목 : 장애인 전용...'
        '제 목 장애인화장실...' -> '제 목 : 장애인화장실...'
    이미 콜론이 있으면 그대로 둠(count=1이라 문서당 한 번만, 맨 앞에서만 매칭되므로
    본문 중간의 '제목' 언급은 애초에 안 건드림)."""
    return TITLE_LABEL_RE.sub(r"\1 : ", text, count=1)


def strip_table_placeholder(text: str) -> str:
    """표(테이블) 내용이 통째로 사라지고 "표"라는 단어 한 줄만 남은 경우
    제거. 검색 화면에서 표를 이미지로 보여줄 방법이 없으니 정보 없는
    잡음일 뿐 — 줄 전체가 정확히 "표"뿐인 라인만 제거하고, 문장 중간의
    "[표 14] 휴가 중..." 같은 정상적인 언급은 안 건드림.
    주의: 표 안의 실제 내용까지 복원해주진 못함 — 그 내용이 통째로 사라진
    문서(전체 300자 미만)는 여전히 재추출 대상으로 남음."""
    lines = [line for line in text.split("\n") if line.strip() != "표"]
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def strip_hwpml_leak(text: str) -> str:
    """HWP XML 누출(hwp_leak) 수정. hp: 태그가 아예 없는 문서는 그대로
    반환 — 관련 없는 문서까지 공백/줄바꿈을 건드리는 사고 방지용 가드."""
    if not HWP_LEAK_MARKER.search(text):
        return text
    text = html.unescape(text)
    text = TAG_ATTR_RE.sub(" ", text)
    text = TAG_NAME_RE.sub(" ", text)
    text = BARE_LEAK_TOKEN_RE.sub(" ", text)
    text = re.sub(r"\s*/\s*(?=\s|$)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)           # 개행은 보존, 스페이스/탭만 압축
    text = re.sub(r" *\n *", "\n", text).strip()  # 개행 주변 공백만 정리
    return text


def full_fix(text: str) -> str:
    """hwp_leak을 먼저 벗겨서 구조를 정리 -> 글자/숫자/괄호 중복 collapse ->
    표 placeholder 잡음 제거 -> 제목 라벨 콜론 통일, 순서로 적용."""
    text = strip_hwpml_leak(text)
    text = fix_duplicated_chars(text)
    text = fix_duplicated_digits(text)
    text = fix_duplicated_brackets(text)
    text = strip_table_placeholder(text)
    text = normalize_title_colon(text)
    return text


def _update_changed_rows(cur, conn, table: str, col: str, rows: list, batch_size: int = 500) -> int:
    n = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        cur.executemany(f"UPDATE {table} SET {col} = %s WHERE id = %s", batch)
        conn.commit()
        n += len(batch)
        print(f"  {table}.{col} 진행: {n}/{len(rows)}")
    return n


def apply_fix(conn, table: str, col: str) -> list[str]:
    """table의 col 컬럼 전체를 읽어 full_fix 적용, 바뀐 행만 UPDATE.
    반환값: 실제로 바뀐 id 목록 (chunks면 이 목록으로 재임베딩 대상 산출)."""
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        cur.execute(f"SELECT id, {col} FROM {table}")
        all_rows = cur.fetchall()

    changed = []
    for row_id, text in all_rows:
        fixed = full_fix(text)
        if fixed != text:
            changed.append((fixed, row_id))

    print(f"{table}: 전체 {len(all_rows)}건 중 {len(changed)}건 수정 대상")
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        _update_changed_rows(cur, conn, table, col, changed)

    return [row_id for _, row_id in changed]


# Colab에서 Drive를 마운트했을 때의 고정 경로. load_to_postgres.py의 BASE,
# reembed_changed_chunks.py의 CHECKPOINT_PATH와 동일한 디렉터리로 맞춤.
_COLAB_DRIVE_DIR = "/content/drive/MyDrive/audit_project/"


def _default_reembed_input_path() -> str:
    """Drive가 마운트된 상태(Colab)면 Drive 경로를, 아니면 로컬 상대경로를 기본값으로 사용.
    (2026-08-12: 예전엔 무조건 로컬 상대경로(현재 작업 디렉터리)였는데, 그 상태로 만든
    reembed_input.jsonl이 Drive에 복사되기 전에 런타임이 재배정되면서 통째로 사라지는
    사고가 실제로 발생함 — export 시점부터 영속적인 Drive에 저장되도록 기본값을 바꿈.)"""
    if os.path.isdir(_COLAB_DRIVE_DIR):
        return _COLAB_DRIVE_DIR + "reembed_input.jsonl"
    return "reembed_input.jsonl"


def export_reembed_input(conn, chunk_ids: list[str], out_path: str | None = None) -> None:
    """재임베딩이 필요한 chunk_id들의 (이미 수정된) 현재 text를 뽑아
    Colab의 embed_chunks.py 계열 스크립트가 읽을 수 있는 jsonl로 저장.
    out_path를 안 주면 Drive가 마운트돼 있을 때 자동으로 Drive에 저장됨(_default_reembed_input_path)."""
    if out_path is None:
        out_path = _default_reembed_input_path()
    if not chunk_ids:
        print("재임베딩 대상 없음")
        return
    with conn.cursor() as cur:
        cur.execute("SELECT id, text FROM chunks WHERE id = ANY(%s)", (chunk_ids,))
        rows = cur.fetchall()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for chunk_id, text in rows:
            f.write(json.dumps({"chunk_id": chunk_id, "text": text}, ensure_ascii=False) + "\n")
    print(f"{out_path} 저장 완료 ({len(rows)}건) — Colab(GPU)에서 BGE-m3로 재임베딩 필요")


if __name__ == "__main__":
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL 환경변수를 설정하세요")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        apply_fix(conn, "documents", "raw_text")
        changed_chunk_ids = apply_fix(conn, "chunks", "text")
        export_reembed_input(conn, changed_chunk_ids)
    finally:
        conn.close()
