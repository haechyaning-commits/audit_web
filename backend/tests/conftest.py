"""pytest 전역 설정.

app.db가 import되는 시점에 DATABASE_URL이 없으면 바로 RuntimeError를 던지고
(db.py 참고, 프로덕션에서 설정을 깜빡하는 걸 조기에 잡기 위한 의도적 설계), app.main의
ADMIN_TOKEN도 import 시점에 환경변수에서 한 번만 읽힘 — 그래서 두 값 다 어떤
테스트 모듈이 `from app import main`을 하기도 전에, 즉 이 conftest.py가 로드되는
시점에 미리 정해둬야 함(pytest는 각 테스트 디렉터리의 conftest.py를 그 안의
테스트 모듈들을 수집(import)하기 전에 먼저 로드함).

여기서 정한 ADMIN_TOKEN 값은 tests/test_main.py가 "정답 토큰"으로 그대로 가져다 씀.
실제 프로덕션 토큰과는 무관한 테스트 전용 값.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/testdb")
os.environ.setdefault("ADMIN_TOKEN", "pytest-fixture-admin-token")
