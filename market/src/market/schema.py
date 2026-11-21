"""Schema and forward-only migrations.

The world is persistent and cannot be reset once live, so migrations only ever
go forward. There is no ``downgrade``. If a migration is wrong, the fix is
another migration.

Nothing in this schema permits editing a balance. There is no balance column
anywhere. Balances are derived by summing postings, every time, because a
stored balance is a second source of truth that will eventually disagree with
the first one and there will be no way to tell which is right.
"""

from __future__ import annotations

import sqlite3

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        -- Accounts. Everything that can hold value, including the world
        -- itself. See ledger.py for what the world accounts mean.
        CREATE TABLE account (
            id         TEXT PRIMARY KEY,
            kind       TEXT NOT NULL CHECK (kind IN
                         ('player','agent','institution','escrow','world')),
            label      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        -- Tradeable assets. CREDIT is present as a row so that postings can
        -- reference it uniformly; its lot mass and base value are unused.
        CREATE TABLE asset (
            symbol      TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            lot_mass_kg INTEGER NOT NULL,
            base_value  INTEGER NOT NULL
        );

        -- One row per economic event. Postings hang off it.
        CREATE TABLE txn (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            kind      TEXT NOT NULL,
            game_time TEXT NOT NULL,
            ref       TEXT,
            memo      TEXT NOT NULL DEFAULT ''
        );

        -- The ledger. Append-only: there is no UPDATE or DELETE on this table
        -- anywhere in the package, and a trigger below enforces it.
        --
        -- amount is signed, in credits for CREDIT and in kilograms for
        -- commodities. Postings within one txn sum to zero per asset, which
        -- is what makes conservation structural.
        CREATE TABLE posting (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_id     INTEGER NOT NULL REFERENCES txn(id),
            account_id TEXT NOT NULL REFERENCES account(id),
            asset      TEXT NOT NULL REFERENCES asset(symbol),
            amount     INTEGER NOT NULL
        );

        CREATE INDEX idx_posting_balance ON posting (account_id, asset);
        CREATE INDEX idx_posting_txn     ON posting (txn_id);

        -- Append-only, enforced by the database rather than by convention.
        -- If someone later writes an UPDATE against the ledger, it fails
        -- loudly instead of quietly rewriting history.
        CREATE TRIGGER posting_is_append_only_update
        BEFORE UPDATE ON posting
        BEGIN
            SELECT RAISE(ABORT, 'the ledger is append-only: postings cannot be updated');
        END;

        CREATE TRIGGER posting_is_append_only_delete
        BEFORE DELETE ON posting
        BEGIN
            SELECT RAISE(ABORT, 'the ledger is append-only: postings cannot be deleted');
        END;

        -- Resting orders. Unlike postings these do change: an order fills
        -- down and is eventually closed.
        CREATE TABLE book_order (
            id           TEXT PRIMARY KEY,
            node         TEXT NOT NULL,
            asset        TEXT NOT NULL REFERENCES asset(symbol),
            side         TEXT NOT NULL CHECK (side IN ('BID','ASK')),
            price        INTEGER NOT NULL CHECK (price > 0),
            qty_kg       INTEGER NOT NULL CHECK (qty_kg > 0),
            remaining_kg INTEGER NOT NULL CHECK (remaining_kg >= 0),
            account_id   TEXT NOT NULL REFERENCES account(id),
            escrow_id    TEXT NOT NULL REFERENCES account(id),
            status       TEXT NOT NULL CHECK (status IN ('OPEN','FILLED','CANCELLED')),
            placed_at    TEXT NOT NULL,
            seq          INTEGER NOT NULL
        );

        -- Price-time priority. The partial index keeps the hot path -- find
        -- the best resting order on the opposite side -- reading only open
        -- orders.
        CREATE INDEX idx_book_match ON book_order
            (node, asset, side, price, seq) WHERE status = 'OPEN';

        CREATE TABLE trade (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            node          TEXT NOT NULL,
            asset         TEXT NOT NULL REFERENCES asset(symbol),
            price         INTEGER NOT NULL,
            qty_kg        INTEGER NOT NULL,
            buy_order_id  TEXT NOT NULL REFERENCES book_order(id),
            sell_order_id TEXT NOT NULL REFERENCES book_order(id),
            txn_id        INTEGER NOT NULL REFERENCES txn(id),
            game_time     TEXT NOT NULL
        );

        CREATE INDEX idx_trade_tape ON trade (node, asset, id);
        """,
    ),
    (
        2,
        """
        -- Found when planning a world that runs continuously rather than for
        -- a test's few hundred ticks. Every order placement takes the next
        -- sequence number with MAX(seq), and with no index on seq that is a
        -- scan of every order ever placed. Fine for a test, and a slowdown
        -- that grows without bound for a server that runs for months.
        CREATE INDEX idx_book_seq ON book_order (seq);

        -- A firm's own open orders are cancelled and replaced every tick.
        -- Without this the lookup filters the open-order index by account.
        CREATE INDEX idx_book_account ON book_order (account_id, status);
        """,
    ),
    (
        3,
        """
        -- A derived cache of balances, and the one exception to "no stored
        -- balance anywhere" -- so it is worth being exact about why it is
        -- not a second source of truth.
        --
        -- A live world writes roughly 800,000 postings per real day. Summing
        -- an account's whole history on every balance read was a few
        -- microseconds in a test and would be seconds per tick within weeks.
        --
        -- Every row here is the sum of every posting for that account and
        -- asset up to ``checkpoint_mark.through_posting``, written only by
        -- ``Ledger.checkpoint`` in a single statement that reads postings
        -- and nothing else. Nothing ever edits a row by hand, a balance is
        -- still checkpoint plus the postings after the mark, and
        -- ``Ledger.verify_checkpoints`` recomputes the whole table from the
        -- raw ledger and compares. The postings remain the truth; delete
        -- this table and every balance is still recoverable.
        CREATE TABLE balance_checkpoint (
            account_id TEXT NOT NULL,
            asset      TEXT NOT NULL,
            amount     INTEGER NOT NULL,
            PRIMARY KEY (account_id, asset)
        ) WITHOUT ROWID;
        CREATE INDEX idx_checkpoint_asset ON balance_checkpoint (asset);

        CREATE TABLE checkpoint_mark (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            through_posting INTEGER NOT NULL
        );
        INSERT INTO checkpoint_mark (id, through_posting) VALUES (1, 0);
        """,
    ),
    (
        4,
        """
        -- Old history leaves the live file (market/archive.py). A world at
        -- the faster clock writes most of a gigabyte a day, on a disk it
        -- shares, and nothing in the game reads a posting once it is in
        -- the checkpoint. So transactions past a horizon are copied whole
        -- into archive files beside the world and then removed from here.
        --
        -- The ledger stays append-only in the sense that matters: nothing
        -- is ever changed, and nothing leaves that has not first been
        -- written to an archive and summed into `archive_total`.
        --
        -- `archive_total` is the sum of every posting that has left, by
        -- account and asset: with the postings still here it is the whole
        -- truth a balance is checked against (Ledger.verify_checkpoints).
        -- Written only by the archive step, in the same transaction that
        -- removes the postings it sums.
        CREATE TABLE archive_total (
            account_id TEXT NOT NULL,
            asset      TEXT NOT NULL,
            amount     INTEGER NOT NULL,
            PRIMARY KEY (account_id, asset)
        ) WITHOUT ROWID;

        -- Every transaction up to and including `through_txn` has been
        -- archived, with all its postings. `through_seq` is how far the
        -- order book has been looked through for closed orders to move.
        CREATE TABLE archive_mark (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            through_txn INTEGER NOT NULL,
            through_seq INTEGER NOT NULL
        );
        INSERT INTO archive_mark (id, through_txn, through_seq) VALUES (1, 0, 0);

        -- The one way a posting can leave: its transaction is at or below
        -- the archive mark. Anything else still fails loudly, as before.
        DROP TRIGGER posting_is_append_only_delete;
        CREATE TRIGGER posting_is_append_only_delete
        BEFORE DELETE ON posting
        WHEN OLD.txn_id > (SELECT through_txn FROM archive_mark WHERE id = 1)
        BEGIN
            SELECT RAISE(ABORT, 'the ledger is append-only: postings cannot be deleted');
        END;

        -- Removing a transaction, an order or an escrow account makes the
        -- database check that nothing still points at it. Without these
        -- each check is a scan of the whole table.
        CREATE INDEX idx_trade_txn   ON trade (txn_id);
        CREATE INDEX idx_trade_buy   ON trade (buy_order_id);
        CREATE INDEX idx_trade_sell  ON trade (sell_order_id);
        CREATE INDEX idx_book_escrow ON book_order (escrow_id);
        """,
    ),
]


def migrate(db: sqlite3.Connection) -> int:
    """Apply every migration not yet applied. Returns the resulting version."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = (row["v"] if row["v"] is not None else 0)

    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        db.executescript(sql)
        db.execute(
            "INSERT INTO schema_version (version, applied_at) "
            "VALUES (?, datetime('now'))",
            (version,),
        )
        current = version
    db.commit()
    return current
