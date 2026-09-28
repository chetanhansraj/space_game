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


class Exchange(RuleBasedStateMachine):
    """A market being used, roughly, by people who do not read documentation."""

    def __init__(self) -> None:
        super().__init__()
        self.db = connect(":memory:")
        self.ledger = Ledger(self.db)
        self.book = OrderBook(self.db, self.ledger, NODE)
        self.minted = 0

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

    # -- what must always be true ----------------------------------------

    @invariant()
    def the_balance_cache_agrees_with_the_raw_ledger(self):
        assert self.ledger.verify_checkpoints() == []
        for who in TRADERS + (ARK,):
            for asset in (CREDIT,) + TRADED:
                raw = self.db.execute(
                    "SELECT COALESCE(SUM(amount), 0) FROM posting "
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
            "FROM posting p JOIN account a ON a.id = p.account_id "
            "GROUP BY p.account_id, p.asset HAVING b < 0"
        ).fetchall()
        offenders = [dict(r) for r in rows if r["kind"] != "world"]
        assert not offenders, offenders

    @invariant()
    def credits_add_up(self):
        """Everything outside the world equals what was minted, less sinks."""
        row = self.db.execute(
            "SELECT COALESCE(SUM(p.amount), 0) AS held FROM posting p "
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
            "FROM book_order o JOIN posting p ON p.account_id = o.escrow_id "
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

    def _open_orders(self) -> list[str]:
        return [
            r["id"] for r in self.db.execute(
                "SELECT id FROM book_order WHERE status = 'OPEN'"
            ).fetchall()
        ]

    def teardown(self) -> None:
        self.db.close()


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
