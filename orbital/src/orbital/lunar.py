"""The Moon, handled analytically.

The bible's dodge: for interplanetary purposes the Moon sits at the Earth-Moon
barycentre, and everything inside the lunar system is a fixed delta-v budget
that never changes with geometry. That is what makes v1 shippable without a
lunar ephemeris, and it is physically defensible -- lunar surface-to-orbit
genuinely does not care where Mars is.

Two kinds of cost live here:

Vertical    Surface to low lunar orbit and back, and low lunar orbit to
            escape. Flat numbers from the seed data.

Lateral     Surface to surface. A ballistic suborbital hop on an airless
            body, which is a closed-form minimum-energy problem. The seed
            data did not have a number for this and the whole of v1 is
            lunar surface nodes, so it is derived here rather than guessed.

The suborbital solution is the standard minimum-energy ballistic arc between
two points on a sphere. For a central angle theta:

    v^2 / v_c^2 = 2 sin(theta/2) / (1 + sin(theta/2))

with v_c the circular orbit speed at the surface. Total delta-v is 2v: once
to launch, once to land, because there is no atmosphere to brake in. As
theta approaches 180 degrees this tends to 2 v_c = 3.36 km/s, which is
correctly a little cheaper than going up to orbit and back down (3.74 km/s),
and the two converge for antipodal trips exactly as they should.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import GM_MOON, R_MOON

#: Circular orbital speed at the lunar surface, m/s. ~1680.
V_CIRCULAR = math.sqrt(GM_MOON / R_MOON)

#: Lunar surface to low lunar orbit. From docs/seed-data.md.
DV_SURFACE_TO_LLO = 1_870.0

#: Low lunar orbit to Earth-Moon system escape. From docs/seed-data.md.
DV_LLO_TO_ESCAPE = 700.0

#: Lunar surface to interplanetary space: the sum of the two above. This is
#: the fixed budget added to any transfer departing from a lunar surface node.
DV_SURFACE_TO_ESCAPE = DV_SURFACE_TO_LLO + DV_LLO_TO_ESCAPE


@dataclass(frozen=True)
class Site:
    """A point on the lunar surface."""

    name: str
    lat_deg: float
    lon_deg: float


def central_angle(a: Site, b: Site) -> float:
    """Great-circle angle between two sites, radians."""
    lat1, lat2 = math.radians(a.lat_deg), math.radians(b.lat_deg)
    dlon = math.radians(b.lon_deg - a.lon_deg)
    cos_theta = (math.sin(lat1) * math.sin(lat2)
                 + math.cos(lat1) * math.cos(lat2) * math.cos(dlon))
    return math.acos(max(-1.0, min(1.0, cos_theta)))


@dataclass(frozen=True)
class Hop:
    dv_total: float      # m/s
    tof: float           # seconds
    central_angle: float # radians


def suborbital_hop(a: Site, b: Site) -> Hop:
    """Minimum-energy ballistic hop between two lunar surface sites."""
    theta = central_angle(a, b)
    if theta < 1e-9:
        return Hop(dv_total=0.0, tof=0.0, central_angle=0.0)

    s_half = math.sin(theta / 2.0)
    v = V_CIRCULAR * math.sqrt(2.0 * s_half / (1.0 + s_half))
    dv_total = 2.0 * v

    # Minimum-energy time of flight via Lambert's theorem. The transfer
    # ellipse has semi-major axis a_m = s/2 where s is the semi-perimeter of
    # the space triangle; for two points at the same radius R this reduces to
    # a_m = R (1 + sin(theta/2)) / 2.
    a_m = R_MOON * (1.0 + s_half) / 2.0
    sin_beta_half = math.sqrt(max(0.0, (1.0 - s_half) / (1.0 + s_half)))
    beta = 2.0 * math.asin(min(1.0, sin_beta_half))
    tof = math.sqrt(a_m**3 / GM_MOON) * (math.pi - beta + math.sin(beta))

    return Hop(dv_total=dv_total, tof=tof, central_angle=theta)
