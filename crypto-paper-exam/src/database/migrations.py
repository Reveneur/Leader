"""Schema management for Exam V1.

SQLite + SQLAlchemy's create_all is sufficient for this project's needs (a
single, additive schema that does not change during the exam). This module
is the single place that would grow into Alembic migrations if the project
later moves to PostgreSQL, per the README's stated migration path.
"""
from __future__ import annotations

from database.connection import get_engine, init_db
from database.models import Base


def create_schema() -> None:
    init_db()


def drop_schema() -> None:
    """Destructive — used only by test fixtures and explicit reset scripts."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
