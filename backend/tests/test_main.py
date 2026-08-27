"""FastAPI 엔드포인트 유닛테스트.

이 프로젝트는 지금까지 자동화된 백엔드 테스트가 없었음(CI의 backend-syntax 잡은
`python -m py_compile`로 문법 에러만 확인, 실제 동작은 검증 안 함) — 특히
POST /reports(로그인 없이 누구나 호출 가능)와 GET /admin/reports(토큰 하나로
지키는 관리자 페이지) 같은 입력검증/인가 로직은 회귀가 생겨도 화면상 티가 안
나는 종류의 버그라 우선 테스트를 붙임.

TestClient(app)를 `with` 없이 그냥 인스턴스화하면 FastAPI lifespan(startup)이
실행되지 않음 — 즉 db.init_pool()/embedding.load_model()이 전혀 호출되지 않아
실제 Postgres나 임베딩 모델 없이도 라우트를 호출할 수 있음. 그 대신 db.get_pool()을
실제로 건드리는 코드 경로(성공 응답)는 호출 시 RuntimeError가 나므로, 아래 테스트는
① db 접근 전에 끝나는 입력검증/인가 실패 경로와 ② db.get_pool()/repository 함수를
monkeypatch로 스텁 처리한 성공 경로만 다룸 — 실제 SQL/벡터 검색 자체는 이 테스트의
범위가 아님(이 세션엔 프로덕션 DB 접근이 없어 검증 불가, STATUS.md 참고).
"""
from datetime import datetime

from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_search_rejects_empty_query():
    # db.get_pool() 이전에 걸러지므로 lifespan 없이도 안전하게 테스트 가능
    resp = client.get("/search", params={"q": ""})
    assert resp.status_code == 400


def test_search_rejects_single_char_query():
    # "a"처럼 의미 없는 한 글자 검색어 거절(main.py 주석 참고)
    resp = client.get("/search", params={"q": "a"})
    assert resp.status_code == 400
    assert "2자 이상" in resp.json()["detail"]


def test_reports_rejects_blank_message():
    resp = client.post("/reports", json={"message": "   "})
    assert resp.status_code == 400


def test_reports_rejects_message_over_max_length():
    # MAX_REPORT_MESSAGE_LEN=2000 경계값 확인
    resp = client.post("/reports", json={"message": "x" * 2001})
    assert resp.status_code == 400
    assert "2000자" in resp.json()["detail"]


def test_admin_reports_rejects_missing_token():
    resp = client.get("/admin/reports")
    assert resp.status_code == 403


def test_admin_reports_rejects_wrong_token():
    resp = client.get("/admin/reports", params={"token": "definitely-wrong"})
    assert resp.status_code == 403


def test_admin_reports_rejects_everything_when_admin_token_unset(monkeypatch):
    # main.py 주석의 핵심 보안 의도: ADMIN_TOKEN이 빈 문자열이면(설정을 깜빡한 경우)
    # 빈 문자열끼리 비교돼서 통과하는 사고를 막기 위해 항상 403이어야 함.
    monkeypatch.setattr(main, "ADMIN_TOKEN", "")
    resp = client.get("/admin/reports", params={"token": ""})
    assert resp.status_code == 403


def test_admin_reports_accepts_correct_token(monkeypatch):
    # 인가를 통과한 뒤에는 db.get_pool()/repository.list_error_reports가 호출되므로,
    # 실제 Postgres 없이 검증하기 위해 둘 다 스텁으로 치환.
    fake_row = {
        "id": 1,
        "created_at": datetime(2026, 8, 27, 9, 30),
        "document_id": "doc-123",
        "institution": "한국테스트공사",
        "year": 2025,
        "audit_type": "종합감사",
        "page_url": "https://example.com/cases/doc-123",
        "message": "이 문서의 채용 절차 설명이 원문과 다릅니다.",
    }

    async def fake_list_error_reports(pool):
        return [fake_row]

    monkeypatch.setattr(main.db, "get_pool", lambda: object())
    monkeypatch.setattr(main.repository, "list_error_reports", fake_list_error_reports)

    resp = client.get("/admin/reports", params={"token": "pytest-fixture-admin-token"})
    assert resp.status_code == 200
    assert "이 문서의 채용 절차 설명이 원문과 다릅니다." in resp.text
    assert "한국테스트공사" in resp.text
