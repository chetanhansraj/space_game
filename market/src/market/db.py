"""Connection handling and the transaction boundary.

Every money movement in this package happens inside ``transaction``. There is
no code path that writes a posting outside one. That is the whole mechanism by
which "money movements are transactional or they are bugs" is true rather than
aspirational: a matching engine that raises halfway through a fill leaves the
database exactly as it found it.

SQLite is used because it has real transactions, needs no server, and is
trivially inspectable at 2am against a live economy -- which CLAUDE.md
explicitly asks for. The SQL is kept plain enough to move to Postgres when
concurrency demands it; the only SQLite-specific pieces are the pragmas here
and ``AUTOINCREMENT``.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .schema import migrate


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    db = sqlite3.connect(str(path), isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL") if str(path) != ":memory:" else None
    # Without this, a crash between the write and the fsync can lose a
    # committed transaction. For a ledger that is not an acceptable trade.
    db.execute("PRAGMA synchronous = FULL")
    migrate(db)
    return db


@contextmanager
def transaction(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """All-or-nothing. Commit on clean exit, roll back on any exception.

    IMMEDIATE takes the write lock at the start rather than on first write,
    so two concurrent settlements cannot both read a balance, both decide it
    is sufficient, and both spend it.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except Exception:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")
