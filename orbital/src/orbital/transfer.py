"""Turning a Lambert arc into a delta-v cost.

The cost of a transfer between two anchors is:

    departure v-infinity + arrival v-infinity + fixed anchor budgets

The v-infinity terms are the hyperbolic excess speeds -- the difference
between the velocity the transfer arc needs and the velocity the body is
already moving at. The fixed budgets cover getting off a surface or out of a
local gravity well, and never change with geometry (see ``lunar``).

This is a patched-conic cost, which is the committed model. It ignores the
Oberth benefit of burning deep in a gravity well, which would reduce the real
cost of departing from a surface. That is a deliberate simplification in the
conservative direction and is documented rather than hidden.
"""

from __future__ import annotations

import numpy as np

from .constants import GM_SUN
from .costs import Transfer
from .ephemeris import State
from .lambert import Arc, LambertFailure, solve

__all__ = ["Transfer", "cost", "cheapest"]


def cost(
    origin: State,
    destination: State,
    tof: float,
    dv_fixed: float = 0.0,
    mu: float = GM_SUN,
    revolutions: int = 0,
) -> Transfer:
    """Cost a single arc between two body states separated by ``tof``."""
    arc: Arc = solve(origin.r, destination.r, tof, mu=mu, revolutions=revolutions)
    dv_depart = float(np.linalg.norm(arc.v1 - origin.v))
    dv_arrive = float(np.linalg.norm(arc.v2 - destination.v))
    return Transfer(
        tof=float(tof),
        dv_depart=dv_depart,
        dv_arrive=dv_arrive,
        dv_fixed=float(dv_fixed),
        revolutions=revolutions,
    )


def cheapest(
    origin: State,
    destination: State,
    tof: float,
    dv_fixed: float = 0.0,
    mu: float = GM_SUN,
    max_revolutions: int = 1,
) -> Transfer | None:
    """Cheapest arc for this time of flight, considering multi-revolution paths.

    For long times of flight a transfer that loops the Sun once can be
    cheaper than the direct arc. Sweeping revolutions is what stops the cost
    curve developing a spurious cliff where the direct solution goes bad.
    Returns ``None`` if no revolution count converged.
    """
    best: Transfer | None = None
    for revs in range(max_revolutions + 1):
        for low_path in (True, False) if revs else (True,):
            try:
                arc = solve(origin.r, destination.r, tof, mu=mu,
                            revolutions=revs, low_path=low_path)
            except LambertFailure:
                continue
            candidate = Transfer(
                tof=float(tof),
                dv_depart=float(np.linalg.norm(arc.v1 - origin.v)),
                dv_arrive=float(np.linalg.norm(arc.v2 - destination.v)),
                dv_fixed=float(dv_fixed),
                revolutions=revs,
            )
            if best is None or candidate.dv_total < best.dv_total:
                best = candidate
    return best
