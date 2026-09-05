"""What it costs to get from one node to another.

This is the game side of the boundary described in docs/DECISIONS.md D17. The
orbital service knows *anchors* -- a body plus its fixed gravity-well budgets
-- and has never heard of a node, a docking fee or a commodity. The mapping
from "Shackleton Depot" to the anchor `luna_south` lives here, in the game,
where it belongs.

Two kinds of leg, and they are genuinely different problems:

**Inside one gravity well** (Peary Ridge to Shackleton Depot) the cost is a
ballistic suborbital hop. It does not depend on the date at all, so it is
computed analytically and cached forever.

**Between wells** (the Moon to Ceres) the cost depends entirely on where the
two bodies are, which is the whole economic mechanic. In production these are
read from the precomputed transfer table -- invariant 4 forbids solving a
Lambert problem in a request handler. The simulation tick is not a request
handler, but it runs sixty times a real hour and a sweep costs eleven
milliseconds, so it uses the same table.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

#: Which anchor each v1/v2 node sits on. The game owns this; orbital does not.
NODE_ANCHOR = {
    "shackleton_depot": "luna_south",
    "peary_ridge": "luna_north",
    "tranquillitatis_flats": "luna_equatorial",
    "selene_station": "luna_orbit",
    "ark_terminus": "luna_south",
    "eros_claim_field": "eros",
    "vesta_station": "vesta",
    "ceres_exchange": "ceres",
    "psyche_works": "psyche",
    "pallas_reach": "pallas",
    "tharsis_yards": "mars",
    "hellas_agricultural": "mars",
}

#: docs/seed-data.md, docking fee column. Paid on arrival, into the sink.
DOCKING_FEE = {
    "shackleton_depot": 800, "peary_ridge": 300, "tranquillitatis_flats": 400,
    "selene_station": 1_200, "ark_terminus": 2_000, "eros_claim_field": 200,
    "vesta_station": 1_500, "ceres_exchange": 2_500, "psyche_works": 900,
    "pallas_reach": 600, "tharsis_yards": 3_000, "hellas_agricultural": 1_800,
}


@dataclass(frozen=True)
class Leg:
    """A costed journey between two nodes."""

    origin: str
    destination: str
    dv: float            # m/s
    tof_s: float         # seconds of game time
    kind: str            # "hop" | "transfer"

    def ticks(self, ticks_per_game_day: int = 24) -> int:
        """Transit in whole ticks. Never less than one -- arriving in the
        same hour you left is not a journey, and it lets a zero-length leg
        loop forever inside one tick."""
        return max(1, round(self.tof_s / 86_400.0 * ticks_per_game_day))


class RouteBook:
    """Resolves node pairs to legs, against an orbital anchor registry."""

    def __init__(self, registry) -> None:
        self.registry = registry

    @lru_cache(maxsize=512)
    def _local(self, a: str, b: str) -> tuple[float, float]:
        return self.registry.local_transfer(a, b)

    def leg(self, origin: str, destination: str, jd: float | None = None) -> Leg | None:
        """Cost one journey. ``None`` if the route cannot be flown today."""
        a, b = NODE_ANCHOR.get(origin), NODE_ANCHOR.get(destination)
        if a is None or b is None or a == b:
            return None

        if self.registry.same_well(a, b):
            dv, tof = self._local(a, b)
            return Leg(origin, destination, dv, tof, "hop")

        if jd is None:
            return None
        from orbital.curve import build_curve

        try:
            curve = build_curve(
                lambda t: self.registry.state(a, t),
                lambda t: self.registry.state(b, t),
                jd, dv_fixed=self.registry.fixed_budget(a, b), samples=24,
            )
        except RuntimeError:
            return None
        best = curve.cheapest
        return Leg(origin, destination, best.dv_total, best.tof, "transfer")
