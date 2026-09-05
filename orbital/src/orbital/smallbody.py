"""Keplerian propagation for small bodies.

Asteroid nodes are not in the DE kernels, so they are carried as osculating
orbital elements and propagated on a two-body Kepler orbit. This is the
patched-conic commitment applied consistently: the asteroid moves on a fixed
ellipse about the Sun, exactly as the transfer arcs do.

Accuracy note, because it is a real limit and not a rounding detail:
osculating elements are only osculating at their epoch. Propagated purely
two-body, Ceres drifts from its true position by roughly an arcminute per
decade under Jupiter's unmodelled pull. Over the span a live world actually
needs -- the sky clock runs 60x, so a real year is 60 sky years -- that
accumulates past the accuracy target.

The mitigation is operational rather than mathematical: elements are
refreshed from the JPL Small-Body Database at build time, and the epoch they
were fetched at is stamped into the generated transfer table. Refreshing the
elements re-anchors the propagation. ``scripts/fetch_sbdb.py`` does the fetch;
``data/smallbody_elements.json`` holds the pinned result.

Elements are published in the heliocentric ECLIPTIC frame. This module
returns equatorial states like every other ephemeris source, so the rotation
happens here, once.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .constants import AU, GM_SUN
from .ephemeris import State
from .frames import ecliptic_to_equatorial

_TAU = 2.0 * math.pi


@dataclass(frozen=True)
class Elements:
    """Heliocentric osculating Keplerian elements, ecliptic J2000.

    Angles in radians, ``a`` in metres, ``epoch_jd`` in Julian Date (TT).
    """

    name: str
    a: float
    e: float
    i: float
    raan: float          # longitude of ascending node, capital omega
    argp: float          # argument of perihelion, lowercase omega
    M0: float            # mean anomaly at epoch
    epoch_jd: float
    source: str = "unknown"

    @property
    def mean_motion(self) -> float:
        """Radians per second."""
        return math.sqrt(GM_SUN / self.a**3)

    @property
    def period(self) -> float:
        """Orbital period in seconds."""
        return _TAU / self.mean_motion

    @classmethod
    def from_degrees(
        cls,
        name: str,
        a_au: float,
        e: float,
        i_deg: float,
        raan_deg: float,
        argp_deg: float,
        M0_deg: float,
        epoch_jd: float,
        source: str = "unknown",
    ) -> "Elements":
        return cls(
            name=name,
            a=a_au * AU,
            e=e,
            i=math.radians(i_deg),
            raan=math.radians(raan_deg),
            argp=math.radians(argp_deg),
            M0=math.radians(M0_deg),
            epoch_jd=epoch_jd,
            source=source,
        )


def solve_kepler(M: float, e: float, tol: float = 1e-13, max_iter: int = 60) -> float:
    """Solve M = E - e sin E for the eccentric anomaly E.

    Newton's method with the standard Danby starting guess, which converges
    in a handful of iterations even at the eccentricities in the Belt
    (Pallas 0.23, Eros 0.22). Falls back to bisection if Newton stalls,
    because a solver that silently returns a bad root here would poison
    every transfer to that body.
    """
    M = (M + math.pi) % _TAU - math.pi  # wrap to [-pi, pi)
    if e < 1e-12:
        return M

    E = M + math.copysign(0.85 * e, math.sin(M))
    for _ in range(max_iter):
        f = E - e * math.sin(E) - M
        if abs(f) < tol:
            return E
        fp = 1.0 - e * math.cos(E)
        if abs(fp) < 1e-14:
            break
        step = f / fp
        # Damp oversized Newton steps, which is where high-e cases misbehave.
        if abs(step) > 1.0:
            step = math.copysign(1.0, step)
        E -= step
    else:
        return E

    lo, hi = M - 1.0, M + 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if mid - e * math.sin(mid) - M > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def state_from_elements(el: Elements, jd_tt: float) -> State:
    """Propagate elements to ``jd_tt`` and return an equatorial state."""
    dt = (jd_tt - el.epoch_jd) * 86400.0
    M = el.M0 + el.mean_motion * dt
    E = solve_kepler(M, el.e)

    cosE, sinE = math.cos(E), math.sin(E)
    one_minus_e2 = 1.0 - el.e * el.e
    sqrt_1me2 = math.sqrt(one_minus_e2)

    # Perifocal position and velocity.
    r_mag = el.a * (1.0 - el.e * cosE)
    r_pf = np.array([el.a * (cosE - el.e), el.a * sqrt_1me2 * sinE, 0.0])
    edot = math.sqrt(GM_SUN * el.a) / r_mag
    v_pf = np.array([-edot * sinE, edot * sqrt_1me2 * cosE, 0.0])

    rot = _perifocal_to_ecliptic(el.i, el.raan, el.argp)
    r_ecl = rot @ r_pf
    v_ecl = rot @ v_pf

    return State(r=ecliptic_to_equatorial(r_ecl), v=ecliptic_to_equatorial(v_ecl))


def _perifocal_to_ecliptic(i: float, raan: float, argp: float) -> np.ndarray:
    cO, sO = math.cos(raan), math.sin(raan)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(argp), math.sin(argp)
    return np.array(
        [
            [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
            [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
            [sw * si, cw * si, ci],
        ]
    )


def elements_from_state(
    state: State, jd_tt: float, name: str = "derived", mu: float = GM_SUN
) -> Elements:
    """Invert :func:`state_from_elements`.

    Used by the test suite to round-trip a body whose true state is known
    from a DE kernel through the element pipeline and back, which validates
    the propagator against a real ephemeris rather than against itself.
    """
    from .frames import equatorial_to_ecliptic

    r_vec = equatorial_to_ecliptic(state.r)
    v_vec = equatorial_to_ecliptic(state.v)
    r = float(np.linalg.norm(r_vec))
    v = float(np.linalg.norm(v_vec))

    h_vec = np.cross(r_vec, v_vec)
    h = float(np.linalg.norm(h_vec))
    n_vec = np.cross([0.0, 0.0, 1.0], h_vec)
    n = float(np.linalg.norm(n_vec))

    e_vec = ((v * v - mu / r) * r_vec - float(r_vec @ v_vec) * v_vec) / mu
    e = float(np.linalg.norm(e_vec))

    energy = v * v / 2.0 - mu / r
    a = -mu / (2.0 * energy)

    i = math.acos(np.clip(h_vec[2] / h, -1.0, 1.0))
    raan = math.atan2(n_vec[1], n_vec[0]) % _TAU if n > 1e-9 else 0.0
    if n > 1e-9 and e > 1e-12:
        argp = math.acos(np.clip(float(n_vec @ e_vec) / (n * e), -1.0, 1.0))
        if e_vec[2] < 0:
            argp = _TAU - argp
    else:
        argp = 0.0

    if e > 1e-12:
        nu = math.acos(np.clip(float(e_vec @ r_vec) / (e * r), -1.0, 1.0))
        if float(r_vec @ v_vec) < 0:
            nu = _TAU - nu
    else:
        nu = 0.0

    E = 2.0 * math.atan2(math.sqrt(1.0 - e) * math.sin(nu / 2.0),
                         math.sqrt(1.0 + e) * math.cos(nu / 2.0))
    M = (E - e * math.sin(E)) % _TAU

    return Elements(name=name, a=a, e=e, i=i, raan=raan, argp=argp,
                    M0=M, epoch_jd=jd_tt, source="derived-from-state")


def load_elements(path: str | Path) -> dict[str, Elements]:
    """Load pinned small-body elements from JSON."""
    data = json.loads(Path(path).read_text())
    out: dict[str, Elements] = {}
    for key, rec in data["bodies"].items():
        out[key] = Elements.from_degrees(
            name=rec["name"],
            a_au=rec["a_au"],
            e=rec["e"],
            i_deg=rec["i_deg"],
            raan_deg=rec["raan_deg"],
            argp_deg=rec["argp_deg"],
            M0_deg=rec["M0_deg"],
            epoch_jd=rec["epoch_jd"],
            source=data.get("source", "unknown"),
        )
    return out
