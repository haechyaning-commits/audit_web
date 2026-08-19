# ------------------------------------------------------------------
# "1. 제목:" 번호 유실 수정 (Colab 실행용, 2026-08-19 설계)
# ------------------------------------------------------------------
# 배경: scripts/audit_title_number_and_wordbreak.py로 규모조사한 결과 —
# 문서 맨 앞 "제목 : ..." 줄에 원래 있었어야 할 "1. " 번호가 원본 데이터
# 적재 시점부터 유실된 문서가 4,305건(전체 67,751건의 6.35%) 확인됨. 이
# 저장소 코드가 지운 게 아니라 raw_text 자체에 이미 없는 상태(한국보훈복지
# 의료공단 2022 01ff5cfbb6fafddd로 최초 확인, 8/14 9차).
#
# 기관별 분포: 한국보훈복지의료공단(2,871) + 한국자산관리공사(766) +
# 한국토지주택공사(507) = 전체의 96.3%, 나머지는 소수 기관에 흩어져 있음.
# 탐지 패턴(제목 줄에 번호 없음 + 바로 다음 비어있지 않은 줄이 "2." 이상)이
# 구조적으로 명확해서 오탐 위험이 낮음 — 샘플 검증(5건)도 전부 명백한
# 유실 패턴이었음.
#
# **수정 방식**: fix_text_corruption.py(2026-08-07)와 동일한 "정규식으로
# 그 자리에서 패치" 패턴 — raw_text/chunks.text 둘 다 같은 변환 함수를
# 독립적으로 적용(두 테이블 사이에 별도 연결 로직 없음, 그 스크립트와 같은
# 전제: 대부분의 문서에서 chunks의 첫 청크가 raw_text 맨 앞과 동일한 줄로
# 시작한다고 가정). 구조 변경(청크 경계) 없이 텍스트 한 줄만 바뀌므로,
# HWP/PDF 재추출 스크립트들과 달리 전체 재청킹은 안 하고 바뀐 chunk만
# 재임베딩하면 됨 — 기존 reembed_changed_chunks.py를 그대로 재사용.
#
# **실행 순서**:
#   1) DRY_RUN=True로 이 스크립트 실행 — 수정 대상 건수, 샘플 확인.
#   2) 이상 없으면 DRY_RUN=False로 재실행 — 백업 저장 -> documents.raw_text
#      UPDATE -> chunks.text UPDATE(바뀐 것만) -> reembed_input.jsonl 저장.
#   3) 별도 GPU 런타임에서 scripts/reembed_changed_chunks.py를 그대로 실행
#      (이미 이 저장소에 있는 스크립트, 수정 불필요) — reembed_input.jsonl을
#      읽어 재임베딩 + chunks.embedding UPDATE까지 끝냄.
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary

import datetime
import json
import os
import re

import psycopg2

DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로

TITLE_LINE_RE = re.compile(r"^[\[【]?제\s*목\s*[\]】]?\s*[:：]?\s*\S")
NUMBERED_LINE_RE = re.compile(r"^(\d{1,2})[.)]\s+\S")

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

_COLAB_DRIVE_DIR = "/content/drive/MyDrive/audit_project/"
BACKUP_PATH = (
    f"{_COLAB_DRIVE_DIR}title_number_fix_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.jsonl"
)
# reembed_changed_chunks.py가 읽는 고정 경로와 일치시킴(그 스크립트 코드 그대로 재사용)
REEMBED_INPUT_PATH = _COLAB_DRIVE_DIR + "reembed_input.jsonl"


def fix_title_number(text: str) -> str | None:
    """문서(또는 청크) 텍스트 맨 앞부분에서 "제목:" 줄에 번호가 없고 바로
    다음 비어있지 않은 줄이 "2." 이상으로 시작하면 "1. "을 삽입.
    audit_title_number_and_wordbreak.py의 탐지 로직과 동일(검증된 패턴) —
    수정 없으면 None 반환."""
    if not text:
        return None
    lines = text.split("\n")
    for i, line in enumerate(lines[:5]):
        trimmed = line.strip()
        if not trimmed:
            continue
        if TITLE_LINE_RE.match(trimmed) and not NUMBERED_LINE_RE.match(trimmed):
            for j in range(i + 1, min(i + 3, len(lines))):
                nxt = lines[j].strip()
                if not nxt:
                    continue
                m = NUMBERED_LINE_RE.match(nxt)
                if m and int(m.group(1)) >= 2:
                    lines[i] = "1. " + trimmed
                    return "\n".join(lines)
                break
        break  # 제목 후보 줄 하나만 확인(대부분 첫 줄) — 조사 스크립트와 동일
    return None


# ------------------------------------------------------------------
# 1) documents.raw_text 전체 스캔 — 수정 대상 계산 (아직 DB 안 건드림)
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '300s'")
    cur.execute("SELECT id, institution, year, raw_text FROM documents")
    doc_rows = cur.fetchall()
conn.close()

