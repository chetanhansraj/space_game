"""Determinism and architectural invariants.

CLAUDE.md requires simulation runs to be reproducible. The orbital service is
upstream of the simulation, so if it is not deterministic nothing downstream
can be.
"""

import datetime as dt
import importlib
import sys

import numpy as np

from orbital.clock import to_jd
from orbital.curve import build_curve
from orbital.ephemeris import EARTH_MOON, MARS

UTC = dt.timezone.utc


def test_repeated_calls_are_bit_identical(de421):
    jd = to_jd(dt.datetime(2028, 6, 1, tzinfo=UTC))
    state_a = de421.state(MARS, jd)
    state_b = de421.state(MARS, jd)
    assert np.array_equal(state_a.r, state_b.r)
    assert np.array_equal(state_a.v, state_b.v)


def test_curves_are_reproducible(de421):
    jd = to_jd(dt.datetime(2028, 11, 16, tzinfo=UTC))
    args = (lambda t: de421.state(EARTH_MOON, t),
            lambda t: de421.state(MARS, t), jd)
    first = build_curve(*args, samples=24)
    second = build_curve(*args, samples=24)
    assert len(first) == len(second)
    for a, b in zip(first.points, second.points):
        assert a.tof == b.tof
        assert a.dv_total == b.dv_total


def test_the_sixty_times_factor_lives_in_exactly_one_module():
    """Invariant 5: the 60x clock rate appears in clock.py and nowhere else.

    Scattering the rate is how a codebase ends up with two subtly different
    notions of how fast the world runs. Scan the package for any module-level
    constant assigned the value 60 and assert clock.py owns the only one.
    """
    import pathlib
    import re

    import orbital
    from orbital.clock import TIME_RATE

    assert TIME_RATE == 60

    pattern = re.compile(r"^[A-Z][A-Z0-9_]*\s*=\s*60\b", re.MULTILINE)
    root = pathlib.Path(orbital.__file__).parent
    offenders = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if path.name != "clock.py" and pattern.search(path.read_text())
    ]
    assert not offenders, f"rate constant defined outside clock.py: {offenders}"


def test_api_module_cannot_reach_a_solver():
    """Invariant 4, enforced structurally rather than by discipline.

    Importing the API must not pull in the Lambert solver. If it does, a
    future request handler could call it, and the whole point of the
    precomputed table is lost.
    """
    for name in list(sys.modules):
        if name.startswith("orbital") or name == "lamberthub":
            del sys.modules[name]

    importlib.import_module("orbital.table.store")
    assert "lamberthub" not in sys.modules, (
        "the read path pulled in a Lambert solver"
    )
