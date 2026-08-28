# ------------------------------------------------------------------
# 부서/기관명 익명화 심볼 누출 수정 반영 (2026-08-27)
# ------------------------------------------------------------------
# 배경: audit_dept_anon_symbol_leak_scope.py(1차)~_round3.py(3차)로 규모조사 완료.
# 확정된 마스킹 전용 문자 42종(카드무늬 7 + 기하학무늬/블록기호 33 + outline 짝 2,
# 컨텍스트 샘플 전수 확인 — 정상 용도 없음 확정) + 기존 8종(○□△▲▽▼◇◆, 정상 불릿으로도
# 쓰여서 reextract_pdf_text.py 원래 설계대로 "2개 이상 연속"일 때만 마스킹으로 판단하는
# 안전장치 유지)을 대상으로 raw_text를 정규화. 최종 합집합 규모: 24,920건/67,751건
# (36.78%) — 이 프로젝트 역대 최대 데이터 품질 문제(STATUS.md 9차 참고).
#
# **라벨을 "[부서]"에서 "[비공개]"로 통일한 이유**: 이번 조사로 가려진 대상이 부서만이
# 아니라 기관 자기이름(한국문화예술위원회 사례)·직위·회사명·숫자(순위 등)까지 다양함이
# 확인됨 — "부서"라는 특정 라벨은 자주 틀리지만 "비공개"는 어떤 걸 가렸든 항상 맞는
# 표현. 이미 DB에 저장된 기존 "[부서]" 토큰도 이 스크립트가 전부 "[비공개]"로 통일함
# (신규 치환분과 라벨을 맞추기 위해 — 그래서 이 스크립트의 "영향 문서" 수는 3차 규모조사
# 숫자(24,920건, 심볼이 새는 문서만)보다 더 큼: 심볼 누출은 없지만 "[부서]"만 있던
# 문서도 라벨 통일 대상이라서).
#
# **알려진 한계**: 컨텍스트 샘플 중 "♭♡♥♧정리"처럼 42종 밖의 미확인 심볼(♭ 등)이 섞인
# 마스킹 자리는 그 글자만 남고 나머지만 치환됨 — 42종은 3차에 걸친 규모조사로 확정된
# 것만 다루고, 미발견 심볼은 이후 라운드 과제로 남김(이 프로젝트 관례상 100%를 한 번에
# 해결하려 하지 않음 — 안전하게 확인된 것부터).
#
# **실행 순서**:
#   1) DRY_RUN=True로 먼저 — 영향 문서 수/치환 샘플(before/after) 확인.
#   2) 이상 없으면 DRY_RUN=False로 재실행 — batch UPDATE + 영향받은 문서 ID를
#      JSONL로 저장(rechunk_reembed_dept_anon_symbol_fix.py가 이어서 읽음).
#   3) 재청킹+재임베딩은 이 스크립트 범위 밖 —
#      rechunk_reembed_dept_anon_symbol_fix.py로 이어서 진행(GPU 필요, 대상이 약
#      24,920건+로 과거 재임베딩(5,436건)보다 훨씬 커서 시간이 오래 걸림 — 체크포인트
#      지원되니 끊겨도 이어서 하면 됨, 별도 세션/시간 잡고 진행 권장).
# ------------------------------------------------------------------

# !pip install -q psycopg2-binary

import json
import os
import re

import psycopg2
from psycopg2.extras import execute_values

DRY_RUN = True  # 먼저 True로 돌려서 확인, 이상 없으면 False로

AFFECTED_IDS_OUT_PATH = "/content/drive/MyDrive/audit_project/dept_anon_fix_affected_ids.jsonl"
BACKUP_OUT_PATH = "/content/drive/MyDrive/audit_project/dept_anon_fix_backup_raw_text.jsonl"

