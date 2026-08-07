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
# 이 두 버그로 못 고치는 별개 문제(재추출 필요, 이 스크립트 범위 밖):
#   - raw_text가 50자 미만인데 parsing_quality가 fallback이 아닌 문서
#   - 인코딩이 깨져 치환문자(U+FFFD)가 섞인 문서
#   - 표가 있던 자리에 실제 표 내용 대신 "표"라는 placeholder 한 단어만
#     남고, 그걸 빼면 전체 300자도 안 되는 문서 (표 파싱 실패의 세 번째
#     변종 — 이건 XML도 라벨도 안 남고 아예 내용이 없어짐)
#   -> 총 1,765건 (2026-08-07 기준), 별도 재추출 워크스트림으로 분리.
#      텍스트 치환으로 복구 불가능하므로 이 스크립트로는 처리 안 함.
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
TAG_ATTR_RE = re.compile(r'\b[\w:]+="[^"]*"')
TAG_NAME_RE = re.compile(r"/?\bhp:[A-Za-z]+\b")
HWP_LEAK_MARKER = re.compile(r"hp:run|hp:lineseg|hp:sz|hp:pos")


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


def strip_hwpml_leak(text: str) -> str:
    """HWP XML 누출(hwp_leak) 수정. hp: 태그가 아예 없는 문서는 그대로
    반환 — 관련 없는 문서까지 공백/줄바꿈을 건드리는 사고 방지용 가드."""
    if not HWP_LEAK_MARKER.search(text):
        return text
    text = html.unescape(text)
    text = TAG_ATTR_RE.sub(" ", text)
    text = TAG_NAME_RE.sub(" ", text)
    text = re.sub(r"\s*/\s*(?=\s|$)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)           # 개행은 보존, 스페이스/탭만 압축
    text = re.sub(r" *\n *", "\n", text).strip()  # 개행 주변 공백만 정리
    return text


def full_fix(text: str) -> str:
    """hwp_leak을 먼저 벗겨서 구조를 정리한 다음, bold_dup을 collapse."""
    return fix_duplicated_chars(strip_hwpml_leak(text))


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


def export_reembed_input(conn, chunk_ids: list[str], out_path: str = "reembed_input.jsonl") -> None:
    """재임베딩이 필요한 chunk_id들의 (이미 수정된) 현재 text를 뽑아
    Colab의 embed_chunks.py 계열 스크립트가 읽을 수 있는 jsonl로 저장."""
    if not chunk_ids:
        print("재임베딩 대상 없음")
        return
    with conn.cursor() as cur:
        cur.execute("SELECT id, text FROM chunks WHERE id = ANY(%s)", (chunk_ids,))
        rows = cur.fetchall()
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
