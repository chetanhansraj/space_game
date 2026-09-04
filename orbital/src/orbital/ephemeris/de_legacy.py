"""JPL DE421 via the legacy ``jplephem`` coefficient packages.

The ``de421`` distribution on PyPI ships its Chebyshev coefficients as
importable numpy arrays rather than a binary SPK. That makes it the only
real JPL ephemeris obtainable without reaching naif.jpl.nasa.gov, so it is
what CI and sealed build environments use.

DE421 covers 1900-2050 and is a generation behind DE440, but the difference
between them for inner-planet positions is well under an arcsecond -- three
orders of magnitude inside the accuracy target. It is a legitimate stand-in,
not a compromise.
"""

from __future__ import annotations

import numpy as np

from ..frames import km_per_day_to_m_per_s, km_to_m
from . import EARTH_MOON, JUPITER, MARS, MERCURY, SATURN, SUN, VENUS, State

_NAMES = {
    EARTH_MOON: "earthmoon",
    MARS: "mars",
    MERCURY: "mercury",
    VENUS: "venus",
    JUPITER: "jupiter",
    SATURN: "saturn",
    SUN: "sun",
}

_FIRST_JD = 2_414_992.5  # 1899-07-29
_LAST_JD = 2_471_184.5   # 2053-10-09


class LegacyBackend:
    name = "de421"

    def __init__(self) -> None:
        import de421
        from jplephem import Ephemeris

        self._eph = Ephemeris(de421)

    def _ssb(self, body: str, jd_tt: float) -> tuple[np.ndarray, np.ndarray]:
        pos, vel = self._eph.position_and_velocity(_NAMES[body], jd_tt)
        return np.ravel(pos).astype(float), np.ravel(vel).astype(float)

    def state(self, body: str, jd_tt: float) -> State:
        if body not in _NAMES:
            raise ValueError(f"de421 backend has no body {body!r}")

        # The kernel is barycentric. Subtracting the Sun is not optional:
        # the Sun sits up to ~0.01 AU from the solar system barycentre, and a
        # Lambert solve using GM_sun against SSB vectors is wrong by that much
        # while looking entirely reasonable.
        body_r, body_v = self._ssb(body, jd_tt)
        sun_r, sun_v = self._ssb(SUN, jd_tt)

        return State(
            r=km_to_m(body_r - sun_r),
            v=km_per_day_to_m_per_s(body_v - sun_v),
        )

    def coverage(self) -> tuple[float, float]:
        return (_FIRST_JD, _LAST_JD)
