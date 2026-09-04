"""Transfer costing, validated against real interplanetary missions.

CLAUDE.md: "The orbital service is tested against known JPL values. Pick a
handful of real transfer solutions and assert against them."

These are the launch characteristic energies published in NASA press kits for
four Mars missions. Reconstructing them from nothing but a launch date, an
arrival date and an ephemeris is the strongest end-to-end check available:
it exercises the ephemeris, the barycentre correction, the frame handling,
the Lambert solver and the v-infinity arithmetic in one number.

Tolerances are loose on purpose. Real missions are not pure ballistic arcs --
they carry trajectory correction manoeuvres, they inject from a parking orbit
rather than from the Earth-Moon barycentre, and MSL in particular flew a
deliberately lofted trajectory. Agreement to a few percent is the correct
expectation, and is far inside what the game needs.
"""

import datetime as dt

import pytest

from orbital.clock import to_jd
from orbital.ephemeris import EARTH_MOON, MARS
from orbital.transfer import cheapest, cost

UTC = dt.timezone.utc

# name, launch, Mars arrival, published launch C3 (km^2/s^2), tolerance
MISSIONS = [
    ("Mars 2020 Perseverance",
     dt.datetime(2020, 7, 30, 11, 50, tzinfo=UTC),
     dt.datetime(2021, 2, 18, 20, 55, tzinfo=UTC), 14.5, 0.05),
    ("InSight",
     dt.datetime(2018, 5, 5, 11, 5, tzinfo=UTC),
     dt.datetime(2018, 11, 26, 19, 53, tzinfo=UTC), 8.1, 0.05),
    ("MAVEN",
     dt.datetime(2013, 11, 18, 18, 28, tzinfo=UTC),
     dt.datetime(2014, 9, 22, 2, 24, tzinfo=UTC), 12.2, 0.05),
    ("MSL Curiosity",
     dt.datetime(2011, 11, 26, 15, 2, tzinfo=UTC),
     dt.datetime(2012, 8, 6, 5, 17, tzinfo=UTC), 11.39, 0.10),
]


@pytest.mark.parametrize("name,launch,arrival,c3_published,tol", MISSIONS)
def test_reproduces_published_launch_energy(
    de421, name, launch, arrival, c3_published, tol
):
    jd1, jd2 = to_jd(launch), to_jd(arrival)
    transfer = cost(
        de421.state(EARTH_MOON, jd1),
        de421.state(MARS, jd2),
        (jd2 - jd1) * 86400.0,
    )
    c3 = transfer.c3_depart / 1e6  # m^2/s^2 -> km^2/s^2
    assert abs(c3 - c3_published) / c3_published < tol, (
        f"{name}: got C3={c3:.2f}, published {c3_published}"
    )


@pytest.mark.parametrize("name,launch,arrival,_c3,_tol", MISSIONS)
def test_arrival_speed_is_physically_plausible(
    de421, name, launch, arrival, _c3, _tol
):
    """Mars arrival v-infinity for a Hohmann-like transfer is 2-4 km/s."""
    jd1, jd2 = to_jd(launch), to_jd(arrival)
    transfer = cost(
        de421.state(EARTH_MOON, jd1),
        de421.state(MARS, jd2),
        (jd2 - jd1) * 86400.0,
    )
    assert 2_000 < transfer.dv_arrive < 4_500, transfer.dv_arrive


def test_fixed_budget_is_added_not_folded_in(de421):
    jd1 = to_jd(dt.datetime(2020, 7, 30, tzinfo=UTC))
    jd2 = to_jd(dt.datetime(2021, 2, 18, tzinfo=UTC))
    args = (de421.state(EARTH_MOON, jd1), de421.state(MARS, jd2),
            (jd2 - jd1) * 86400.0)
    plain = cost(*args)
    charged = cost(*args, dv_fixed=2570.0)
    assert charged.dv_depart == plain.dv_depart
    assert charged.dv_total == pytest.approx(plain.dv_total + 2570.0)


def test_cheapest_never_returns_worse_than_direct(de421):
    """Sweeping revolutions must never make a route more expensive."""
    jd1 = to_jd(dt.datetime(2020, 7, 30, tzinfo=UTC))
    tof = 210 * 86400.0
    jd2 = jd1 + 210
    origin, dest = de421.state(EARTH_MOON, jd1), de421.state(MARS, jd2)
    direct = cost(origin, dest, tof)
    best = cheapest(origin, dest, tof, max_revolutions=1)
    assert best is not None
    assert best.dv_total <= direct.dv_total + 1e-6
