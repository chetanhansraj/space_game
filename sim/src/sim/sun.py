"""The one Sun over the Moon.

There is one Sun in this world and every place on the Moon keeps time by
it (docs/DECISIONS.md D93). The globe is lit from where it stands; a town's
day and night follow it; and both ask here, so they cannot disagree.

Low-precision series (Meeus, ch. 47, leading terms only), good to about a
degree. A terminator a degree out of place is not something anyone can see
on a globe, and a town's sunrise an hour or two early is not something
anyone can plan against.
"""

from __future__ import annotations

import math

#: Hours from one sunrise to the next anywhere on the Moon. The town's rules
#: own this number (city/src/sim/sim.ts LUNAR_DAY); it is repeated here only
#: to turn an angle into the hours those rules count in.
LUNAR_DAY = 708


def elongation(jd: float) -> float:
    """The Moon's angle from the Sun as seen from Earth, degrees 0 to 360."""
    d = jd - 2_451_545.0
    moon_l = 218.316 + 13.176396 * d
    moon_m = math.radians(134.963 + 13.064993 * d)
    moon_lon = moon_l + 6.289 * math.sin(moon_m)
    sun_g = math.radians(357.528 + 0.9856003 * d)
    sun_lon = (280.460 + 0.9856474 * d + 1.915 * math.sin(sun_g)
               + 0.020 * math.sin(2 * sun_g))
    return (moon_lon - sun_lon) % 360.0


def subsolar_lon(jd: float) -> float:
    """The longitude the Sun is overhead at, degrees east, -180 to 180.

    New moon puts the Sun over the far side (180), full moon over the near
    side (0), first quarter over the eastern limb (+90). It moves west.
    """
    return (180.0 - elongation(jd) + 540.0) % 360.0 - 180.0


def hours_since_noon(lon: float, jd: float) -> float:
    """Hours since the Sun was highest over this longitude: -354 to 354.

    Negative in the morning. In the hours a town's rules count: a whole
    turn of the Sun is LUNAR_DAY of them.
    """
    angle = (lon - subsolar_lon(jd) + 540.0) % 360.0 - 180.0
    return angle / 360.0 * LUNAR_DAY


def phase(lon: float, dark: float, jd: float) -> float:
    """Hours since sunrise at a place whose night is ``dark`` hours long.

    The middle of the place's daylight is at its noon, which is the rule
    the town's own clock follows (setSun in city/src/sim/sim.ts).
    """
    light = LUNAR_DAY - dark
    return (light / 2 + hours_since_noon(lon, jd)) % LUNAR_DAY
