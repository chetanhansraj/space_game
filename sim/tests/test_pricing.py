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


def test_reversion_runs_inverse_to_volatility():
    """A stable good is dragged back to its anchor hard; a volatile one roams."""
    assert REVERSION["low"] > REVERSION["medium"] > REVERSION["high"] \
        > REVERSION["very high"]
    assert set(REVERSION) == set(ELASTICITY)
