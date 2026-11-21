"""Moving old history out of the live ledger file.

The ledger is append-only and nothing here changes that: no posting is ever
altered, and none leaves the live file until it has been written, whole, to
an archive file and its amount added to ``archive_total``. What this does
is stop the live file growing without end. A world at the faster clock
(docs/DECISIONS.md D93) writes most of a gigabyte a real day; the disk it
lives on is shared and finite; and once a posting is in the balance
checkpoint, nothing in the game reads it again.

One step, called between the world's hours and never inside one:

1. Choose a cut: the newest transaction old enough to go, no further than
   ``max_txns`` past the last cut. Everything is decided against that one
   number.
2. Copy to the archive file, and commit there: every transaction up to the
   cut with all its postings, the trades settled by them (but for the newest
   few at each market, which the price and the chart are read from), the
   closed orders nothing still refers to, and those orders' empty escrow
   accounts.
3. In one transaction on the live file: add the postings' sums to
   ``archive_total``, move the mark, and remove exactly what was copied.

The copy is committed before anything is removed, never the other way
round. If the process dies between the two, the archive holds rows the live
file still has, and the next step copies them again and is told they are
already there. The reverse order could lose history; this one cannot.

A balance does not change by a single unit: it is the checkpoint plus the
postings after it, and only postings already in the checkpoint may leave.
``Ledger.verify_checkpoints`` goes on proving the cache against the truth,
which is now the postings still here plus ``archive_total``.

The archive files are plain SQLite, one table for each kind of row, readable
with the same tools as the world. Managing them (rolling to a new file when
one is full, compressing closed ones, keeping the folder under a size) is
at the bottom of this module and touches no database.
"""

from __future__ import annotations

import gzip
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import transaction
from .errors import LedgerImbalance

#: The newest trades at each market for each commodity never leave: the last
#: price is read from the newest, and the chart from the newest forty.
TAPE_KEEP = 64

#: An archive file is closed and a new one begun once it is this big.
ROTATE_BYTES = 1_000_000_000

_FILE = re.compile(r"^ledger-(\d{6})\.db(\.gz)?$")

_ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS arc.txn (
    id INTEGER PRIMARY KEY, kind TEXT, game_time TEXT, ref TEXT, memo TEXT);
CREATE TABLE IF NOT EXISTS arc.posting (
    id INTEGER PRIMARY KEY, txn_id INTEGER, account_id TEXT, asset TEXT,
    amount INTEGER);
CREATE TABLE IF NOT EXISTS arc.trade (
    id INTEGER PRIMARY KEY, node TEXT, asset TEXT, price INTEGER,
    qty_kg INTEGER, buy_order_id TEXT, sell_order_id TEXT, txn_id INTEGER,
    game_time TEXT);
CREATE TABLE IF NOT EXISTS arc.book_order (
    id TEXT PRIMARY KEY, node TEXT, asset TEXT, side TEXT, price INTEGER,
    qty_kg INTEGER, remaining_kg INTEGER, account_id TEXT, escrow_id TEXT,
    status TEXT, placed_at TEXT, seq INTEGER);
CREATE TABLE IF NOT EXISTS arc.account (
    id TEXT PRIMARY KEY, kind TEXT, label TEXT, created_at TEXT);
