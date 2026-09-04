"""Analytic ephemeris via ERFA's VSOP87-derived series.

No data files, no download, always available. Accuracy over 1000-3000 AD is
tens of arcseconds for the inner planets -- comfortably inside the arcminute
target, and its real value is being a completely independent implementation
to test the JPL kernel backends against.

Frame note, asserted in the tests rather than assumed: both ``erfa.plan94``
and ``erfa.epv00`` return heliocentric vectors referred to the mean equator
and equinox of J2000 -- the same equatorial frame the DE kernels use. No
rotation is applied. This was verified by direct comparison against DE421
rather than read off a docstring; an incorrect 23.44 degree rotation here
produces positions that look completely reasonable and are 23 degrees wrong.
"""

from __future__ import annotations

import erfa
import numpy as np

from ..constants import JD_J2000
from ..frames import au_per_day_to_m_per_s, au_to_m
from . import EARTH_MOON, JUPITER, MARS, MERCURY, SATURN, SUN, VENUS, State

# ERFA plan94 body numbers. Note that 3 is the Earth-Moon barycentre, which
# is exactly what this service wants: the bible treats the Earth-Moon system
# as a single point for interplanetary purposes.
_PLAN94 = {
    MERCURY: 1,
    VENUS: 2,
    EARTH_MOON: 3,
    MARS: 4,
    JUPITER: 5,
    SATURN: 6,
}

# plan94 is documented as valid 1000-3000 AD; it degrades outside that.
_FIRST_JD = 2_086_302.5  # 1000-01-01
_LAST_JD = 2_816_787.5   # 3000-01-01


class AnalyticBackend:
    name = "erfa-plan94"

    def state(self, body: str, jd_tt: float) -> State:
        if body == SUN:
            return State(r=np.zeros(3), v=np.zeros(3))
        try:
            index = _PLAN94[body]
        except KeyError:
            raise ValueError(f"analytic backend has no body {body!r}") from None

        # plan94 splits the date for precision: integer part plus fraction.
        jd1 = JD_J2000
        jd2 = jd_tt - JD_J2000
        pv = erfa.plan94(jd1, jd2, index)
        return State(
            r=au_to_m(np.asarray(pv[0], dtype=float)),
            v=au_per_day_to_m_per_s(np.asarray(pv[1], dtype=float)),
        )

    def coverage(self) -> tuple[float, float]:
        return (_FIRST_JD, _LAST_JD)


class EpvEarthBackend:
    """Earth only, via ``erfa.epv00``. Sub-milliarcsecond, equatorial already.

    Exists purely as a third opinion on the Earth-Moon position in tests. Not
    used in production: it covers one body, and it returns Earth rather than
    the Earth-Moon barycentre, a distinction worth about 4,700 km.
    """

    name = "erfa-epv00"

    def state(self, body: str, jd_tt: float) -> State:
        if body != EARTH_MOON:
            raise ValueError("epv00 backend covers Earth only")
        pvh, _pvb = erfa.epv00(JD_J2000, jd_tt - JD_J2000)
        return State(
            r=au_to_m(np.asarray(pvh[0], dtype=float)),
            v=au_per_day_to_m_per_s(np.asarray(pvh[1], dtype=float)),
        )

    def coverage(self) -> tuple[float, float]:
        return (2_305_447.5, 2_597_641.5)  # 1600-2200
