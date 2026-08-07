"""
온디맨드 4줄 요약 생성 (architecture.md §4.5, §4.6).

프롬프트/모델은 `scripts/summary_smoke_test.py`에서 35건 실측 검증된 것을 그대로 재사용
(건당 평균 1.77초/$0.0002, standard 등급 미기재 사용 0% 확인됨 — STATUS.md 5차).
상세 API가 문서 조회 시 summary_point가 비어있으면 여기를 호출하고, 결과를
repository.save_summary()로 캐싱해서 다음부터는 재호출 안 함.
"""
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
    return {"point": lines[0], "cause": lines[1], "action": lines[2], "result": lines[3]}


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
