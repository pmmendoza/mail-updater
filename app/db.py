"""Database helpers for connecting to the compliance SQLite store."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


@lru_cache(maxsize=None)
def get_engine(db_path: Path) -> Engine:
    """Return a cached SQLAlchemy engine for the given SQLite path."""
    if not db_path.exists():
        raise FileNotFoundError(f"Compliance database not found at {db_path}")
    return create_engine(f"sqlite:///{db_path}", future=True)
