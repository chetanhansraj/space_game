"""Cost curves: the shape the service returns, and the economics it implies.

These are as much design assertions as physics ones. The game's core
mechanic is that geometry sets price. If the cost curve ever stopped varying
with departure date, the economy would lose its rhythm and no test of a
single delta-v number would catch it.
"""

import datetime as dt

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from orbital.clock import to_jd
from orbital.curve import build_curve, pareto
from orbital.ephemeris import EARTH_MOON, MARS
from orbital.transfer import Transfer

UTC = dt.timezone.utc


def _t(tof, dv):
    return Transfer(tof=tof, dv_depart=dv, dv_arrive=0.0, dv_fixed=0.0,
                    revolutions=0)


@given(
    st.lists(
        st.tuples(
            st.floats(1e5, 5e7, allow_nan=False),
            st.floats(1e2, 5e5, allow_nan=False),
        ),
        min_size=1,
        max_size=60,
    )
)
@settings(max_examples=200, deadline=None)
def test_pareto_frontier_is_strictly_monotonic(raw):
    """Cheaper must always mean slower. That is the entire trade."""
    front = pareto([_t(tof, dv) for tof, dv in raw])
    tofs = [p.tof for p in front]
    dvs = [p.dv_total for p in front]
    assert tofs == sorted(tofs)
    assert dvs == sorted(dvs, reverse=True)


@given(
    st.lists(
        st.tuples(
            st.floats(1e5, 5e7, allow_nan=False),
            st.floats(1e2, 5e5, allow_nan=False),
        ),
        min_size=1,
        max_size=60,
    )
)
@settings(max_examples=200, deadline=None)
def test_no_frontier_point_is_dominated(raw):
    points = [_t(tof, dv) for tof, dv in raw]
    front = pareto(points)
    for kept in front:
        for other in points:
            dominates = (
                other.tof <= kept.tof
                and other.dv_total <= kept.dv_total
                and (other.tof < kept.tof or other.dv_total < kept.dv_total)
            )
            assert not dominates


def test_the_cheapest_option_is_the_slowest(de421):
    jd = to_jd(dt.datetime(2028, 11, 16, tzinfo=UTC))
    curve = build_curve(
        lambda t: de421.state(EARTH_MOON, t),
        lambda t: de421.state(MARS, t),
        jd, samples=24,
    )
    assert curve.cheapest.tof > curve.fastest.tof
    assert curve.cheapest.dv_total < curve.fastest.dv_total


def test_geometry_sets_price(de421):
    """The core economic mechanic, asserted directly.

    A favourable Earth-Mars alignment and an unfavourable one, roughly one
    synodic period apart, must differ in minimum-energy cost by a large
    factor. If this shrinks toward 1, launch windows have stopped mattering
    and the merchant profession has no reason to exist.
    """
    origin = lambda t: de421.state(EARTH_MOON, t)
    dest = lambda t: de421.state(MARS, t)
    good = build_curve(origin, dest,
                       to_jd(dt.datetime(2028, 11, 16, tzinfo=UTC)), samples=32)
    bad = build_curve(origin, dest,
                      to_jd(dt.datetime(2029, 12, 21, tzinfo=UTC)), samples=32)
    ratio = bad.cheapest.dv_total / good.cheapest.dv_total
    assert ratio > 3.0, f"only {ratio:.1f}x between best and worst window"


def test_queries_respect_their_constraint(de421):
    jd = to_jd(dt.datetime(2028, 11, 16, tzinfo=UTC))
    curve = build_curve(
        lambda t: de421.state(EARTH_MOON, t),
        lambda t: de421.state(MARS, t),
        jd, samples=32,
    )
    deadline = 120 * 86400.0
    pick = curve.at_most(deadline)
    assert pick is not None and pick.tof <= deadline

    budget = pick.dv_total
    affordable = curve.within_budget(budget)
    assert affordable is not None and affordable.dv_total <= budget


def test_impossible_constraints_return_nothing(de421):
    jd = to_jd(dt.datetime(2028, 11, 16, tzinfo=UTC))
    curve = build_curve(
        lambda t: de421.state(EARTH_MOON, t),
        lambda t: de421.state(MARS, t),
        jd, samples=24,
    )
    assert curve.at_most(60.0) is None          # one minute to Mars
    assert curve.within_budget(1.0) is None      # one metre per second
