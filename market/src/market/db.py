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

import itertools
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .schema import migrate


def connect(path: str | Path = ":memory:",
            threadsafe: bool = False) -> sqlite3.Connection:
    """Open a ledger database and bring its schema up to date.

    ``threadsafe`` lets the connection be used from threads other than the
    one that opened it. It does not make concurrent use safe: a server that
    passes it must serialise every access behind one lock, which is what
    ``api/`` does. One world, one connection, one writer.
    """
    db = sqlite3.connect(str(path), isolation_level=None,
                         check_same_thread=not threadsafe)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL") if str(path) != ":memory:" else None
    # Without this, a crash between the write and the fsync can lose a
    # committed transaction. For a ledger that is not an acceptable trade.
    db.execute("PRAGMA synchronous = FULL")
    migrate(db)
    return db


_savepoints = itertools.count(1)


@contextmanager
def transaction(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """All-or-nothing. Commit on clean exit, roll back on any exception.

    IMMEDIATE takes the write lock at the start rather than on first write,
    so two concurrent settlements cannot both read a balance, both decide it
    is sufficient, and both spend it.

    **Nesting is allowed, and nests as a savepoint.** An order placed inside
    a world tick is all-or-nothing on its own -- a refused order leaves no
    trace -- while the tick as a whole is still one transaction. That second
    property is what makes a persistent world safe to stop: a server killed
    halfway through an hour must not leave half the hour's production
    committed and the other half not, because on restart the hour would run
    again and pay out twice. It also means one fsync per tick rather than
    one per order.
    """
    if db.in_transaction:
        name = f"sp_{next(_savepoints)}"
        db.execute(f"SAVEPOINT {name}")
        try:
            yield db
        except BaseException:
            db.execute(f"ROLLBACK TO {name}")
            db.execute(f"RELEASE {name}")
            raise
        db.execute(f"RELEASE {name}")
        return

    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")
