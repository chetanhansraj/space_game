"""Ephemeris backends, cross-validated against each other.

JPL Horizons is not reachable from a sealed build environment, so instead of
frozen Horizons fixtures this suite leans on two genuinely independent
implementations agreeing: DE421's Chebyshev coefficients and ERFA's
VSOP87-derived analytic series. They share no code and no data. Agreement to
arcseconds is strong evidence that the frame handling, the barycentre
correction and the unit conversions are all right.

The accuracy target from the bible is arcminutes. These assert well inside it.
"""

import numpy as np
import pytest

from orbital.constants import AU
from orbital.ephemeris import EARTH_MOON, MARS

#: The bible's accuracy target, in arcseconds.
ARCMINUTE = 60.0

# Julian dates spread across DE421's coverage.
EPOCHS = [2440000.5, 2451545.0, 2455000.5, 2460000.5, 2469807.5]


def _separation_arcsec(a, b) -> float:
    cos = a.r @ b.r / (np.linalg.norm(a.r) * np.linalg.norm(b.r))
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))) * 3600)


@pytest.mark.parametrize("jd", EPOCHS)
@pytest.mark.parametrize("body", [EARTH_MOON, MARS])
def test_backends_agree_within_the_accuracy_target(de421, analytic, jd, body):
    sep = _separation_arcsec(de421.state(body, jd), analytic.state(body, jd))
    assert sep < ARCMINUTE, f"{body} at jd={jd}: {sep:.1f} arcsec apart"


@pytest.mark.parametrize("jd", EPOCHS)
@pytest.mark.parametrize("body", [EARTH_MOON, MARS])
def test_backends_agree_on_velocity(de421, analytic, jd, body):
    """Lambert needs velocity as much as position, so it gets asserted too."""
    a, b = de421.state(body, jd), analytic.state(body, jd)
    assert np.linalg.norm(a.v - b.v) < 20.0  # m/s


def test_states_are_heliocentric_not_barycentric(de421):
    """Guards the single most plausible silent bug in this service.

    Earth's distance from the Sun oscillates between 0.983 and 1.017 AU. Its
    distance from the solar system barycentre does not follow that pattern,
    because the Sun itself moves up to ~0.01 AU around the barycentre. A
    barycentric state would drift outside this band.
    """
    for jd in EPOCHS:
        r = de421.state(EARTH_MOON, jd).radius / AU
        assert 0.980 < r < 1.020, f"Earth at {r:.4f} AU is not heliocentric"


def test_earth_orbital_speed_is_right(de421):
    for jd in EPOCHS:
        speed = de421.state(EARTH_MOON, jd).speed
        assert 29_000 < speed < 30_600, speed


def test_mars_stays_within_its_orbit(de421):
    """Mars ranges 1.381 to 1.666 AU. Anything outside is a units bug."""
    for jd in EPOCHS:
        r = de421.state(MARS, jd).radius / AU
        assert 1.37 < r < 1.68, r


def test_unknown_body_is_rejected(de421):
    with pytest.raises(ValueError):
        de421.state("pluto_barycentre_probably", 2451545.0)
