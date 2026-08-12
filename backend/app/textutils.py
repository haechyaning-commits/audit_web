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

_SENT_END = re.compile(r"[.!?]")
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
