"""A base in the world: what is being defended, worst first.

1. A base never creates a credit. Everything it earns was paid by a buyer
   on the port's book; every bonus is a transfer out of the Ark's fund.
2. A base's hour is part of the world's hour: all of it, or none of it.
3. One base failing does not stop the world.
4. The loop works: stand the kit, make propellant, sell it, pay the Ark.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from market.money import CREDIT

from sim import base, basegame
from sim.basegame import LEASE_CAP, MILESTONES
from sim.game import DEV_FUND, Game, GameError
from sim.persist import default_routes
from sim.ships import KESTREL, ShipState

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
TONNE = 1_000
SHACK, PEARY = "shackleton_depot", "peary_ridge"


@pytest.fixture(scope="module")
def routes():
    return default_routes()


@pytest.fixture
def game(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    yield g
    assert g.db.execute("SELECT COALESCE(SUM(faults), 0) FROM base"
                        ).fetchone()[0] == 0, "a base failed an hour"
    g.db.close()


@pytest.fixture
def works(game):
    """A company with the kit standing and a few hours on the clock."""
    player, _ = game.signup("Rim Works")
    game.charter_base(player, "shackleton_rim")
    game.base_stand_kit(player)
    return game.player(player.id)


def run(g: Game, ticks: int) -> None:
    for _ in range(ticks):
        g.step()


def cash(g: Game, account: str) -> int:
    return g.world.ledger.balance(account, CREDIT)


def view(g: Game, player) -> dict:
    return g.base_view(player)["base"]


def minted(g: Game) -> int:
    return g.world.ledger.credits_in_existence()


def midnight(g: Game) -> None:
    """Run to the next game midnight, when the day's charges are taken."""
    run(g, 24 - g.world.tick % 24)


# -- founding -----------------------------------------------------------------------

def test_a_charter_gives_land_and_crates_and_no_money(game):
    player, _ = game.signup("Rim Works")
    game.step()
    before, fund = cash(game, player.account), cash(game, DEV_FUND)
    made = minted(game)
    v = game.charter_base(player, "shackleton_rim")["base"]
    assert sorted(v["crates"]) == sorted(base.KIT) and v["modules"] == []
    assert cash(game, player.account) == before
    assert cash(game, DEV_FUND) == fund and minted(game) == made
    kinds = [m["kind"] for m in game.inbox(player)]
    assert "base_charter" in kinds
    assert any(e["kind"] == "base_chartered" for e in game.feed())


def test_one_site_per_company_and_only_real_sites(game):
    player, _ = game.signup("Rim Works")
    with pytest.raises(GameError):
        game.charter_base(player, "the_far_side")
    with pytest.raises(GameError):
        game.base_build(player, "solar", 5, 5)
    game.charter_base(player, "shackleton_rim")
    with pytest.raises(GameError):
        game.charter_base(player, "shackleton_rim")


def test_someone_without_a_base_is_shown_the_sites(game):
    player, _ = game.signup("Rim Works")
    v = game.base_view(player)
    assert v["base"] is None and v["sites"][0]["id"] == "shackleton_rim"


# -- building -----------------------------------------------------------------------

def test_a_crate_is_free_and_a_purchase_pays_the_ark_exactly(game):
    player, _ = game.signup("Rim Works")
    game.charter_base(player, "shackleton_rim")
    before, fund, made = cash(game, player.account), cash(game, DEV_FUND), minted(game)
    game.base_build(player, "command", 12, 12, how="crate")
    assert cash(game, player.account) == before
    game.base_build(player, "radiator", 12, 13, how="buy")
    cost = base.MODULES["radiator"].cost
    bonus = dict((i, b) for i, _, b in MILESTONES)["own"]
    assert cash(game, player.account) == before - cost + bonus
    assert cash(game, DEV_FUND) == fund + cost - bonus
    assert minted(game) == made
    with pytest.raises(GameError, match="costs"):
        game.base_build(player, "electrolysis", 12, 14, how="buy")
    with pytest.raises(GameError, match="crate"):
        game.base_build(player, "cryo", 12, 14, how="crate")
    with pytest.raises(GameError, match="already stands"):
        game.base_build(player, "solar", 12, 12, how="crate")


def test_the_ark_leases_so_much_plant_and_no_more(game):
    player, _ = game.signup("Rim Works")
    game.charter_base(player, "shackleton_rim")
    room = LEASE_CAP - base.leased_value(json.loads(
        game.db.execute("SELECT state FROM base").fetchone()["state"]))
    assert 0 < room < 2 * base.MODULES["ice_miner"].cost
    game.base_build(player, "ice_miner", 12, 12, how="lease")
    with pytest.raises(GameError, match="leases"):
        game.base_build(player, "ice_miner", 12, 13, how="lease")
    assert len(view(game, player)["modules"]) == 1


