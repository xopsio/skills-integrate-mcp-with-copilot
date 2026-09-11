"""Database configuration for the Mergington High School API."""

import os
import pathlib
import sqlite3

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Resolve repo root from this file's location so the default SQLite path is
# independent of the current working directory.
_repo_root = pathlib.Path(__file__).parent.parent.resolve()
_default_db_url = f"sqlite:///{_repo_root / 'mergington.db'}"

DATABASE_URL = os.environ.get("DATABASE_URL", _default_db_url)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable foreign key support for every new SQLite connection."""
    if isinstance(dbapi_conn, sqlite3.Connection):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


_naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Base = declarative_base(metadata=MetaData(naming_convention=_naming_convention))


def get_db() -> Session:
    """FastAPI dependency that yields a request-scoped Session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
