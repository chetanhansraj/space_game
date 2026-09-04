"""The Ark Authority: a market maker of last resort that dissolves itself.

The bible: "The Ark maintains a standing bid and ask on every commodity with
a deliberately wide spread. It will always buy at a floor and always sell at
a ceiling." Two things this achieves -- on day one a lone player has a
functioning market with no other participants, and over time, as real players
and agents quote inside that spread, the Authority's volume falls toward zero
without anyone flipping a switch.

Nothing here is special-cased in the matching engine. The Authority is an
ordinary institutional account placing ordinary limit orders that escrow like
everyone else's. Anyone quoting inside its spread simply gets hit first by
price priority, which is exactly how the training wheels come off on their
own.

**It has a finite treasury, and this matters.** "Always buys at a floor" read
literally means unlimited credits, which is a printing press wearing an
institution's clothes -- and invariant 3 exists precisely to stop that. So the
Authority is funded once from genesis, in a single auditable transaction, and
trades against real holdings from then on. Its bid is backed by credits it
actually has and its ask by goods it actually owns. If a sustained crash
drains its treasury, the floor thins and then disappears, which is a genuine
economic event rather than a bug -- and the players who sold into it were paid
with real money the whole way down.

Spread values are set in docs/DECISIONS.md D33; seed-data left them open.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .book import ASK, BID, OrderBook
from .ledger import Ledger
from .money import CREDIT

ACCOUNT = "institution:ark_authority"

#: Fractions of a commodity's base value, in percent, kept as integers so
#: that quote prices are exact. A bid at 60% and an ask at 175% is roughly a
#: 3x spread: wide enough that any serious quote beats it, tight enough that
#: day-one prices are not meaningless.
BID_PERCENT = 60
ASK_PERCENT = 175


@dataclass(frozen=True)
class Quote:
    asset: str
    bid_price: int
    ask_price: int
    bid_kg: int
    ask_kg: int


def bid_price(base_value: int) -> int:
    """Floor price, in credits per lot. Integer division, floors downward."""
    return max(1, base_value * BID_PERCENT // 100)


def ask_price(base_value: int) -> int:
    """Ceiling price, in credits per lot."""
    return max(2, base_value * ASK_PERCENT // 100)


class ArkAuthority:
    """Maintains standing quotes at one node."""

    def __init__(self, db: sqlite3.Connection, ledger: Ledger,
                 book: OrderBook) -> None:
        self.db = db
        self.ledger = ledger
        self.book = book

    def establish(self, game_time: str, treasury: int) -> None:
        """Open the account and fund it. Once, at world creation.

        This is one of the few legitimate uses of ``mint``, and the reason is
        recorded permanently against ``world:genesis``.
        """
        try:
            self.ledger.open_account(ACCOUNT, "institution", game_time,
                                     label="Ark Authority")
        except sqlite3.IntegrityError:
            pass  # already established
        if self.ledger.balance(ACCOUNT, CREDIT) == 0 and treasury > 0:
            self.ledger.mint(ACCOUNT, treasury, game_time,
                             memo="Ark Authority treasury, world genesis")

    def endow(self, asset_symbol: str, qty_kg: int, game_time: str) -> None:
        """Give the Authority opening inventory so its ask is real.

        Booked as extraction rather than conjured: the goods came out of the
        ground like everything else, and ``world:extraction`` records it.
        """
        self.ledger.extract(ACCOUNT, asset_symbol, qty_kg, game_time,
                            memo="Ark Authority opening inventory")

    def quote(self, asset_symbol: str, game_time: str,
              bid_lots: int = 50, ask_lots: int = 50) -> Quote:
        """Refresh the standing quote: cancel the old, place what it can afford.

        Sizes are capped by what the Authority actually holds. A bid is
        trimmed to the treasury; an ask is trimmed to inventory. Neither is
        ever a promise it cannot keep.
        """
        asset = self.ledger.asset(asset_symbol)
        self.withdraw(asset_symbol, game_time)

        bid = bid_price(asset.base_value)
        ask = ask_price(asset.base_value)

        affordable_lots = self.ledger.balance(ACCOUNT, CREDIT) // bid
        bid_lots = min(bid_lots, affordable_lots)

        held_lots = self.ledger.balance(ACCOUNT, asset.symbol) // asset.lot_mass_kg
        ask_lots = min(ask_lots, held_lots)

        bid_kg = ask_kg = 0
        if bid_lots > 0:
            bid_kg = asset.kg(bid_lots)
            self.book.place(asset.symbol, BID, bid, bid_kg, ACCOUNT, game_time)
        if ask_lots > 0:
            ask_kg = asset.kg(ask_lots)
            self.book.place(asset.symbol, ASK, ask, ask_kg, ACCOUNT, game_time)

        return Quote(asset=asset.symbol, bid_price=bid, ask_price=ask,
                     bid_kg=bid_kg, ask_kg=ask_kg)

    def withdraw(self, asset_symbol: str, game_time: str) -> None:
        """Pull the Authority's resting orders for one commodity."""
        rows = self.db.execute(
            "SELECT id FROM book_order WHERE node = ? AND asset = ? "
            "AND account_id = ? AND status = 'OPEN'",
            (self.book.node, asset_symbol, ACCOUNT),
        ).fetchall()
        for row in rows:
            self.book.cancel(row["id"], game_time)

    def share_of_volume(self, asset_symbol: str) -> float:
        """Fraction of traded mass the Authority was on one side of.

        The number that should fall toward zero as the world fills up. This
        is the metric that says whether the training wheels are coming off,
        and it is worth watching from the first simulation run.
        """
        row = self.db.execute(
            """
            SELECT
              COALESCE(SUM(t.qty_kg), 0) AS total,
              COALESCE(SUM(CASE WHEN b.account_id = :acct OR s.account_id = :acct
                                THEN t.qty_kg ELSE 0 END), 0) AS ours
            FROM trade t
            JOIN book_order b ON b.id = t.buy_order_id
            JOIN book_order s ON s.id = t.sell_order_id
            WHERE t.node = :node AND t.asset = :asset
            """,
            {"acct": ACCOUNT, "node": self.book.node, "asset": asset_symbol},
        ).fetchone()
        total = int(row["total"])
        return 0.0 if total == 0 else int(row["ours"]) / total
