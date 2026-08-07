"""
DB 연결 관리 (asyncpg 비동기 커넥션 풀).

- FastAPI를 고른 이유 중 하나가 비동기 지원(architecture.md §5.7)인데, psycopg2 같은 동기
  드라이버를 쓰면 이 장점을 못 씀 (async def 라우트 안에서 동기 I/O를 부르면 이벤트 루프가
  막혀서 그 요청 처리 중엔 다른 요청도 다 같이 멈춤). 그래서 asyncpg(비동기 전용 Postgres
  드라이버)로 통일.
- architecture.md §5.2 원칙: uvicorn 단일 워커 전제 (멀티 워커 쓰면 인메모리 LRU 캐시가
  워커별로 갈라져서 히트율이 떨어짐) — 커넥션 풀도 프로세스 하나 안에서만 공유되므로 같은
  전제를 따름.
"""
import os

import asyncpg
from pgvector.asyncpg import register_vector

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다 (Railway Postgres Connect 탭 참고)")

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """풀에서 새 연결이 만들어질 때마다 호출됨 — pgvector 타입 어댑터 등록."""
    await register_vector(conn)


async def init_pool(min_size: int = 1, max_size: int = 5) -> None:
    """
    max_size=5 근거: 포트폴리오 프로젝트 규모에서 실제 동시 요청은 최악의 경우를 가정해도
    5건을 넘기 어렵고(면접관 시연 등), uvicorn 단일 워커 + 요청당 연결 점유 시간이 짧아서
    (벡터 검색 실측 수십ms + 쿼리 임베딩 ~100ms) 회전율이 빠름. 실제 트래픽 보고 조정 가능.
    """
    global _pool
    if _pool is not None:
        return
    _pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=min_size,
        max_size=max_size,
        init=_init_connection,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("커넥션 풀이 초기화되지 않았습니다 (startup에서 init_pool 호출 필요)")
    return _pool