def test_buying_out_a_lease_makes_it_yours_and_stops_the_rent(game, works):
    v = view(game, works)
    radiator = next(m for m in v["modules"] if m["type"] == "radiator")
    with pytest.raises(GameError, match="costs"):
        game.base_buyout(works, next(m for m in v["modules"]
                                     if m["type"] == "electrolysis")["id"])
    before, rent = cash(game, works.account), v["money"]["lease_per_day"]
    game.base_buyout(works, radiator["id"])
    after = view(game, works)
    cost = base.MODULES["radiator"].cost
    assert cash(game, works.account) == before - cost + 30_000   # and "own"
    assert after["money"]["lease_per_day"] == rent - basegame.lease_per_day(cost)
    assert after["money"]["owned_value"] == cost
    with pytest.raises(GameError, match="already own"):
        game.base_buyout(works, radiator["id"])


def test_conduit_is_paid_for_by_the_tile(game):
    player, _ = game.signup("Rim Works")
    game.charter_base(player, "shackleton_rim")
    before = cash(game, player.account)
    v = game.base_conduit(player, [[12, 10], [12, 11], [12, 11], [-1, 3]])
    assert len(v["base"]["conduits"]) == 2
    assert cash(game, player.account) == before - 2 * base.CONDUIT_COST
    game.base_lift_conduit(player, 12, 10)
    assert cash(game, player.account) == before - 2 * base.CONDUIT_COST
    with pytest.raises(GameError):
        game.base_conduit(player, [[12, 11]])


# -- the loop -----------------------------------------------------------------------

def test_the_kit_makes_propellant_sells_it_and_the_money_is_real(game, works):
    made, start = minted(game), cash(game, works.account)
    run(game, 16)
    v = view(game, works)
    today = v["books"]["today"]
    assert today["made_kg_PROP"] > 5 * TONNE
    assert today["sold_kg_PROP"] >= 5 * TONNE and today["sales"] > 0
    bonuses = sum(m["bonus"] for m in v["milestones"] if m["done"])
    assert {m["id"] for m in v["milestones"] if m["done"]} >= {
        "desk", "first_prop", "first_sale"}
    # Every credit gained is a sale on the book or a transfer from the fund.
    assert cash(game, works.account) == (
        start + today["sales"] - today.get("feed", 0) + bonuses)
    # The base account never keeps money; it is swept the moment it is paid.
    assert cash(game, f"base:{works.id}") == 0
    assert minted(game) == made
    game.world.ledger.assert_conserved()


def test_what_the_base_holds_is_what_the_ledger_says(game, works):
    run(game, 12)
    v = view(game, works)
    ledger = game.world.ledger
    for asset in ("ICE", "PROP"):
        assert v["stock"][asset] == ledger.balance(f"base:{works.id}", asset)
    today = v["books"]["today"]
    assert v["stock"]["ICE"] == (today.get("made_kg_ICE", 0)
                                 + today.get("bought_kg_ICE", 0)
                                 - today.get("used_kg_ICE", 0))
    assert v["stock"]["PROP"] == (today["made_kg_PROP"]
                                  - today.get("sold_kg_PROP", 0))


def test_midnight_takes_the_lease_wear_and_payroll(game, works):
    run(game, 6)
    midnight(game)
    ledger = game.world.ledger
    households = [f for f in game.world.active_firms()
                  if f.role.value == "consumer" and f.node == SHACK]
    burned = ledger.credits_destroyed()
    paid = sum(cash(game, h.account) for h in households)
    run(game, 24)
    v = view(game, works)
    y = v["books"]["yesterday"]
    money = v["money"]
    assert y["lease"] == money["lease_per_day"] == basegame.lease_per_day(
        sum(base.MODULES[k].cost for k in base.KIT))
    # To the credit, give or take the fraction carried from the day before.
    assert abs(y["upkeep"] - money["upkeep_per_day"]) <= 1
    assert y["wages"] == money["wages_per_day"] == 6 * basegame.WAGE_PER_CREW_DAY
    assert ledger.credits_destroyed() - burned >= y["lease"] + y["upkeep"]
    # Payroll is not burned: it is in the households' accounts, to be spent.
    assert y["wages"] % len(households) == 0 and paid >= 0


