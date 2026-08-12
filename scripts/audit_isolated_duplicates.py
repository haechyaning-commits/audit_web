# ------------------------------------------------------------------
# 단독 한글 글자 중복 실태 조사 (2026-08-12, 읽기 전용 — DB에 아무것도 안 씀)
# ------------------------------------------------------------------
# fix_text_corruption.py의 CHAIN_RE는 "연쇄 2회 이상"(예: "제제목목")만 잡고,
# "목목"처럼 단독으로만 중복된 건 안 건드림 — "각각"/"종종" 같은 정상적으로
# 반복되는 한국어 단어와 진짜 corruption(bold_dup 렌더링 버그)을 정규식만으로
# 구분할 수 없기 때문. 그래서 DB에 반영하기 전에, 실제로 어떤 패턴들이 이 조건에
# 걸리는지 전수 조사해서 사람이 눈으로 "이건 진짜 오류 / 이건 정상 단어"를
# 분류할 수 있게 목록을 뽑는 스크립트. 아무것도 수정 안 함(읽기 전용).
# ------------------------------------------------------------------
import os
import re
from collections import Counter

import psycopg2

ISOLATED_DUP_RE = re.compile(r"([가-힣])\1")


def find_isolated_dups(text: str) -> set[str]:
    """CHAIN_RE가 이미 처리한 '연쇄 2회 이상' 케이스는 애초에 DB text에서
    사라졌으므로 여기서 찾히는 건 전부 단독 중복(연쇄 아님)."""
    return {m.group(0) for m in ISOLATED_DUP_RE.finditer(text)}


DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from google.colab import userdata

    DATABASE_URL = userdata.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
word_counter = Counter()
doc_ids_by_word: dict[str, list[str]] = {}
doc_count_with_dup = 0

with conn.cursor() as cur:
    cur.execute("SET statement_timeout = '180s'")
    cur.execute("SELECT id, raw_text FROM documents")
    rows = cur.fetchall()
conn.close()

print(f"전체 문서 {len(rows)}건 조사 중...")
for doc_id, text in rows:
    dups = find_isolated_dups(text)
    if dups:
        doc_count_with_dup += 1
        word_counter.update(dups)
        for w in dups:
            doc_ids_by_word.setdefault(w, [])
            if len(doc_ids_by_word[w]) < 2:  # 샘플 문서 id 최대 2개만 보관(확인용)
                doc_ids_by_word[w].append(doc_id)

print(f"\n단독 중복이 하나라도 있는 문서: {doc_count_with_dup}건 / 전체 {len(rows)}건")
print(f"고유 중복 패턴 종류: {len(word_counter)}개\n")
print("빈도순 전체 목록 (단어: 등장 횟수 | 샘플 document_id):")
for word, cnt in word_counter.most_common(500):
    sample = ", ".join(doc_ids_by_word[word])
    print(f"  {word}: {cnt}  |  {sample}")