"""


@dataclass(frozen=True)
class Archived:
    """What one step moved. All zero when there was nothing old enough."""

    txns: int = 0
    postings: int = 0
    trades: int = 0
    orders: int = 0
    accounts: int = 0
    through_txn: int = 0
    why_not: str = ""

    def __bool__(self) -> bool:
        return self.txns > 0


def backlog(db: sqlite3.Connection, keep_txns: int) -> int:
    """How many transactions are old enough to go and still here."""
    mark = db.execute("SELECT through_txn FROM archive_mark WHERE id = 1"
                      ).fetchone()[0]
    top = db.execute("SELECT COALESCE(MAX(id), 0) FROM txn").fetchone()[0]
    return max(0, top - keep_txns - mark)


def archive_step(db: sqlite3.Connection, archive_file: str | Path,
                 keep_txns: int, max_txns: int) -> Archived:
    """Move one batch of old history into ``archive_file``. See the module.

    ``keep_txns`` is how many of the newest transactions always stay.
    ``max_txns`` bounds the batch, so that a large backlog is worked off a
    little between each of the world's hours and never holds one up.
    """
    if db.in_transaction:
        raise RuntimeError("archive_step runs between transactions, not in one")
    mark, seq_mark = db.execute(
        "SELECT through_txn, through_seq FROM archive_mark WHERE id = 1"
    ).fetchone()
    top = db.execute("SELECT COALESCE(MAX(id), 0) FROM txn").fetchone()[0]
    cut = min(top - keep_txns, mark + max_txns)
    if cut <= mark:
        return Archived(through_txn=mark, why_not="nothing is old enough")

    # Only postings already in the balance checkpoint may leave: a balance
    # is the checkpoint plus the postings after it.
    newest = db.execute(
        "SELECT COALESCE(MAX(id), 0) FROM posting "
        "WHERE txn_id > ? AND txn_id <= ?", (mark, cut)).fetchone()[0]
    checkpointed = db.execute(
        "SELECT through_posting FROM checkpoint_mark WHERE id = 1"
    ).fetchone()[0]
    if newest > checkpointed:
        return Archived(through_txn=mark,
                        why_not="the checkpoint has not reached them yet")

    db.execute("ATTACH DATABASE ? AS arc", (str(archive_file),))
    try:
        # The copy must be on the disk before anything is removed here.
        db.execute("PRAGMA arc.synchronous = FULL")
        db.executescript(_ARCHIVE_SCHEMA)
        _choose(db, mark, cut, seq_mark)
        with transaction(db):            # the copy, committed on its own
            _copy(db, mark, cut)
        with transaction(db):            # then, and only then, the removal
            moved = _remove(db, mark, cut)
    finally:
        db.execute("DETACH DATABASE arc")
    return moved


def _choose(db: sqlite3.Connection, mark: int, cut: int, seq_mark: int
            ) -> None:
    """Write down, once, exactly which rows this step moves."""
    for name in ("go_trade", "go_txn", "go_order", "go_account"):
        db.execute(f"DROP TABLE IF EXISTS temp.{name}")
    # Trades at or below the cut, but for the newest TAPE_KEEP at each
    # market for each commodity. Only markets with a trade that old are
    # looked at, and each through the tape's own index, so this costs the
    # same however long the tape has grown.
    db.execute("DROP TABLE IF EXISTS temp.keep_trade")
    db.execute("CREATE TEMP TABLE keep_trade (id INTEGER PRIMARY KEY)")
    for market in db.execute(
            "SELECT DISTINCT node, asset FROM trade WHERE txn_id <= ?",
            (cut,)).fetchall():
        db.execute(
            "INSERT OR IGNORE INTO keep_trade (id) SELECT id FROM trade "
            "WHERE node = ? AND asset = ? ORDER BY id DESC LIMIT ?",
            (market["node"], market["asset"], TAPE_KEEP))
    db.execute(
        "CREATE TEMP TABLE go_trade AS SELECT id FROM trade WHERE txn_id <= ? "
        "AND id NOT IN (SELECT id FROM keep_trade)", (cut,))
    db.execute("CREATE UNIQUE INDEX temp.go_trade_id ON go_trade (id)")
    # Transactions at or below the cut that no remaining trade records.
    # Their postings all go, whichever way this falls.
    db.execute(
        "CREATE TEMP TABLE go_txn AS SELECT id FROM txn WHERE id <= ? "
        "AND id NOT IN (SELECT txn_id FROM trade WHERE txn_id <= ? "
        "               AND id NOT IN (SELECT id FROM go_trade))", (cut, cut))
    db.execute("CREATE UNIQUE INDEX temp.go_txn_id ON go_txn (id)")
    # Closed orders: placed no later than the cut, nothing left in escrow,
    # no posting of theirs staying behind and no remaining trade naming them.
    # An order is placed by the transaction that locks its escrow, which
    # carries the order's id, and orders are numbered in the order they are
    # placed: so the highest-numbered order placed in this batch marks how
    # far up the book everything is at or before the cut.
    placed = db.execute(
        "SELECT MAX(o.seq) FROM txn t JOIN book_order o ON o.id = t.ref "
        "WHERE t.id > ? AND t.id <= ? AND t.kind = 'escrow_lock'",
        (mark, cut)).fetchone()[0]
    seq_to = max(seq_mark, placed or 0)
    db.execute(
        "CREATE TEMP TABLE go_order AS SELECT o.id, o.escrow_id "
        "FROM book_order o WHERE o.seq <= ? AND o.status != 'OPEN' "
        "AND NOT EXISTS (SELECT 1 FROM posting p WHERE p.account_id = "
        "                o.escrow_id AND p.txn_id > ?) "
        "AND NOT EXISTS (SELECT 1 FROM balance_checkpoint c "
        "                WHERE c.account_id = o.escrow_id) "
        "AND NOT EXISTS (SELECT 1 FROM trade t WHERE t.buy_order_id = o.id "
        "                AND t.id NOT IN (SELECT id FROM go_trade)) "
        "AND NOT EXISTS (SELECT 1 FROM trade t WHERE t.sell_order_id = o.id "
        "                AND t.id NOT IN (SELECT id FROM go_trade))",
        (seq_to, cut))
    db.execute("CREATE UNIQUE INDEX temp.go_order_id ON go_order (id)")
    # Their escrow accounts: made for the one order, empty, used by no other.
    db.execute(
        "CREATE TEMP TABLE go_account AS SELECT a.id FROM account a "
        "JOIN go_order g ON g.escrow_id = a.id WHERE a.kind = 'escrow' "
        "AND NOT EXISTS (SELECT 1 FROM book_order o WHERE "
        "  (o.escrow_id = a.id OR o.account_id = a.id) "
        "  AND o.id NOT IN (SELECT id FROM go_order))")
    db.execute("CREATE TEMP TABLE IF NOT EXISTS go_seq (seq INTEGER)")
    db.execute("DELETE FROM go_seq")
    db.execute("INSERT INTO go_seq (seq) VALUES (?)", (seq_to,))


def _copy(db: sqlite3.Connection, mark: int, cut: int) -> None:
    db.execute("INSERT OR IGNORE INTO arc.txn SELECT * FROM txn "
               "WHERE id > ? AND id <= ?", (mark, cut))
    db.execute("INSERT OR IGNORE INTO arc.posting SELECT * FROM posting "
               "WHERE txn_id > ? AND txn_id <= ?", (mark, cut))
    db.execute("INSERT OR IGNORE INTO arc.trade SELECT * FROM trade "
               "WHERE id IN (SELECT id FROM go_trade)")
    db.execute("INSERT OR IGNORE INTO arc.book_order SELECT * FROM book_order "
               "WHERE id IN (SELECT id FROM go_order)")
    db.execute("INSERT OR IGNORE INTO arc.account SELECT * FROM account "
               "WHERE id IN (SELECT id FROM go_account)")


def _remove(db: sqlite3.Connection, mark: int, cut: int) -> Archived:
    # Whole transactions leave, and a transaction sums to nothing for each
    # asset it touches. If this batch does not, something is wrong with the
    # ledger itself and nothing may be removed.
    uneven = db.execute(
        "SELECT asset, SUM(amount) AS total FROM posting "
        "WHERE txn_id > ? AND txn_id <= ? GROUP BY asset HAVING total != 0",
        (mark, cut)).fetchall()
    if uneven:
        raise LedgerImbalance(
            "postings to archive do not sum to zero: "
            f"{ {r['asset']: r['total'] for r in uneven} }")
    # Every one of them must be in the archive before it leaves here.
    here = db.execute("SELECT COUNT(*) FROM posting WHERE txn_id > ? "
                      "AND txn_id <= ?", (mark, cut)).fetchone()[0]
    there = db.execute("SELECT COUNT(*) FROM arc.posting WHERE txn_id > ? "
                       "AND txn_id <= ?", (mark, cut)).fetchone()[0]
    if here != there:
        raise LedgerImbalance(
            f"the archive holds {there} of {here} postings; nothing removed")
    db.execute(
        "INSERT INTO archive_total (account_id, asset, amount) "
        "SELECT account_id, asset, SUM(amount) FROM posting "
        "WHERE txn_id > ? AND txn_id <= ? GROUP BY account_id, asset "
        "ON CONFLICT (account_id, asset) "
        "DO UPDATE SET amount = amount + excluded.amount", (mark, cut))
    db.execute("DELETE FROM archive_total WHERE amount = 0")
    seq_to = db.execute("SELECT seq FROM go_seq").fetchone()[0]
    db.execute("UPDATE archive_mark SET through_txn = ?, through_seq = ? "
               "WHERE id = 1", (cut, seq_to))
    counts = {}
    for name, sql in (
        ("postings", "DELETE FROM posting WHERE txn_id > ? AND txn_id <= ?"),
        ("trades", "DELETE FROM trade WHERE id IN (SELECT id FROM go_trade)"),
        ("txns", "DELETE FROM txn WHERE id IN (SELECT id FROM go_txn)"),
        ("orders", "DELETE FROM book_order WHERE id IN "
                   "(SELECT id FROM go_order)"),
        ("accounts", "DELETE FROM account WHERE id IN "
                     "(SELECT id FROM go_account)"),
    ):
        args = (mark, cut) if name == "postings" else ()
        counts[name] = db.execute(sql, args).rowcount
    return Archived(through_txn=cut, **counts)


# -- the archive files --------------------------------------------------------------

def _numbered(folder: Path) -> list[tuple[int, Path]]:
    found = []
    for path in folder.iterdir() if folder.is_dir() else ():
        match = _FILE.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found)


def current_file(folder: str | Path, rotate_bytes: int = ROTATE_BYTES) -> Path:
    """The archive file to write to: the newest, or a new one if that is full.

    Files are numbered and only ever the highest-numbered one is written,
    so anything with a lower number is closed and safe to compress.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = _numbered(folder)
    if not files:
        return folder / "ledger-000001.db"
    number, path = files[-1]
    if path.suffix == ".gz" or path.stat().st_size >= rotate_bytes:
        return folder / f"ledger-{number + 1:06d}.db"
    return path


