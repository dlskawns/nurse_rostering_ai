import os
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _build_mysql_url() -> str:
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "readonly_user")
    pwd = os.getenv("DB_PASSWORD", "readonly_password")
    db = os.getenv("DB_NAME", "meditong_roster")
    charset = os.getenv("DB_CHARSET", "utf8mb4")
    return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?charset={charset}"


def create_readonly_engine() -> Engine:
    """읽기 전용으로 사용되는 MySQL 엔진을 생성합니다."""
    url = _build_mysql_url()
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=5,
        max_overflow=10,
        connect_args={"ssl_disabled": True},
    )
    return engine


@contextmanager
def connect(engine: Engine):
    """엔진으로부터 연결을 얻는 컨텍스트 매니저.

    쓰기 금지 정책: 트랜잭션은 사용하지 않으며, 오직 SELECT 류만 실행해야 합니다.
    """
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()


def execute_select(engine: Engine, sql: str, params: Dict[str, Any] | None = None) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """SELECT 쿼리를 실행하고 (컬럼명, 결과 rows)를 반환합니다."""
    with connect(engine) as conn:
        result = conn.execute(text(sql), params or {})
        keys = list(result.keys())
        rows = list(result.fetchall())
        return keys, rows 