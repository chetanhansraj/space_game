"""Bankruptcy, liquidation and re-entry. Implements docs/DECISIONS.md D37.

A firm that cannot meet its obligations is wound up. Its holdings are sold
into the live order book at whatever the market will pay -- no reserve price,
no institutional bailout, no special case in the matching engine. Rivals and
players bid like anyone else, so a bankruptcy is a buying opportunity for
whoever has capital and nerve.

Two halves of D37 live here. The third -- the owner taking a berth on someone
else's ship and earning their way back -- needs ships and crew, so it lands
with v3. The design is fixed now because it changes how risk should be tuned
everywhere before then.

Population regeneration deserves a note. A world where firms only ever die
empties itself, so something has to replace them. Minting capital for new
entrants would be inflation with extra steps, and having the Ark fund them
makes the institution a charity. Instead a **prosperous firm spins off a
competitor out of its own balance sheet** once it clears a wealth threshold.
No credits are created, and it is self-balancing: concentration produces
entrants, entrants produce competition, competition erodes concentration.
"""

from __future__ import annotations

from dataclasses import dataclass

from market.book import ASK, OrderBook
from market.db import transaction
from market.errors import MarketError
from market.ledger import Ledger
from market.money import CREDIT

#: A firm is wound up once it cannot cover this many days of upkeep.
INSOLVENCY_GRACE_DAYS = 3

#: A firm spins off a competitor once it holds this multiple of its starting
#: capital, seeding the new entrant with this share of its own balance.
SPINOFF_THRESHOLD = 4
SPINOFF_SHARE = 4  # one quarter


@dataclass
class Liquidation:
    firm_id: str
    orders_cancelled: int
    assets_listed: dict[str, int]


@dataclass
class Spinoff:
    parent_id: str
    child_id: str
    capital: int


class Receiver:
    """Winds up failed firms and lets successful ones spawn rivals."""

    def __init__(self, ledger: Ledger, books: dict[str, OrderBook]) -> None:
        self.ledger = ledger
        self.books = books

    def is_insolvent(self, firm, ) -> bool:
        """Broke means unable to fund the grace period, not merely poor."""
        required = firm.upkeep_per_day * INSOLVENCY_GRACE_DAYS
        return self.ledger.balance(firm.account, CREDIT) < required

    def liquidate(self, firm, game_time: str) -> Liquidation:
        """Cancel the firm's orders and dump its holdings onto the book.

        Sold as aggressive asks a long way under the reference price, which is
        the honest representation of a forced sale: a receiver takes what the
        book will give today. Anything that does not clear stays listed and
        fills later, or does not.
        """
        book = self.books[firm.node]

        cancelled = 0
        for row in book.open_orders(firm.account):
            try:
                book.cancel(row["id"], game_time)
                cancelled += 1
            except MarketError:
                pass

        listed: dict[str, int] = {}
        for asset, held in self.ledger.holdings(firm.account).items():
            if asset == CREDIT or held <= 0:
                continue
            spec = self.ledger.asset(asset)
            lots = held // spec.lot_mass_kg
            if lots < 1:
                continue
            reference = book.last_price(asset) or spec.base_value
            fire_sale = max(1, int(reference * 0.6))
            try:
                book.place(asset, ASK, fire_sale, spec.kg(lots),
                           firm.account, game_time)
                listed[asset] = spec.kg(lots)
            except MarketError:
                pass

        firm.insolvent = True
        return Liquidation(firm_id=firm.id, orders_cancelled=cancelled,
                           assets_listed=listed)

    def should_spin_off(self, firm, starting_capital: int) -> bool:
        if firm.insolvent or starting_capital <= 0:
            return False
        return (self.ledger.balance(firm.account, CREDIT)
                >= starting_capital * SPINOFF_THRESHOLD)

    def spin_off(self, firm, child_id: str, child_account: str,
                 game_time: str) -> Spinoff:
        """Fund a new competitor from the parent's own balance sheet."""
        capital = self.ledger.balance(firm.account, CREDIT) // SPINOFF_SHARE
        with transaction(self.ledger.db):
            self.ledger.open_account(child_account, "agent", game_time,
                                     label=child_id)
            self.ledger.transfer(
                firm.account, child_account, CREDIT, capital,
                kind="spinoff", game_time=game_time, ref=child_id,
                memo=f"{firm.id} capitalises {child_id}",
            )
        return Spinoff(parent_id=firm.id, child_id=child_id, capital=capital)
