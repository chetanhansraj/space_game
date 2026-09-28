"""The world's own tables: players, contracts, messages, history, snapshot.

These live in the same SQLite file as the market's ledger so that one file is
one world, and a backup of that file is a backup of everything. They migrate
on their own version counter, separate from the market's, because the two
packages evolve independently and neither should need to know the other's
history.

Forward-only, like every migration in this repository. The world is
persistent and cannot be reset once live.
"""

from __future__ import annotations

import sqlite3

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        -- A person playing. The ledger account holds their money and cargo;
        -- this row holds who they are. The token is stored hashed: a leaked
        -- database must not be a list of working logins.
        --
        -- upkeep_owed is not a balance. It is a record of a charge the
        -- ledger could not take because the money was not there; the charge
        -- itself is only ever a ledger entry, when it is finally paid.
        CREATE TABLE player (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL UNIQUE COLLATE NOCASE,
            account        TEXT NOT NULL UNIQUE,
            ship_id        TEXT NOT NULL UNIQUE,
            token_hash     TEXT NOT NULL UNIQUE,
            created_tick   INTEGER NOT NULL,
            created_at     TEXT NOT NULL,
            last_seen_tick INTEGER NOT NULL,
            upkeep_owed    INTEGER NOT NULL DEFAULT 0 CHECK (upkeep_owed >= 0)
        );

        -- Facts about this world that never change once it exists: when its
        -- clock started, what seed its randomness comes from.
        CREATE TABLE world_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- A firm asking for goods delivered to it, with the payment already
        -- held in escrow so the promise cannot be broken by the issuer
        -- running short later.
        CREATE TABLE contract (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer         TEXT NOT NULL,
            issuer_account TEXT NOT NULL,
            node           TEXT NOT NULL,
            asset          TEXT NOT NULL,
            qty_kg         INTEGER NOT NULL CHECK (qty_kg > 0),
            payment        INTEGER NOT NULL CHECK (payment > 0),
            escrow_account TEXT NOT NULL,
            posted_tick    INTEGER NOT NULL,
            deadline_tick  INTEGER NOT NULL,
            status         TEXT NOT NULL CHECK (status IN
                             ('OPEN','ACCEPTED','FULFILLED','EXPIRED')),
            taker          TEXT,
            closed_tick    INTEGER
        );
        CREATE INDEX idx_contract_status ON contract (status, node);
        CREATE INDEX idx_contract_taker ON contract (taker, status);

        -- A player's inbox. The body is not stored: `data` holds the
        -- structured facts, and voice/ turns them into prose when the
        -- message is read. If voice/ is down the facts still arrive.
        CREATE TABLE message (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id TEXT NOT NULL,
            tick      INTEGER NOT NULL,
            sender    TEXT NOT NULL,
            kind      TEXT NOT NULL,
            data      TEXT NOT NULL DEFAULT '{}',
            read      INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_message_player ON message (player_id, id);

        -- Everything that happened, in order. The raw material for the
        -- codex the Archivist writes, and for "while you were away".
        CREATE TABLE event_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            tick    INTEGER NOT NULL,
            kind    TEXT NOT NULL,
            subject TEXT NOT NULL,
            detail  TEXT NOT NULL,
            data    TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX idx_event_tick ON event_log (tick);

        -- The parts of the world that are not money: which firms exist, how
        -- worked each deposit is, where every ship is. One row, replaced at
        -- the end of every tick. The ledger stays the authority on value.
        CREATE TABLE world_snapshot (
            id        INTEGER PRIMARY KEY CHECK (id = 1),
            tick      INTEGER NOT NULL,
            saved_at  TEXT NOT NULL,
            state     TEXT NOT NULL
        );
        """,
    ),
]


def migrate(db: sqlite3.Connection) -> int:
    db.execute(
        "CREATE TABLE IF NOT EXISTS sim_schema_version ("
        " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = db.execute("SELECT MAX(version) AS v FROM sim_schema_version").fetchone()
    current = row["v"] if row["v"] is not None else 0
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        db.executescript(sql)
        db.execute(
            "INSERT INTO sim_schema_version (version, applied_at) "
            "VALUES (?, datetime('now'))",
            (version,),
        )
        current = version
    return current
