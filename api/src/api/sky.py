"""Where everything is in the sky, for the client to draw.

Display only. Nothing here feeds a price, a route or a transfer cost -- those
come from `orbital` through `sim`. This is the view out of the window: the
planets where the ephemerides put them at the world's sky time, and the
Moon's real phase, so the terminator on the globe a player looks at is where
the real terminator is at that instant.
"""

from __future__ import annotations

import math

from orbital.frames import equatorial_to_ecliptic

AU = 149_597_870_700.0

#: Bodies drawn on the system map: (id, label, anchor or backend body, kind).
BODIES = (
    ("mercury", "Mercury", "mercury_barycentre", "planet"),
    ("venus", "Venus", "venus_barycentre", "planet"),
    ("earth", "Earth", "earth_moon_barycentre", "planet"),
    ("mars", "Mars", "mars_barycentre", "planet"),
    ("jupiter", "Jupiter", "jupiter_barycentre", "planet"),
    ("saturn", "Saturn", "saturn_barycentre", "planet"),
    ("ceres", "Ceres", "ceres", "asteroid"),
    ("vesta", "Vesta", "vesta", "asteroid"),
    ("pallas", "Pallas", "pallas", "asteroid"),
    ("psyche", "Psyche", "psyche", "asteroid"),
    ("eros", "Eros", "eros", "asteroid"),
)


def moon_phase(jd: float) -> dict:
    """The Moon's phase, and where on it the Sun is overhead.

    Low-precision series (Meeus, ch. 47, leading terms only), good to about a
    degree -- a terminator a degree out of place is not something anyone can
    see on a globe. The sub-solar longitude follows from the elongation: new
    moon puts the Sun over the far side (180), full moon over the near side
    (0), first quarter over the eastern limb (+90).
    """
    d = jd - 2_451_545.0
    moon_l = 218.316 + 13.176396 * d
    moon_m = math.radians(134.963 + 13.064993 * d)
    moon_lon = moon_l + 6.289 * math.sin(moon_m)
    sun_g = math.radians(357.528 + 0.9856003 * d)
    sun_lon = (280.460 + 0.9856474 * d + 1.915 * math.sin(sun_g)
               + 0.020 * math.sin(2 * sun_g))
    elongation = (moon_lon - sun_lon) % 360.0
    subsolar = (180.0 - elongation + 540.0) % 360.0 - 180.0
    illuminated = (1 - math.cos(math.radians(elongation))) / 2
    names = ("new", "waxing crescent", "first quarter", "waxing gibbous",
             "full", "waning gibbous", "last quarter", "waning crescent")
    name = names[int(((elongation + 22.5) % 360) // 45)]
    return {"elongation": round(elongation, 2),
            "subsolar_lon": round(subsolar, 2),
            "illuminated": round(illuminated, 3), "phase": name}


def positions(registry, jd: float) -> list[dict]:
    """Heliocentric ecliptic positions in AU. Bodies that fail are skipped."""
    out = []
    for bid, label, source, kind in BODIES:
        try:
            if source in registry:
                state = registry.state(source, jd)
            else:
                state = registry.backend.state(source, jd)
        except Exception:
            continue
        r = equatorial_to_ecliptic(state.r) / AU
        out.append({"id": bid, "name": label, "kind": kind,
                    "x": round(float(r[0]), 5), "y": round(float(r[1]), 5),
                    "z": round(float(r[2]), 5)})
    return out
