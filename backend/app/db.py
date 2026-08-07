"""
DB 연결 관리.

- architecture.md §5.2 원칙: uvicorn 단일 워커 전제 (멀티 워커 쓰면 인메모리 LRU 캐시가
  워커별로 갈라져서 히트율이 떨어짐 — 지금은 psycopg2 SimpleConnectionPool도 프로세스
  하나 안에서만 공유되므로 같은 전제를 따름).
- 커넥션 풀을 쓰는 이유: 요청마다 psycopg2.connect()를 새로 하면 TCP+TLS 핸드셰이크가
  매 요청 지연시간에 더해짐 (NFR2: 1~2초 예산 안에서 불필요한 지연 요소).
"""
import os

import psycopg2.pool
from pgvector.psycopg2 import register_vector

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다 (Railway Postgres Connect 탭 참고)")

_pool: psycopg2.pool.SimpleConnectionPool | None = None


def init_pool(minconn: int = 1, maxconn: int = 5) -> None:
    global _pool
    if _pool is not None:
        return
    _pool = psycopg2.pool.SimpleConnectionPool(minconn, maxconn, dsn=DATABASE_URL)
    # 풀에서 미리 하나 받아서 register_vector 해두면, 이후 getconn()으로 받는 연결들도
    # 같은 프로세스 내에서 벡터 어댑터가 이미 등록된 상태로 동작함
    conn = _pool.getconn()
    try:
        register_vector(conn)
    finally:
        _pool.putconn(conn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


def get_conn():
    if _pool is None:
        raise RuntimeError("커넥션 풀이 초기화되지 않았습니다 (startup에서 init_pool 호출 필요)")
    conn = _pool.getconn()
    register_vector(conn)  # 풀에서 나온 개별 연결에도 안전하게 재등록 (idempotent)
    return conn


def put_conn(conn) -> None:
    if _pool is not None:
        _pool.putconn(conn)
