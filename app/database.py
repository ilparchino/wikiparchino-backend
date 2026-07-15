from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    created_engine = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith("sqlite"):
        event.listen(created_engine, "connect", _enable_sqlite_foreign_keys)
    return created_engine


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def configure_database(database_url: str) -> None:
    global engine, SessionLocal
    engine = make_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
