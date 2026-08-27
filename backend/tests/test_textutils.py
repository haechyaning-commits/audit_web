"""textutils.py 순수 함수 유닛테스트 — DB/네트워크 의존 없는 텍스트 가공 로직."""
from app.textutils import (
    build_preview,
    build_source_url,
    extract_law_citations,
    extract_title,
)


def test_extract_title_from_label_line():
    assert extract_title("제목: 채용비리 특정감사\n\n본문...") == "채용비리 특정감사"


def test_extract_title_handles_missing_label():
    assert extract_title("라벨 없이 바로 시작하는 본문") is None


def test_extract_title_handles_none_and_empty():
    assert extract_title(None) is None
    assert extract_title("") is None


def test_build_preview_returns_short_text_unchanged():
    assert build_preview("짧은 미리보기 문장.") == "짧은 미리보기 문장."


def test_build_preview_skips_leading_sentence_fragment():
    # 첫 문장부호 앞부분은 이전 문장의 잘린 꼬리로 보고 건너뛰고 "…"를 붙임
    buffer = "다 이전 문장의 조각. 실제로 보여줄 문장이 여기서부터 시작한다."
    preview = build_preview(buffer, target_len=200)
    assert preview.startswith("…실제로 보여줄 문장")


def test_build_source_url_strips_data_repo_prefix_and_encodes():
    url = build_source_url("data_repo/한국공사/2024 감사.pdf")
    assert url == "https://cdn.jsdelivr.net/gh/haechyaning-commits/data@main/%ED%95%9C%EA%B5%AD%EA%B3%B5%EC%82%AC/2024%20%EA%B0%90%EC%82%AC.pdf"


def test_build_source_url_returns_none_when_missing():
    assert build_source_url(None) is None
    assert build_source_url("") is None


def test_extract_law_citations_keeps_only_real_statutes():
    text = "「공공기관의 운영에 관한 법률」 및 「법인카드 사용 및 관리지침」에 따라..."
    assert extract_law_citations(text) == {"공공기관의 운영에 관한 법률"}


def test_extract_law_citations_returns_empty_set_for_none():
    assert extract_law_citations(None) == set()
