"""Depletion.

The bible: "A rock that has been mined for six months yields less per hour
than it did on day one. This is the primary reason the frontier keeps moving
outward and the primary defence against price collapse."
"""

import pytest

from sim.deposits import ABANDON_RICHNESS, Deposit

TONNE = 1_000


def deposit(scale_t=3_000):
    return Deposit(id="d", node="n", asset="ICE", scale_kg=scale_t * TONNE)


def test_a_fresh_deposit_yields_its_nameplate():
    assert deposit().yield_for(12 * TONNE) == 12 * TONNE


def test_richness_only_falls():
    d = deposit()
    previous = d.richness
    for tick in range(200):
        d.work(12 * TONNE, tick)
        assert d.richness <= previous
        previous = d.richness


def test_six_months_of_work_roughly_halves_the_yield():
    """The bible's own stated behaviour, asserted as a number.

    182 game days at 12 t/day is 2,184 t, and the 3,000 t scale is chosen so
    that lands near half. If this test breaks, either the scale changed or the
    curve did, and both are design decisions rather than accidents.
    """
    d = deposit()
    d.work(182 * 12 * TONNE, 0)
    assert 0.45 < d.richness < 0.55


def test_a_worked_out_deposit_is_abandoned():
    d = deposit()
    d.work(20_000 * TONNE, 0)
    assert d.richness < ABANDON_RICHNESS
    assert d.exhausted


def test_yield_reaches_zero_before_richness_does():
    """A rig on a poor rock returns nothing, which is the signal to stop."""
    d = deposit()
    d.work(50_000 * TONNE, 0)
    assert d.yield_for(12 * TONNE) == 0
    assert d.richness > 0


def test_half_life_is_quotable_to_a_player():
    assert deposit(3_000).half_life_kg() == pytest.approx(2_079_441, rel=1e-3)


def test_cannot_un_mine():
    with pytest.raises(ValueError):
        deposit().work(-1, 0)
