"""Moving old history out of the live ledger file (market/archive.py).

The property test in test_conservation.py archives at random moments and
checks that no balance moves. These are the particular promises: the price
and the chart survive, a crash between the copy and the removal loses
nothing, only what is in the checkpoint may leave, and the ledger is still
append-only against everything but the archive step itself.
"""
from __future__ import annotations

import gzip
import sqlite3

import pytest

from market import archive
from market.archive import (TAPE_KEEP, archive_step, backlog, compress_closed,
                            current_file, enforce_cap)
from market.book import ASK, BID
from market.db import transaction
from market.errors import LedgerImbalance
from market.money import CREDIT

T0 = "2190-01-01T00:00:00Z"
TONNE = 1_000


def trade(book, seller, buyer, price=100_000, when=T0):
    """One tonne of ice changes hands: an ask rests, a bid takes it."""
    book.place("ICE", ASK, price, TONNE, seller, when)
    return book.place("ICE", BID, price, TONNE, buyer, when)


def fold(db, ledger):
    with transaction(db):
        ledger.checkpoint()


def rows(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def read(path, sql):
    arc = sqlite3.connect(str(path))
    try:
        return arc.execute(sql).fetchall()
    finally:
        arc.close()


@pytest.fixture
def busy(db, ledger, book, trader, tmp_path):
    """A market with a hundred trades behind it and one order still resting."""
    alice = trader("alice", credits=50_000_000, ICE=200 * TONNE)
    bob = trader("bob", credits=50_000_000, ICE=200 * TONNE)
    for n in range(100):
        trade(book, alice, bob, price=100_000 + n, when=f"2190-01-01T{n // 60:02d}:{n % 60:02d}:00Z")
    resting = book.place("ICE", BID, 50_000, 3 * TONNE, bob, "2190-01-01T02:00:00Z")
    fold(db, ledger)
    return db, ledger, book, alice, bob, resting.order_id, tmp_path / "ledger-000001.db"


def test_balances_the_price_and_the_chart_are_untouched(busy):
    db, ledger, book, alice, bob, resting, path = busy
    before = {who: ledger.holdings(who) for who in (alice, bob)}
    last, depth = book.last_price("ICE"), book.depth("ICE", BID, 8)
    tape = db.execute("SELECT id, price FROM trade ORDER BY id DESC LIMIT 40").fetchall()
    made, burned = ledger.credits_in_existence(), ledger.credits_destroyed()
    had = {t: rows(db, t) for t in ("txn", "posting", "trade", "book_order", "account")}

    moved = archive_step(db, path, keep_txns=0, max_txns=10**9)

    assert moved and moved.txns > 0 and moved.postings == had["posting"]
    assert rows(db, "posting") == 0, "every posting was old enough and in the checkpoint"
    assert {who: ledger.holdings(who) for who in (alice, bob)} == before
    assert ledger.credits_in_existence() == made and ledger.credits_destroyed() == burned
    assert ledger.verify_checkpoints() == []
    ledger.assert_conserved()
    assert book.last_price("ICE") == last and book.depth("ICE", BID, 8) == depth
    assert db.execute("SELECT id, price FROM trade ORDER BY id DESC LIMIT 40"
                      ).fetchall() == tape, "the chart reads the same forty trades"
    assert rows(db, "trade") == TAPE_KEEP and moved.trades == had["trade"] - TAPE_KEEP
    # the closed orders and their escrow accounts went with them, but for
    # the ones the remaining trades still name
    assert moved.orders == moved.accounts > 0
    assert rows(db, "book_order") == had["book_order"] - moved.orders
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    # and all of it is in the archive, whole
    assert read(path, "SELECT COUNT(*) FROM posting")[0][0] == had["posting"]
    assert read(path, "SELECT COUNT(*) FROM txn")[0][0] == had["txn"]
    assert read(path, "SELECT asset, SUM(amount) FROM posting GROUP BY asset "
                      "HAVING SUM(amount) != 0") == []


def test_an_order_resting_across_the_cut_is_still_an_order(busy):
    db, ledger, book, alice, bob, resting, path = busy
    held = ledger.balance(bob, CREDIT)
    archive_step(db, path, keep_txns=0, max_txns=10**9)
    row = db.execute("SELECT status, escrow_id FROM book_order WHERE id = ?",
                     (resting,)).fetchone()
    assert row["status"] == "OPEN"
    assert ledger.balance(row["escrow_id"], CREDIT) == 3 * 50_000
    # it can be hit...
    fill = book.place("ICE", ASK, 50_000, TONNE, alice, T0)
    assert fill.fills and ledger.balance(row["escrow_id"], CREDIT) == 2 * 50_000
    # ...and what is left comes home when it is cancelled
    assert book.cancel(resting, T0) == 2 * 50_000
    assert ledger.balance(bob, CREDIT) == held + 2 * 50_000
    ledger.assert_conserved()
    assert ledger.verify_checkpoints() == []
    # While the trade it made is among the newest on the tape it is kept,
    # because that trade names it.
    fold(db, ledger)
    archive_step(db, path, keep_txns=0, max_txns=10**9)
    assert db.execute("SELECT 1 FROM book_order WHERE id = ?", (resting,)).fetchone()
    # Once the tape has moved on, it goes like the rest.
    for _ in range(TAPE_KEEP):
        trade(book, alice, bob)
    fold(db, ledger)
    archive_step(db, path, keep_txns=0, max_txns=10**9)
    assert db.execute("SELECT 1 FROM book_order WHERE id = ?", (resting,)).fetchone() is None
    assert db.execute("SELECT 1 FROM account WHERE id = ?", (row["escrow_id"],)).fetchone() is None
    assert read(path, f"SELECT status FROM book_order WHERE id = '{resting}'") == [("CANCELLED",)]


def test_the_newest_stay_and_a_backlog_is_worked_off_a_step_at_a_time(busy):
    db, ledger, book, alice, bob, resting, path = busy
    top = db.execute("SELECT MAX(id) FROM txn").fetchone()[0]
    assert backlog(db, keep_txns=50) == top - 50
    steps = 0
    while archive_step(db, path, keep_txns=50, max_txns=40):
        steps += 1
        assert ledger.verify_checkpoints() == []
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert steps == -(-(top - 50) // 40)
    assert backlog(db, keep_txns=50) == 0
    assert db.execute("SELECT MIN(txn_id) FROM posting").fetchone()[0] == top - 49
    assert not archive_step(db, path, keep_txns=50, max_txns=40), "nothing more to do"


def test_only_what_is_in_the_checkpoint_may_leave(db, ledger, book, trader, tmp_path):
    alice, bob = trader("alice", ICE=10 * TONNE), trader("bob", credits=10_000_000)
    trade(book, alice, bob)
    path = tmp_path / "ledger-000001.db"
    refused = archive_step(db, path, keep_txns=0, max_txns=10**9)
    assert not refused and "checkpoint" in refused.why_not
    assert rows(db, "posting") > 0 and not path.exists() or read(
        path, "SELECT COUNT(*) FROM sqlite_master")[0][0] == 0
    fold(db, ledger)
    assert archive_step(db, path, keep_txns=0, max_txns=10**9)
    assert ledger.balance(bob, "ICE") == TONNE


def test_a_crash_between_the_copy_and_the_removal_loses_nothing(busy):
    db, ledger, book, alice, bob, resting, path = busy
    before = {who: ledger.holdings(who) for who in (alice, bob)}
    posts = rows(db, "posting")
    real = archive._remove

    def dies(*args):
        raise RuntimeError("the power went")

    archive._remove = dies
    try:
        with pytest.raises(RuntimeError, match="the power went"):
            archive_step(db, path, keep_txns=0, max_txns=10**9)
    finally:
        archive._remove = real
    # the copy was made and nothing was removed: the live file is as it was
    assert rows(db, "posting") == posts and rows(db, "archive_total") == 0
    assert db.execute("SELECT through_txn FROM archive_mark").fetchone()[0] == 0
    assert read(path, "SELECT COUNT(*) FROM posting")[0][0] == posts
    assert not db.in_transaction
    # the next step copies again, is told the rows are there, and finishes
    assert archive_step(db, path, keep_txns=0, max_txns=10**9)
    assert read(path, "SELECT COUNT(*) FROM posting")[0][0] == posts, "copied once, not twice"
    assert rows(db, "posting") == 0
    assert {who: ledger.holdings(who) for who in (alice, bob)} == before
    assert ledger.verify_checkpoints() == []


def test_the_ledger_is_still_append_only_to_everything_else(busy):
    db, ledger, book, alice, bob, resting, path = busy
    archive_step(db, path, keep_txns=40, max_txns=10**9)
    assert rows(db, "posting") > 0
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM posting")
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM posting WHERE id = (SELECT MIN(id) FROM posting)")
    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE posting SET amount = amount + 1")
    # and the step itself will not run inside somebody else's transaction
    with transaction(db):
        with pytest.raises(RuntimeError, match="between transactions"):
            archive_step(db, path, keep_txns=0, max_txns=10**9)


def test_a_batch_that_does_not_balance_stops_everything(busy):
    db, ledger, book, alice, bob, resting, path = busy
    # a ledger somebody has tampered with: one leg of a transaction altered
    db.execute("DROP TRIGGER posting_is_append_only_update")
    db.execute("UPDATE posting SET amount = amount + 1 WHERE id = 5")
    posts = rows(db, "posting")
    with pytest.raises(LedgerImbalance, match="do not sum to zero"):
        archive_step(db, path, keep_txns=0, max_txns=10**9)
    assert rows(db, "posting") == posts, "nothing is removed from a ledger that is wrong"
    assert db.execute("SELECT through_txn FROM archive_mark").fetchone()[0] == 0


# -- the files ----------------------------------------------------------------------

def test_archive_files_roll_over_are_compressed_and_kept_under_a_size(tmp_path):
    folder = tmp_path / "archive"
    first = current_file(folder)
    assert first.name == "ledger-000001.db" and folder.is_dir()
    first.write_bytes(b"a" * 5000)
    assert current_file(folder, rotate_bytes=10_000) == first, "not full yet"
    second = current_file(folder, rotate_bytes=4_000)
    assert second.name == "ledger-000002.db"
    second.write_bytes(b"b" * 5000)
    third = current_file(folder, rotate_bytes=4_000)
    third.write_bytes(b"c" * 100)

    packed = compress_closed(folder)
    assert [p.name for p in packed] == ["ledger-000001.db.gz", "ledger-000002.db.gz"]
    assert not first.exists() and not second.exists() and third.exists(), \
        "the file being written is left alone"
    assert gzip.open(packed[0]).read() == b"a" * 5000
    assert compress_closed(folder) == [], "once"
    assert current_file(folder, rotate_bytes=4_000) == third

    size = sum(p.stat().st_size for p in folder.iterdir())
    assert enforce_cap(folder, size) == []
    gone = enforce_cap(folder, size - 1)
    assert [p.name for p in gone] == ["ledger-000001.db.gz"], "the oldest goes first"
    assert enforce_cap(folder, 0) == [packed[1]]
    assert third.exists(), "never the file being written, whatever the cap"
    # a folder whose newest file is already compressed starts a new one
    third.unlink()
    (folder / "ledger-000007.db.gz").write_bytes(b"z")
    assert current_file(folder).name == "ledger-000008.db"
