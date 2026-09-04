"""The world tick.

One tick is one game hour. Everything that happens in the economy happens
here, in a fixed order, driven by seeded randomness.

The ordering is deliberate and worth keeping. Production before consumption,
so a firm can sell what it made this hour. Upkeep before quoting, so a firm
that just went broke does not place orders it cannot honour. Insolvency after
trading, so a firm gets its full chance to sell its way out before the
receiver arrives. Conservation is checked last, every single tick, because a
leak found one tick after it happens is a debuggable bug and a leak found a
week later is an archaeology project.

`sim` never moves money itself. Every credit and kilogram goes through
`market`, so conservation stays structural rather than being this package's
job to get right.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from market.authority import ArkAuthority
from market.book import ASK, BID, OrderBook
from market.db import transaction
from market.errors import MarketError
from market.ledger import Ledger
from market.money import CREDIT

from . import TICKS_PER_GAME_DAY
from .deposits import Deposit
from .earth import EarthMarket
from .estate import Receiver
from .firms import ELASTICITY, REVERSION, Firm, FirmBehaviour, Role
from .rng import Streams
from .shocks import REPAIR_COST, Event, Weather

#: How often institutions replace their standing quotes, in ticks.
QUOTE_REFRESH_TICKS = 6


@dataclass
class World:
    """Everything the simulation needs, and the tick that advances it."""

    ledger: Ledger
    books: dict[str, OrderBook]
    authorities: dict[str, ArkAuthority]
    earth: EarthMarket
    firms: list[Firm]
    deposits: dict[str, Deposit]
    seed: int
    volatility: dict[str, str] = field(default_factory=dict)
    earth_assets: dict[str, str] = field(default_factory=dict)
    quoted_assets: dict[str, list[str]] = field(default_factory=dict)
    starting_capital: dict[str, int] = field(default_factory=dict)

    tick: int = 0
    events: list[Event] = field(default_factory=list)
    _spinoff_count: int = 0

    def __post_init__(self) -> None:
        self.streams = Streams(self.seed)
        self.weather = Weather(self.streams)
        self.receiver = Receiver(self.ledger, self.books)
        self.behaviour = FirmBehaviour(self.ledger, self.books,
                                       TICKS_PER_GAME_DAY)

    # -- time ----------------------------------------------------------

    def game_time(self) -> str:
        """Sky time as an ISO string. One tick is one game hour."""
        day, hour = divmod(self.tick, TICKS_PER_GAME_DAY)
        return f"2190-01-01T{hour:02d}:00:00Z+{day}d"

    def elasticity(self, asset: str) -> float:
        return ELASTICITY.get(self.volatility.get(asset, "medium"), 0.20)

    def reversion(self, asset: str) -> float:
        return REVERSION.get(self.volatility.get(asset, "medium"), 0.20)

    def active_firms(self) -> list[Firm]:
        return [f for f in self.firms if not f.insolvent]

    # -- the tick ------------------------------------------------------

    def run_tick(self) -> list[Event]:
        self.tick += 1
        now = self.game_time()
        produced: list[Event] = []

        produced += self.weather.roll(self.tick,
                                      [f.id for f in self.active_firms()])

        for firm in self.active_firms():
            self._produce(firm, now)
        for firm in self.active_firms():
            self._consume(firm, now)
        for firm in self.active_firms():
            self._pay_upkeep(firm, now)
        for firm in self.active_firms():
            self._pay_wages(firm, now)
        for firm in self.active_firms():
            self._quote(firm, now)

        if self.tick % QUOTE_REFRESH_TICKS == 0:
            self._refresh_institutions(now)

        produced += self._wind_up_failures(now)
        produced += self._spin_off_successes(now)

        # Every tick, without exception. See the module docstring.
        self.ledger.assert_conserved()

        self.events.extend(produced)
        return produced

    # -- production and consumption --------------------------------------

    def _produce(self, firm: Firm, now: str) -> None:
        if firm.role is Role.EXTRACTOR:
            self._extract(firm, now)
        elif firm.role is Role.REFINER:
            self._refine(firm, now)

    def _extract(self, firm: Firm, now: str) -> None:
        """Work a deposit. Halted by flares, stopped by exhaustion."""
        if self.weather.flaring(self.tick) or self.weather.rig_down(firm.id, self.tick):
            return
        deposit = self.deposits.get(firm.deposit_id or "")
        if deposit is None or deposit.exhausted:
            return

        nameplate = firm.nameplate_kg_per_day // TICKS_PER_GAME_DAY
        won = deposit.yield_for(nameplate)
        if won < 1:
            return
        deposit.work(won, self.tick)
        with transaction(self.ledger.db):
            self.ledger.extract(firm.account, deposit.asset, won, now,
                                memo=f"{firm.id} works {deposit.id}")

    def _refine(self, firm: Firm, now: str) -> None:
        """Convert feedstock into a processed good, lossily.

        Output is not rounded to trading lots. Mass is stored in kilograms and
        only *orders* need whole lots, so a plant is free to hold a partial
        lot -- which the helium-3 chain requires: a separator yields 0.6 kg per
        400 tonnes of regolith, so rounding output to a lot every tick would
        produce exactly nothing forever.

        The remainder below one kilogram is carried in ``yield_buffer`` rather
        than discarded. Over a game year a separator would otherwise lose most
        of its product to truncation, and the discarded mass would be a silent
        violation of conservation in the one direction the ledger cannot catch.
        """
        if self.weather.rig_down(firm.id, self.tick):
            return
        wanted = firm.conversion_rate // TICKS_PER_GAME_DAY
        held = self.ledger.balance(firm.account, firm.input_asset)
        feed = min(wanted, held)
        if feed < 1:
            return

        firm.yield_buffer += feed * firm.yield_numerator
        made = firm.yield_buffer // firm.yield_denominator
        firm.yield_buffer -= made * firm.yield_denominator

        with transaction(self.ledger.db):
            self.ledger.consume(firm.account, firm.input_asset, feed, now,
                                memo=f"{firm.id} feedstock")
            if made >= 1:
                self.ledger.extract(firm.account, firm.output_asset, made, now,
                                    memo=f"{firm.id} output")

    def _consume(self, firm: Firm, now: str) -> None:
        """Life support, propellant burned, food eaten. Mass leaves the world."""
        if firm.role is not Role.CONSUMER or not firm.consumes:
            return
        wanted = firm.consumption_kg_per_day // TICKS_PER_GAME_DAY
        held = self.ledger.balance(firm.account, firm.consumes)
        burn = min(wanted, held)
        if burn < 1:
            return
        with transaction(self.ledger.db):
            self.ledger.consume(firm.account, firm.consumes, burn, now,
                                memo=f"{firm.id} consumption")

    def _pay_upkeep(self, firm: Firm, now: str) -> None:
        """Money leaving the world. Invariant 7's drain, per firm, per hour."""
        due = firm.upkeep_per_day // TICKS_PER_GAME_DAY
        if self.weather.rig_down(firm.id, self.tick):
            due += REPAIR_COST // TICKS_PER_GAME_DAY
        if due < 1:
            return
        try:
            with transaction(self.ledger.db):
                self.ledger.burn(firm.account, due, now,
                                 memo=f"{firm.id} upkeep")
        except MarketError:
            pass  # cannot pay; the receiver will notice below

    def _pay_wages(self, firm: Firm, now: str) -> None:
        """Pay the household sector. This is what makes the economy circulate.

        Credits enter the world at exactly one place -- Earth's standing order,
        at whichever node sells it helium-3. Everyone else is downstream of
        that, and without a wage bill the settlements at the other nodes would
        simply run out of money and stop buying, which is precisely the death
        spiral the demo harness showed when its haulers went broke.

        A firm that cannot make payroll pays nothing and is on its way to the
        receiver. It does not pay partially: a half-paid workforce is a
        modelling fiction, and the failure is more informative than the fudge.
        """
        due = firm.wages_per_day // TICKS_PER_GAME_DAY
        if due < 1:
            return
        households = [f for f in self.active_firms()
                      if f.role is Role.CONSUMER and f.node == firm.node]
        if not households:
            return
        share = due // len(households)
        if share < 1:
            return
        try:
            with transaction(self.ledger.db):
                for household in households:
                    self.ledger.transfer(
                        firm.account, household.account, CREDIT, share,
                        kind="wages", game_time=now, ref=firm.id,
                        memo=f"{firm.id} payroll",
                    )
        except MarketError:
            pass  # cannot make payroll; the receiver will notice

    # -- trading ---------------------------------------------------------

    def _quote(self, firm: Firm, now: str) -> None:
        """Refresh this firm's orders for the hour.

        Standing orders are pulled before new ones go up. This is not
        housekeeping -- it is the difference between a working agent and a
        bankrupt one.

        A resting bid holds its credits in escrow from the moment it is
        placed. A firm that re-bids its full shortfall every tick without
        retiring the previous bid escrows the same purchase again and again:
        the helium-3 separators in the first run of this world bled 201,066
        credits an hour against an expected 6,667, and were wound up with
        5.8 million credits still on their balance sheet, because almost all
        of their capital was locked behind orders they had already placed.

        Cancel-then-replace is also what a real market participant does: a
        quote is a statement about right now, not an accumulating pile of
        intentions.
        """
        for row in self.books[firm.node].open_orders(firm.account):
            try:
                self.books[firm.node].cancel(row["id"], now)
            except MarketError:
                pass

        if firm.role is Role.EXTRACTOR:
            deposit = self.deposits.get(firm.deposit_id or "")
            if deposit:
                self._sell_surplus(firm, deposit.asset, now)
        elif firm.role is Role.REFINER:
            self._buy_shortfall(firm, firm.input_asset, now)
            self._sell_surplus(firm, firm.output_asset, now)
        elif firm.role is Role.CONSUMER:
            self._buy_shortfall(firm, firm.consumes, now)
        elif firm.role is Role.TRADER:
            self._make_market(firm, firm.trades, now)

    def _sell_surplus(self, firm: Firm, asset: str, now: str) -> None:
        spec = self.ledger.asset(asset)
        held = self.ledger.balance(firm.account, asset)
        keep = firm.targets.get(asset, 0)
        surplus = held - keep
        if surplus >= spec.lot_mass_kg:
            self.behaviour.quote(firm, asset, ASK, surplus,
                                 self.elasticity(asset), now,
                                 self.reversion(asset))

    def _buy_shortfall(self, firm: Firm, asset: str, now: str) -> None:
        spec = self.ledger.asset(asset)
        held = self.ledger.balance(firm.account, asset)
        shortfall = firm.targets.get(asset, 0) - held
        if shortfall >= spec.lot_mass_kg:
            self.behaviour.quote(firm, asset, BID, shortfall,
                                 self.elasticity(asset), now,
                                 self.reversion(asset))

    def _make_market(self, firm: Firm, asset: str, now: str) -> None:
        """Quote both sides and live on the spread.

        Traders are what let the Ark Authority's share of volume fall to zero.
        Without someone quoting inside its spread, the institution stays the
        counterparty to everything and the training wheels never come off.
        """
        spec = self.ledger.asset(asset)
        book = self.books[firm.node]
        reference = self.behaviour.reference_price(firm, asset,
                                                   self.reversion(asset))
        edge = max(1, int(reference * 0.04))
        size = spec.kg(max(1, firm.targets.get(asset, spec.lot_mass_kg)
                           // spec.lot_mass_kg // 4))

        cash = self.ledger.balance(firm.account, CREDIT)
        bid = max(1, reference - edge)
        if cash >= bid * (size // spec.lot_mass_kg):
            try:
                book.place(asset, BID, bid, size, firm.account, now)
            except MarketError:
                pass
        if self.ledger.balance(firm.account, asset) >= size:
            try:
                book.place(asset, ASK, reference + edge, size,
                           firm.account, now)
            except MarketError:
                pass

    def _refresh_institutions(self, now: str) -> None:
        for node, assets in self.quoted_assets.items():
            authority = self.authorities.get(node)
            if authority is None:
                continue
            for asset in assets:
                try:
                    authority.quote(asset, now, bid_lots=60, ask_lots=60)
                except MarketError:
                    pass
        for node, asset in self.earth_assets.items():
            self.earth.refresh(node, asset, now)

    # -- failure and renewal ---------------------------------------------

    def _wind_up_failures(self, now: str) -> list[Event]:
        events: list[Event] = []
        for firm in self.active_firms():
            if not self.receiver.is_insolvent(firm):
                continue
            result = self.receiver.liquidate(firm, now)
            events.append(Event(
                tick=self.tick, kind="insolvency", subject=firm.id,
                detail=(f"wound up; {result.orders_cancelled} orders cancelled, "
                        f"estate listed: {result.assets_listed or 'nothing'}"),
            ))
        return events

    def _spin_off_successes(self, now: str) -> list[Event]:
        """Prosperous firms fund rivals out of their own balance sheet. D37."""
        events: list[Event] = []
        for firm in self.active_firms():
            start = self.starting_capital.get(firm.id, 0)
            if not self.receiver.should_spin_off(firm, start):
                continue
            self._spinoff_count += 1
            child_id = f"{firm.id}_spinoff_{self._spinoff_count}"
            child = self.receiver.spin_off(firm, child_id,
                                           f"agent:{child_id}", now)
            clone = Firm(
                id=child_id, role=firm.role, node=firm.node,
                account=f"agent:{child_id}", deposit_id=firm.deposit_id,
                nameplate_kg_per_day=firm.nameplate_kg_per_day,
                input_asset=firm.input_asset, output_asset=firm.output_asset,
                conversion_rate=firm.conversion_rate,
                consumes=firm.consumes,
                consumption_kg_per_day=firm.consumption_kg_per_day,
                trades=firm.trades, targets=dict(firm.targets),
                upkeep_per_day=firm.upkeep_per_day,
            )
            self.firms.append(clone)
            self.starting_capital[child_id] = child.capital
            events.append(Event(
                tick=self.tick, kind="spinoff", subject=firm.id,
                detail=f"capitalises {child_id} with {child.capital:,} cr",
            ))
        return events
