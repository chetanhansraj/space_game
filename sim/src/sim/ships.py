"""Ships: what they are, what they can carry, and what it costs them to move.

The bible: "A ship is defined by cargo capacity, delta-v, fuel mass, crew
requirement, hull integrity and upkeep. Upgrades improve one at the cost of
another: bigger tanks mean less cargo, better engines cost more to maintain.
There is no strictly best ship, only ships suited to particular routes."

That tradeoff is not a rule anyone has to enforce -- it falls out of the
rocket equation. A tonne of propellant is a tonne that is not cargo, so
range and payload are the same quantity spent two ways, and every route has
a different best answer.

    delta-v available = v_e * ln(wet mass / dry mass)

`docs/seed-data.md` gave the Kestrel a 40 t hold, one crew and 400 cr per game
day of upkeep, and nothing else -- no dry mass, no tank. Those are set in
docs/DECISIONS.md D41, chosen so a fully loaded Kestrel can just about make
a favourable 30-day Mars crossing, and an empty one can go almost anywhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

TONNE = 1_000

#: Fusion torch exhaust velocity, m/s. docs/DECISIONS.md D2.
#:
#: This is the game's constant, not the orbital service's -- it describes an
#: engine, not the solar system -- so `sim` owns it and everything else reads
#: it from here.
EXHAUST_VELOCITY = 400_000.0


class ShipState(str, Enum):
    DOCKED = "docked"
    IN_TRANSIT = "in_transit"


@dataclass(frozen=True)
class ShipClass:
    """A hull design. Immutable; ships are instances of one."""

    id: str
    name: str
    dry_mass_kg: int          # structure, engine, crew space. Never cargo.
    cargo_capacity_kg: int
    tank_capacity_kg: int
    crew: int
    upkeep_per_day: int
    hull_rating: int          # 1 light, 2 heavy. Hard burns need 2. D42.

    def max_wet_mass(self) -> int:
        return self.dry_mass_kg + self.cargo_capacity_kg + self.tank_capacity_kg

    def delta_v_available(self, cargo_kg: int, fuel_kg: int) -> float:
        """What this ship can still do, loaded as it is. Metres per second."""
        burnout = self.dry_mass_kg + cargo_kg
        if burnout <= 0 or fuel_kg <= 0:
            return 0.0
        return EXHAUST_VELOCITY * math.log((burnout + fuel_kg) / burnout)

    def fuel_for(self, dv: float, cargo_kg: int) -> int:
        """Propellant needed to make ``dv`` carrying ``cargo_kg``. Kilograms.

        Rounded up: a ship that departs with the exact theoretical minimum and
        loses a gram to rounding does not arrive.
        """
        if dv <= 0:
            return 0
        burnout = self.dry_mass_kg + cargo_kg
        return math.ceil(burnout * (math.expm1(dv / EXHAUST_VELOCITY)))

    def max_cargo_for(self, dv: float) -> int:
        """Largest payload that still leaves room for the fuel to move it.

        The whole tradeoff in one function. Solve
        ``fuel_for(dv, c) + c <= cargo + tank`` for c, given that fuel grows
        with cargo. Closed form, because the rocket equation is exponential
        in delta-v but linear in burnout mass.
        """
        if dv <= 0:
            return self.cargo_capacity_kg
        k = math.expm1(dv / EXHAUST_VELOCITY)
        budget = self.cargo_capacity_kg + self.tank_capacity_kg
        cargo = (budget - self.dry_mass_kg * k) / (1.0 + k)
        return max(0, min(self.cargo_capacity_kg, int(cargo)))


#: docs/seed-data.md gives the hold, crew and upkeep. The rest is D41.
KESTREL = ShipClass(
    id="kestrel", name="Kestrel-class light hauler",
    dry_mass_kg=30 * TONNE, cargo_capacity_kg=40 * TONNE,
    tank_capacity_kg=40 * TONNE, crew=1,
    upkeep_per_day=400, hull_rating=1,
)

CLASSES = {KESTREL.id: KESTREL}


@dataclass
class Ship:
    """One hull, owned by one firm."""

    id: str
    owner: str                       # firm id
    account: str                     # ledger account holding cargo and fuel
    ship_class: ShipClass
    location: str                    # node id when docked, origin when flying
    state: ShipState = ShipState.DOCKED

    destination: str | None = None
    depart_tick: int | None = None
    arrive_tick: int | None = None
    leg_dv: float = 0.0
    manifest: tuple[str, int] | None = None   # (asset, kg) riding along
    voyages: int = 0
    log: list[str] = field(default_factory=list)

    #: Flown by a person rather than by the hauling agent. The world tick
    #: moves a player's ship and docks it, and nothing else: it never picks
    #: a cargo, buys fuel or sells on a player's behalf unless they asked.
    player_owned: bool = False
    #: The player's standing instruction for arrival: sell the hold at the
    #: best bid on docking, or keep it aboard.
    sell_on_arrival: bool = True
    #: Docking fee paid in advance at departure, so an arrival can never
    #: fail for want of money. Recorded so the arrival report can say so.
    prepaid_fee: int = 0
    #: Kilograms bought at the current dock since arriving, by asset. Goods
    #: bought here cannot be handed over here against a delivery contract:
    #: a contract pays for carrying something, and buying it at the door is
    #: not carrying it. Cleared on departure.
    loaded: dict[str, int] = field(default_factory=dict)

    def progress(self, tick: int) -> float:
        """0 at departure, 1 on arrival. What the map draws."""
        if self.state is not ShipState.IN_TRANSIT:
            return 0.0
        span = (self.arrive_tick or 0) - (self.depart_tick or 0)
        if span <= 0:
            return 1.0
        return max(0.0, min(1.0, (tick - self.depart_tick) / span))

    @property
    def cargo_kg(self) -> int:
        return self.manifest[1] if self.manifest else 0
