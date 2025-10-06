# import logging
# import os
# from contextlib import contextmanager
# from typing import Generator, Any
# import dotenv
# dotenv.load_dotenv()

# import pymssql
# import pymysql

# # 로깅 설정
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# class MssqlDatabasemanager:
#     def __init__(self):
#         self.host = os.getenv("MS_DB_HOST")
#         self.port = os.getenv("MS_DB_PORT")
#         self.database = os.getenv("MS_DB_NAME")
#         self.user = os.getenv("MS_DB_USER")
#         self.password = os.getenv("MS_DB_PASSWORD")

#     def get_connection(self, database: str | None = None, charset: str | None = 'EUC-KR') -> pymssql.Connection:
#         """데이터베이스 연결을 생성합니다. 선택적으로 데이터베이스명을 지정할 수 있습니다."""
#         try:
#             connection = pymssql.connect(
#                 server=self.host,
#                 port=self.port,
#                 database=(database or self.database),
#                 user=self.user,
#                 password=self.password,
#                 charset='EUC-KR'
#                 #charset= charset

#             )
#             return connection
#         except Exception as e:
#             logger.error(f"데이터베이스 연결 실패: {e}")
#             raise

#     @contextmanager
#     def connection(self, database: str | None = None, charset: str | None = 'EUC-KR') -> Generator[pymssql.Connection, None, None]:
#         """컨텍스트 매니저로 연결을 열고 자동으로 닫습니다."""
#         conn = self.get_connection(database, charset)
#         try:
#             yield conn
#         finally:
#             conn.close()

#     def fetch_all(self, query: str, params: tuple | None = None, database: str | None = None) -> list[dict]:
#         """SELECT 쿼리를 실행하고 결과를 리스트[dict]로 반환합니다."""
#         with self.connection(database) as conn:
#             cursor = conn.cursor()
#             cursor.execute(query, params or ())
#             rows = cursor.fetchall()
#             columns = [column[0] for column in cursor.description]
#             return [dict(zip(columns, row)) for row in rows]

#     def fetch_one(self, query: str, params: tuple | None = None, database: str | None = None) -> list[dict]:
#         """SELECT COUNT(*) 쿼리를 실행하고 결과를 반환합니다."""
#         with self.connection(database) as conn:
#             cursor = conn.cursor()
#             cursor.execute(query, params or ())
#             rows = cursor.fetchone()
#             return rows[0]

#     def execute(self, query: str, params: tuple | None = None, database: str | None = None) -> int:
#         """INSERT/UPDATE/DELETE 쿼리를 실행하고 영향 받은 행 수를 반환합니다."""
#         charset = 'UTF-8'

#         with self.connection(database, charset) as conn:
#             cursor = conn.cursor()
#             cursor.execute(query, params)
#             conn.commit()
#             return cursor.rowcount

#     def bulk_execute(self, query: str, params: list, database: str | None = None) -> int:
#         if not isinstance(params, list) or not all(isinstance(item, (tuple, list)) for item in params):
#             raise TypeError("params argument must be a list of tuples or lists.")
#         charset = 'UTF-8'

#         with self.connection(database, charset) as conn:
#             cursor = conn.cursor()
#             cursor.executemany(query, params)
#             conn.commit()
#             return cursor.rowcount
        
# # 전역 데이터베이스 매니저 인스턴스
# msdb_manager = MssqlDatabasemanager()

# class MariaDatabasemanager:
#     def __init__(self):
#         self.host = os.getenv("DB_HOST")
#         self.port = os.getenv("DB_PORT")
#         self.database = os.getenv("DB_NAME")
#         self.user = os.getenv("DB_USER")
#         self.password = os.getenv("DB_PASSWORD")
#     def get_connection(self, database: str | None = None) -> pymysql.connections.Connection:
#         """데이터베이스 연결을 생성합니다. 선택적으로 데이터베이스명을 지정할 수 있습니다."""
#         try:
#             connection = pymysql.connect(
#                 host=self.host,
#                 port=int(self.port),
#                 db=(database or self.database),
#                 user=self.user,
#                 password=self.password,
#                 charset='utf8mb4',
#                 autocommit=False,
#                 cursorclass=pymysql.cursors.Cursor,
#             )
#             return connection
#         except Exception as e:
#             logger.error(f"마리아DB 연결 실패: {e}")
#             raise

#     @contextmanager
#     def connection(self, database: str | None = None) -> Generator[pymysql.connections.Connection, None, None]:
#         """컨텍스트 매니저로 연결을 열고 자동으로 닫습니다."""
#         conn = self.get_connection(database)
#         try:
#             yield conn
#         finally:
#             conn.close()

#     def fetch_all(self, query: str, params: tuple | None = None, database: str | None = None) -> list[dict[str, Any]]:
#         """SELECT 쿼리를 실행하고 결과를 리스트[dict]로 반환합니다."""
#         with self.connection(database) as conn:
#             cursor = conn.cursor()
#             cursor.execute(query, params or ())
#             rows = cursor.fetchall()
#             columns = [desc[0] for desc in cursor.description]
#             return [dict(zip(columns, row)) for row in rows]

#     def fetch_one(self, query: str, params: tuple | None = None, database: str | None = None) -> Any:
#         """SELECT COUNT(*)와 같은 단일 값을 반환하는 쿼리를 실행하고 결과를 반환합니다."""
#         with self.connection(database) as conn:
#             cursor = conn.cursor()
#             cursor.execute(query, params or ())
#             row = cursor.fetchone()
#             return row if row else None

#     def execute(self, query: str, params: tuple | None = None, database: str | None = None) -> int:
#         """INSERT/UPDATE/DELETE 쿼리를 실행하고 영향 받은 행 수를 반환합니다."""

#         with self.connection(database) as conn:
#             cursor = conn.cursor()
#             cursor.execute(query, params or ())
#             conn.commit()
#             return cursor.rowcount


# # 전역 마리아DB 매니저 인스턴스
# mariadb_manager = MariaDatabasemanager()


# from sqlalchemy.orm import Session, sessionmaker
# from sqlalchemy import create_engine, func
# _MSSQL_SESSION_MAKER: sessionmaker | None = None


# def _get_mssql_session() -> Session:
#     """MSSQL 전용 SQLAlchemy 세션을 반환합니다. .env의 MS_DB_* 값을 사용합니다."""
#     global _MSSQL_SESSION_MAKER
#     if _MSSQL_SESSION_MAKER is None:
#         host = os.getenv("MS_DB_HOST")
#         port = os.getenv("MS_DB_PORT")
#         dbname = os.getenv("MS_DB_NAME")
#         user = os.getenv("MS_DB_USER")
#         password = os.getenv("MS_DB_PASSWORD")
#         database_url = f"mssql+pymssql://{user}:{password}@{host}:{port}/{dbname}"
#         engine = create_engine(database_url, pool_pre_ping=True)
#         _MSSQL_SESSION_MAKER = sessionmaker(autocommit=False, autoflush=False, bind=engine)
#     return _MSSQL_SESSION_MAKER()