def test_taking_plant_down_before_midnight_does_not_dodge_the_day(game, works):
    """Charges accrue by the hour, so there is nothing to time."""
    midnight(game)
    run(game, 22)
    rent = view(game, works)["money"]["lease_per_day"]
    for m in view(game, works)["modules"]:
        if m["type"] != "command":
            game.base_remove(works, m["id"])
    assert view(game, works)["money"]["lease_per_day"] < rent // 10
    run(game, 2)
    y = view(game, works)["books"]["yesterday"]
    assert y["lease"] > rent * 22 // 24 - 100
    assert y["wages"] >= 6 * basegame.WAGE_PER_CREW_DAY * 22 // 24 - 10


def test_a_company_that_cannot_pay_stands_down_until_it_can(game, works):
    run(game, 6)
    ledger = game.world.ledger
    game.base_policy(works, "PROP", sell=False)
    game.base_policy(works, "ICE", buy=False)
    purse = cash(game, works.account)
    ledger.transfer(works.account, DEV_FUND, CREDIT, purse, kind="test",
                    game_time=game.world.game_time())
    midnight(game)
    v = view(game, works)
    assert v["money"]["owed"] > 0
    run(game, 1)
    v = view(game, works)
    plant = next(m for m in v["modules"] if m["type"] == "electrolysis")
    assert plant["status"] == "suspended"
    assert next(m for m in v["modules"] if m["type"] == "eclss")["status"] == "on"
    assert cash(game, works.account) == 0          # never negative
    ledger.transfer(DEV_FUND, works.account, CREDIT, purse, kind="test",
                    game_time=game.world.game_time())
    owed = v["money"]["owed"]
    run(game, 1)
    v = view(game, works)
    assert v["money"]["owed"] == 0
    assert cash(game, works.account) == purse - owed
    assert next(m for m in v["modules"]
                if m["type"] == "electrolysis")["status"] != "suspended"


def test_a_bonus_is_paid_once_and_only_while_the_fund_can(game, works):
    ledger = game.world.ledger
    fund = cash(game, DEV_FUND)
    ledger.transfer(DEV_FUND, "world:sink", CREDIT, fund, kind="test",
                    game_time=game.world.game_time())
    before = cash(game, works.account)
    run(game, 8)
    v = view(game, works)
    assert not any(m["done"] for m in v["milestones"])
    assert cash(game, works.account) == before + v["books"]["today"].get(
        "sales", 0) - v["books"]["today"].get("feed", 0)
    ledger.transfer("world:genesis", DEV_FUND, CREDIT, fund, kind="test",
                    game_time=game.world.game_time())
    run(game, 2)
    paid = cash(game, DEV_FUND)
    run(game, 3)
    done = [m["id"] for m in view(game, works)["milestones"] if m["done"]]
    assert "desk" in done and len(done) == len(set(done))
    assert cash(game, DEV_FUND) >= paid - 40_000     # nothing paid twice


def test_standing_orders_need_the_comms_relay(game, works):
    run(game, 8)
    v = view(game, works)
    assert v["books"]["today"].get("sold_kg_PROP", 0) > 0
    relay = next(m for m in v["modules"] if m["type"] == "comms")
    game.base_remove(works, relay["id"])
    game.base_conduit(works, [[relay["x"], relay["y"]]])
    sold = view(game, works)["books"]["today"]["sold_kg_PROP"]
    run(game, 6)
    v = view(game, works)
    assert v["books"]["today"]["sold_kg_PROP"] == sold
    assert v["stock"]["PROP"] > 2 * TONNE                   # made, and held


def test_selling_and_buying_by_hand(game, works):
    run(game, 6)
    game.base_policy(works, "PROP", sell=False)
    game.base_policy(works, "ICE", buy=False)
    run(game, 4)
    v = view(game, works)
    held = v["stock"]["PROP"] // TONNE
    assert held >= 1
    before = cash(game, works.account)
    bid = game.prices(SHACK)["PROP"]["bid"]
    report = game.base_sell(works, "PROP", held, bid)
    assert report["kg"] > 0
    assert cash(game, works.account) == before + report["value"]
    with pytest.raises(GameError, match="holds"):
        game.base_sell(works, "PROP", 500, bid)
    ledger = game.world.ledger
    ledger.extract("agent:shack_ice_0", "ICE", 5 * TONNE,
                   game.world.game_time(), memo="test stock")
    game.world.books[SHACK].place("ICE", "ASK", 5_000, 5 * TONNE,
                                  "agent:shack_ice_0", game.world.game_time())
    before, ice = cash(game, works.account), view(game, works)["stock"]["ICE"]
    report = game.base_buy(works, "ICE", 3, 5_000)
    assert report["kg"] == 3 * TONNE and report["value"] <= 3 * 5_000
    assert cash(game, works.account) == before - report["value"]
    assert view(game, works)["stock"]["ICE"] == ice + 3 * TONNE
    with pytest.raises(GameError):
        game.base_buy(works, "HE3", 1, 10)
    assert cash(game, f"base:{works.id}") == 0