# 2026-08-27 DRY_RUN 1차 실행 후 발견한 버그 수정: 아래 6종(▢■▶●★☆)을 애초
# "마스킹 전용"으로 분류했었는데, 실제 DRY_RUN 샘플에서 "▢ 인적사항"(불릿+소제목,
# 마스킹 아님)이 "[비공개] 인적사항"으로 망가지는 걸 확인함. ▢/■는 한국 공문서에서
# 소제목 불릿로도 흔히 쓰임(2차 조사 샘플에도 "■ 주요 지적사항 요약" 존재, 당시엔
# 놓쳤음) — ▶●★☆도 같은 관례로 흔히 쓰이는 불릿/강조 기호라 같은 위험으로 보고
# 선제적으로 옮김(이 4종은 이번 코퍼스에서 불릿으로 쓰인 샘플이 직접 잡히진 않았지만,
# 확신이 없는 채로 "단독 1개=마스킹" 취급하면 위험이 너무 큼 — 안전한 쪽으로 판단).
# 이 6종은 기존 8종과 같은 취급(2개 이상 연속일 때만 마스킹)으로 내려서, 짧은(1글자)
# 마스킹은 못 잡더라도 불릿 파괴를 막음. ▢/■의 실제 짧은 마스킹 사례("김▢▢", "■팀")는
# 이미 2개 이상 연속이라 이 완화로도 여전히 잡힘 — 못 잡는 건 "이 6종이 1글자만
# 마스킹한 극소수 사례" 뿐(발생 시 다음 라운드 과제로 남김).
#
# 확정된 마스킹 전용 문자 36종(1차+2차 규모조사, 컨텍스트 전수 확인 — 정상 용도 없음
# 확정됨, 위 6종 제외). 단독 1개만 나와도 항상 마스킹으로 간주(반복 조건 없음). "+"라
# 서로 다른 문자가 섞여 연속되는 경우("♭" 같은 미확인 문자가 안 섞인 구간에 한해)도
# 한 번에 처리.
MASK_ONLY_CHARS = "♣♧▩▧♥♠⊗♡♤◉▤◐◁▷◍▥▨◎◈◒▣◌◧◊▒◕◫◑◩◷◨◰⊠◪◘▦"
# 기존 8종(○□△▲▽▼◇◆, reextract_pdf_text.py 원래 설계 — 정상 불릿과 겸용이라 "2개
# 이상 연속"일 때만 마스킹으로 판단) + 위에서 옮긴 6종(▢■▶●★☆) = 14종.
AMBIGUOUS_DUAL_USE_CHARS = "○□△▲▽▼◇◆▢■▶●★☆"

PLACEHOLDER = "[비공개]"

_MASK_ONLY_RE = re.compile("[" + re.escape(MASK_ONLY_CHARS) + "]+")
_AMBIGUOUS_RUN_RE = re.compile("([" + re.escape(AMBIGUOUS_DUAL_USE_CHARS) + "])\\1+")
_OLD_PLACEHOLDER_RE = re.compile(re.escape("[부서]"))
# 2026-08-27 DRY_RUN 2차 실행 후 발견: 이미 "[부서]"로 라벨된 자리 바로 옆에 공백 없이
# 또 다른 마스킹 자리가 붙어있는 경우(예: "[부서]◉◉◉"), 위 세 치환을 각각 거치면
# "[비공개][비공개]"처럼 구분 없이 붙어버림 — 틀린 내용은 아니지만(둘 다 실제로 가려진
# 자리) 읽기 불편해서, 바로 붙어 나오는 placeholder 반복은 하나로 합침.
_REPEATED_PLACEHOLDER_RE = re.compile(f"(?:{re.escape(PLACEHOLDER)})+")


def normalize_masked_glyphs(text: str) -> str:
    """규모조사로 확정된 마스킹 문자를 통일된 [비공개] 토큰으로 치환.
    기존 [부서] 토큰도 같이 통일함(라벨 자체가 부정확했던 문제 대응, STATUS.md 9차)."""
    if not text:
        return text
    text = _MASK_ONLY_RE.sub(PLACEHOLDER, text)
    text = _AMBIGUOUS_RUN_RE.sub(PLACEHOLDER, text)
    text = _OLD_PLACEHOLDER_RE.sub(PLACEHOLDER, text)
    text = _REPEATED_PLACEHOLDER_RE.sub(PLACEHOLDER, text)
    return text


# 2026-08-27 실행 중 발견한 버그 수정: DATABASE_PUBLIC_URL 시크릿이 아예 없으면
# userdata.get()이 None을 주는 게 아니라 SecretNotFoundError를 던져서, `or` 뒤의
# DATABASE_URL 조회까지 통째로 못 가고 실패했음(이 계정엔 DATABASE_URL 시크릿만 있고
# DATABASE_PUBLIC_URL은 없음). audit_dept_anon_symbol_leak_scope.py(1~3차)에서 원래
# 잘 동작하던 방식으로 되돌림 — DATABASE_URL 하나만 조회.
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    try:
        from google.colab import userdata

        DATABASE_URL = userdata.get("DATABASE_URL")
    except Exception:
        pass

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '300s'")
    cur.execute("SELECT id, raw_text FROM documents")
    rows = cur.fetchall()
