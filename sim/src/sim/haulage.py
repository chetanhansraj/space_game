"""The merchant: deciding whether a run is worth flying, and flying it.

This is the loop the whole game is built around. The bible: "The moment there
are two places with different prices, the game becomes trade, and that is the
real product."

A hauler looks at one commodity in two places and asks whether the gap covers
the cost of closing it:

    revenue  = cargo x price it will fetch there
    cost     = cargo x price it costs here
             + propellant burned getting there
             + the docking fee on arrival

If what is left is worth the trip, it buys, fuels, and goes. If not, it waits.
Nothing else is needed to produce a merchant.

Two consequences worth watching for, because they are the point rather than
side effects:

**Ships buy their own propellant**, which is where propellant demand comes
from. The bible calls propellant "effectively a second currency... consumed by
the act of trading", and this is that sentence made mechanical: every run
burns fuel someone had to refine, so hauling is what makes the electrolysis
plants worth owning.

**Arbitrage closes the gap it feeds on.** Shackleton ice sits at 657 and Peary
at 333 only because nothing moves between them. Once ships run, the spread
should fall toward the cost of the run and stop there. If it collapses to
zero the model is wrong; if it never moves, the haulers are not working.
"""

from __future__ import annotations

from dataclasses import dataclass

from market.book import ASK, BID
from market.db import transaction
from market.errors import MarketError
from market.money import CREDIT

from .routes import DOCKING_FEE, Leg
from .ships import Ship, ShipState

#: A run must clear this much to be worth flying. Below it the hauler waits
#: rather than burn a ship's life on a rounding error.
MIN_MARGIN = 2_000

#: What the hauler expects to pay per tonne of propellant when it has no
#: local quote to go on. The seed anchor, per docs/seed-data.md.
FALLBACK_FUEL_PRICE = 1_800

#: How far above the going rate a hauler will bid to win cargo, and how far
#: below it will offer to shift cargo on arrival, in percent.
#:
#: Without these the hauler priced every run off `best_ask`, and in a thin
#: book the only resting ask is the Ark Authority's ceiling -- 700 for ice
#: against a market trading at 333. Valued that way, no run on the map was
#: ever profitable, because the hauler believed it had to lift the
#: institution's offer. A merchant bids against the going rate; it does not
#: pay the ceiling.
BID_PREMIUM = 5
ASK_DISCOUNT = 4


@dataclass(frozen=True)
class Prospect:
    """A run the hauler could make, and what it thinks it is worth."""

    asset: str
    destination: str
    leg: Leg
    cargo_kg: int
    fuel_kg: int
    buy_price: int
    sell_price: int
    margin: int


