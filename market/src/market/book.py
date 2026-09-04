"""The order book and the matching engine.

One book per (node, commodity). Prices form locally: water on the Moon and
water at Ceres are different goods with different books, and the gap between
them minus fuel and time is the entire merchant profession.

Rules, all of them boring on purpose:

**Limit orders only.** No market orders in v1. A market order is a promise to
pay whatever the book asks, which in a thin market with fifty agents and one
player is how someone loses their whole balance to a fat finger. The bible
also puts limit orders at the centre of the standing-instruction design, since
players are offline most of the time.

**Price-time priority.** Best price first; among equal prices, whoever rested
first. No pro-rata, no hidden size, no priority for being large.

**The resting order sets the price.** An aggressor that crosses the spread
pays the price already on the book, not its own limit. A buyer whose limit was
generous keeps the difference -- it is refunded from escrow on each fill.

**Everything resting is escrowed.** A bid holds its credits in an escrow
account from the moment it is placed; an ask holds its goods. Nothing can be
promised twice, and cancelling returns exactly what is left.

**Self-trading is skipped.** An account never matches its own resting order.
One account per person is an invariant, so trading with yourself can only be
wash trading -- manufacturing a price history to sell into. Skipping rather
than rejecting can briefly leave a crossed book if one account holds both
sides, which is harmless and clears the moment anyone else trades.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field

from .db import transaction
from .errors import UnknownOrder
from .ledger import Ledger, Posting
from .money import CREDIT, check_price, check_quantity

BID = "BID"
ASK = "ASK"


@dataclass(frozen=True)
class Fill:
    price: int
    qty_kg: int
    value: int          # credits that changed hands
    maker_order_id: str
    taker_order_id: str
    trade_id: int


@dataclass
class PlaceResult:
    order_id: str
    fills: list[Fill] = field(default_factory=list)
    resting_kg: int = 0

    @property
    def filled_kg(self) -> int:
        return sum(f.qty_kg for f in self.fills)


class OrderBook:
    """Matching for one node. Assets are per-call; the node is fixed."""

    def __init__(self, db: sqlite3.Connection, ledger: Ledger, node: str) -> None:
        self.db = db
        self.ledger = ledger
        self.node = node

    # -- reading -------------------------------------------------------

    def best_bid(self, asset: str) -> int | None:
        row = self.db.execute(
            "SELECT MAX(price) AS p FROM book_order WHERE node = ? AND asset = ? "
            "AND side = 'BID' AND status = 'OPEN'",
            (self.node, asset),
        ).fetchone()
        return row["p"]

    def best_ask(self, asset: str) -> int | None:
        row = self.db.execute(
            "SELECT MIN(price) AS p FROM book_order WHERE node = ? AND asset = ? "
            "AND side = 'ASK' AND status = 'OPEN'",
            (self.node, asset),
        ).fetchone()
        return row["p"]

    def spread(self, asset: str) -> int | None:
        bid, ask = self.best_bid(asset), self.best_ask(asset)
        return None if bid is None or ask is None else ask - bid

    def depth(self, asset: str, side: str, levels: int = 10
              ) -> list[tuple[int, int]]:
        """(price, total remaining kg) per level, best first."""
        order = "DESC" if side == BID else "ASC"
        rows = self.db.execute(
            f"SELECT price, SUM(remaining_kg) AS qty FROM book_order "
            f"WHERE node = ? AND asset = ? AND side = ? AND status = 'OPEN' "
            f"GROUP BY price ORDER BY price {order} LIMIT ?",
            (self.node, asset, side, levels),
        ).fetchall()
        return [(int(r["price"]), int(r["qty"])) for r in rows]

    def last_price(self, asset: str) -> int | None:
        row = self.db.execute(
            "SELECT price FROM trade WHERE node = ? AND asset = ? "
            "ORDER BY id DESC LIMIT 1",
            (self.node, asset),
        ).fetchone()
        return row["price"] if row else None

    def open_orders(self, account_id: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM book_order WHERE node = ? AND account_id = ? "
            "AND status = 'OPEN' ORDER BY seq",
            (self.node, account_id),
        ).fetchall()

    # -- writing -------------------------------------------------------

    def place(
        self,
        asset_symbol: str,
        side: str,
        price: int,
        qty_kg: int,
        account_id: str,
        game_time: str,
    ) -> PlaceResult:
        """Place a limit order: escrow, match, rest the remainder.

        The whole thing is one database transaction. A failure at any point
        -- insufficient funds, a bad quantity, a bug in matching -- leaves the
        book and the ledger exactly as they were.
        """
        asset = self.ledger.asset(asset_symbol)
        check_price(price)
        check_quantity(qty_kg)
        asset.lots(qty_kg)  # raises unless a whole number of lots
        if side not in (BID, ASK):
            raise ValueError(f"side must be {BID} or {ASK}, got {side!r}")

        with transaction(self.db):
            order_id = f"ord_{uuid.uuid4().hex[:16]}"
            escrow_id = f"escrow:{order_id}"
            self.ledger.open_account(escrow_id, "escrow", game_time,
                                     label=f"escrow for {order_id}")

            # Escrow before anything else. If this fails the order never
            # existed, which is the correct outcome.
            if side == BID:
                self.ledger.transfer(
                    account_id, escrow_id, CREDIT, asset.cost(price, qty_kg),
                    kind="escrow_lock", game_time=game_time, ref=order_id,
                    memo=f"bid {qty_kg}kg {asset.symbol} @ {price}",
                )
            else:
                self.ledger.transfer(
                    account_id, escrow_id, asset.symbol, qty_kg,
                    kind="escrow_lock", game_time=game_time, ref=order_id,
                    memo=f"ask {qty_kg}kg {asset.symbol} @ {price}",
                )

            seq = self._next_seq()
            self.db.execute(
                "INSERT INTO book_order (id, node, asset, side, price, qty_kg, "
                "remaining_kg, account_id, escrow_id, status, placed_at, seq) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)",
                (order_id, self.node, asset.symbol, side, price, qty_kg,
                 qty_kg, account_id, escrow_id, game_time, seq),
            )

            result = PlaceResult(order_id=order_id)
            remaining = qty_kg
            for maker in self._matchable(asset.symbol, side, price, account_id):
                if remaining == 0:
                    break
                traded = min(remaining, int(maker["remaining_kg"]))
                fill = self._settle(asset, maker, order_id, account_id,
                                    side, price, traded, game_time)
                result.fills.append(fill)
                remaining -= traded

            self._set_remaining(order_id, remaining)
            result.resting_kg = remaining

            # A fully filled order holds nothing; release any dust anyway so
            # escrow accounts always end at zero.
            if remaining == 0:
                self._release(order_id, asset, game_time, close_as="FILLED")

            return result

    def cancel(self, order_id: str, game_time: str) -> int:
        """Cancel an open order and return whatever escrow still holds."""
        with transaction(self.db):
            row = self._order(order_id)
            if row["status"] != "OPEN":
                raise UnknownOrder(f"{order_id} is {row['status']}")
            asset = self.ledger.asset(row["asset"])
            released = self._release(order_id, asset, game_time,
                                     close_as="CANCELLED")
            return released

    # -- internals -----------------------------------------------------

    def _next_seq(self) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS s FROM book_order"
        ).fetchone()
        return int(row["s"])

    def _order(self, order_id: str) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT * FROM book_order WHERE id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise UnknownOrder(order_id)
        return row

    def _matchable(self, asset: str, side: str, price: int,
                   account_id: str) -> list[sqlite3.Row]:
        """Resting orders on the opposite side that this order can trade with.

        Ordered by price-time priority. The account filter is self-trade
        prevention and is applied in SQL so a large book of one's own orders
        costs nothing to skip.
        """
        if side == BID:
            return self.db.execute(
                "SELECT * FROM book_order WHERE node = ? AND asset = ? "
                "AND side = 'ASK' AND status = 'OPEN' AND price <= ? "
                "AND account_id != ? ORDER BY price ASC, seq ASC",
                (self.node, asset, price, account_id),
            ).fetchall()
        return self.db.execute(
            "SELECT * FROM book_order WHERE node = ? AND asset = ? "
            "AND side = 'BID' AND status = 'OPEN' AND price >= ? "
            "AND account_id != ? ORDER BY price DESC, seq ASC",
            (self.node, asset, price, account_id),
        ).fetchall()

    def _settle(self, asset, maker: sqlite3.Row, taker_id: str,
                taker_account: str, taker_side: str, taker_price: int,
                qty_kg: int, game_time: str) -> Fill:
        """Execute one fill: goods one way, credits the other, atomically.

        Price is the maker's, always. The taker's limit only decided whether
        this fill was allowed to happen.
        """
        exec_price = int(maker["price"])
        lots = asset.lots(qty_kg)
        value = exec_price * lots

        if taker_side == BID:
            buy_order_id, sell_order_id = taker_id, maker["id"]
            buyer_escrow, buyer_account = f"escrow:{taker_id}", taker_account
            buyer_limit = taker_price
            seller_escrow, seller_account = maker["escrow_id"], maker["account_id"]
        else:
            buy_order_id, sell_order_id = maker["id"], taker_id
            buyer_escrow, buyer_account = maker["escrow_id"], maker["account_id"]
            buyer_limit = exec_price  # the maker is the buyer; its own price
            seller_escrow, seller_account = f"escrow:{taker_id}", taker_account

        postings = [
            # Credits: out of the buyer's escrow, into the seller's hands.
            Posting(buyer_escrow, CREDIT, -value),
            Posting(seller_account, CREDIT, value),
            # Goods: out of the seller's escrow, into the buyer's hands.
            Posting(seller_escrow, asset.symbol, -qty_kg),
            Posting(buyer_account, asset.symbol, qty_kg),
        ]

        # A buyer who crossed the spread escrowed at their own limit and
        # traded at a better one. The difference is theirs and is returned
        # here rather than left sitting in escrow.
        refund = (buyer_limit - exec_price) * lots
        if refund > 0:
            postings.append(Posting(buyer_escrow, CREDIT, -refund))
            postings.append(Posting(buyer_account, CREDIT, refund))

        txn_id = self.ledger.post(
            "trade", game_time, postings, ref=taker_id,
            memo=f"{qty_kg}kg {asset.symbol} @ {exec_price} at {self.node}",
        )

        cursor = self.db.execute(
            "INSERT INTO trade (node, asset, price, qty_kg, buy_order_id, "
            "sell_order_id, txn_id, game_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (self.node, asset.symbol, exec_price, qty_kg, buy_order_id,
             sell_order_id, txn_id, game_time),
        )

        maker_remaining = int(maker["remaining_kg"]) - qty_kg
        self._set_remaining(maker["id"], maker_remaining)
        if maker_remaining == 0:
            self._release(maker["id"], asset, game_time, close_as="FILLED")

        return Fill(price=exec_price, qty_kg=qty_kg, value=value,
                    maker_order_id=maker["id"], taker_order_id=taker_id,
                    trade_id=int(cursor.lastrowid))

    def _set_remaining(self, order_id: str, remaining: int) -> None:
        self.db.execute(
            "UPDATE book_order SET remaining_kg = ? WHERE id = ?",
            (remaining, order_id),
        )

    def _release(self, order_id: str, asset, game_time: str,
                 close_as: str) -> int:
        """Return everything left in an order's escrow and close it.

        Called on cancel and on full fill. Always leaves the escrow account
        at exactly zero for every asset, which the tests assert globally.
        """
        row = self._order(order_id)
        escrow_id = row["escrow_id"]
        released = 0

        credits_held = self.ledger.balance(escrow_id, CREDIT)
        if credits_held > 0:
            self.ledger.transfer(
                escrow_id, row["account_id"], CREDIT, credits_held,
                kind="escrow_release", game_time=game_time, ref=order_id,
                memo=f"release from {order_id}",
            )
            released += credits_held

        goods_held = self.ledger.balance(escrow_id, asset.symbol)
        if goods_held > 0:
            self.ledger.transfer(
                escrow_id, row["account_id"], asset.symbol, goods_held,
                kind="escrow_release", game_time=game_time, ref=order_id,
                memo=f"release from {order_id}",
            )
            released += goods_held

        self.db.execute(
            "UPDATE book_order SET status = ? WHERE id = ?",
            (close_as, order_id),
        )
        return released
