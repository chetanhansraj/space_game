"""Earth's standing order: the economy's only faucet.

The bible: "Earth is not in this game. It is the demand at the end of the
pipe: an enormous, wealthy, resource-exhausted customer that buys helium-3 and
platinum-group metals at a price that makes the entire off-world economy
viable. Players never go there. Earth exists as a standing order on the
exchange and as the reason anyone bothers."

Mechanically this is the **only source of credits after world genesis**, and
the sinks in `market.ledger` are the only drain. Together they are the money
supply, and the ratio between them is the single most important macro number
in the game. Nothing in the design documents states it, so it is flagged in
docs/DECISIONS.md D40 rather than quietly chosen here.

Earth's bid also anchors the price of everything else. Helium-3's seed value
is what Earth pays; every other commodity is priced against it through the
energy anchor. So this is not one participant among many -- it is the number
the whole board is denominated in.

v1 simplification: Earth bids at the node where helium-3 is produced. D21 puts
the real delivery point at Selene Station in low lunar orbit, which needs
ships, so that arrives with v2.
"""

from __future__ import annotations

from dataclasses import dataclass

from market.book import BID, OrderBook
from market.db import transaction
from market.errors import MarketError
from market.ledger import Ledger
from market.money import CREDIT

ACCOUNT = "institution:earth_standing_order"

#: What Earth will take per game day, per node, in lots. Finite on purpose:
#: an unbounded bid is an unbounded credit faucet.
DAILY_APPETITE_LOTS = 40


@dataclass
class StandingOrder:
    asset: str
    price: int
    lots: int


class EarthMarket:
    """Maintains Earth's standing bid at the nodes that can fill it."""

    def __init__(self, ledger: Ledger, books: dict[str, OrderBook]) -> None:
        self.ledger = ledger
        self.books = books

    def establish(self, game_time: str, funding: int) -> None:
        try:
            self.ledger.open_account(ACCOUNT, "institution", game_time,
                                     label="Earth standing order")
        except Exception:
            pass
        if self.ledger.balance(ACCOUNT, CREDIT) == 0 and funding > 0:
            self.ledger.mint(ACCOUNT, funding, game_time,
                             memo="Earth standing order funding, world genesis")

    def refresh(self, node: str, asset: str, game_time: str,
                lots: int = DAILY_APPETITE_LOTS) -> StandingOrder | None:
        """Replace Earth's bid at one node.

        Earth pays the seed anchor and does not haggle: its price is the
        definition of the commodity's value, not a negotiation over it. It
        buys what it can afford and no more.
        """
        spec = self.ledger.asset(asset)
        book = self.books[node]

        for row in book.open_orders(ACCOUNT):
            if row["asset"] == asset:
                try:
                    book.cancel(row["id"], game_time)
                except MarketError:
                    pass

        price = spec.base_value
        affordable = self.ledger.balance(ACCOUNT, CREDIT) // price
        lots = min(lots, affordable)
        if lots < 1:
            return None

        try:
            book.place(asset, BID, price, spec.kg(lots), ACCOUNT, game_time)
        except MarketError:
            return None
        return StandingOrder(asset=asset, price=price, lots=lots)

    def absorbed(self, asset: str) -> int:
        """Kilograms Earth has taken delivery of. Never returns to the world."""
        return self.ledger.balance(ACCOUNT, asset)

    def credits_injected(self) -> int:
        """Credits Earth has actually paid into the economy.

        Read off the trade tape, because that is the only place the truth
        lives. Two earlier attempts at this were both wrong in instructive
        ways:

        Summing every debit against Earth's account overstates it wildly --
        placing a bid moves credits into escrow, which is a debit that has
        bought nothing and is refunded when the quote is refreshed. Earth
        re-quotes every six ticks, so the same unspent credits were counted
        again and again: it read 764 million against a true 10 million.

        Filtering those debits to settled trades then reads *zero*, because a
        fill is paid out of the order's escrow account, not out of the
        buyer's. Earth's own balance is never touched at the moment of sale.

        So: join the trades to the orders and total what Earth bought.
        """
        row = self.ledger.db.execute(
            """
            SELECT COALESCE(SUM(t.price * t.qty_kg / a.lot_mass_kg), 0) AS spent
            FROM trade t
            JOIN book_order b ON b.id = t.buy_order_id
            JOIN asset a ON a.symbol = t.asset
            WHERE b.account_id = ?
            """,
            (ACCOUNT,),
        ).fetchone()
        return int(row["spent"])
