"""Lambert solving, against published textbook solutions.

Vallado's Example 7-5 is the standard regression case for a Lambert solver:
published to seven figures, and wrong answers are wrong in obvious ways.
"""

import numpy as np
import pytest

from orbital.constants import GM_EARTH, GM_SUN
from orbital.lambert import LambertFailure, hohmann_time, solve
from orbital.constants import AU

KM = 1000.0


def test_vallado_example_7_5():
    """Vallado, Fundamentals of Astrodynamics and Applications, Example 7-5."""
    r1 = np.array([15945.34, 0.0, 0.0]) * KM
    r2 = np.array([12214.83899, 10249.46731, 0.0]) * KM
    tof = 76.0 * 60.0

    arc = solve(r1, r2, tof, mu=GM_EARTH)

    expected_v1 = np.array([2.058913, 2.915965, 0.0]) * KM
    expected_v2 = np.array([-3.451565, 0.910315, 0.0]) * KM

    assert np.allclose(arc.v1, expected_v1, atol=1.0)   # 1 m/s
    assert np.allclose(arc.v2, expected_v2, atol=1.0)


def test_arc_actually_connects_the_two_points():
    """Propagate the solved departure state and check it arrives.

    Independent of any published number: if the returned velocity does not
    carry the spacecraft from r1 to r2 in the stated time, the solver is
    wrong regardless of what a textbook says.
    """
    r1 = np.array([15945.34, 0.0, 0.0]) * KM
    r2 = np.array([12214.83899, 10249.46731, 0.0]) * KM
    tof = 76.0 * 60.0
    arc = solve(r1, r2, tof, mu=GM_EARTH)

    from orbital.ephemeris import State
    from orbital.smallbody import elements_from_state, state_from_elements

    el = elements_from_state(State(r=r1, v=arc.v1), 0.0, mu=GM_EARTH)
    # elements_from_state assumes the Sun; redo with Earth's mu via a direct
    # two-body propagation instead.
    landed = _propagate_two_body(r1, arc.v1, tof, GM_EARTH)
    assert np.linalg.norm(landed - r2) < 1_000.0  # within a kilometre


def _propagate_two_body(r0, v0, dt, mu, steps=200_000):
    """Deliberately dumb RK4. Slow, obvious, and independent of the solver."""
    r = np.array(r0, float)
    v = np.array(v0, float)
    h = dt / steps

    def accel(rv):
        return -mu * rv / np.linalg.norm(rv) ** 3

    for _ in range(steps):
        k1v = accel(r); k1r = v
        k2v = accel(r + 0.5 * h * k1r); k2r = v + 0.5 * h * k1v
        k3v = accel(r + 0.5 * h * k2r); k3r = v + 0.5 * h * k2v
        k4v = accel(r + h * k3r); k4r = v + h * k3v
        r = r + (h / 6) * (k1r + 2 * k2r + 2 * k3r + k4r)
        v = v + (h / 6) * (k1v + 2 * k2v + 2 * k3v + k4v)
    return r


def test_rejects_nonpositive_time_of_flight():
    r1 = np.array([1.0, 0.0, 0.0]) * AU
    r2 = np.array([0.0, 1.0, 0.0]) * AU
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            solve(r1, r2, bad)


def test_hohmann_time_matches_the_textbook_earth_to_mars():
    """The classic 259-day Earth-Mars minimum-energy transfer."""
    days = hohmann_time(1.0 * AU, 1.523679 * AU, mu=GM_SUN) / 86400.0
    assert 255 < days < 262, days
