"""Conservation of credits and mass across arbitrary sequences of activity.

CLAUDE.md: "The market and ledger need property tests, not just examples.
Conservation of credits across any sequence of trades is the core invariant
to assert."

So this does not test a scenario. It generates thousands of them -- orders
placed and cancelled, partial fills, sweeps across levels, self-trades,
insufficient funds, fees burned, mass extracted and consumed, interleaved in
whatever order Hypothesis finds interesting -- and after every single step it
checks that nothing was created or destroyed except through a world account.

Because conservation is structural rather than enforced by this test, a
failure here means something has subverted the ledger's own rules. That is
worth stopping the world for, which is why ``LedgerImbalance`` says so.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from market.authority import ACCOUNT as ARK
from market import archive as archive_module
from market.authority import ArkAuthority
from market.book import ASK, BID, OrderBook
from market.db import connect, transaction
from market.errors import MarketError
from market.ledger import CONSUMPTION, EXTRACTION, GENESIS, SINK, Ledger
from market.money import CREDIT
from market.seed import COMMODITIES, seed_assets

T0 = "2190-01-01T00:00:00Z"
NODE = "shackleton_depot"
TRADERS = ("alice", "bob", "carol", "dan")
# One tonne-lot commodity and one kilogram-lot commodity, so both lot sizes
# get exercised by every generated sequence.
TRADED = ("ICE", "HE3")

WORLD = {GENESIS, SINK, EXTRACTION, CONSUMPTION}

#: Every posting there has ever been: those still in the live file, and the
#: sums of those the archive step has moved out of it. The tests below ask
#: their questions of this, so that archiving can never hide a discrepancy.
EVERY_POSTING = (
    "(SELECT account_id, asset, amount FROM posting "
    " UNION ALL SELECT account_id, asset, amount FROM archive_total)")


class Exchange(RuleBasedStateMachine):
    """A market being used, roughly, by people who do not read documentation."""

    def __init__(self) -> None:
        super().__init__()
        self.db = connect(":memory:")
        self.ledger = Ledger(self.db)
        self.book = OrderBook(self.db, self.ledger, NODE)
        self.minted = 0
        self.folder = Path(tempfile.mkdtemp(prefix="ark-archive-"))
        self.archive = self.folder / "ledger-000001.db"

    @initialize()
    def build_world(self) -> None:
        with transaction(self.db):
            self.ledger.bootstrap(T0)
            seed_assets(self.ledger)
            for name in TRADERS:
                self.ledger.open_account(name, "player", T0, label=name)
                self.ledger.mint(name, 5_000_000, T0, memo="test funding")
                self.minted += 5_000_000
                for symbol in TRADED:
                    self.ledger.extract(name, symbol, 500_000, T0)

    # -- things people do ------------------------------------------------

    @rule(
        who=st.sampled_from(TRADERS),
        asset=st.sampled_from(TRADED),
        side=st.sampled_from([BID, ASK]),
        price=st.integers(min_value=1, max_value=400_000),
        lots=st.integers(min_value=1, max_value=25),
    )
    def place(self, who, asset, side, price, lots):
        spec = next(a for a in COMMODITIES if a.symbol == asset)
        try:
            self.book.place(asset, side, price, spec.kg(lots), who, T0)
        except MarketError:
            # Refusals are fine and are themselves under test: a refused
            # order must leave the world untouched, which the invariants
            # below check on the very next step.
            pass

    @precondition(lambda self: self._open_orders())
    @rule(data=st.data())
    def cancel(self, data):
        orders = self._open_orders()
        chosen = data.draw(st.sampled_from(orders))
        try:
            self.book.cancel(chosen, T0)
        except MarketError:
            pass

    @rule(who=st.sampled_from(TRADERS),
          amount=st.integers(min_value=1, max_value=50_000))
    def pay_a_fee(self, who, amount):
        """Docking fees, upkeep, fuel. Invariant 7's drain."""
        try:
            with transaction(self.db):
                self.ledger.burn(who, amount, T0, memo="docking fee")
        except MarketError:
            pass

    @rule(who=st.sampled_from(TRADERS), asset=st.sampled_from(TRADED),
          qty=st.integers(min_value=1, max_value=20_000))
    def mine(self, who, asset, qty):
        with transaction(self.db):
            self.ledger.extract(who, asset, qty, T0, memo="extraction tick")

    @rule(who=st.sampled_from(TRADERS), asset=st.sampled_from(TRADED),
          qty=st.integers(min_value=1, max_value=20_000))
    def consume(self, who, asset, qty):
        try:
            with transaction(self.db):
                self.ledger.consume(who, asset, qty, T0, memo="life support")
        except MarketError:
            pass

    @rule()
    def take_a_checkpoint(self):
        """The server folds the ledger into its balance cache once a game day.

        Interleaved with everything else here, so a checkpoint lands between
        a bid and its cancel, mid-way through partial fills, and on top of
        escrow accounts that are about to close.
        """
        with transaction(self.db):
            self.ledger.checkpoint()

    @rule(keep=st.integers(min_value=0, max_value=12),
          most=st.integers(min_value=1, max_value=30),
          tape=st.integers(min_value=1, max_value=3),
          fold=st.booleans())
    def archive_old_history(self, keep, most, tape, fold):
        """The server moves old transactions out of the live file between
        hours. Here it does so at any moment, with almost nothing kept, so
        that the cut lands between a bid and its fill, on escrow accounts
        still open, and on the newest trades at a market (of which only
        ``tape`` are held back, where the server holds back sixty-four)."""
        if fold:
            with transaction(self.db):
                self.ledger.checkpoint()
        held, archive_module.TAPE_KEEP = archive_module.TAPE_KEEP, tape
        try:
            archive_module.archive_step(self.db, self.archive,
                                        keep_txns=keep, max_txns=most)
        finally:
            archive_module.TAPE_KEEP = held

    # -- what must always be true ----------------------------------------

    @invariant()
    def the_balance_cache_agrees_with_the_raw_ledger(self):
        assert self.ledger.verify_checkpoints() == []
        for who in TRADERS + (ARK,):
            for asset in (CREDIT,) + TRADED:
                raw = self.db.execute(
                    f"SELECT COALESCE(SUM(amount), 0) FROM {EVERY_POSTING} "
                    "WHERE account_id = ? AND asset = ?", (who, asset),
                ).fetchone()[0]
                assert self.ledger.balance(who, asset) == raw

    @invariant()
    def nothing_is_created_or_destroyed(self):
        self.ledger.assert_conserved()

    @invariant()
    def no_ordinary_account_is_overdrawn(self):
        rows = self.db.execute(
            "SELECT p.account_id, p.asset, SUM(p.amount) AS b, a.kind "
            f"FROM {EVERY_POSTING} p JOIN account a ON a.id = p.account_id "
            "GROUP BY p.account_id, p.asset HAVING b < 0"
        ).fetchall()
        offenders = [dict(r) for r in rows if r["kind"] != "world"]
        assert not offenders, offenders

    @invariant()
    def credits_add_up(self):
        """Everything outside the world equals what was minted, less sinks."""
        row = self.db.execute(
            "SELECT COALESCE(SUM(p.amount), 0) AS held "
            f"FROM {EVERY_POSTING} p "
            "JOIN account a ON a.id = p.account_id "
            "WHERE p.asset = ? AND a.kind != 'world'",
            (CREDIT,),
        ).fetchone()
        expected = self.ledger.credits_in_existence() - self.ledger.credits_destroyed()
        assert int(row["held"]) == expected

    @invariant()
    def closed_orders_hold_no_escrow(self):
        rows = self.db.execute(
            "SELECT o.id, o.escrow_id, p.asset, SUM(p.amount) AS b "
            f"FROM book_order o JOIN {EVERY_POSTING} p "
            "ON p.account_id = o.escrow_id "
            "WHERE o.status != 'OPEN' GROUP BY o.id, p.asset HAVING b != 0"
        ).fetchall()
        assert not rows, [dict(r) for r in rows]

    @invariant()
    def open_orders_are_fully_collateralised(self):
        """Every resting order's escrow still holds what it promised."""
        for row in self.db.execute(
            "SELECT * FROM book_order WHERE status = 'OPEN'"
        ).fetchall():
            spec = next(a for a in COMMODITIES if a.symbol == row["asset"])
            if row["side"] == BID:
                need = row["price"] * (row["remaining_kg"] // spec.lot_mass_kg)
                assert self.ledger.balance(row["escrow_id"], CREDIT) >= need
            else:
                held = self.ledger.balance(row["escrow_id"], row["asset"])
                assert held >= row["remaining_kg"]

    @invariant()
    def the_book_never_holds_a_nonpositive_order(self):
        bad = self.db.execute(
            "SELECT COUNT(*) c FROM book_order "
            "WHERE status = 'OPEN' AND (price <= 0 OR remaining_kg <= 0)"
        ).fetchone()
        assert bad["c"] == 0

    @invariant()
    def nothing_has_left_the_ledger_without_being_archived(self):
        """The live file and the archive together are the whole history:
        every transaction and every posting is in exactly one of them, and
        what the archive holds is what ``archive_total`` says left."""
        live_txn = {r[0] for r in self.db.execute("SELECT id FROM txn")}
        live_post = {r[0] for r in self.db.execute("SELECT id FROM posting")}
        gone_txn, gone_post, sums = set(), set(), {}
        if self.archive.exists():
            arc = sqlite3.connect(str(self.archive))
            gone_txn = {r[0] for r in arc.execute("SELECT id FROM txn")}
            gone_post = {r[0] for r in arc.execute("SELECT id FROM posting")}
            sums = {(a, s): t for a, s, t in arc.execute(
                "SELECT account_id, asset, SUM(amount) FROM posting "
                "GROUP BY account_id, asset HAVING SUM(amount) != 0")}
            # an archived transaction is whole: its postings came with it
            orphans = arc.execute(
                "SELECT COUNT(*) FROM posting WHERE txn_id NOT IN "
                "(SELECT id FROM txn)").fetchone()[0]
            arc.close()
            assert orphans == 0
        ever_txn = self.db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'txn'").fetchone()
        ever_post = self.db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'posting'").fetchone()
        assert live_txn | gone_txn == set(range(1, (ever_txn[0] if ever_txn else 0) + 1))
        assert live_post | gone_post == set(range(1, (ever_post[0] if ever_post else 0) + 1))
        assert not live_post & gone_post, "a posting is in one place, not two"
        total = {(r["account_id"], r["asset"]): r["amount"] for r in
                 self.db.execute("SELECT * FROM archive_total")}
        assert total == sums
        # and nothing still here points at something that is gone
        assert self.db.execute("PRAGMA foreign_key_check").fetchall() == []

    @invariant()
    def the_newest_trade_at_the_market_is_always_still_there(self):
        """The last price is read from the tape, so the tape's newest entry
        for each commodity must outlive any amount of archiving."""
        for asset in TRADED:
            ever = self.db.execute(
                "SELECT 1 FROM book_order WHERE asset = ? AND status = 'FILLED' "
                "LIMIT 1", (asset,)).fetchone()
            if ever:
                assert self.book.last_price(asset) is not None

    def _open_orders(self) -> list[str]:
        return [
            r["id"] for r in self.db.execute(
                "SELECT id FROM book_order WHERE status = 'OPEN'"
            ).fetchall()
        ]

    def teardown(self) -> None:
        self.db.close()
        shutil.rmtree(self.folder, ignore_errors=True)


Exchange.TestCase.settings = settings(
    max_examples=150,
    stateful_step_count=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
TestExchange = Exchange.TestCase


@given(
    ask_price=st.integers(min_value=1, max_value=10_000),
    premium=st.integers(min_value=0, max_value=5_000),
    lots=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=200, deadline=None)
def test_a_single_trade_moves_exactly_what_it_should(ask_price, premium, lots):
    """Narrower and sharper than the state machine: one crossing trade,
    checked to the credit, across the whole plausible price range.

    ``premium`` is how far the buyer crossed the spread. It must make no
    difference to what anyone ends up with, because the resting order sets
    the price -- so this also pins the escrow refund.
    """
    db = connect(":memory:")
    try:
        ledger = Ledger(db)
        book = OrderBook(db, ledger, NODE)
        with transaction(db):
            ledger.bootstrap(T0)
            seed_assets(ledger)
            ledger.open_account("seller", "player", T0)
            ledger.open_account("buyer", "player", T0)
            ledger.extract("seller", "ICE", lots * 1_000, T0)
            ledger.mint("buyer", 10_000_000_000, T0, memo="funding")

        book.place("ICE", ASK, ask_price, lots * 1_000, "seller", T0)
        book.place("ICE", BID, ask_price + premium, lots * 1_000, "buyer", T0)

        value = ask_price * lots
        assert ledger.balance("seller", CREDIT) == value
        assert ledger.balance("buyer", CREDIT) == 10_000_000_000 - value
        assert ledger.balance("buyer", "ICE") == lots * 1_000
        assert ledger.balance("seller", "ICE") == 0
        ledger.assert_conserved()
    finally:
        db.close()