class Haulier:
    """Evaluates and flies runs for one fleet."""

    def __init__(self, world) -> None:
        self.w = world

    # -- deciding -------------------------------------------------------

    def survey(self, ship: Ship, assets: tuple[str, ...]) -> Prospect | None:
        """The best run available from where this ship is sitting, or None."""
        best: Prospect | None = None
        here = ship.location
        home = self.w.books.get(here)
        if home is None:
            return None

        for destination in self.w.books:
            if destination == here:
                continue
            leg = self.w.routes.leg(here, destination)
            if leg is None:
                continue

            for asset in assets:
                spec = self.w.ledger.asset(asset)
                buy = self._bid_price(home, asset)
                sell = self._sale_price(self.w.books[destination], asset)
                if not buy or not sell or sell <= buy:
                    continue

                cargo = ship.ship_class.max_cargo_for(leg.dv)
                cargo -= cargo % spec.lot_mass_kg
                available = self._affordable(ship, buy, cargo, leg, spec.lot_mass_kg)
                cargo = min(cargo, available)
                if cargo < spec.lot_mass_kg:
                    continue

                fuel = ship.ship_class.fuel_for(leg.dv, cargo)
                lots = cargo // spec.lot_mass_kg
                fuel_price = home.best_ask("PROP") or FALLBACK_FUEL_PRICE
                margin = (sell - buy) * lots \
                    - fuel_price * -(-fuel // 1_000) \
                    - DOCKING_FEE.get(destination, 0)

                if margin >= MIN_MARGIN and (best is None or margin > best.margin):
                    best = Prospect(asset, destination, leg, cargo, fuel,
                                    buy, sell, margin)
        return best

    def _going_rate(self, book, asset: str) -> int | None:
        """What this commodity is actually changing hands for, here, now.

        The last trade first. A resting quote in a thin book is as likely to
        be an institution's floor or ceiling as a real price, and pricing a
        voyage off one of those is how the haulers concluded there was no
        trade worth making anywhere in the system.
        """
        last = book.last_price(asset)
        if last:
            return last
        bid, ask = book.best_bid(asset), book.best_ask(asset)
        if bid and ask:
            return (bid + ask) // 2
        return bid or ask

    def _bid_price(self, book, asset: str) -> int | None:
        """What the hauler will pay here. Never more than the standing ask."""
        rate = self._going_rate(book, asset)
        if not rate:
            return None
        bid = max(1, rate * (100 + BID_PREMIUM) // 100)
        ask = book.best_ask(asset)
        return min(bid, ask) if ask else bid

    def _sale_price(self, book, asset: str) -> int | None:
        """What the hauler expects to realise there, conservatively."""
        rate = self._going_rate(book, asset)
        if not rate:
            return None
        return max(1, rate * (100 - ASK_DISCOUNT) // 100)

    def _affordable(self, ship: Ship, buy: int, cargo: int, leg: Leg,
                    lot: int) -> int:
        """Trim the load to what the owner can actually pay for.

        A hauler that loads a full hold it cannot fund ends up with the cargo
        stuck in escrow and no money for fuel, which is how the demo harness's
        agents bankrupted themselves before anyone noticed.
        """
        cash = self.w.ledger.balance(ship.account, CREDIT)
        fuel_price = self.w.books[ship.location].best_ask("PROP") or FALLBACK_FUEL_PRICE
        spare = cash - DOCKING_FEE.get(leg.destination, 0)
        lots = 0
        while lots * lot < cargo:
            trial = (lots + 1) * lot
            fuel_t = -(-ship.ship_class.fuel_for(leg.dv, trial) // 1_000)
            if buy * (lots + 1) + fuel_price * fuel_t > spare:
                break
            lots += 1
        return lots * lot

    def unload(self, ship: Ship, now: str) -> int:
        """Sell anything still in the hold at the current node.

        A ship that arrives somewhere with no bid on its cargo keeps the
        cargo. Without this it sits loaded forever: the hold is full, so no
        new run can be planned, and the ship is retired by accident. Trying
        again each tick is what a stuck freighter would actually do.
        """
        sold = 0
        book = self.w.books[ship.location]
        for asset, held in self.w.ledger.holdings(ship.account).items():
            if asset in (CREDIT, "PROP") or held <= 0:
                continue
            spec = self.w.ledger.asset(asset)
            qty = held - held % spec.lot_mass_kg
            price = book.best_bid(asset) or self._sale_price(book, asset)
            if qty < spec.lot_mass_kg or not price:
                continue
            try:
                book.place(asset, ASK, price, qty, ship.account, now)
                sold += qty
            except MarketError:
                pass
        self._cancel(ship, now)
        return sold

    def refuel(self, ship: Ship, now: str) -> int:
        """Top the tank up wherever propellant can be bought.

        Fuel is a stock the ship carries, not something bought at the moment
        of departure. That distinction is not pedantry: Peary Ridge produces
        no propellant at all, so under a just-in-time model every hauler
        based there was permanently stranded -- it could never buy the fuel
        it needed to leave for the one place selling fuel.

        A ship fills up where it can and spends the tank where it must, which
        is also why propellant is worth hauling to a node that has none.
        """
        tank = ship.ship_class.tank_capacity_kg
        held = self.w.ledger.balance(ship.account, "PROP")
        if held >= tank * 0.75:
            return 0
        book = self.w.books[ship.location]
        price = self._bid_price(book, "PROP")
        if not price:
            return 0                          # nothing for sale here
        want = tank - held
        lots = want // 1_000
        cash = self.w.ledger.balance(ship.account, CREDIT)
        lots = min(lots, cash // (price * 2))  # never spend more than half on fuel
        if lots < 1:
            return 0
        try:
            got = book.place("PROP", BID, price, lots * 1_000, ship.account, now)
        except MarketError:
            return 0
        self._cancel(ship, now)
        return got.filled_kg

    # -- flying ---------------------------------------------------------

    def dispatch(self, ship: Ship, plan: Prospect, tick: int, now: str) -> bool:
        """Buy the cargo, buy and burn the fuel, and go.

        Everything or nothing: if the cargo fills but the fuel does not, the
        ship stays docked holding cargo it can sell again next tick, rather
        than departing on a tank it never bought.
        """
        book = self.w.books[ship.location]
        spec = self.w.ledger.asset(plan.asset)

        try:
            bought = book.place(plan.asset, BID, plan.buy_price, plan.cargo_kg,
                                ship.account, now)
        except MarketError:
            return False
        if bought.filled_kg < spec.lot_mass_kg:
            self._cancel(ship, now)
            return False
        self._cancel(ship, now)               # drop any unfilled remainder

        cargo = bought.filled_kg
        fuel = ship.ship_class.fuel_for(plan.leg.dv, cargo)
        if self.w.ledger.balance(ship.account, "PROP") < fuel:
            return False                      # dry tank: the run does not happen

        with transaction(self.w.ledger.db):
            self.w.ledger.consume(ship.account, "PROP", fuel, now,
                                  memo=f"{ship.id} transit burn")

        ship.state = ShipState.IN_TRANSIT
        ship.destination = plan.destination
        ship.depart_tick = tick
        ship.arrive_tick = tick + plan.leg.ticks()
        ship.leg_dv = plan.leg.dv
        ship.manifest = (plan.asset, cargo)
        ship.log.append(f"T{tick} depart {ship.location} -> {plan.destination}"
                        f" with {cargo//1000} t {plan.asset}")
        del ship.log[:-20]      # a ship in a world that never stops
        return True

    def arrive(self, ship: Ship, tick: int, now: str) -> int:
        """Dock, pay the fee, sell the cargo. Returns credits realised."""
        node = ship.destination or ship.location
        ship.location = node
        ship.state = ShipState.DOCKED
        ship.destination = None
        ship.voyages += 1

        fee = DOCKING_FEE.get(node, 0)
        if fee:
            try:
                with transaction(self.w.ledger.db):
                    self.w.ledger.burn(ship.account, fee, now,
                                       memo=f"{ship.id} docking at {node}")
            except MarketError:
                pass

        if not ship.manifest:
            return 0
        asset, qty = ship.manifest
        book = self.w.books[node]
        price = book.best_bid(asset) or self._sale_price(book, asset)
        held = self.w.ledger.balance(ship.account, asset)
        qty = min(qty, held)
        spec = self.w.ledger.asset(asset)
        if not price or qty < spec.lot_mass_kg:
            ship.manifest = None
            return 0
        before = self.w.ledger.balance(ship.account, CREDIT)
        try:
            book.place(asset, ASK, price, qty - qty % spec.lot_mass_kg,
                       ship.account, now)
        except MarketError:
            pass
        self._cancel(ship, now)
        ship.manifest = None
        realised = self.w.ledger.balance(ship.account, CREDIT) - before
        ship.log.append(f"T{tick} arrive {node}, sold for {realised:,} cr")
        del ship.log[:-20]
        return realised

    def _cancel(self, ship: Ship, now: str) -> None:
        for row in self.w.books[ship.location].open_orders(ship.account):
            try:
                self.w.books[ship.location].cancel(row["id"], now)
            except MarketError:
                pass