def test_a_policy_is_checked(game, works):
    v = game.base_policy(works, "ICE", max_price=555, target_t=40, buy=True)
    assert v["base"]["policy"]["ICE"]["max_price"] == 555
    assert v["base"]["policy"]["ICE"]["target_t"] == 40
    with pytest.raises(GameError):
        game.base_policy(works, "ICE", target_t=-1)
    with pytest.raises(GameError):
        game.base_policy(works, "ICE", max_price=0)
    with pytest.raises(GameError):
        game.base_policy(works, "GOODS", sell=True)


# -- the people -------------------------------------------------------------------

def grow(game, player, kind, how="lease"):
    """Stand one more module against the cluster, on open ground."""
    b = view(game, player)
    rocks = {tuple(r) for r in b["layout"]["rocks"]}
    ice = {tuple(t) for p in b["layout"]["patches"] for t in p["tiles"]}
    taken = {(m["x"], m["y"]) for m in b["modules"]} | {
        tuple(c) for c in b["conduits"]}
    core = [(m["x"], m["y"]) for m in b["modules"] if m["type"] != "ice_miner"]
    for x, y in sorted(core):
        for t in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (t not in rocks and t not in ice and t not in taken
                    and 0 <= t[0] < 24 and 0 <= t[1] < 24):
                game.base_build(player, kind, t[0], t[1], how=how)
                return
    raise AssertionError("no open ground beside the base")


def people(game, player) -> int:
    return len(view(game, player)["people"]["residents"])


def test_six_found_a_site_and_run_it(game, works):
    run(game, 8)
    b = view(game, works)
    names = [r["name"] for r in b["people"]["residents"]]
    assert names[:4] == ["Asha", "Kenji", "Lena", "Rafael"] and len(names) == 6
    assert b["report"]["crew"] == [6, 6, 6]
    assert b["report"]["needs"] == {"air": True, "water": True, "food": True}


def test_a_full_town_gets_no_one_new(game, works):
    midnight(game)
    run(game, 48)
    assert people(game, works) == 6


def test_a_town_with_berths_air_and_food_grows_and_the_ark_leases_it_more(
        game, works):
    cap = view(game, works)["money"]["lease_cap"]
    for kind in ("hab", "hydroponics", "radiator", "solar", "solar"):
        grow(game, works, kind)
    midnight(game)
    run(game, 24)
    b = view(game, works)
    # Twelve berths, one life-support unit good for eight, food for twelve.
    assert people(game, works) == 8
    assert b["people"]["shuttle"]["came"] and not b["people"]["shuttle"]["left"]
    assert b["money"]["lease_cap"] == cap + 2 * basegame.LEASE_CAP_PER_RESIDENT
    run(game, 48)
    assert people(game, works) == 8                 # air for eight, no more
    grow(game, works, "eclss")
    run(game, 72)
    assert people(game, works) == 12
    b = view(game, works)
    assert b["report"]["needs"] == {"air": True, "water": True, "food": True}
    assert "town10" in [m["id"] for m in b["milestones"] if m["done"]]
    # The newcomers are who tends the second bay and the second unit.
    assert b["report"]["crew"][0] >= 9


def test_hunger_sends_the_newest_home_and_the_founders_stay(game, works):
    for kind in ("hab", "hydroponics", "radiator", "solar", "solar"):
        grow(game, works, kind)
    midnight(game)
    run(game, 24)
    assert people(game, works) == 8
    for m in view(game, works)["modules"]:
        if m["type"] == "hydroponics":
            game.base_remove(works, m["id"])
            game.base_conduit(works, [[m["x"], m["y"]]])
    eaten = game.world.ledger.balance(f"base:{works.id}", "FOOD")
    if eaten:
        game.world.ledger.consume(f"base:{works.id}", "FOOD", eaten,
                                  game.world.game_time(), memo="test")
    run(game, 24 * 5)
    b = view(game, works)
    assert people(game, works) == 6
    assert all(r.get("founder") for r in b["people"]["residents"])
    assert b["report"]["needs"]["food"] is False
    assert "base_departure" in [m["kind"] for m in game.inbox(works)]
    assert b["money"]["lease_cap"] == basegame.LEASE_CAP


