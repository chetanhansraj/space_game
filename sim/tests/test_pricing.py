"""Price formation from inventory pressure.

The bible: "Prices form from local inventory against local demand: as a
warehouse fills, the bid falls; as it empties, the ask climbs."
"""

import pytest

from sim.firms import ELASTICITY, REVERSION, pressure, reservation_price


def test_pressure_is_zero_on_target():
    assert pressure(100, 100) == 0.0


def test_pressure_is_clamped():
    """Without this a firm at twenty times its target quotes a negative price,
    and a firm at zero stock bids arbitrarily high and hands over its balance."""
    assert pressure(10_000, 100) == 1.0
    assert pressure(0, 100) == -1.0


def test_a_full_warehouse_lowers_the_price():
    assert reservation_price(400, 200, 100, 0.20) < 400


def test_an_empty_warehouse_raises_it():
    assert reservation_price(400, 0, 100, 0.20) > 400


def test_price_is_monotonic_in_stock():
    prices = [reservation_price(400, held, 100, 0.20)
              for held in range(0, 250, 10)]
    assert prices == sorted(prices, reverse=True)


def test_price_is_never_zero_or_negative():
    for elasticity in ELASTICITY.values():
        assert reservation_price(1, 10_000, 1, elasticity) >= 1


def test_volatile_goods_move_further():
    """Volatility is shock sensitivity, per seed-data."""
    calm = reservation_price(400, 0, 100, ELASTICITY["low"])
    wild = reservation_price(400, 0, 100, ELASTICITY["very high"])
    assert wild > calm


def test_reversion_rises_with_volatility():
    """A market that swings harder needs a shorter leash, not a longer one.

    This asserted the opposite until propellant proved otherwise. The
    intuition that a volatile commodity should be "free to roam" is right
    about the *swings*, which elasticity produces -- but reversion is what
    keeps those swings around a price instead of walking away from one, and
    the bigger the swing the stronger it has to be. See the convergence
    condition below.
    """
    assert REVERSION["low"] < REVERSION["medium"] < REVERSION["high"] \
        < REVERSION["very high"]
    assert set(REVERSION) == set(ELASTICITY)


def test_every_volatility_class_converges_to_a_price():
    """The condition that keeps a market from running away.

    A short buyer bids ref x (1+e); that print becomes the next reference,
    pulled back toward the anchor by r. The iteration converges only when
    (1+e)(1-r) < 1, that is r > e/(1+e).

    Below the threshold there is no equilibrium at all, and the failure is
    silent until the market dies: propellant at Peary Ridge reached 18,018
    against an 1,800 anchor and then stopped trading entirely, because
    nothing could afford a bid. Its elasticity of 0.35 wanted reversion above
    0.259 and had 0.12.
    """
    from sim.firms import is_stable

    for name, e in ELASTICITY.items():
        r = REVERSION[name]
        assert r > e / (1 + e), f"{name}: reversion {r} <= threshold {e/(1+e):.3f}"
        assert is_stable(e, r)


def test_the_stability_check_rejects_a_divergent_pairing():
    from sim.firms import is_stable

    assert not is_stable(0.35, 0.12)   # the pairing that killed Peary
    assert not is_stable(0.50, 0.06)
