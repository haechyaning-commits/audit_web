"""
온디맨드 4줄 요약 생성 (architecture.md §4.5, §4.6).

프롬프트/모델은 `scripts/summary_smoke_test.py`에서 35건 실측 검증된 것을 그대로 재사용
(건당 평균 1.77초/$0.0002, standard 등급 미기재 사용 0% 확인됨 — STATUS.md 5차).
상세 API가 문서 조회 시 summary_point가 비어있으면 여기를 호출하고, 결과를
repository.save_summary()로 캐싱해서 다음부터는 재호출 안 함.
"""
import re

import openai

MODEL = "gpt-4o-mini"  # 참고치 가격: $0.15/1M input, $0.60/1M output — 실행 전 재확인 권장

PROMPT_TEMPLATE = """아래 감사 사례 원문을 읽고 정확히 4줄로 요약해라.
1줄: 지적사항 한 문장 (원문에 관련 내용이 전혀 없을 때만 "지적사항 불분명"으로 표시)
2줄: 원인/경위 한 문장 (원문에 관련 내용이 전혀 없을 때만 "원인 미기재"로 표시)
3줄: 조치사항 한 문장 (원문에 관련 내용이 전혀 없을 때만 "조치사항 미기재"로 표시)
4줄: 처리결과 한 문장 (원문에 관련 내용이 전혀 없을 때만 "처리결과 미기재"로 표시)
원문:
{raw_text}"""

FALLBACK_PHRASES = ["지적사항 불분명", "원인 미기재", "조치사항 미기재", "처리결과 미기재"]

# 자유형 요약(문장형) — 지적사항/원인/조치/결과 틀에 안 맞추고, 원문 전체에서 중요하다고
# 판단되는 내용을 자유롭게 뽑아냄. 프론트 상세페이지에 구조화된 박스 요약과 나란히(그
# 아래에) 보여주기 위한 용도 — 완전히 별도의 프롬프트+API 호출.
# 2026-08-12: "정확히 4줄"을 강제하지 않도록 완화 — 4줄 형식을 못 맞추면(모델이 3줄이나
# 5줄, 또는 줄바꿈 없는 한 문단으로 답하는 경우가 꽤 있었음) 무조건 실패로 캐싱돼서
# summary_freeform이 계속 안 보이는 문제가 있었음. 이제는 줄 수 상관없이 핵심만 짧게
# 담으면 되고, 파싱도 "4줄인지"를 안 따짐(_call_once_freeform 참고).
FREEFORM_PROMPT_TEMPLATE = """아래 감사 사례 원문을 읽고, 항목 구분 없이 가장 핵심적인 내용만
간단히 요약해라. 정해진 줄 수는 없다 — 짧고 자연스러운 문장 2~4개 정도로, 지적사항/원인/조치/
결과 같은 틀에 얽매이지 말고 전체 맥락에서 중요한 내용만 자연스럽게 이어지도록 써라.
원문에 요약할 만한 내용이 전혀 없을 때만 "요약할 내용 없음"이라고만 답해라.
원문:
{raw_text}"""

FREEFORM_FALLBACK_PHRASE = "요약할 내용 없음"

# 2026-08-26(실제 브라우저 렌더링으로 발견): PROMPT_TEMPLATE이 모델에게 "1줄: ...", "2줄:
# ..." 형식으로 답하라고 시키는데, 모델이 그 "N줄: " 라벨까지 그대로 출력에 포함시켜서
# summary_point 등에 "1줄: 부적정한 출장비 정산으로..."처럼 저장되고 있었음. 상세페이지는
# 이미 "① 지적사항" 같은 자체 라벨을 헤더로 보여주고 있어서, 화면에 "① 지적사항 / 1줄:
# 부적정한..."처럼 라벨이 중복으로 겹쳐 보이는 문제였음(FALLBACK_PHRASES 판별은 부분
# 문자열 매칭이라 이 프리픽스가 있어도 원래 정상 동작했음 — 그 로직은 안 건드림).
_LINE_PREFIX_RE = re.compile(r"^\d\s*줄\s*[:：]\s*")


