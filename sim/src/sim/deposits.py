"""Ore bodies, and the depletion that moves the frontier.

The bible: "Every extraction site has a finite ore body with a richness value
that falls as it is worked. A rock that has been mined for six months yields
less per hour than it did on day one. This is the primary reason the frontier
keeps moving outward and the primary defence against price collapse."

`docs/seed-data.md` left the curve shape and decay rate open. Both are decided
here -- see docs/DECISIONS.md D38.

Richness decays exponentially in cumulative mass extracted:

    richness(x) = exp(-x / scale)

Exponential rather than hyperbolic because the tail matters. A hyperbolic
curve leaves a worked-out rock limping along at 10% forever, which keeps
marginal supply on the market and blunts exactly the pressure that is supposed
to push players outward. Exponential decay makes a mature site genuinely not
worth working, and that is the point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Below this richness a site is not worth the power to run, and is abandoned.
ABANDON_RICHNESS = 0.05


@dataclass
class Deposit:
    """A finite ore body at one node.

    ``scale`` is the mass that reduces richness to 1/e (about 37%). It is the
    single number that says how long this rock is worth working.
    """

    id: str
    node: str
    asset: str
    scale_kg: int
    extracted_kg: int = 0
    history: list[tuple[int, float]] = field(default_factory=list)

    @property
    def richness(self) -> float:
        return math.exp(-self.extracted_kg / self.scale_kg)

    @property
    def exhausted(self) -> bool:
        return self.richness < ABANDON_RICHNESS

    def yield_for(self, nameplate_kg: int) -> int:
        """What a rig rated at ``nameplate_kg`` actually gets this tick.

        Returns whole kilograms; a rig on a poor rock can return zero, which
        is the correct signal to shut it down rather than a rounding bug.
        """
        return int(nameplate_kg * self.richness)

    def work(self, mass_kg: int, tick: int) -> None:
        if mass_kg < 0:
            raise ValueError("cannot un-mine a deposit")
        self.extracted_kg += mass_kg
        self.history.append((tick, self.richness))

    def half_life_kg(self) -> float:
        """Mass extracted before output halves. The number to quote to players."""
        return self.scale_kg * math.log(2)