conn.close()

print(f"전체 문서 {len(rows)}건 처리 중...")

to_update = []  # (doc_id, old_text, new_text) — old_text는 백업/샘플 출력용
sample_diffs = []
for doc_id, raw_text in rows:
    if not raw_text:
        continue
    new_text = normalize_masked_glyphs(raw_text)
    if new_text != raw_text:
        to_update.append((doc_id, raw_text, new_text))
        if len(sample_diffs) < 10:
            sample_diffs.append((doc_id, raw_text, new_text))

print(f"\n영향받는 문서: {len(to_update)}건 / {len(rows)}건")
print("(참고: 3차 규모조사 24,920건은 '심볼이 새는' 문서만 — 여기엔 심볼 누출 없이")
print(" 라벨만 [부서]->[비공개]로 바뀌는 문서도 포함돼서 더 큰 숫자가 정상)")

print("\n치환 샘플(최대 10건, 첫 변경 지점 앞뒤):")
for doc_id, old_text, new_text in sample_diffs:
    i = 0
    while i < min(len(old_text), len(new_text)) and old_text[i] == new_text[i]:
        i += 1
    start = max(0, i - 30)
    print(f"  [{doc_id}]")
    print(f"    이전: ...{old_text[start:i + 60]!r}...")
    print(f"    이후: ...{new_text[start:i + 60]!r}...")

if DRY_RUN:
    raise SystemExit(
        "\nDRY_RUN=True라 여기서 멈춤(DB 변경 없음). "
        f"위 결과(영향 {len(to_update)}건)와 치환 샘플이 말이 되면 "
        "DRY_RUN=False로 바꿔서 다시 실행하세요."
    )

# 반영 전 백업 — 이 변환은 원본을 남겨두지 않으면 되돌릴 방법이 없음(재추출 파이프라인을
# 다시 돌리는 것 말고는 옛 raw_text를 복구할 길이 없음). id별 옛 raw_text를 그대로
# 저장해서, 나중에 이번 판단(예: 위에서 옮긴 6종 말고 또 다른 불릿 오탐)이 틀렸다고
# 밝혀지면 이 파일로 원상복구할 수 있게 함.
os.makedirs(os.path.dirname(BACKUP_OUT_PATH), exist_ok=True)
with open(BACKUP_OUT_PATH, "w", encoding="utf-8") as f:
    for doc_id, old_text, _ in to_update:
        f.write(json.dumps({"id": doc_id, "raw_text": old_text}) + "\n")
print(f"\n반영 전 원본 raw_text {len(to_update)}건을 {BACKUP_OUT_PATH}에 백업함")

conn = psycopg2.connect(DATABASE_URL)
try:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '120s'")
        batch_size = 500
        update_pairs = [(doc_id, new_text) for doc_id, _, new_text in to_update]
        for i in range(0, len(update_pairs), batch_size):
            batch = update_pairs[i:i + batch_size]
            execute_values(
                cur,
                "UPDATE documents SET raw_text = data.new_text "
                "FROM (VALUES %s) AS data(id, new_text) "
                "WHERE documents.id = data.id",
                batch,
            )
            conn.commit()
            print(f"  DB 반영: {min(i + batch_size, len(update_pairs))}/{len(update_pairs)}")
finally:
    conn.close()

os.makedirs(os.path.dirname(AFFECTED_IDS_OUT_PATH), exist_ok=True)
with open(AFFECTED_IDS_OUT_PATH, "w", encoding="utf-8") as f:
    for doc_id, _, _ in to_update:
        f.write(json.dumps({"id": doc_id}) + "\n")
print(f"\n영향받은 문서 ID {len(to_update)}건을 {AFFECTED_IDS_OUT_PATH}에 저장함")
print("완료 — 다음 단계: rechunk_reembed_dept_anon_symbol_fix.py로 재청킹+재임베딩 진행")
print("(상세페이지/기관 프로필은 raw_text를 직접 쓰니 이 스크립트만으로 바로 반영됨.")
print(" 검색결과 카드 미리보기(preview_buffer)와 검색 랭킹은 chunks 테이블 기준이라")
print(" 재청킹+재임베딩 전까지는 옛 텍스트로 남아있음 — 정상, 순차 반영 과정)")
