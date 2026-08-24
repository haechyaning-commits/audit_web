# ------------------------------------------------------------------
# Wingdings 심볼폰트 불릿 오염 수정 (2026-08-24)
# ------------------------------------------------------------------
# 배경: 사용자가 검색 예시로 상세페이지를 둘러보다 한국농어촌공사 문서에서
# 이상한 글자를 제보한 것에서 시작한 조사(STATUS.md 14차 항목 전체 참고).
# 원본 PDF에서 Wingdings 폰트로 렌더링된 체크마크류 불릿 기호가, 폰트 정보 없이
# 문자코드만 뽑는 텍스트 추출 과정에서 그 코드값이 우연히 겹치는 라틴 알파벳
# 한 글자로 남는 버그. pymupdf로 원본 PDF를 직접 열어 `font='Wingdings-Regular'`
# 임을 확인한 조합만 이 스크립트의 대상으로 삼음 — 그 외(다른 기관의 'm' 소수
# 사례 등)는 아직 미검증이라 의도적으로 제외.
#
# 왜 "기관+글자" 조합으로 좁혔나: 범위조사 중 'y'(한국에너지공단)/'r'(한국남부
# 발전)이 처음엔 유력해 보였지만 실제로는 그 기관 PDF 머리말의 영단어
# ("...Advisory", "...Audit Leader") 끝글자가 우연히 앵커 문구 앞에 온
# 가짜 경보로 판명됨(font_check5.py 실행 결과 참고). "특정 기관에 집중"이라는
# 신호만으로는 못 믿는다는 게 이 과정에서 확인됐으므로, 여기 나열한 조합
# 외에는 절대 확장하지 말 것 — 새 조합을 추가하려면 반드시 pymupdf로 실제
# 폰트를 먼저 확인해야 함.
#
# 이 글자는 순수 장식용 불릿이라 제거해도 내용 손실이 없음. 다만 오탐을
# 막기 위해 엄격한 경계 조건(양옆 모두 알파벳이 아님 — "Advisory"의 y처럼
# 더 긴 영단어의 일부인 경우는 매칭 안 되게)을 그대로 사용.
#
# 실행 순서 (기존 fix_text_corruption.py와 동일한 패턴):
#   1) scripts/backup_before_fix.py로 documents.raw_text/chunks.text 백업
#      (아직 안 했다면 먼저 실행 — 이 스크립트는 백업을 자체적으로 하지 않음)
#   2) DRY_RUN=True로 이 스크립트 실행 — 영향받는 문서/청크 수, 전후 샘플 확인
#   3) 이상 없으면 DRY_RUN=False로 재실행 — documents.raw_text, chunks.text UPDATE
#   4) 바뀐 chunk만 재임베딩 필요 (reembed_input.jsonl 자동 export됨,
#      embed_chunks.py 계열로 재임베딩 후 chunks.embedding UPDATE)
# ------------------------------------------------------------------
import json
import os
import re

import psycopg2

DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로

# (기관, 글자) — pymupdf로 Wingdings-Regular 폰트를 실제 확인한 조합만.
# 확장하려면 반드시 새 (기관, 글자) 조합을 pymupdf로 먼저 검증할 것.
CONFIRMED_BULLET_RULES = [
    ("한국수력원자력", "v"),
    ("서울대학교병원", "m"),
    ("국립부산과학관", "m"),
    ("한국수자원조사기술원", "m"),
    ("한국원자력통제기술원", "q"),
]

# 기관별로 여러 글자가 있을 수 있으니 institution -> [letter, ...] 로 재구성
RULES_BY_INSTITUTION = {}
for institution, letter in CONFIRMED_BULLET_RULES:
    RULES_BY_INSTITUTION.setdefault(institution, []).append(letter)


def _bullet_re_for(letter: str) -> re.Pattern:
    # 양옆 모두 라틴 알파벳이 아닐 때만 매칭(더 긴 영단어의 일부는 제외) —
    # 불릿 뒤에 붙는 공백 한 칸까지 같이 제거(문맥 샘플 전부 "m 감사..."
    # 처럼 글자+공백 형태였음).
    # 2026-08-24: 숫자 바로 뒤도 제외 — digit_check.py로 전수조사한 결과
    # 한국수자원조사기술원 문서 하나에서 "약 2.0m에 위치"(실제 미터 단위 표기)가
    # 오탐으로 잡히는 걸 확인함(869건 중 1건). m=미터/v=볼트처럼 진짜 단위
    # 표기가 숫자 바로 뒤에 오는 경우와, 불릿 누출(항상 줄바꿈/항목기호 뒤,
    # 숫자 뒤인 사례는 0건)을 구분하는 안전한 경계.
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(letter) + r"(?![A-Za-z]) ?")


_BULLET_RES = {letter: _bullet_re_for(letter) for _, letter in CONFIRMED_BULLET_RULES}


