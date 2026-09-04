"""Bulk agents: the firms that make the market exist.

The bible puts ~90% of the population here. "Pure code. Numbers on an order
book. They produce, consume, haul and quote. They give the market depth and
they never speak."

No language model is involved, per invariant 2. Every decision below is
arithmetic over the firm's own balance sheet.

Price formation is the part worth reading carefully, because it is the
mechanic the whole game rests on. The bible: "Prices form from local inventory
against local demand: as a warehouse fills, the bid falls; as it empties, the
ask climbs." So a firm's reservation price is not random and not a fixed
markup -- it is a function of how far its stock sits from where it wants it:

    pressure = (holding - target) / target        surplus positive, deficit negative
    price    = reference x (1 - elasticity x pressure)

One formula covers both sides, because the incentive is symmetric. A seller
sitting on surplus lowers its ask to move it; a seller running dry holds out
for more. A buyer with full tanks bids weakly; a buyer running dry bids up.
Supply and demand fall out of that, and nothing else has to impose them.

``elasticity`` comes from the volatility column in docs/seed-data.md, which
until now was a word with no mechanical meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from market.book import ASK, BID, OrderBook
from market.errors import MarketError
from market.ledger import Ledger


class Role(str, Enum):
    EXTRACTOR = "extractor"   # works a deposit, sells the output
    REFINER = "refiner"       # buys feedstock, sells a processed good
    CONSUMER = "consumer"     # buys and consumes; the settlement's demand
    TRADER = "trader"         # quotes both sides, lives on the spread


#: docs/seed-data.md volatility column, given two mechanical meanings, because
#: the seed data says it has exactly two: "Volatility is the mean-reversion
#: strength and shock sensitivity, not a price band."
#:
#: ELASTICITY is how hard a firm moves off the going rate when its inventory is
#: off target -- the shock-sensitivity half.
#:
#: REVERSION is how strongly the going rate is pulled back toward the seed
#: anchor -- the mean-reversion half. It runs *inverse* to volatility: a stable
#: commodity is dragged back to its anchor hard, a volatile one is free to roam.
#:
#: Reversion is not optional decoration. Without it the reference price is
#: purely the last trade, so a market where most firms are short ratchets
#: upward without limit: each deficit buyer bids above the last print, that
#: print becomes the next reference, and the loop has no ceiling. The first
#: run of this world put water ice at 1,670 credits against a 400 anchor
#: before this existed.
ELASTICITY = {
    "low": 0.10,
    "medium": 0.20,
    "high": 0.35,
    "very high": 0.50,
}

REVERSION = {
    "low": 0.30,
    "medium": 0.20,
    "high": 0.12,
    "very high": 0.06,
}


@dataclass
class Firm:
    """One bulk agent."""

    id: str
    role: Role
    node: str
    account: str

    #: Extractors: the deposit worked and the rig's nameplate rate.
    deposit_id: str | None = None
    nameplate_kg_per_day: int = 0

    #: Refiners: what goes in, what comes out, at what yield and power cost.
    input_asset: str | None = None
    output_asset: str | None = None
    conversion_rate: int = 0          # kg of input per game day
    yield_numerator: int = 3
    yield_denominator: int = 4

    #: Consumers: what it burns and how fast.
    consumes: str | None = None
    consumption_kg_per_day: int = 0

    #: Traders: the book they make.
    trades: str | None = None

    #: Inventory the firm wants to hold, per asset. Drives its prices.
    targets: dict[str, int] = field(default_factory=dict)

    #: Fixed operating cost per game day. Money leaving the world.
    upkeep_per_day: int = 0

    #: Wage bill per game day, paid to the consumer firms at this node.
    #:
    #: This is what closes the economy. Without it, consumers only ever spend
    #: and the settlement runs out of money, because the only credits entering
    #: the world arrive at whichever node sells to Earth. Wages circulate them
    #: to everyone else.
    #:
    #: Per D37, wages paid to a modelled account are a *transfer*, not a sink,
    #: even though the bible lists crew wages among the sinks -- that is only
    #: true for crew who are not modelled. Conflating the two would quietly
    #: break invariant 7's accounting.
    wages_per_day: int = 0

    #: Sub-kilogram conversion remainder, in numerator units. Carried between
    #: ticks so a low-yield process (helium-3 separation is 0.6 kg per 400 t)
    #: does not truncate its entire output to zero every hour.
    yield_buffer: int = 0

    insolvent: bool = False
    idle_since: int | None = None

    def per_tick(self, per_day: int, ticks_per_day: int) -> int:
        return per_day // ticks_per_day


def pressure(holding_kg: int, target_kg: int) -> float:
    """How far off target a firm's stock is. Clamped to [-1, 1].

    Positive means surplus and pushes the price down; negative means deficit
    and pushes it up. Clamping matters: without it a firm holding twenty times
    its target quotes a negative price, and a firm at zero stock bids
    arbitrarily high and hands its whole balance to the first seller.
    """
    if target_kg <= 0:
        return 0.0
    raw = (holding_kg - target_kg) / target_kg
    return max(-1.0, min(1.0, raw))


def reservation_price(reference: int, holding_kg: int, target_kg: int,
                      elasticity: float) -> int:
    """What this firm will pay, or accept, given its stock.

    Never returns less than 1 credit: a price of zero is not a price, and an
    order book with a zero on it is a bug waiting to be exploited.
    """
    adjusted = reference * (1.0 - elasticity * pressure(holding_kg, target_kg))
    return max(1, int(round(adjusted)))


class FirmBehaviour:
    """Runs one firm for one tick. All decisions, no bookkeeping."""

    def __init__(self, ledger: Ledger, books: dict[str, OrderBook],
                 ticks_per_day: int) -> None:
        self.ledger = ledger
        self.books = books
        self.ticks_per_day = ticks_per_day

    def reference_price(self, firm: Firm, asset: str,
                        reversion: float = 0.20) -> int:
        """What the firm thinks the going rate is.

        The last trade, pulled part of the way back toward the seed anchor.
        A firm quoting purely off the anchor is how the Ark Authority became a
        one-way valve in finding F2, so agents do track the market -- but a
        firm quoting purely off the last print has no anchor at all, and the
        market ratchets away from any sane value. The blend is the fix, and
        ``reversion`` is what the seed data's volatility column was for.
        """
        spec = self.ledger.asset(asset)
        book = self.books[firm.node]

        observed = book.last_price(asset)
        if observed is None:
            bid, ask = book.best_bid(asset), book.best_ask(asset)
            if bid is not None and ask is not None:
                observed = (bid + ask) // 2
        if observed is None:
            return spec.base_value

        blended = observed * (1.0 - reversion) + spec.base_value * reversion
        return max(1, int(round(blended)))

    def quote(self, firm: Firm, asset: str, side: str, qty_kg: int,
              elasticity: float, game_time: str,
              reversion: float = 0.20) -> None:
        """Place one order, sized to a whole number of lots.

        A refusal is not an error. A firm that cannot afford its own bid, or
        has less stock than it thought, simply does not trade this tick --
        which is what a real firm does too.
        """
        spec = self.ledger.asset(asset)
        lots = qty_kg // spec.lot_mass_kg
        if lots < 1:
            return
        price = reservation_price(
            self.reference_price(firm, asset, reversion),
            self.ledger.balance(firm.account, asset),
            firm.targets.get(asset, spec.lot_mass_kg),
            elasticity,
        )
        try:
            self.books[firm.node].place(asset, side, price, spec.kg(lots),
                                        firm.account, game_time)
        except MarketError:
            pass
