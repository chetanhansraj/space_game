"""Where everything is in the sky, for the client to draw.

Display only. Nothing here feeds a price, a route or a transfer cost -- those
come from `orbital` through `sim`. This is the view out of the window: the
planets where the ephemerides put them at the world's sky time, and the
Moon's real phase, so the terminator on the globe a player looks at is where
the real terminator is at that instant.
"""

from __future__ import annotations

import math

from sim import sun

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

    Both come from ``sim.sun``, which is also what every town keeps its day
    by, so the globe's light and a town's sunrise are the same Sun.
    """
    elongation, subsolar = sun.elongation(jd), sun.subsolar_lon(jd)
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
