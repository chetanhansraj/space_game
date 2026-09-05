"""Lambert arc solving. Izzo 2015, via lamberthub.

Deliberately thin. The wrapper exists so that the rest of the service never
touches a third-party solver signature directly, which means swapping in a
vendored Izzo implementation later is a one-file change on the most
correctness-critical numeric path in the service.

Everything here is SI: metres, seconds, metres per second.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from lamberthub import izzo2015

from .constants import GM_SUN


class LambertFailure(RuntimeError):
    """The solver did not converge for these inputs."""


@dataclass(frozen=True)
class Arc:
    """A ballistic transfer arc between two position vectors."""

    v1: np.ndarray       # velocity on the arc at departure, m/s
    v2: np.ndarray       # velocity on the arc at arrival, m/s
    tof: float           # seconds
    revolutions: int


def solve(
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float = GM_SUN,
    revolutions: int = 0,
    prograde: bool = True,
    low_path: bool = True,
) -> Arc:
    """Solve the Lambert problem for a single arc.

    ``prograde`` is correct for every body in this game: the planets and all
    five candidate asteroid nodes orbit prograde, and a retrograde transfer
    between prograde bodies costs an absurd amount of delta-v.
    """
    if tof <= 0:
        raise ValueError("time of flight must be positive")
    try:
        v1, v2 = izzo2015(
            mu,
            np.asarray(r1, dtype=float),
            np.asarray(r2, dtype=float),
            float(tof),
            M=revolutions,
            prograde=prograde,
            low_path=low_path,
            maxiter=64,
            atol=1e-5,
            rtol=1e-7,
        )
    except Exception as exc:  # solver raises a variety of types
        raise LambertFailure(
            f"Lambert failed: tof={tof:.1f}s revolutions={revolutions}"
        ) from exc

    if not (np.all(np.isfinite(v1)) and np.all(np.isfinite(v2))):
        raise LambertFailure("Lambert returned non-finite velocities")

    return Arc(v1=np.asarray(v1, float), v2=np.asarray(v2, float),
               tof=float(tof), revolutions=revolutions)


def hohmann_time(a1: float, a2: float, mu: float = GM_SUN) -> float:
    """Half-period of the ellipse tangent to both circular orbits, seconds.

    Not used as a transfer in its own right -- real bodies are not on
    circular coplanar orbits -- but it is the natural length scale for a
    route, so it sets the time-of-flight range that gets swept when building
    a cost curve.
    """
    a_t = 0.5 * (a1 + a2)
    return float(np.pi * np.sqrt(a_t**3 / mu))
