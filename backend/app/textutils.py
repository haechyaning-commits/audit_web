"""검색 카드 미리보기 텍스트를 문장/어절 경계에 맞춰 자르는 유틸.

기존엔 SQL에서 그냥 left(text, 200)으로 정확히 200번째 글자에서 뚝 잘랐음 — 문장 중간에서
끊기고 "…" 표시도 없어서 "텍스트가 짤린다"는 피드백(2026-08-12)의 원인이었음.

repository.py가 넉넉히(320자) 가져온 buffer를 받아서:
1) 머리 — 매치된 청크는 원문 중간에서 시작하는 경우가 많아, 첫 문장부호 앞부분은 이전
   문장이 잘려 들어온 조각일 가능성이 높음. 그 조각은 건너뛰고 "…"를 앞에 붙임.
2) 꼬리 — 목표 길이 근처에서 문장부호를 우선으로, 없으면 공백(어절 경계)에서 자르고
   "…"를 뒤에 붙임.
"""
import re

# 문서 맨 앞 "제목"/"제 목" 라벨 줄에서 실제 제목만 뽑음(URL 슬러그/카드 표시용).
# scripts/fix_text_corruption.py의 normalize_title_colon()이 이미 이 라벨 뒤에 콜론을
# 통일해뒀지만(2026-08-12 재임베딩분), 콜론이 없는 옛 표기("제목 XXX")도 그대로 매칭되게
# 콜론은 optional로 둠 — 재임베딩 전 문서와도 호환.
#
# "목" 다음에 실제 구분자(콜론 또는 공백)가 있는지를 반드시 확인해야 함 — 처음 버전은
# "제\s*목\s*[:：]?\s*"가 전부 0개 이상이라 구분자가 아예 없어도 통과돼서, "[제 목] X"에서
# 여는 대괄호가 원문 추출 단계에서 빠져 "제 목] X"로 시작하는 문서(실사용 중 발견,
# 2026-08-13)에서 "]"까지 제목으로 캡처하는 버그가 있었음("] X"가 그대로 탭 타이틀에
# 노출됨). "(?:[:：]\s*|\s+)"로 콜론 또는 공백 중 하나는 반드시 있어야 매칭되게 해서,
# 구분자 없이 다른 문자(대괄호 등)가 바로 붙은 경우는 아예 매칭 실패 -> None 처리.
_TITLE_LINE_RE = re.compile(r"^\s*제\s*목(?:\s*[:：]\s*|\s+)(.+?)\s*$")


def extract_title(raw_text: str | None) -> str | None:
    """raw_text 첫 줄에서 문서 제목을 뽑음. 라벨이 없거나(포맷이 다른 소수 문서) 라벨
    뒤에 내용이 없으면 None — 호출부(프론트 URL 슬러그, 카드 표시)가 document_id 등으로
    폴백하면 됨."""
    if not raw_text:
        return None
    first_line = raw_text.split("\n", 1)[0]
    m = _TITLE_LINE_RE.match(first_line)
    if not m:
        return None
    title = m.group(1).strip()
    return title or None


# 숫자 바로 뒤의 마침표는 제외 — "2024.", "제148조.", "1." 같은 날짜/조항/목차 번호가
# 실측(2026-08-12)에서 진짜 문장 끝으로 오인되는 경우가 많았음(목차·법조문 인용이 잦은
# 감사보고서 특성상). 한국어 문장은 보통 한글 뒤에 마침표가 오므로 이 조건으로 대부분 걸러짐.
_SENT_END = re.compile(r"(?<!\d)[.!?]")
_HEAD_SCAN_WINDOW = 80  # 이 안에서 첫 문장부호를 찾아 앞쪽 조각을 건너뜀
_TAIL_SCAN_WINDOW = 60  # 목표 길이 뒤쪽 이 폭 안에서 자를 지점을 찾음


def build_preview(buffer: str, target_len: int = 200) -> str:
    if not buffer:
        return buffer

    # 1) 머리 — 첫 문장부호 앞은 이전 문장의 잘린 꼬리일 가능성이 높음
    head_start = 0
    had_lead_cut = False
    m = _SENT_END.search(buffer[:_HEAD_SCAN_WINDOW])
    if m and m.end() < len(buffer):
        head_start = m.end()
        while head_start < len(buffer) and buffer[head_start].isspace():
            head_start += 1
        had_lead_cut = head_start > 0

    body = buffer[head_start:]
    prefix = "…" if had_lead_cut else ""

    if len(body) <= target_len:
        return prefix + body.rstrip()

    # 2) 꼬리 — target_len 근처에서 문장부호 우선, 없으면 공백(어절 경계)
    window_start = max(0, target_len - _TAIL_SCAN_WINDOW)
    window = body[window_start : target_len + _TAIL_SCAN_WINDOW]

    cut = None
    for hit in _SENT_END.finditer(window):
        cut = window_start + hit.end()  # 윈도우 안 마지막 문장부호를 씀

    if cut is None:
        sp = body.find(" ", target_len)
        if sp != -1 and sp < target_len + _TAIL_SCAN_WINDOW:
            cut = sp

    if cut is None:
        cut = target_len  # 자연스러운 경계가 전혀 없으면 예전처럼 목표 길이에서 자름

    return prefix + body[:cut].rstrip() + "…"
