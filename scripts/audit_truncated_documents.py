# ------------------------------------------------------------------
# 원문 잘림(truncation) 실태 조사 — 2차 수정본 (2026-08-13, 읽기 전용 — DB에 아무것도 안 씀)
# ------------------------------------------------------------------
# 상세페이지에서 "① 지적사항 관련... 상기 사례 및"처럼 문장 중간에서 뚝 끊긴
# 원문이 발견됨(예: 1ca9faabf1df243f) — 같은 양식의 유사 문서(dd4748d57bc77db8 등)와
# 비교해보니 원본 PDF/HWP 추출 단계(이 레포 밖, Colab 파이프라인)에서 이 문서만
# 잘린 것으로 확인됨. 전체 규모를 파악하기 위한 전수 조사 스크립트.
#
# 판정 방식(완벽하지 않은 휴리스틱): raw_text의 마지막 줄이 문장부호/닫는 기호로
# 안 끝나고 조사/어미/접속사로 끝나면 "잘림 의심"으로 분류.
#
# 2026-08-13 2차 수정: 1차 버전을 샘플(검색 API로 모은 1,198건)에 돌려보니 "주의"/
# "통보"처럼 표(연번/지적사항/처분류)의 "처분" 칸 값 자체가 정상적으로 조사로 끝나는
# 경우(예: "...행정상 주의", "니다 주의")가 대거 오탐으로 잡힘 — 표 컬럼 뒤섞임 스캔
# 때와 같은 종류의 실수. 실제 처분 문서에 쓰이는 종결 키워드로 끝나면 오탐으로 보고
# 제외하도록 DISPOSITION_END_WORDS를 추가. 또한 "주 의"처럼 글자 사이에 공백이 낀
# 경우(bold_dup류 렌더링 오염과 유사)도 있어서, 공백을 다 지운 뒤에 비교함.
# 사람이 눈으로 최종 확인하는 걸 전제로 함. 아무것도 수정 안 함(읽기 전용).
# ------------------------------------------------------------------
import os
import re
from collections import Counter

import psycopg2

# 문장이 정상적으로 끝났다고 볼 수 있는 마지막 글자(마침표/느낌표/물음표/닫는 인용부호/
# 닫는 괄호 등)
END_OK_RE = re.compile(r'[.!?。」』"\')\]】>]\s*$')

# 잘렸을 가능성이 높은 마지막 글자(조사/어미/접속사로 문장이 끝나면 부자연스러움)
SUSPICIOUS_END_RE = re.compile(
    r"(및|에|은|는|이|가|을|를|로|와|과|의|하고|하며|또는|그리고)\s*$"
)

# 감사결과 처분서류 표의 "처분" 칸에 실제로 쓰이는 종결 키워드 — 문장이 아니라
# 표 항목 값 자체라서 조사/어미로 끝나는 게 정상. 이 단어들로 끝나면 잘림이 아니라
# 정상 종결로 보고 제외(오탐 방지, filter_results.py에서 실제 오탐 샘플로 확인한 목록).
DISPOSITION_END_WORDS = [
    "주의", "경고", "시정", "견책", "해임", "파면", "강등", "정직",
    "감봉", "훈계", "통보", "권고", "불가", "효과", "개선", "증가",
    "결과", "협의", "건의", "완료",
]


def looks_truncated(raw_text: str) -> bool:
    tail = raw_text.rstrip()
    if not tail:
        return False
    last_line = tail.split("\n")[-1].strip()
    if not last_line:
        return False
    if not SUSPICIOUS_END_RE.search(last_line) or END_OK_RE.search(last_line):
        return False
    # "주 의"처럼 글자 사이 공백이 낀 경우까지 잡기 위해 공백 다 지우고 비교
    no_space = re.sub(r"\s+", "", last_line)
    if any(no_space.endswith(w) for w in DISPOSITION_END_WORDS):
        return False
    return True


DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute("SELECT id, institution, year, audit_type, raw_text FROM documents")
    rows = cur.fetchall()
conn.close()

print(f"전체 문서 {len(rows)}건 조사 중...")

candidates = []
for doc_id, institution, year, audit_type, raw_text in rows:
    if looks_truncated(raw_text):
        tail = raw_text.rstrip().split("\n")[-1].strip()[-50:]
        candidates.append((doc_id, institution, year, audit_type, tail))

print(f"\n잘림 의심 문서: {len(candidates)}건 / 전체 {len(rows)}건 "
      f"({len(candidates) / len(rows) * 100:.2f}%)\n")

# 기관 x 연도별로 몰려있는지 확인(파이프라인 배치 단위로 문제가 생겼을 가능성 확인용)
group_counter = Counter((inst, yr) for _, inst, yr, _, _ in candidates)
print("기관/연도별 분포 (2건 이상만):")
for (inst, yr), cnt in group_counter.most_common():
    if cnt >= 2:
        print(f"  {inst} {yr}: {cnt}건")

print("\n전체 목록 (document_id | 기관 | 연도 | 감사종류 | 마지막 50자):")
for doc_id, institution, year, audit_type, tail in candidates:
    print(f"  {doc_id} | {institution} | {year} | {audit_type} | ...{tail!r}")
