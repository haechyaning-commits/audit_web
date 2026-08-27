"""
한국어 형태소 토큰화 (architecture.md §3.6, 스트레치 목표 — 2026-08-27 코드 준비).

문제: `to_tsvector('simple', ...)`/`plainto_tsquery('simple', ...)`는 공백·구두점
기준으로만 토큰을 나누고 한국어 조사/어미를 떼어내지 않는다. 예를 들어 원문에
"예산낭비가"로 붙어 있으면 검색어 "예산 낭비"가 정확히 매칭되지 않는다(§3.6 변경이유).
실측(2026-08-27, kiwipiepy==0.23.2): kiwi.tokenize("예산낭비가 심각한 수의계약 특혜")
→ 예산(NNG) 낭비(NNG) 가(JKS) 심각(XR) 하(XSA) ㄴ(ETM) 수의(NNG) 계약(NNG) 특혜(NNG) —
조사("가")·어미(XSA/ETM)가 실제로 분리됨을 확인.

해결: 배치(색인)와 온라인(검색 쿼리) 양쪽 모두 이 모듈의 tokenize()를 거쳐서 나온
토큰만 `simple` 사전에 태운다 — 배치 쪽만 바꾸거나 쿼리 쪽만 바꾸면 색인과 쿼리의
토큰화 기준이 어긋나서 매칭이 아예 깨지므로(§3.6), 반드시 공통 함수 하나를 같이 써야
한다(배치 스크립트는 scripts/backfill_tsv_text.py가 sys.path로 이 모듈을 그대로 import).

embedding.py와 동일한 패턴: 모델(Kiwi)은 프로세스당 한 번만 로드해서 재사용 — 요청마다
새로 만들면 초기화 비용(사전 로딩)이 매번 들어가 지연시간이 늘어난다.

**아직 안 한 것(2026-08-27 세션은 DB/Railway 접근이 없어 여기까지만 준비)**:
- scripts/tsv_text_migration.sql + scripts/backfill_tsv_text.py로 기존 96,355개
  chunks.tsv_text를 실제로 채우고 tsv 생성 컬럼을 tsv_text 기준으로 교체하는 작업은
  DB 접근 가능한 세션에서 실행 필요.
- 그 전까지는 TOKENIZER_ENABLED가 켜져 있어도 색인 쪽(tsv)은 여전히 원문(text) 기준이라,
  쿼리만 형태소 토큰으로 바꾸면 오히려 매칭이 줄어들 수 있음(위 "해결" 문단 참고) —
  그래서 기본값은 꺼짐(false)으로 두고, 마이그레이션이 실제로 끝난 뒤에만 켤 것.
"""
import os

from kiwipiepy import Kiwi

_kiwi: Kiwi | None = None

# 명사(N)/동사(V)/부사(MAG) 위주로만 남기고 조사·어미 등 기능어는 제거 — architecture.md
# §3.6 설계 그대로. 어근(XR, "심각"의 "심각" 같은 것)도 검색 의미가 있어 포함.
_KEEP_TAG_PREFIXES = ("N", "V", "MAG", "XR")


def load_model() -> None:
    global _kiwi
    if _kiwi is not None:
        return
    _kiwi = Kiwi(num_workers=int(os.environ.get("KIWI_NUM_WORKERS", "1")))


def is_loaded() -> bool:
    return _kiwi is not None


def _join_tokens(tokens) -> str:
    return " ".join(t.form for t in tokens if t.tag.startswith(_KEEP_TAG_PREFIXES))


def tokenize(text: str) -> str:
    """형태소 분석 후 의미어만 공백 join해서 반환. 배치(색인)·온라인(쿼리) 양쪽에서
    반드시 이 함수를 그대로 써야 함(모듈 docstring 참고) — 결과가 비어 있으면(예: 검색어가
    전부 조사/어미로만 이뤄진 극단적 케이스) 호출부가 원문을 그대로 fallback으로 쓸 수
    있도록 빈 문자열을 그대로 반환함(에러를 던지지 않음)."""
    if _kiwi is None:
        raise RuntimeError("형태소 분석기가 로드되지 않았습니다 (startup에서 load_model 호출 필요)")
    return _join_tokens(_kiwi.tokenize(text))


def tokenize_batch(texts: list[str]) -> list[str]:
    """scripts/backfill_tsv_text.py 같은 배치 백필용 — 한 건씩 tokenize()를 반복 호출하는
    것보다 kiwi.tokenize(list)로 한 번에 넘기는 게 num_workers만큼 병렬 처리돼 훨씬 빠름
    (실측 2026-08-27: num_workers=2, 2,000건 배치 기준 약 3초 → 96,355건 규모면 수 분 내)."""
    if _kiwi is None:
        raise RuntimeError("형태소 분석기가 로드되지 않았습니다 (startup에서 load_model 호출 필요)")
    return [_join_tokens(tokens) for tokens in _kiwi.tokenize(texts)]