doc_fixes = []  # (doc_id, old_text, new_text)
for doc_id, institution, year, raw_text in doc_rows:
    new_text = fix_title_number(raw_text)
    if new_text is not None:
        doc_fixes.append((doc_id, institution, year, raw_text, new_text))

print(f"전체 문서 {len(doc_rows)}건 중 수정 대상: {len(doc_fixes)}건")

print("\n샘플 3건 (수정 전 -> 수정 후, 첫 줄만):")
for doc_id, institution, year, old_text, new_text in doc_fixes[:3]:
    old_first = old_text.split("\n", 1)[0]
    new_first = new_text.split("\n", 1)[0]
    print(f"  {doc_id} ({institution} {year}): {old_first!r} -> {new_first!r}")

if DRY_RUN:
    raise SystemExit(
        "\nDRY_RUN=True라 여기서 멈춤(DB 변경 없음). 위 건수와 샘플이 말이 되면 "
        "DRY_RUN=False로 바꿔서 다시 실행하세요."
    )

# ------------------------------------------------------------------
# 2) 백업 — documents.raw_text + 관련 chunks.text (수정 대상 문서만)
# ------------------------------------------------------------------
_fix_ids = [doc_id for doc_id, *_ in doc_fixes]

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '60s'")
    cur.execute(
        "SELECT id, document_id, text FROM chunks WHERE document_id = ANY(%s)",
        (_fix_ids,),
    )
    old_chunks_by_doc: dict[str, list] = {}
    for cid, did, text in cur.fetchall():
        old_chunks_by_doc.setdefault(did, []).append({"id": cid, "text": text})
conn.close()

os.makedirs(_COLAB_DRIVE_DIR, exist_ok=True)
with open(BACKUP_PATH, "w", encoding="utf-8") as f:
    for doc_id, institution, year, old_text, new_text in doc_fixes:
        f.write(json.dumps({
            "id": doc_id,
            "raw_text": old_text,
            "chunks": old_chunks_by_doc.get(doc_id, []),
        }, ensure_ascii=False) + "\n")
print(f"백업 저장 완료: {BACKUP_PATH} ({len(doc_fixes)}건)")

# ------------------------------------------------------------------
# 3) documents.raw_text UPDATE
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '120s'")
        for doc_id, institution, year, old_text, new_text in doc_fixes:
            cur.execute("UPDATE documents SET raw_text = %s WHERE id = %s", (new_text, doc_id))
        conn.commit()
    print(f"documents.raw_text 갱신: {len(doc_fixes)}건")
finally:
    conn.close()

# ------------------------------------------------------------------
# 4) chunks.text 패치 — 같은 변환을 각 청크 텍스트에도 독립적으로 적용
#    (대부분 첫 청크가 raw_text 맨 앞과 같은 줄로 시작한다고 가정 —
#    fix_text_corruption.py와 동일한 전제)
# ------------------------------------------------------------------
conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '60s'")
    cur.execute(
        "SELECT id, document_id, text FROM chunks WHERE document_id = ANY(%s)",
        (_fix_ids,),
    )
    chunk_rows = cur.fetchall()
conn.close()

changed_chunks = []  # (chunk_id, new_text)
for chunk_id, document_id, text in chunk_rows:
    new_text = fix_title_number(text)
    if new_text is not None:
        changed_chunks.append((chunk_id, new_text))

print(f"chunks.text 수정 대상: {len(changed_chunks)}건 "
      f"(수정된 문서 {len(doc_fixes)}건 중 첫 청크가 라인 경계 그대로 유지된 것만 매칭됨)")

conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '120s'")
        for chunk_id, new_text in changed_chunks:
            cur.execute("UPDATE chunks SET text = %s WHERE id = %s", (new_text, chunk_id))
        conn.commit()
    print(f"chunks.text 갱신: {len(changed_chunks)}건")
finally:
    conn.close()

# ------------------------------------------------------------------
# 5) 재임베딩 입력 저장 — scripts/reembed_changed_chunks.py가 그대로 읽음
# ------------------------------------------------------------------
changed_chunk_ids = [cid for cid, _ in changed_chunks]
if changed_chunk_ids:
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT id, text FROM chunks WHERE id = ANY(%s)", (changed_chunk_ids,))
        rows = cur.fetchall()
    conn.close()
    with open(REEMBED_INPUT_PATH, "w", encoding="utf-8") as f:
        for chunk_id, text in rows:
            f.write(json.dumps({"chunk_id": chunk_id, "text": text}, ensure_ascii=False) + "\n")
    print(f"{REEMBED_INPUT_PATH} 저장 완료 ({len(rows)}건)")
else:
    print("재임베딩 대상 chunk 없음")

print(f"\n완료 — documents {len(doc_fixes)}건 / chunks {len(changed_chunks)}건 수정")
print("다음 단계: GPU 런타임에서 scripts/reembed_changed_chunks.py를 그대로 실행해서 "
      "재임베딩 + chunks.embedding 반영을 마무리할 것.")