def _strip_line_prefix(line: str) -> str:
    return _LINE_PREFIX_RE.sub("", line.strip(), count=1)


_client: openai.AsyncOpenAI | None = None


def _get_client() -> openai.AsyncOpenAI:
    global _client
    if _client is None:
        # AsyncOpenAI 사용 이유: 네트워크 I/O(API 호출 대기)는 스레드로 우회할 필요 없이
        # 진짜 비동기로 처리 가능 — asyncpg와 같은 이유(이벤트 루프를 안 막기 위함)
        _client = openai.AsyncOpenAI()  # OPENAI_API_KEY 환경변수 사용
    return _client


async def _call_once(raw_text: str) -> dict | None:
    """API 1회 호출 + 4줄 파싱. 형식이 깨지면(4줄 아님) None."""
    prompt = PROMPT_TEMPLATE.format(raw_text=raw_text)
    try:
        resp = await _get_client().chat.completions.create(
            model=MODEL,
            max_completion_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
    except (openai.APIStatusError, openai.APIConnectionError):
        return None

    text = resp.choices[0].message.content or ""
    lines = [l for l in text.strip().split("\n") if l.strip()]
    if len(lines) != 4:
        return None
    return {
        "point": _strip_line_prefix(lines[0]),
        "cause": _strip_line_prefix(lines[1]),
        "action": _strip_line_prefix(lines[2]),
        "result": _strip_line_prefix(lines[3]),
    }


def _all_fallback(summary: dict) -> bool:
    """4줄 전부 탈출구 문구면 실질적으로 요약 실패 (§4.6)."""
    values = [summary["point"], summary["cause"], summary["action"], summary["result"]]
    return all(any(p in v for p in FALLBACK_PHRASES) for v in values)


async def generate_summary(raw_text: str) -> tuple[dict | None, bool]:
    """
    반환: (summary dict 또는 None, summary_failed 여부)
    1차 생성 실패(형식 깨짐 또는 4줄 전부 미기재) → 재시도 1회 → 그래도 실패하면
    summary_failed=True로 캐싱해서, 진짜 요약 불가능한 문서를 조회될 때마다
    API 2번씩(1차+재시도) 낭비하는 것을 방지.
    """
    for _ in range(2):  # 1차 + 재시도 1회
        summary = await _call_once(raw_text)
        if summary is not None and not _all_fallback(summary):
            return summary, False
    return None, True


async def _call_once_freeform(raw_text: str) -> str | None:
    """API 1회 호출(자유형). 줄 수는 안 따지고, 응답이 비어있지 않으면 그대로 받아들임
    (2026-08-12 — 예전엔 "정확히 4줄"이 아니면 형식 깨짐으로 보고 버렸음)."""
    prompt = FREEFORM_PROMPT_TEMPLATE.format(raw_text=raw_text)
    try:
        resp = await _get_client().chat.completions.create(
            model=MODEL,
            max_completion_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
    except (openai.APIStatusError, openai.APIConnectionError):
        return None

    text = (resp.choices[0].message.content or "").strip()
    return text or None


def _all_fallback_freeform(text: str) -> bool:
    return FREEFORM_FALLBACK_PHRASE in text


async def generate_freeform_summary(raw_text: str) -> tuple[str | None, bool]:
    """
    구조화된 4줄(지적/원인/조치/결과)과 별개로, 항목 틀 없이 원문에서 핵심만 자유형으로
    뽑아냄. 반환: (요약 문자열 또는 None, failed 여부). 재시도/실패 캐싱 정책은
    generate_summary와 동일(§4.6) — 2회 다 실패하면 failed=True로 캐싱해서 재조회마다
    API 낭비하는 것 방지.
    """
    for _ in range(2):
        text = await _call_once_freeform(raw_text)
        if text is not None and not _all_fallback_freeform(text):
            return text, False
    return None, True
