# ------------------------------------------------------------------
# 규모 재조사 — 단어 중간 줄바꿈, "확정 조사"만으로 좁힘 (Colab 실행용, 읽기 전용)
# ------------------------------------------------------------------
# 배경: audit_title_number_and_wordbreak.py의 1차 조사(SUSPICIOUS_LEADING_PARTICLES
# 17개, 23.88%/16,182건)를 실제 샘플로 까보니, "만"/"도"/"은"/"는" 등은 조사로도 쓰이지만
# "만 나이"(국제 나이 표기)처럼 독립된 단어·새 구문 시작으로도 흔히 쓰여서, 공백을
# 자동으로 지우면 오히려 원래 맞던 공백(나열 콤마 뒤 등)까지 잘못 지우는 사례가 실제
# 샘플로 확인됨(2026-08-24, 사용자 제보 — "등"+"만 70세와 만 60세를 혼용" 등).
#
# 그래서 "명사 뒤에만 붙고, 그 자체로 독립된 단어로 문장/구를 새로 시작하는 일이
# 사실상 없는" 조사만 남김: 을/를(목적격)/의(관형격)/에(처격)/로(도구·방향격)/
# 와/과(접속격). "도/만/은/는/이/가/나/다/고/며/서/니/면/야/요"는 전부 독립 단어·구
# 시작으로도 실제 쓰이는 걸 확인해서 제외 — 이 좁힌 집합에 대해서만 규모를 다시
# 재봐서, 이 정도로 좁혀도 여전히 손볼 가치가 있는 규모인지 판단하는 게 목적.
# DB에 아무것도 쓰지 않음(1차 스크립트와 동일하게 읽기 전용).
# ------------------------------------------------------------------

import os
import re

import psycopg2

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

# 2026-08-24: 1차 조사(SUSPICIOUS_LEADING_PARTICLES, 17개)에서 아래로 좁힘 —
# 독립 단어/새 구문 시작으로 흔히 쓰이는 "도/만/은/는/이/가/나/다/고/며/서/니/면/야/요"
# 는 전부 제외. 이 7개는 명사 뒤에 붙는 조사 용법 외에 독립된 단어로 줄을 시작하는
# 경우가 사실상 없음(문어체 감사보고서 기준 — "와!" 같은 감탄사 용법은 이 말뭉치
# 특성상 실질적으로 없다고 봐도 무방).
SAFE_LEADING_PARTICLES = ["을", "를", "의", "에", "로", "와", "과"]
_particle_re = re.compile(
    "^(" + "|".join(SAFE_LEADING_PARTICLES) + r")(\s|$)"
)


def scan():
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '300s'")
        cur.execute("SELECT id, institution, year, raw_text FROM documents")
        rows = cur.fetchall()
    conn.close()
    print(f"전체 문서: {len(rows)}건 조사 시작 (좁힌 조사 7개: {', '.join(SAFE_LEADING_PARTICLES)})\n")

    wordbreak_doc_ids = set()
    wordbreak_total_hits = 0
    wordbreak_samples = []
    for doc_id, institution, year, raw_text in rows:
        if not raw_text:
            continue
        lines = raw_text.split("\n")
        doc_hits = 0
        for i in range(1, len(lines)):
            cur_line = lines[i].strip()
            if not cur_line:
                continue
            m = _particle_re.match(cur_line)
            if not m:
                continue
            prev_line = lines[i - 1].strip()
            # 1차와 동일한 안전장치: 직전 줄이 문장부호(마침표류)로 안 끝나야 카운트.
            # 콤마(",")는 나열 목록일 가능성이 있어 여전히 포함(1차와 동일 기준 유지 —
            # 이번엔 조사 자체를 좁혔으니 이 기준은 그대로 둬도 비교가 공정함).
            if prev_line and not re.search(r"[.!?。:：)\]】」』]$", prev_line):
                doc_hits += 1
                if len(wordbreak_samples) < 15:
                    wordbreak_samples.append((doc_id, institution, prev_line[-25:], cur_line[:25]))
        if doc_hits:
            wordbreak_doc_ids.add(doc_id)
            wordbreak_total_hits += doc_hits

    print(f"의심 문서 수: {len(wordbreak_doc_ids)}건 / 전체 {len(rows)}건 "
          f"({len(wordbreak_doc_ids)/len(rows)*100:.2f}%)")
    print(f"의심 지점 총합: {wordbreak_total_hits}건 (문서당 평균 "
          f"{wordbreak_total_hits/max(1,len(wordbreak_doc_ids)):.1f}건)")
    print("\n샘플 15건 (직전 줄 끝 25자 -> 의심 줄 앞 25자) — 눈으로 훑어서")
    print("실제로 '조사로 붙어야 맞는지' 오탐(독립 단어/나열 등)이 있는지 확인 요망:")
    for doc_id, institution, prev_tail, cur_head in wordbreak_samples:
        print(f"  {doc_id} | {institution} | ...{prev_tail!r} -> {cur_head!r}...")


scan()
