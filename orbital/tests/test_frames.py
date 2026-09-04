"""Frame conversions.

These look trivial. They are here because an unnecessary ecliptic rotation
leaves a body's distance from the Sun exactly right while putting it 23
degrees away from where it is, which passes every casual sanity check.
"""

import numpy as np

from orbital.constants import OBLIQUITY_J2000
from orbital.frames import (
    au_to_m,
    ecliptic_to_equatorial,
    equatorial_to_ecliptic,
)
from orbital.constants import AU


def test_rotation_round_trips():
    rng = np.random.default_rng(20260904)
    for _ in range(50):
        v = rng.normal(size=3) * 1e11
        back = equatorial_to_ecliptic(ecliptic_to_equatorial(v))
        assert np.allclose(v, back, rtol=1e-12, atol=1e-6)


def test_rotation_preserves_length():
    v = np.array([1.0, 2.0, 3.0]) * AU
    assert np.isclose(
        np.linalg.norm(ecliptic_to_equatorial(v)), np.linalg.norm(v), rtol=1e-14
    )


def test_x_axis_is_the_shared_equinox():
    """Both frames share the vernal equinox, so +X must be untouched."""
    x = np.array([1.0, 0.0, 0.0])
    assert np.allclose(ecliptic_to_equatorial(x), x, atol=1e-15)


def test_pole_tilts_by_the_obliquity():
    z = np.array([0.0, 0.0, 1.0])
    tilted = ecliptic_to_equatorial(z)
    angle = np.arccos(np.clip(tilted @ z, -1, 1))
    assert np.isclose(angle, OBLIQUITY_J2000, atol=1e-12)


def test_au_conversion():
    assert np.isclose(au_to_m(np.array([1.0, 0, 0]))[0], 1.495978707e11)
