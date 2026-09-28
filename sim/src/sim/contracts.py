"""Supply contracts: a firm asking for goods to be brought to it.

The bible's first act of the game: "A named agent writes to them: who they
are, where the player stands, what needs moving and why. Attached are two or
three things the player could take on." These are those things.

A contract is a firm that is short of something saying so in public, with the
money already on the table. Three rules keep it honest:

**The payment is escrowed when the contract is posted.** It moves out of the
issuer's account into the contract's own escrow account in the same
transaction that creates the contract. A firm cannot promise money it does not
have, and cannot spend it on something else while a pilot is in flight.

**The payment is the issuer's own money, priced off its own market.** Local
going rate times the quantity, plus a premium for certainty of supply. No
credit is created anywhere in this module -- invariant 3. When nobody takes
the job the escrow goes back to the issuer at the deadline, to the credit.

**Goods must be carried.** A contract is settled when a ship docks carrying the
goods, or by hand for goods that arrived aboard. Buying the goods at the
issuer's own door and handing them straight over is not delivery, and the
premium would turn into a free 12% on anything sold locally.

Nothing here decides anything with a language model. Who posts, what, and for
how much is arithmetic over the issuer's balance sheet and a seeded roll.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from market.db import transaction
from market.money import CREDIT

from .firms import Role
from .shocks import Event

#: How often the board is checked for new postings, in ticks.
POST_EVERY_TICKS = 6

#: At most this many unfilled contracts per node at once. A board with forty
#: jobs on it is a spreadsheet; three is a choice.
MAX_OPEN_PER_NODE = 3

#: Chance, per node per check, that a firm short of something posts a job.
POST_CHANCE = 0.5

#: Game hours from posting to deadline. Three game days is 72 real minutes:
#: long enough to take on a return from the tab, short enough that an
#: accepted job is a commitment rather than an option held forever.
DEADLINE_TICKS = 72

#: Paid over the local going rate, in percent, for guaranteed supply.
PREMIUM_PERCENT = 12

#: Size of a job in lots (tonnes). A Kestrel holds 40.
LOTS_MIN = 8
LOTS_MAX = 30

#: An issuer never commits more than 1/N of its cash to one contract.
ISSUER_CASH_FRACTION = 5

#: How many jobs one pilot may hold at once.
MAX_ACCEPTED_PER_PLAYER = 3

#: A job paying less than this is not worth a flight: the docking fee and
#: fuel alone would eat it. The first run of the board posted regolith jobs
#: at Tranquillitatis for 1,915 cr against a 400 cr fee.
MIN_PAYMENT = 5_000


class ContractError(Exception):
    """A request the board refuses. The message is shown to the player."""


@dataclass(frozen=True)
class Contract:
    id: int
    issuer: str
    issuer_account: str
    node: str
    asset: str
    qty_kg: int
    payment: int
    escrow_account: str
    posted_tick: int
    deadline_tick: int
    status: str
    taker: str | None
    closed_tick: int | None

    @classmethod
    def from_row(cls, row) -> "Contract":
        return cls(**{k: row[k] for k in row.keys()})

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class ContractBoard:
    """Posts, hands out, settles and expires contracts. Owns no money."""

    def __init__(self, world, db) -> None:
        self.w = world
        self.db = db

    # -- reading ---------------------------------------------------------

    def get(self, contract_id: int) -> Contract:
        row = self.db.execute("SELECT * FROM contract WHERE id = ?",
                              (contract_id,)).fetchone()
        if row is None:
            raise ContractError("No such contract.")
        return Contract.from_row(row)

    def open(self, node: str | None = None) -> list[Contract]:
        sql = "SELECT * FROM contract WHERE status = 'OPEN'"
        args: tuple = ()
        if node:
            sql += " AND node = ?"
            args = (node,)
        return [Contract.from_row(r) for r in
                self.db.execute(sql + " ORDER BY deadline_tick", args)]

    def held_by(self, player_id: str) -> list[Contract]:
        return [Contract.from_row(r) for r in self.db.execute(
            "SELECT * FROM contract WHERE taker = ? AND status = 'ACCEPTED' "
            "ORDER BY deadline_tick", (player_id,))]

    def history_of(self, player_id: str, limit: int = 20) -> list[Contract]:
        return [Contract.from_row(r) for r in self.db.execute(
            "SELECT * FROM contract WHERE taker = ? AND status != 'ACCEPTED' "
            "ORDER BY id DESC LIMIT ?", (player_id, limit))]

    # -- the tick ------------------------------------------------------

    def tick(self, now: str) -> list[Event]:
        events = self.expire(now)
        if self.w.tick % POST_EVERY_TICKS == 0:
            events += self.post_new(now)
        return events

    def post_new(self, now: str, force: bool = False) -> list[Event]:
        """Let firms that are short of something ask for it.

        ``force`` skips the dice. Used when a new pilot arrives to a board
        with nothing on it, so the first thing they read is never an empty
        list -- though a firm still posts only if it really is short and
        really can pay.
        """
        events: list[Event] = []
        for node in sorted(self.w.books):
            if len(self.open(node)) >= MAX_OPEN_PER_NODE:
                continue
            if not force and not self.w.streams.chance(
                    "contract_post", self.w.tick, POST_CHANCE, salt=node):
                continue
            posted = self._post_one(node, now)
            if posted is not None:
                events.append(posted)
        return events

    def _wants(self, node: str) -> list[tuple[object, str, int]]:
        """(firm, asset, shortfall kg) for every firm here that is short."""
        out = []
        for firm in self.w.active_firms():
            if firm.node != node:
                continue
            if firm.role is Role.CONSUMER and firm.consumes:
                asset = firm.consumes
            elif firm.role is Role.REFINER and firm.input_asset:
                asset = firm.input_asset
            else:
                continue
            spec = self.w.ledger.asset(asset)
            if spec.lot_mass_kg != 1_000:
                continue                 # tonne goods only: a Kestrel's trade
            held = self.w.ledger.balance(firm.account, asset)
            short = firm.targets.get(asset, 0) - held
            if short >= LOTS_MIN * spec.lot_mass_kg:
                out.append((firm, asset, short))
        out.sort(key=lambda t: t[0].id)
        return out

    def _sold_elsewhere(self, node: str, asset: str) -> bool:
        """Can a pilot actually buy this anywhere but here?

        Without this the board asked for regolith at Tranquillitatis, which
        is the only place on the Moon that produces any: a job nobody could
        ever fill, sitting on the board for three days with money locked
        behind it.
        """
        return any(book.best_ask(asset) for other, book in self.w.books.items()
                   if other != node)

    def _post_one(self, node: str, now: str) -> Event | None:
        wants = self._wants(node)
        already = {(c.issuer, c.asset) for c in self.open(node)}
        wants = [w for w in wants if (w[0].id, w[1]) not in already
                 and self._sold_elsewhere(node, w[1])]
        if not wants:
            return None
        firm, asset, short = self.w.streams.pick(
            "contract_issuer", self.w.tick, wants, salt=node)

        spec = self.w.ledger.asset(asset)
        book = self.w.books[node]
        rate = book.last_price(asset) or spec.base_value
        most = min(LOTS_MAX, short // spec.lot_mass_kg)
        lots = self.w.streams.integer("contract_size", self.w.tick,
                                      LOTS_MIN, max(LOTS_MIN, most), salt=node)
        payment = rate * lots * (100 + PREMIUM_PERCENT) // 100

        if payment < MIN_PAYMENT:
            return None
        cash = self.w.ledger.balance(firm.account, CREDIT)
        if payment * ISSUER_CASH_FRACTION > cash:
            return None                  # cannot afford to ask; stays short

        with transaction(self.db):
            cur = self.db.execute(
                "INSERT INTO contract (issuer, issuer_account, node, asset, "
                "qty_kg, payment, escrow_account, posted_tick, deadline_tick, "
                "status) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, 'OPEN')",
                (firm.id, firm.account, node, asset, spec.kg(lots), payment,
                 self.w.tick, self.w.tick + DEADLINE_TICKS),
            )
            cid = int(cur.lastrowid)
            escrow = f"escrow:contract:{cid}"
            self.db.execute("UPDATE contract SET escrow_account = ? WHERE id = ?",
                            (escrow, cid))
            self.w.ledger.open_account(escrow, "escrow", now,
                                       label=f"contract {cid}")
            self.w.ledger.transfer(
                firm.account, escrow, CREDIT, payment, kind="contract_escrow",
                game_time=now, ref=f"contract:{cid}",
                memo=f"{firm.id} posts {lots} t {asset} to {node}",
            )
        return Event(
            tick=self.w.tick, kind="contract_posted", subject=firm.id,
            detail=f"{lots} t {asset} wanted at {node} for {payment:,} cr",
            data={"contract": cid, "issuer": firm.id, "node": node,
                  "asset": asset, "kg": spec.kg(lots), "payment": payment,
                  "deadline_tick": self.w.tick + DEADLINE_TICKS},
        )

    def expire(self, now: str) -> list[Event]:
        """Return the escrow of every contract past its deadline."""
        events: list[Event] = []
        rows = self.db.execute(
            "SELECT * FROM contract WHERE status IN ('OPEN','ACCEPTED') "
            "AND deadline_tick <= ? ORDER BY id", (self.w.tick,)).fetchall()
        for row in rows:
            c = Contract.from_row(row)
            with transaction(self.db):
                held = self.w.ledger.balance(c.escrow_account, CREDIT)
                if held > 0:
                    self.w.ledger.transfer(
                        c.escrow_account, c.issuer_account, CREDIT, held,
                        kind="contract_refund", game_time=now,
                        ref=f"contract:{c.id}",
                        memo=f"contract {c.id} expired unfilled",
                    )
                self.db.execute(
                    "UPDATE contract SET status = 'EXPIRED', closed_tick = ? "
                    "WHERE id = ?", (self.w.tick, c.id))
            events.append(Event(
                tick=self.w.tick, kind="contract_expired", subject=c.issuer,
                detail=f"contract {c.id} expired",
                data={"contract": c.id, "issuer": c.issuer, "node": c.node,
                      "asset": c.asset, "kg": c.qty_kg, "taker": c.taker},
            ))
        return events

    # -- pilots ----------------------------------------------------------

    def accept(self, contract_id: int, player_id: str) -> Contract:
        c = self.get(contract_id)
        if c.status != "OPEN":
            raise ContractError("That contract has already been taken.")
        if c.deadline_tick <= self.w.tick:
            raise ContractError("That contract has expired.")
        if len(self.held_by(player_id)) >= MAX_ACCEPTED_PER_PLAYER:
            raise ContractError(
                f"You can hold at most {MAX_ACCEPTED_PER_PLAYER} contracts.")
        with transaction(self.db):
            self.db.execute(
                "UPDATE contract SET status = 'ACCEPTED', taker = ? "
                "WHERE id = ? AND status = 'OPEN'", (player_id, contract_id))
        return self.get(contract_id)

    def abandon(self, contract_id: int, player_id: str) -> Contract:
        c = self.get(contract_id)
        if c.status != "ACCEPTED" or c.taker != player_id:
            raise ContractError("That is not one of your contracts.")
        with transaction(self.db):
            self.db.execute(
                "UPDATE contract SET status = 'OPEN', taker = NULL "
                "WHERE id = ?", (contract_id,))
        return self.get(contract_id)

    def deliver(self, c: Contract, from_account: str, now: str) -> Event:
        """Goods to the issuer, escrow to the pilot, in one transaction.

        The caller has already checked the goods are aboard and were carried
        here. The ledger checks everything else: a pilot short a kilogram
        makes the whole transfer fail, and nothing moves.
        """
        with transaction(self.db):
            self.w.ledger.transfer(
                from_account, c.issuer_account, c.asset, c.qty_kg,
                kind="contract_delivery", game_time=now,
                ref=f"contract:{c.id}", memo=f"contract {c.id} delivered",
            )
            held = self.w.ledger.balance(c.escrow_account, CREDIT)
            self.w.ledger.transfer(
                c.escrow_account, from_account, CREDIT, held,
                kind="contract_payment", game_time=now,
                ref=f"contract:{c.id}", memo=f"contract {c.id} paid",
            )
            self.db.execute(
                "UPDATE contract SET status = 'FULFILLED', closed_tick = ? "
                "WHERE id = ?", (self.w.tick, c.id))
        return Event(
            tick=self.w.tick, kind="contract_fulfilled", subject=c.issuer,
            detail=f"contract {c.id} delivered for {held:,} cr",
            data={"contract": c.id, "issuer": c.issuer, "node": c.node,
                  "asset": c.asset, "kg": c.qty_kg, "payment": held,
                  "taker": c.taker},
        )


def encode(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)
