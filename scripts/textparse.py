# ------------------------------------------------------------------
# 원본 파일명에서 감사종류(audit_type) 파싱 (2026-08-12 추가)
# ------------------------------------------------------------------
# GitHub/Drive에 올릴 때 "기관이름_2021년_복무감사.pdf" 형태로 저장해왔는데, 정작
# build_final_dataset.py가 documents_final.jsonl을 만들 때 institution/year만 뽑고
# source_file(따라서 감사종류)은 버려서, 검색 결과/상세페이지에 감사종류가 안 보였음.
#
# 이 모듈은 build_final_dataset.py(앞으로 새로 빌드할 때)와 backfill_audit_type.py
# (이미 DB에 있는 기존 문서에 소급 적용할 때) 둘 다에서 같이 씀 — 파싱 로직이 두 군데서
# 어긋나지 않게 하기 위함.
#
# 패턴 가정: "{기관이름}_{연도}년_{감사종류}" (+ 확장자, + 중복 방지용 꼬리 숫자/괄호 있을 수 있음)
# 기관이름 자체에 언더스코어가 없다는 전제 — 있는 경우가 발견되면 이 파서부터 고쳐야 함.
# ------------------------------------------------------------------
import re

_EXT_RE = re.compile(r"\.(pdf|hwp|hwpx|doc|docx)$", re.IGNORECASE)
_YEAR_RE = re.compile(r"(\d{4})")
_TRAILING_PAREN_RE = re.compile(r"[\(（]\d+[\)）]$")  # "복무감사(1)" 같은 중복 방지 꼬리
_TRAILING_NUM_RE = re.compile(r"_\d+$")  # "복무감사_2" 같은 중복 방지 꼬리


def parse_source_file(source_file: str | None) -> tuple[str | None, int | None, str | None]:
    """'기관이름_2021년_복무감사.pdf' -> ('기관이름', 2021, '복무감사').
    형식이 예상과 다르면(언더스코어 2개 미만 등) 뽑을 수 있는 것만 뽑고 나머지는 None —
    통째로 실패시켜서 적재를 막지 않고, 감사종류 하나만 비어있는 상태로 넘어가게 함."""
    if not source_file:
        return None, None, None

    name = _EXT_RE.sub("", source_file.strip())
    parts = name.split("_")

    if len(parts) < 3:
        institution = parts[0].strip() if parts and parts[0].strip() else None
        return institution, None, None

    institution = parts[0].strip() or None

    year_match = _YEAR_RE.search(parts[1])
    year = int(year_match.group(1)) if year_match else None

    audit_type = "_".join(parts[2:]).strip() or None
    if audit_type:
        audit_type = _TRAILING_PAREN_RE.sub("", audit_type).strip()
        audit_type = _TRAILING_NUM_RE.sub("", audit_type).strip()
        audit_type = audit_type or None

    return institution, year, audit_type
