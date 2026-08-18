# ------------------------------------------------------------------
# 규모 조사 — "1. 제목:" 번호 유실 + 단어 중간 줄바꿈 (Colab 실행용, 읽기 전용)
# ------------------------------------------------------------------
# 배경: PDF 2단 레이아웃 작업(rechunk_reembed_pdf_column_fix*.py) 검증 중 발견한
# 별개의 두 데이터 문제 — 어느 정도 규모인지 먼저 파악하기 위한 조사 스크립트.
# DB에 아무것도 쓰지 않음.
#
# 1) "1. 제목:" 번호 유실 — 한국보훈복지의료공단 2022(01ff5cfbb6fafddd) 실제 확인:
#    원본 PDF는 "1. 제 목 : 채용절차 운영 부적정" / "2. 관계기관 : ..."인데, DB
#    raw_text는 "제 목 : 채용절차 운영 부적정" / "2. 관계기관 : ..."로 제목 줄
#    앞의 "1. "만 사라짐(extract_title() 등 이 저장소 코드가 지운 게 아니라 원본
#    데이터 적재 시점부터 이렇게 저장돼 있었음 — 코드로 확인함).
#    탐지 방법: raw_text 앞부분에 "제목:" 줄이 있는데 그 줄 자체에는 번호가 없고,
#    바로 이어지는 다른 줄에는 "2. " 같은 번호가 있는 경우 — 즉 번호가 2부터
#    시작하는 문서.
#
# 2) 단어 중간 줄바꿈 — DetailPage.jsx의 splitIntoBlocks()가 문단 안 줄들을 공백으로
#    이어붙이는데, PDF가 원래 단어 중간에서 줄을 끊은 경우(예: "복귀하였음에"/"도")
#    이어붙이면 "복귀하였음에 도"처럼 단어 안에 공백이 생김. 코퍼스 전체 조사는
#    어려워서(형태소 분석 없이는 완벽 판별 불가), 근사 휴리스틱만 씀: 어떤 줄
#    다음에 오는 줄이 흔한 조사/어미 1~2글자로만 시작하고 그 뒤에 공백이 오는
#    경우(그 조사/어미가 문장 맨 앞에 홀로 오는 건 부자연스러움 — 대부분 앞줄
#    단어의 연속일 가능성이 높음). 오탐/누락 둘 다 있을 수 있는 "대략적인 규모
#    감"용 지표로만 쓸 것.
# ------------------------------------------------------------------

import os
import re
from collections import Counter

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

TITLE_LINE_RE = re.compile(r"^[\[【]?제\s*목\s*[\]】]?\s*[:：]?\s*\S")
NUMBERED_LINE_RE = re.compile(r"^(\d{1,2})[.)]\s+\S")

# 흔한 조사/어미(홀로 줄 맨 앞에 나오면 부자연스러운 것들) — highlight.jsx의
# STOPWORDS와 비슷한 취지지만 목적이 달라서(여기는 "줄 맨 앞 단독 등장 탐지") 별도로 씀
SUSPICIOUS_LEADING_PARTICLES = [
    "도", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과",
    "만", "나", "다", "고", "며", "서", "니", "면", "야", "요",
]
_particle_re = re.compile(
    "^(" + "|".join(SUSPICIOUS_LEADING_PARTICLES) + r")(\s|$)"
)


def scan():
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '300s'")
        cur.execute("SELECT id, institution, year, raw_text FROM documents")
        rows = cur.fetchall()
    conn.close()
    print(f"전체 문서: {len(rows)}건 조사 시작\n")

    # ---- 1) "1. 제목:" 번호 유실 ----
    missing_number_docs = []
    for doc_id, institution, year, raw_text in rows:
        if not raw_text:
            continue
        lines = raw_text.split("\n")
        for i, line in enumerate(lines[:5]):  # 문서 앞부분만 봄(제목은 보통 최상단)
            trimmed = line.strip()
            if not trimmed:
                continue
            if TITLE_LINE_RE.match(trimmed) and not NUMBERED_LINE_RE.match(trimmed):
                # 제목 줄에 번호가 없음 — 바로 다음 비어있지 않은 줄이 "2." 이상으로
                # 시작하면 번호가 유실된 것으로 의심
                for j in range(i + 1, min(i + 3, len(lines))):
                    nxt = lines[j].strip()
                    if not nxt:
                        continue
                    m = NUMBERED_LINE_RE.match(nxt)
                    if m and int(m.group(1)) >= 2:
                        missing_number_docs.append((doc_id, institution, year, trimmed[:40], nxt[:40]))
                    break
            break  # 제목 후보 줄 하나만 확인(대부분 첫 줄)

    print(f"--- 1) '1. 제목:' 번호 유실 의심 ---")
    print(f"{len(missing_number_docs)}건 / 전체 {len(rows)}건 ({len(missing_number_docs)/len(rows)*100:.2f}%)")
    inst_counter = Counter(d[1] for d in missing_number_docs)
    print("기관별 상위 10:")
    for inst, cnt in inst_counter.most_common(10):
        print(f"  {cnt:4d}건 | {inst}")
    print("샘플 5건:")
    for doc_id, institution, year, title_line, next_line in missing_number_docs[:5]:
        print(f"  {doc_id} | {institution} {year} | {title_line!r} -> {next_line!r}")

    # ---- 2) 단어 중간 줄바꿈 의심 ----
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
            # 직전 줄이 문장부호로 안 끝나야(끝났으면 새 문장 시작일 수 있어 정상일
            # 가능성이 높음) 의심으로 카운트 — 완벽친 않지만 오탐을 어느 정도 줄임
            if prev_line and not re.search(r"[.!?。:：)\]】」』]$", prev_line):
                doc_hits += 1
                if len(wordbreak_samples) < 8:
                    wordbreak_samples.append((doc_id, institution, prev_line[-25:], cur_line[:25]))
        if doc_hits:
            wordbreak_doc_ids.add(doc_id)
            wordbreak_total_hits += doc_hits

    print(f"\n--- 2) 단어 중간 줄바꿈 의심(근사 휴리스틱 — 오탐/누락 있을 수 있음) ---")
    print(f"의심 문서 수: {len(wordbreak_doc_ids)}건 / 전체 {len(rows)}건 "
          f"({len(wordbreak_doc_ids)/len(rows)*100:.2f}%)")
    print(f"의심 지점 총합: {wordbreak_total_hits}건 (문서당 평균 "
          f"{wordbreak_total_hits/max(1,len(wordbreak_doc_ids)):.1f}건)")
    print("샘플 8건 (직전 줄 끝 25자 -> 의심 줄 앞 25자):")
    for doc_id, institution, prev_tail, cur_head in wordbreak_samples:
        print(f"  {doc_id} | {institution} | ...{prev_tail!r} -> {cur_head!r}...")


scan()