def fix_bullet_leak(text: str, institution: str) -> str:
    """institution에 확정된 규칙이 있을 때만, 그 글자들을 제거."""
    letters = RULES_BY_INSTITUTION.get(institution)
    if not letters or not text:
        return text
    for letter in letters:
        text = _BULLET_RES[letter].sub("", text)
    return text


DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)

# ------------------------------------------------------------------
# 1) documents.raw_text
# ------------------------------------------------------------------
institutions = list(RULES_BY_INSTITUTION.keys())
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute(
        "SELECT id, institution, raw_text FROM documents WHERE institution = ANY(%s)",
        (institutions,),
    )
    doc_rows = cur.fetchall()

doc_changed = []
for doc_id, institution, raw_text in doc_rows:
    fixed = fix_bullet_leak(raw_text, institution)
    if fixed != raw_text:
        doc_changed.append((doc_id, institution, raw_text, fixed))

print(f"documents: 대상 기관 {len(institutions)}곳 {len(doc_rows)}건 중 "
      f"{len(doc_changed)}건 수정 대상")
by_inst = {}
for doc_id, institution, _, _ in doc_changed:
    by_inst[institution] = by_inst.get(institution, 0) + 1
for institution, cnt in sorted(by_inst.items(), key=lambda x: -x[1]):
    print(f"  {institution}: {cnt}건")

print("\n샘플 5건 (수정 전 -> 후, 해당 부분만):")
for doc_id, institution, before, after in doc_changed[:5]:
    letter = RULES_BY_INSTITUTION[institution][0]
    m = _BULLET_RES[letter].search(before)
    if m:
        s, e = max(0, m.start() - 20), min(len(before), m.end() + 30)
        print(f"  [{doc_id}] {institution}")
        print(f"    전: ...{before[s:e]!r}...")
        # after 쪽 대응 구간은 정확히 안 맞을 수 있어 참고용으로만 앞부분 비교
        print(f"    후: ...{after[s:max(s, e - (m.end() - m.start()))]!r}...")

# ------------------------------------------------------------------
# 2) chunks.text — documents와 같은 institution 매핑 필요 (chunks에는
#    institution 컬럼이 없으므로 document_id로 join)
# ------------------------------------------------------------------
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute(
        "SELECT c.id, d.institution, c.text FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE d.institution = ANY(%s)",
        (institutions,),
    )
    chunk_rows = cur.fetchall()

chunk_changed = []
for chunk_id, institution, text in chunk_rows:
    fixed = fix_bullet_leak(text, institution)
    if fixed != text:
        chunk_changed.append((chunk_id, text, fixed))

print(f"\nchunks: 대상 기관 청크 {len(chunk_rows)}건 중 {len(chunk_changed)}건 수정 대상")

# ------------------------------------------------------------------
# 3) 실제 반영 (DRY_RUN=False일 때만)
# ------------------------------------------------------------------
if not DRY_RUN:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        batch = [(fixed, doc_id) for doc_id, _, _, fixed in doc_changed]
        for i in range(0, len(batch), 500):
            cur.executemany(
                "UPDATE documents SET raw_text = %s WHERE id = %s", batch[i:i + 500]
            )
            conn.commit()
            print(f"  documents 진행: {min(i + 500, len(batch))}/{len(batch)}")

    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        batch = [(fixed, chunk_id) for chunk_id, _, fixed in chunk_changed]
        for i in range(0, len(batch), 500):
            cur.executemany(
                "UPDATE chunks SET text = %s WHERE id = %s", batch[i:i + 500]
            )
            conn.commit()
            print(f"  chunks 진행: {min(i + 500, len(batch))}/{len(batch)}")

    # 재임베딩 대상 export (fix_text_corruption.py의 export_reembed_input과 동일 패턴)
    reembed_ids = [chunk_id for chunk_id, _, _ in chunk_changed]
    out_dir = "/content/drive/MyDrive/audit_project/"
    out_path = (out_dir if os.path.isdir(out_dir) else "") + "reembed_input_bullet_fix.jsonl"
    if reembed_ids:
        with conn.cursor() as cur:
            cur.execute("SELECT id, text FROM chunks WHERE id = ANY(%s)", (reembed_ids,))
            rows = cur.fetchall()
        with open(out_path, "w", encoding="utf-8") as f:
            for chunk_id, text in rows:
                f.write(json.dumps({"chunk_id": chunk_id, "text": text}, ensure_ascii=False) + "\n")
        print(f"\n재임베딩 대상 {len(reembed_ids)}건 -> {out_path}")
    else:
        print("\n재임베딩 대상 없음")

    print(f"\n반영 완료 — documents {len(doc_changed)}건, chunks {len(chunk_changed)}건")
else:
    print("\n[DRY RUN] 실제 반영 안 함 — 위 통계/샘플 확인 후 이상 없으면 DRY_RUN=False로 재실행")

conn.close()
