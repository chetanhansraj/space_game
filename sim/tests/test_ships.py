"""Ships, and the tradeoff that makes route choice interesting.

The bible: "Upgrades improve one at the cost of another: bigger tanks mean
less cargo... There is no strictly best ship, only ships suited to particular
routes." Nothing enforces that. It falls out of the rocket equation, and
these tests pin the consequences.
"""

import math

import pytest

from sim.ships import EXHAUST_VELOCITY, KESTREL, Ship, ShipState

TONNE = 1_000


def test_the_rocket_equation_is_the_rocket_equation():
    fuel = KESTREL.fuel_for(50_000, 20 * TONNE)
    burnout = KESTREL.dry_mass_kg + 20 * TONNE
    assert EXHAUST_VELOCITY * math.log((burnout + fuel) / burnout) >= 50_000


def test_fuel_rounds_up_never_down():
    """A ship that departs a gram short of the minimum does not arrive."""
    for dv in (1, 999, 3_360, 84_900):
        fuel = KESTREL.fuel_for(dv, 10 * TONNE)
        assert KESTREL.delta_v_available(10 * TONNE, fuel) >= dv


def test_payload_falls_as_the_route_gets_faster():
    """The whole tradeoff, in one assertion."""
    loads = [KESTREL.max_cargo_for(dv)
             for dv in (3_360, 35_400, 84_900, 182_200)]
    assert loads == sorted(loads, reverse=True)
    assert loads[0] == KESTREL.cargo_capacity_kg     # a lunar hop costs nothing
    assert loads[-1] < loads[0]                       # a 30-day Mars run does


def test_a_load_always_leaves_room_for_its_own_fuel():
    """max_cargo_for must never return a load the ship cannot actually lift."""
    for dv in range(2_000, 220_000, 7_000):
        cargo = KESTREL.max_cargo_for(dv)
        if cargo == 0:
            continue
        fuel = KESTREL.fuel_for(dv, cargo)
        assert cargo + fuel <= KESTREL.cargo_capacity_kg + KESTREL.tank_capacity_kg + 1
        assert KESTREL.delta_v_available(cargo, fuel) >= dv


def test_an_empty_ship_goes_much_further_than_a_full_one():
    full = KESTREL.delta_v_available(KESTREL.cargo_capacity_kg, KESTREL.tank_capacity_kg)
    empty = KESTREL.delta_v_available(0, KESTREL.tank_capacity_kg)
    assert empty > full * 1.7


def test_no_fuel_means_no_delta_v():
    assert KESTREL.delta_v_available(10 * TONNE, 0) == 0.0


def test_progress_runs_zero_to_one():
    s = Ship(id="s", owner="f", account="a", ship_class=KESTREL, location="x")
    assert s.progress(5) == 0.0
    s.state = ShipState.IN_TRANSIT
    s.depart_tick, s.arrive_tick = 10, 20
    assert s.progress(10) == 0.0
    assert s.progress(15) == pytest.approx(0.5)
    assert s.progress(20) == 1.0
    assert s.progress(99) == 1.0
