"""Reference frame and unit conversions.

The internal canonical state is:

    heliocentric, ICRF/J2000 equatorial, metres and metres per second

Everything entering the service is converted to that on the way in, and
everything leaving is converted on the way out. There are exactly two traps
this module exists to contain, and both of them produce numbers that look
entirely plausible while being wrong:

1. SPICE/DE kernels return positions relative to the solar system
   barycentre, not the Sun. The Sun wanders about 0.01 AU around the SSB
   under Jupiter's pull. A Lambert solve using mu_sun with SSB-referenced
   vectors is wrong by roughly that much and will not obviously fail.

2. Analytic ephemerides do not all agree about frames, and their docstrings
   are not always enough to tell. ERFA's ``epv00`` and ``plan94`` both turn
   out to return equatorial vectors, but that was established by comparing
   their output against DE421 rather than assumed -- an unnecessary ecliptic
   rotation tilts a body by 23.4 degrees while leaving its distance from the
   Sun exactly right, so every sanity check short of a direct comparison
   passes. The rotation helpers below stay because small-body elements are
   published in the ecliptic frame and do need them.
"""

from __future__ import annotations

import numpy as np

from .constants import AU, DAY, KM, OBLIQUITY_J2000

_COS_E = np.cos(OBLIQUITY_J2000)
_SIN_E = np.sin(OBLIQUITY_J2000)

#: Rotate an ecliptic J2000 vector into the equatorial ICRF frame.
ECLIPTIC_TO_EQUATORIAL = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, _COS_E, -_SIN_E],
        [0.0, _SIN_E, _COS_E],
    ]
)

EQUATORIAL_TO_ECLIPTIC = ECLIPTIC_TO_EQUATORIAL.T


def ecliptic_to_equatorial(vec: np.ndarray) -> np.ndarray:
    return ECLIPTIC_TO_EQUATORIAL @ np.asarray(vec, dtype=float)


def equatorial_to_ecliptic(vec: np.ndarray) -> np.ndarray:
    return EQUATORIAL_TO_ECLIPTIC @ np.asarray(vec, dtype=float)


def au_to_m(vec: np.ndarray) -> np.ndarray:
    return np.asarray(vec, dtype=float) * AU


def au_per_day_to_m_per_s(vec: np.ndarray) -> np.ndarray:
    return np.asarray(vec, dtype=float) * (AU / DAY)


def km_to_m(vec: np.ndarray) -> np.ndarray:
    return np.asarray(vec, dtype=float) * KM


def km_per_day_to_m_per_s(vec: np.ndarray) -> np.ndarray:
    return np.asarray(vec, dtype=float) * (KM / DAY)
