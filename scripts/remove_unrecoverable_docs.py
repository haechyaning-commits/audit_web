# ------------------------------------------------------------------
# 재추출 불가 문서 제외 스크립트 (2026-08-10, 재추출 대신 확정된 방침)
# ------------------------------------------------------------------
# 2026-08-07 데이터 품질 진단 때 발견된, 텍스트 치환으로 복구 불가능한
# 문서 3종(fix_text_corruption.py 헤더 코멘트에 정의된 기준과 동일)을
# 재추출하지 않고 DB에서 아예 제외하기로 결정함 (재추출은 원본 파일
# 재파싱까지 필요해 비용이 크고, 전체 2.4% 수준이라 검색 커버리지에
# 큰 영향 없다고 판단).
#
# 기준 (fix_text_corruption.py 주석과 동일 — 새 기준 만든 것 아님):
#   1) raw_text가 50자 미만인데 parsing_quality가 fallback이 아닌 문서
#   2) raw_text에 인코딩 깨짐(치환문자 U+FFFD)이 섞인 문서
#   3) strip_table_placeholder() 적용 후 남는 텍스트가 300자 미만인 문서
#      (표 내용이 통째로 사라져 사실상 내용이 없는 경우)
# 총 약 1,765건 예상 (2026-08-07 진단 기준) — 실행 시 정확한 건수를 다시
# 세어서 기대치와 크게 다르면(예: 수만 건) 삭제하지 말고 먼저 원인 확인할 것.
#
# 안전을 위해 2단계로 분리 (fix_text_corruption.py 반영 사고 이후 정착된
# "먼저 확인, 그다음 반영" 절차와 동일한 이유):
#   1) find_unrecoverable() — DB 조회만, 삭제 없음. 대상 id/사유를 로컬
#      manifest 파일(removed_unrecoverable_docs.jsonl)로 저장 + 건수 출력.
#      읽기 전용이라 fix_text_corruption.py 2차 반영이 아직 진행 중이어도
#      동시에 돌려도 안전함.
#   2) delete_unrecoverable() — 위 manifest를 사람이 눈으로 확인하고 건수가
#      기대치와 맞는지 검증한 뒤에만 실행. __main__에서 자동 연결 안 되어
#      있음 (아래 delete_unrecoverable(...) 줄 주석을 직접 풀어야 실행됨).
#      DB 부하/동시 쓰기 충돌을 피하려면 fix_text_corruption.py 2차 반영이
#      완전히 끝난 뒤에 실행 권장.
# ------------------------------------------------------------------

import json
import os
import re
from collections import Counter

import psycopg2

MANIFEST_PATH = "removed_unrecoverable_docs.jsonl"


def strip_table_placeholder(text: str) -> str:
    """fix_text_corruption.py의 동명 함수와 동일 로직 — 기준 판정용으로
    이 스크립트에서 다시 계산하기 위해 그대로 복사해 둠(단일 파일로
    복사-붙여넣기 실행하는 다른 스크립트들과 스타일 통일)."""
    lines = [line for line in text.split("\n") if line.strip() != "표"]
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def classify(raw_text: str, parsing_quality: str) -> str | None:
    """세 기준 중 하나라도 해당하면 그 사유를, 아무것도 해당 안 하면 None."""
    if len(raw_text) < 50 and parsing_quality != "fallback":
        return "short_non_fallback"
    if "�" in raw_text:
        return "encoding_broken"
    if len(strip_table_placeholder(raw_text)) < 300:
        return "table_placeholder_only"
    return None


def find_unrecoverable(conn, manifest_path: str = MANIFEST_PATH) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        cur.execute("SELECT id, institution, year, parsing_quality, raw_text FROM documents")
        rows = cur.fetchall()

    reasons: dict[str, tuple] = {}
    for doc_id, institution, year, parsing_quality, raw_text in rows:
        reason = classify(raw_text, parsing_quality)
        if reason:
            reasons[doc_id] = (institution, year, parsing_quality, reason)

    print(f"전체 {len(rows)}건 중 재추출 불가(제외 대상) {len(reasons)}건")
    print(Counter(v[3] for v in reasons.values()))

    with open(manifest_path, "w", encoding="utf-8") as f:
        for doc_id, (institution, year, parsing_quality, reason) in reasons.items():
            f.write(json.dumps({
                "id": doc_id,
                "institution": institution,
                "year": year,
                "parsing_quality": parsing_quality,
                "reason": reason,
            }, ensure_ascii=False) + "\n")
    print(f"{manifest_path} 저장 완료 — 삭제 전 반드시 내용/건수 확인")

    return list(reasons.keys())


def delete_unrecoverable(conn, doc_ids: list[str]) -> None:
    """documents가 FK로 참조되므로(schema.sql: chunks.document_id REFERENCES
    documents(id), CASCADE 없음) chunks를 먼저 지우고 documents를 지운다."""
    if not doc_ids:
        print("삭제 대상 없음")
        return
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        cur.execute("DELETE FROM chunks WHERE document_id = ANY(%s)", (doc_ids,))
        n_chunks = cur.rowcount
        cur.execute("DELETE FROM documents WHERE id = ANY(%s)", (doc_ids,))
        n_docs = cur.rowcount
        conn.commit()
    print(f"삭제 완료 — documents {n_docs}건, chunks {n_chunks}건 제거")


if __name__ == "__main__":
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL 환경변수를 설정하세요")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        doc_ids = find_unrecoverable(conn)
        # 아래 줄은 일부러 주석 처리 — removed_unrecoverable_docs.jsonl을 열어
        # 건수(기대치 ~1,765건)와 내용을 직접 확인한 뒤에만 주석을 풀고 재실행할 것.
        # delete_unrecoverable(conn, doc_ids)
    finally:
        conn.close()
