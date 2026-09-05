"""Lunar suborbital hops.

The seed data had no surface-to-surface number and the whole of v1 is lunar
surface nodes, so this is derived rather than quoted. That makes asserting
its physical bounds more important, not less.
"""

import math

import pytest

from orbital.lunar import (
    DV_SURFACE_TO_LLO,
    V_CIRCULAR,
    Site,
    central_angle,
    suborbital_hop,
)

SHACKLETON = Site("Shackleton Depot", -89.9, 0.0)
PEARY = Site("Peary Ridge", 88.6, 33.0)
TRANQUILLITATIS = Site("Tranquillitatis Flats", 8.5, 31.4)
SITES = [SHACKLETON, PEARY, TRANQUILLITATIS]


def test_circular_speed_matches_the_known_value():
    """Low lunar orbit is 1.68 km/s. Everything else scales off this."""
    assert V_CIRCULAR == pytest.approx(1680, abs=5)


def test_hop_is_always_cheaper_than_going_via_orbit():
    """The whole reason to model hops separately.

    Surface to orbit and back down costs 2 x 1870 = 3740 m/s. A ballistic hop
    must beat that for every pair, or there would be no point offering it.
    """
    via_orbit = 2 * DV_SURFACE_TO_LLO
    for a in SITES:
        for b in SITES:
            if a is b:
                continue
            assert suborbital_hop(a, b).dv_total < via_orbit


def test_antipodal_hop_approaches_twice_circular_speed():
    north = Site("n", 90.0, 0.0)
    south = Site("s", -90.0, 0.0)
    hop = suborbital_hop(north, south)
    assert hop.dv_total == pytest.approx(2 * V_CIRCULAR, rel=1e-9)
    assert math.degrees(hop.central_angle) == pytest.approx(180.0)


def test_cost_and_time_both_rise_with_distance():
    pairs = sorted(
        ((central_angle(a, b), suborbital_hop(a, b))
         for a in SITES for b in SITES if a is not b),
        key=lambda p: p[0],
    )
    costs = [hop.dv_total for _, hop in pairs]
    times = [hop.tof for _, hop in pairs]
    assert costs == sorted(costs)
    assert times == sorted(times)


def test_hop_is_symmetric():
    for a in SITES:
        for b in SITES:
            assert suborbital_hop(a, b).dv_total == pytest.approx(
                suborbital_hop(b, a).dv_total
            )


def test_zero_distance_is_free():
    hop = suborbital_hop(SHACKLETON, Site("same", -89.9, 0.0))
    assert hop.dv_total == 0.0
    assert hop.tof == 0.0


def test_transit_times_are_minutes_of_real_time():
    """The bible says lunar hops take minutes. At the 60x clock that means a
    game-time flight of roughly an hour. Assert the design intent holds."""
    from orbital.clock import real_seconds

    for a in SITES:
        for b in SITES:
            if a is b:
                continue
            real_minutes = real_seconds(suborbital_hop(a, b).tof) / 60
            assert 0.3 < real_minutes < 3.0, real_minutes
