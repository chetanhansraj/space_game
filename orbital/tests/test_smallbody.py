"""Small-body propagation.

The strongest test here is the Mars round trip: take a body whose true state
is known from a real ephemeris, convert it to Keplerian elements, propagate
it forward on a two-body orbit, and compare against the ephemeris again. That
validates the element pipeline against ground truth rather than against
itself, and it also measures the two-body drift that motivates refreshing
elements from the Small-Body Database.
"""

import math

import numpy as np
import pytest

from orbital.constants import AU, GM_SUN
from orbital.ephemeris import MARS
from orbital.smallbody import (
    elements_from_state,
    solve_kepler,
    state_from_elements,
)

J2000 = 2451545.0


@pytest.mark.parametrize("e", [0.0, 0.01, 0.09, 0.23, 0.5, 0.8, 0.95])
@pytest.mark.parametrize("M_deg", [0, 17, 90, 179, 181, 270, 359])
def test_kepler_solution_satisfies_its_own_equation(e, M_deg):
    M = math.radians(M_deg)
    E = solve_kepler(M, e)
    residual = (E - e * math.sin(E)) - M
    residual = (residual + math.pi) % (2 * math.pi) - math.pi
    assert abs(residual) < 1e-10, f"e={e} M={M_deg}: residual {residual}"


def test_mars_elements_match_published_values(de421):
    el = elements_from_state(de421.state(MARS, J2000), J2000, "mars")
    assert el.a / AU == pytest.approx(1.523679, abs=1e-4)
    assert el.e == pytest.approx(0.09340, abs=2e-4)
    assert math.degrees(el.i) == pytest.approx(1.8497, abs=1e-3)
    assert el.period / 86400 / 365.25 == pytest.approx(1.8808, abs=1e-3)


@pytest.mark.parametrize("days,max_arcsec", [(0, 1e-6), (30, 5), (180, 40)])
def test_propagation_tracks_a_real_ephemeris(de421, days, max_arcsec):
    el = elements_from_state(de421.state(MARS, J2000), J2000, "mars")
    got = state_from_elements(el, J2000 + days)
    want = de421.state(MARS, J2000 + days)
    cos = got.r @ want.r / (np.linalg.norm(got.r) * np.linalg.norm(want.r))
    arcsec = math.degrees(math.acos(np.clip(cos, -1, 1))) * 3600
    assert arcsec < max_arcsec, f"{days}d: {arcsec:.1f} arcsec"


def test_two_body_drift_is_documented_not_denied(de421):
    """Pins the known limitation so it cannot regress unnoticed.

    Ten years of pure two-body propagation puts Mars over an arcminute off,
    which is outside the accuracy target. This is exactly why small-body
    elements are refreshed from the SBDB at build time and the epoch is
    stamped into the transfer table. If this assertion ever starts failing
    because the error got smaller, that is good news worth investigating --
    but it must not fail silently by getting worse.
    """
    el = elements_from_state(de421.state(MARS, J2000), J2000, "mars")
    got = state_from_elements(el, J2000 + 3650)
    want = de421.state(MARS, J2000 + 3650)
    cos = got.r @ want.r / (np.linalg.norm(got.r) * np.linalg.norm(want.r))
    arcsec = math.degrees(math.acos(np.clip(cos, -1, 1))) * 3600
    assert 30 < arcsec < 400, arcsec


def test_propagation_conserves_energy_and_angular_momentum(registry):
    for key, el in registry.elements.items():
        states = [state_from_elements(el, J2000 + d) for d in (0, 400, 900)]
        energies = [
            s.speed**2 / 2 - GM_SUN / s.radius for s in states
        ]
        momenta = [np.linalg.norm(np.cross(s.r, s.v)) for s in states]
        assert np.allclose(energies, energies[0], rtol=1e-10), key
        assert np.allclose(momenta, momenta[0], rtol=1e-10), key


def test_periods_match_the_seed_data(registry):
    """docs/seed-data.md publishes orbital periods. They must agree."""
    expected = {"ceres": 4.60, "vesta": 3.63, "psyche": 5.00,
                "pallas": 4.62, "eros": 1.76}
    for key, years in expected.items():
        got = registry.elements[key].period / 86400 / 365.25
        assert got == pytest.approx(years, abs=0.02), key


def test_element_round_trip_is_lossless(de421):
    original = de421.state(MARS, J2000)
    el = elements_from_state(original, J2000, "mars")
    back = state_from_elements(el, J2000)
    assert np.linalg.norm(back.r - original.r) < 1.0    # metres
    assert np.linalg.norm(back.v - original.v) < 1e-4   # m/s