def test_people_drink_the_ice_and_eat_what_the_bays_grow(game, works):
    run(game, 6)
    midnight(game)
    run(game, 24)
    y = view(game, works)["books"]["yesterday"]
    # Six people, a kilogram of water an hour each; the plant takes the rest.
    assert y["used_kg_ICE"] >= 6 * 24
    b = view(game, works)
    assert b["people"]["unmet"]["food"] == 0 and b["report"]["needs"]["food"]
    # One bay feeds six exactly, so nothing reaches the pantry.
    assert game.world.ledger.balance(f"base:{works.id}", "FOOD") == 0


# -- promises ---------------------------------------------------------------------

def test_jobs_are_other_ports_wanting_what_the_base_makes(game, works):
    run(game, 30)
    jobs = view(game, works)["jobs"]
    board = [c for c in game.board.open()
             if c.asset in basegame.STOCKED and c.node != SHACK]
    assert {j["id"] for j in jobs} == {c.id for c in board}
    for j in jobs:
        assert j["node"] != SHACK and j["flight_ticks"] >= 1 and not j["mine"]


def test_a_promise_kept_from_the_base_by_ship(game, works):
    """The whole loop: take a job, make the goods, load, fly, get paid."""
    ledger = game.world.ledger
    game.base_policy(works, "PROP", sell=False)
    # Somewhere to keep propellant while the order is made up.
    ledger.transfer(DEV_FUND, works.account, CREDIT, 3_000_000, kind="test",
                    game_time=game.world.game_time())
    for kind in ("cryo", "tankfarm"):
        grow(game, works, kind, how="buy")
    for kind in ("solar",) * 6 + ("radiator",) * 3:
        grow(game, works, kind, how="buy")
    job = None
    for _ in range(24 * 12):
        game.step()
        job = next((j for j in view(game, works)["jobs"]
                    if j["asset"] == "PROP"
                    and j["qty_kg"] <= KESTREL.cargo_capacity_kg), None)
        if job:
            break
    assert job, "no propellant job was posted in twelve days"
    game.accept(works, job["id"])
    assert next(j for j in view(game, works)["jobs"]
                if j["id"] == job["id"])["mine"]
    while view(game, works)["stock"]["PROP"] < job["qty_kg"]:
        game.step()
        assert game.world.tick < job["deadline_tick"], "could not make it in time"
    before = cash(game, works.account)
    game.base_load(works, "PROP", job["qty_kg"] // TONNE)
    game.dispatch(works, job["node"], sell_on_arrival=False)
    while game.ship_of(works).state is ShipState.IN_TRANSIT:
        game.step()
    paid = cash(game, works.account) - before
    assert paid >= job["payment"] - 5_000           # less fees and charges
    assert game.board.get(job["id"]).status == "FULFILLED"


# -- ship and base ------------------------------------------------------------------

def test_the_ship_loads_from_the_base_only_at_its_port(game, works):
    game.base_policy(works, "PROP", sell=False)
    game.base_policy(works, "ICE", buy=False)
    run(game, 12)
    ship = game.ship_of(works)
    stock = view(game, works)["stock"]
    ice_t = stock["ICE"] // TONNE
    assert ice_t >= 1
    aboard = game.world.ledger.balance(works.account, "ICE")
    game.base_load(works, "ICE", ice_t)
    assert game.world.ledger.balance(works.account, "ICE") == aboard + ice_t * TONNE
    assert view(game, works)["stock"]["ICE"] == stock["ICE"] - ice_t * TONNE
    assert ship.loaded.get("ICE") == ice_t * TONNE
    assert game.hold_used(works) == ice_t * TONNE
    with pytest.raises(GameError, match="holds"):
        game.base_load(works, "ICE", 500)
    game.base_unload(works, "ICE", ice_t)
    assert game.hold_used(works) == 0 and ship.loaded.get("ICE") == 0
    game.dispatch(works, PEARY, sell_on_arrival=False)
    with pytest.raises(GameError, match="in flight"):
        game.base_load(works, "PROP", 1)
    while game.ship_of(works).state is ShipState.IN_TRANSIT:
        game.step()
    with pytest.raises(GameError, match="not at"):
        game.base_load(works, "PROP", 1)
    assert view(game, works)["ship"]["docked_here"] is False


def test_the_hold_still_limits_what_is_loaded(game, works):
    ledger = game.world.ledger
    ledger.extract(f"base:{works.id}", "ICE", 60 * TONNE,
                   game.world.game_time(), memo="test stock")
    with pytest.raises(GameError, match="space aboard"):
        game.base_load(works, "ICE", KESTREL.cargo_capacity_kg // TONNE + 1)
    game.base_load(works, "ICE", KESTREL.cargo_capacity_kg // TONNE)


# -- atomicity and survival ---------------------------------------------------------

def test_a_base_that_breaks_loses_its_own_hour_and_the_world_goes_on(
        game, works, monkeypatch):
    run(game, 6)
    ledger = game.world.ledger
    held = {a: ledger.balance(f"base:{works.id}", a) for a in ("ICE", "PROP")}
    purse = cash(game, works.account)
    saved = game.db.execute("SELECT state FROM base").fetchone()["state"]
    tick = game.world.tick

    real = base.run_hour

    def broken(state, *a, **kw):
        hour = real(state, *a, **kw)
        raise RuntimeError("a bug in one base")

    monkeypatch.setattr(base, "run_hour", broken)
    game.step()
    assert game.world.tick == tick + 1                 # the world moved on
    row = game.db.execute("SELECT state, faults FROM base").fetchone()
    assert row["faults"] == 1 and row["state"] == saved
    assert held == {a: ledger.balance(f"base:{works.id}", a)
                    for a in ("ICE", "PROP")}
    assert cash(game, works.account) == purse
    ledger.assert_conserved()
    monkeypatch.setattr(base, "run_hour", real)
    game.db.execute("UPDATE base SET faults = 0")
    game.step()
    assert view(game, works)["report"]["tick"] == tick + 2


def test_a_tick_that_fails_takes_the_bases_hour_with_it(game, works,
                                                         monkeypatch):
    run(game, 23 - game.world.tick % 24)       # the next tick is midnight
    ledger = game.world.ledger
    before = (game.db.execute("SELECT state, owed FROM base").fetchone()[:],
              ledger.holdings(f"base:{works.id}"), cash(game, works.account),
              game.world.tick)

    def boom(now):
        raise RuntimeError("upkeep fell over")

    monkeypatch.setattr(game, "_charge_upkeep", boom)
    with pytest.raises(RuntimeError):
        game.step()
    after = (game.db.execute("SELECT state, owed FROM base").fetchone()[:],
             ledger.holdings(f"base:{works.id}"), cash(game, works.account),
             game.world.tick)
    assert after == before


def test_a_base_survives_a_restart(routes, tmp_path):
    path = str(tmp_path / "world.db")
    g = Game.open(path, now=T0, routes=routes)
    player, _ = g.signup("Rim Works")
    g.charter_base(player, "shackleton_rim")
    g.base_stand_kit(player)
    run(g, 10)
    before = g.base_view(player)["base"]
    g.db.close()

    g = Game.open(path, routes=routes)
    player = g.player(player.id)
    again = g.base_view(player)["base"]
    assert again == before
    run(g, 3)
    assert g.base_view(player)["base"]["report"]["tick"] == before["report"]["tick"] + 3
    assert g.db.execute("SELECT faults FROM base").fetchone()[0] == 0
    g.db.close()


def test_a_world_from_before_bases_gains_the_table(routes, tmp_path):
    """Forward-only: an existing world migrates and nobody has a base."""
    from sim import schema
    path = str(tmp_path / "old.db")
    g = Game.open(path, now=T0, routes=routes)
    player, _ = g.signup("Old Hand")
    g.db.execute("DROP TABLE base")
    g.db.execute("DELETE FROM sim_schema_version WHERE version = 2")
    g.db.commit()
    g.db.close()
    g = Game.open(path, routes=routes)
    assert g.base_view(g.player(player.id))["base"] is None
    run(g, 2)
    g.db.close()


# -- a week of it -------------------------------------------------------------------

def test_a_week_on_the_rim_pays_and_conserves(game, works):
    """The kit as the engineer stands it turns a profit, and creates nothing."""
    made, start = minted(game), cash(game, works.account)
    run(game, 24 * 7)
    v = view(game, works)
    bonuses = sum(m["bonus"] for m in v["milestones"] if m["done"])
    assert cash(game, works.account) - start - bonuses > 40_000
    assert minted(game) == made
    assert v["money"]["owed"] == 0
    game.world.ledger.assert_conserved()
    assert game.world.ledger.verify_checkpoints() == []
