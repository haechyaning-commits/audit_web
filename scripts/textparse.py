# ------------------------------------------------------------------
# 원본 파일명에서 감사종류(audit_type) 파싱 (2026-08-12 추가)
# ------------------------------------------------------------------
# GitHub/Drive에 올릴 때 "기관이름_2021년_복무감사" 형태일 거라 짐작하고 처음 짰었는데,
# 실제 embed_ready_v2.jsonl의 source_file로 확인해보니(2026-08-12 dry-run) 진짜 패턴은:
#
#   data_repo/자체감사파일1/{기관명}_{연도}년 {감사종류}({번호}).{확장자}
#
# - source_file은 파일명이 아니라 상대 경로 전체 (맨 뒤 basename만 써야 함)
# - 기관명 뒤 언더스코어는 딱 하나뿐, 그 뒤로는 "2016년 종합감사(27)"처럼 공백 구분
#   (기관명_연도_감사종류처럼 언더스코어 두 개일 거라 짐작했던 게 틀렸음 — 반드시 실제
#   데이터로 재확인해야 하는 이유)
# - 괄호 번호 "(27)"는 같은 기관/연도/감사종류 안에서의 문서 일련번호로 보임, 감사종류에서
#   제외
#
# 이 모듈은 build_final_dataset.py(앞으로 새로 빌드할 때)와 backfill_audit_type.py
# (이미 DB에 있는 기존 문서에 소급 적용할 때) 둘 다에서 같이 씀.
# ------------------------------------------------------------------
import re

_EXT_RE = re.compile(r"\.(pdf|hwp|hwpx|doc|docx)$", re.IGNORECASE)
_YEAR_REST_RE = re.compile(r"^(\d{4})년\s*(.*)$")
_TRAILING_PAREN_RE = re.compile(r"[\(（]\d+[\)）]\s*$")  # 꼬리의 "(27)" 같은 일련번호 제거


def parse_source_file(source_file: str | None) -> tuple[str | None, int | None, str | None]:
    """'data_repo/자체감사파일1/한국조폐공사_2016년 종합감사(27).pdf'
    -> ('한국조폐공사', 2016, '종합감사').
    형식이 예상과 다르면 뽑을 수 있는 것만 뽑고 나머지는 None — 통째로 실패시켜서 적재를
    막지 않고, 감사종류 하나만 비어있는 상태로 넘어가게 함."""
    if not source_file:
        return None, None, None

    base = source_file.strip().split("/")[-1]  # 경로 전체가 아니라 맨 뒤 파일명만
    base = _EXT_RE.sub("", base)

    if "_" not in base:
        return (base.strip() or None), None, None

    institution, rest = base.split("_", 1)
    institution = institution.strip() or None

    m = _YEAR_REST_RE.match(rest.strip())
    if not m:
        return institution, None, None

    year = int(m.group(1))
    audit_type = _TRAILING_PAREN_RE.sub("", m.group(2)).strip() or None

    return institution, year, audit_type
