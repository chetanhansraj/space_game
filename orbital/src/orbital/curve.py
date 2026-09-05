"""Cost curves: the shape the orbital service actually returns.

This is the design decision that resolves the tension in the bible between
"three trajectory classes" and "no game concepts inside the orbital service".

The service does not return classes. It returns the Pareto frontier of the
delta-v against time-of-flight tradeoff for a given departure: a list of
points where no other point is both faster and cheaper. Naming a point on
that curve "standard torch" or "hard burn" is a game decision, and it lives
in ``sim/`` where game decisions belong.

This is strictly more useful than three fixed classes. A ship with an unusual
mass ratio, a contract with an odd deadline, and a player willing to overpay
for one hour of speed all want different points, and they read them off the
same curve. It also means the trajectory-class definitions can be retuned
without regenerating a single transfer table.

The frontier is monotonic by construction: as time of flight increases,
delta-v decreases. That is the entire economic mechanic of the game
expressed as a data structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

from .constants import GM_SUN
from .ephemeris import State
from .lambert import hohmann_time
from .costs import Transfer
from .transfer import cheapest

StateFn = Callable[[float], State]


@dataclass(frozen=True)
class CostCurve:
    """Pareto-optimal transfers for one origin, destination and departure."""

    departure_jd: float
    points: tuple[Transfer, ...]

    def __len__(self) -> int:
        return len(self.points)

    @property
    def cheapest(self) -> Transfer:
        """The minimum-energy end of the curve: slowest, least delta-v."""
        return self.points[-1]

    @property
    def fastest(self) -> Transfer:
        """The quickest arc on the curve, and the most expensive."""
        return self.points[0]

    def at_most(self, tof: float) -> Transfer | None:
        """Cheapest transfer arriving within ``tof`` seconds. None if too fast."""
        for point in reversed(self.points):
            if point.tof <= tof:
                return point
        return None

    def within_budget(self, dv: float) -> Transfer | None:
        """Fastest transfer costing no more than ``dv`` m/s. None if too poor."""
        for point in self.points:
            if point.dv_total <= dv:
                return point
        return None


def pareto(transfers: Sequence[Transfer]) -> tuple[Transfer, ...]:
    """Reduce a sampled sweep to its non-dominated points.

    A transfer is dominated if another is both no slower and no more
    expensive. Walking in order of increasing time of flight and keeping
    only strict improvements in delta-v leaves exactly the frontier.

    The sort breaks ties on delta-v as well as time of flight. Without that,
    two arcs with the same flight time -- which happens when a direct and a
    single-revolution solution land on the same grid sample -- can both
    survive, and the frontier ends up carrying a point that something else
    strictly dominates.
    """
    ordered = sorted(transfers, key=lambda t: (t.tof, t.dv_total))
    frontier: list[Transfer] = []
    best = float("inf")
    for candidate in ordered:
        if candidate.dv_total < best:
            frontier.append(candidate)
            best = candidate.dv_total
    return tuple(frontier)


def build_curve(
    origin: StateFn,
    destination: StateFn,
    departure_jd: float,
    dv_fixed: float = 0.0,
    samples: int = 48,
    tof_min: float | None = None,
    tof_max: float | None = None,
    mu: float = GM_SUN,
    max_revolutions: int = 1,
) -> CostCurve:
    """Sweep time of flight and return the Pareto frontier.

    The sweep range defaults to a span around the Hohmann time for the two
    orbits, which is the natural length scale of the route: from 5% of it
    (a hard burn that costs a fortune) out to 1.6x (a lazy arc that waits for
    the geometry). Sampling is geometric rather than linear because the
    interesting structure is all at the fast end, where delta-v climbs
    steeply.
    """
    departure_state = origin(departure_jd)

    if tof_min is None or tof_max is None:
        a1 = departure_state.radius
        a2 = destination(departure_jd).radius
        reference = hohmann_time(a1, a2, mu=mu)
        tof_min = tof_min if tof_min is not None else 0.05 * reference
        tof_max = tof_max if tof_max is not None else 1.60 * reference

    grid = np.geomspace(tof_min, tof_max, samples)

    found: list[Transfer] = []
    for tof in grid:
        arrival_jd = departure_jd + tof / 86400.0
        transfer = cheapest(
            departure_state,
            destination(arrival_jd),
            float(tof),
            dv_fixed=dv_fixed,
            mu=mu,
            max_revolutions=max_revolutions,
        )
        if transfer is not None:
            found.append(transfer)

    if not found:
        raise RuntimeError(
            f"no convergent arcs for departure jd={departure_jd}"
        )

    return CostCurve(departure_jd=departure_jd, points=pareto(found))