def compress_closed(folder: str | Path) -> list[Path]:
    """Compress every archive file but the one being written. Returns them.

    Safe to run from another thread while the world runs: it only touches
    files with a lower number than the newest, which nothing writes again.
    """
    folder = Path(folder)
    files = _numbered(folder)
    done = []
    for number, path in files[:-1]:
        if path.suffix == ".gz":
            continue
        packed, part = path.with_name(path.name + ".gz"), path.with_name(
            path.name + ".gz.part")
        with open(path, "rb") as src, gzip.open(part, "wb", 6) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        os.replace(part, packed)        # whole, or not there at all
        path.unlink()
        done.append(packed)
    return done


def enforce_cap(folder: str | Path, cap_bytes: int) -> list[Path]:
    """Keep the folder under ``cap_bytes`` by removing the oldest compressed
    files. Never the file being written. Returns what was removed.

    This is where history is finally let go: what is removed here exists
    nowhere else unless somebody copied it off the machine first.
    """
    folder = Path(folder)
    files = _numbered(folder)
    total = sum(p.stat().st_size for _, p in files)
    gone = []
    for _, path in files[:-1]:
        if total <= cap_bytes:
            break
        if path.suffix != ".gz":
            continue
        total -= path.stat().st_size
        path.unlink()
        gone.append(path)
    return gone
