"""The base as physics: what may stand where, what runs, what it makes.

No ledger and no database here. `sim.base` is pure, so every rule the bible
gives a base -- power against draw, heat against radiators, crew against
berths, and a layout that matters -- is checked on plain dictionaries.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sim import base
from sim.base import MODULES, TONNE, BaseError

SEED = "p_test"


@pytest.fixture
def layout():
    return base.site_layout(SEED)


@pytest.fixture
def state():
    return base.new_state("shackleton_rim", SEED, tick=0)


def stand(state, layout, tick=0):
    """Stand the whole kit the engineer's way."""
    plan, lay = base.suggest_layout(state, layout)
    for kind, x, y in plan:
        base.place(state, layout, kind, x, y, tick, leased=True)
        state["crates"].remove(kind)
    base.lay_conduit(state, layout, lay)
    return state


def hour(state, layout, tick=10, stock=None, **kw):
    return base.run_hour(state, layout, tick, stock or {}, **kw)


def of(state, kind):
    return [m for m in state["modules"] if m["type"] == kind]


def take_down(state, layout, module):
    """Remove a module but leave conduit where it stood, so links hold."""
    base.remove(state, module["id"])
    base.lay_conduit(state, layout, [[module["x"], module["y"]]])


# -- the catalogue is the design document's ---------------------------------------

def test_module_figures_are_seed_data(  ):
    """Power, heat, crew and cost are transcribed, not chosen."""
    text = (Path(__file__).resolve().parents[2] / "docs" / "seed-data.md"
            ).read_text(encoding="utf-8")
    rows = {}
    for line in text.split("## 3. Lunar base modules")[1].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 7 and re.fullmatch(r"[\d,]+", cells[5]):
            num = lambda s: int(s.replace("−", "-").replace("+", "")
                                .replace(",", "").replace("—", "0"))
            rows[cells[0]] = (num(cells[2]), num(cells[3]), num(cells[4]),
                              num(cells[5]))
    assert len(rows) == 20
    for spec in MODULES.values():
        assert rows[spec.name] == (spec.power_kw, spec.heat_kw, spec.crew,
                                   spec.cost), spec.name


# -- the ground ---------------------------------------------------------------------

def test_a_site_is_fixed_by_its_seed(layout):
    assert base.site_layout(SEED) == layout
    assert base.site_layout("p_other") != layout


def test_the_ground_is_usable(layout):
    size, mid = layout["size"], layout["size"] // 2
    rocks = {tuple(r) for r in layout["rocks"]}
    assert len(layout["patches"]) == len(base.PATCH_GRADES)
    for p in layout["patches"]:
        assert len(p["tiles"]) >= 5
        for x, y in p["tiles"]:
            assert 0 <= x < size and 0 <= y < size and (x, y) not in rocks
    assert not any(abs(x - mid) <= 3 and abs(y - mid) <= 3 for x, y in rocks)


def test_richer_ice_is_further_out(layout):
    mid = layout["size"] // 2
    reach = lambda p: min(abs(x - mid) + abs(y - mid) for x, y in p["tiles"])
    poorest, richest = layout["patches"][0], layout["patches"][-1]
    assert poorest["grade"] < richest["grade"]
    assert reach(poorest) < reach(richest)


# -- standing things ----------------------------------------------------------------

def test_refusals(state, layout):
    rock = layout["rocks"][0]
    with pytest.raises(BaseError):
        base.place(state, layout, "solar", -1, 0, 0, True)
    with pytest.raises(BaseError):
        base.place(state, layout, "solar", rock[0], rock[1], 0, True)
    with pytest.raises(BaseError):
        base.place(state, layout, "reactor", 12, 12, 0, True)
    base.place(state, layout, "command", 12, 12, 0, True)
    with pytest.raises(BaseError):
        base.place(state, layout, "solar", 12, 12, 0, True)
    with pytest.raises(BaseError):
        base.place(state, layout, "command", 13, 12, 0, True)
    with pytest.raises(BaseError):
        base.place(state, layout, "solar", True, 12, 0, True)


def test_a_module_is_down_while_it_is_assembled_or_moved(state, layout):
    stand(state, layout)
    plant = of(state, "electrolysis")[0]
    assert hour(state, layout, tick=1).status[plant["id"]] == "assembling"
    assert hour(state, layout, tick=10,
                stock={"ICE": 5 * TONNE}).status[plant["id"]] == "on"
    free = next((x, y) for x in range(24) for y in range(24)
                if [x, y] not in layout["rocks"]
                and (x, y) not in {(m["x"], m["y"]) for m in state["modules"]})
    base.move(state, layout, plant["id"], free[0], free[1], tick=10)
    assert hour(state, layout, tick=11).status[plant["id"]] == "assembling"


# -- the kit closes its budgets -----------------------------------------------------

def test_the_kit_runs_as_the_engineer_stands_it(state, layout):
    stand(state, layout)
    assert state["crates"] == []
    h = hour(state, layout, stock={"ICE": 10 * TONNE})
    assert set(h.status.values()) == {"on"}, h.status
    assert h.power_use <= h.power_gen
    assert h.heat_load <= h.heat_reject and h.throttle == (1, 1)
    assert h.crew_working == h.crew_need <= h.crew_cap
    assert h.made["ICE"] > 0 and h.made["PROP"] > 0


def test_nothing_runs_without_a_link_back_to_the_command_post(state, layout):
    stand(state, layout)
    spot = next((x, y) for x in (0, 1, 2) for y in (0, 1, 2)
                if [x, y] not in layout["rocks"]
                and base.patch_at(layout, x, y) is None)
    lone = base.place(state, layout, "solar", spot[0], spot[1], 0, False)
    assert hour(state, layout).status[lone["id"]] == "unlinked"
    run = [[x, spot[1]] for x in range(spot[0] + 1, 12)] + \
          [[11, y] for y in range(min(spot[1], 12), 12)]
    base.lay_conduit(state, layout, run)
    if lone["id"] in base.linked(state):
        assert hour(state, layout).status[lone["id"]] == "on"


# -- power, crew, heat --------------------------------------------------------------

def test_short_of_power_the_diggers_go_first_and_people_keep_breathing(
        state, layout):
    stand(state, layout)
    for m in of(state, "solar")[:3]:
        take_down(state, layout, m)
    h = hour(state, layout, stock={"ICE": 10 * TONNE})
    shed = {m["type"] for m in state["modules"]
            if h.status[m["id"]] == "no_power"}
    assert shed == {"ice_miner"}
    for kind in ("hab", "airlock", "eclss", "command", "electrolysis"):
        assert h.status[of(state, kind)[0]["id"]] == "on"
    assert h.power_use <= h.power_gen


def test_no_airlock_means_no_crew_and_no_crew_means_no_works(state, layout):
    stand(state, layout)
    take_down(state, layout, of(state, "airlock")[0])
    h = hour(state, layout, stock={"ICE": 10 * TONNE})
    assert h.crew_cap == 0
    assert h.status[of(state, "command")[0]["id"]] == "no_crew"
    assert h.status[of(state, "electrolysis")[0]["id"]] == "no_command"
    assert not h.ops


def test_too_few_radiators_throttle_the_plant(state, layout):
    stand(state, layout)
    full = hour(state, layout, stock={"ICE": 10 * TONNE})
    for m in of(state, "radiator")[:2]:
        take_down(state, layout, m)
    h = hour(state, layout, stock={"ICE": 10 * TONNE})
    num, den = h.throttle
    assert 0 < num < den
    assert h.heat_load > h.heat_reject
    assert 0 < h.made["PROP"] < full.made["PROP"]
    assert h.status[of(state, "electrolysis")[0]["id"]] == "hot"


def test_dust_halves_an_array_beside_a_digger(state, layout):
    stand(state, layout)
    miner = of(state, "ice_miner")[0]
    array = of(state, "solar")[0]
    clean = hour(state, layout).power_gen
    # Leave conduit where the array stood, so moving it unlinks nothing.
    base.lay_conduit(state, layout, [[array["x"], array["y"]]])
    state["conduits"].append([array["x"], array["y"]])
    spot = next((miner["x"] + dx, miner["y"] + dy)
                for dx in (-1, 1, 0) for dy in (-1, 1, 0)
                if (dx or dy)
                and [miner["x"] + dx, miner["y"] + dy] not in layout["rocks"]
                and (miner["x"] + dx, miner["y"] + dy) not in
                {(m["x"], m["y"]) for m in state["modules"]})
    base.move(state, layout, array["id"], spot[0], spot[1], tick=0)
    h = hour(state, layout)
    assert h.status[array["id"]] == "dusty"
    assert clean - h.power_gen == MODULES["solar"].power_kw // 2


def test_a_flare_or_arrears_stops_the_works_but_not_the_air(state, layout):
    stand(state, layout)
    for kw, why in (({"flaring": True}, "flare"),
                    ({"suspended": True}, "suspended")):
        h = hour(state, layout, stock={"ICE": 10 * TONNE}, **kw)
        assert not h.ops
        assert h.status[of(state, "electrolysis")[0]["id"]] == why
        assert h.status[of(state, "eclss")[0]["id"]] == "on"


# -- digging and refining -----------------------------------------------------------

def test_a_miner_digs_only_on_ice_and_richer_ice_gives_more(state, layout):
    stand(state, layout)
    miner = of(state, "ice_miner")[0]
    rate = MODULES["ice_miner"].extract_kg_per_day // 24
    won = {}
    for patch in (layout["patches"][0], layout["patches"][-1]):
        x, y = next(t for t in patch["tiles"]
                    if tuple(t) not in {(m["x"], m["y"])
                                        for m in state["modules"]})
        base.move(state, layout, miner["id"], x, y, tick=0)
        _, lay = base.suggest_layout(state, layout)
        base.lay_conduit(state, layout, lay)
        before = state["patches"][patch["id"]]
        hour(state, layout)
        won[patch["grade"]] = state["patches"][patch["id"]] - before
    poor, rich = min(won), max(won)
    assert won[poor] == pytest.approx(rate * poor / 100, abs=2)
    assert won[rich] > won[poor]
    bare = next((x, y) for x in range(9, 15) for y in range(9, 15)
                if base.patch_at(layout, x, y) is None
                and (x, y) not in {(m["x"], m["y"]) for m in state["modules"]})
    base.move(state, layout, miner["id"], bare[0], bare[1], tick=0)
    assert hour(state, layout).status[miner["id"]] in ("no_ice", "unlinked")


def test_ground_gives_less_the_more_it_is_worked(state, layout):
    stand(state, layout)
    first = hour(state, layout).made["ICE"]
    for i, _ in enumerate(state["patches"]):
        state["patches"][i] = base.PATCH_SCALE_KG      # down to 1/e
    later = hour(state, layout).made["ICE"]
    assert later == pytest.approx(first * 0.368, rel=0.02)


def test_the_plant_loses_a_tenth_and_not_a_gram_more(state, layout):
    """Remainders are carried, so mass is never rounded away."""
    stand(state, layout)
    for m in of(state, "ice_miner"):
        take_down(state, layout, m)
    stock = {"ICE": 1_000 * TONNE, "PROP": 0}
    fed = made = 0
    for t in range(10, 10 + 37):
        stock["PROP"] = 0                    # sold as fast as it is made
        h = hour(state, layout, tick=t, stock=stock)
        fed += h.used.get("ICE", 0)
        made += h.made.get("PROP", 0)
        stock["ICE"] -= h.used.get("ICE", 0)
    carry = sum(state["carry"].values())
    assert fed == 37 * (MODULES["electrolysis"].feed_kg_per_day // 24)
    assert made * base.YIELD_DENOMINATOR + carry == fed * base.YIELD_NUMERATOR


def test_the_plant_never_eats_ice_it_has_no_tank_for(state, layout):
    stand(state, layout)
    h = hour(state, layout, stock={"ICE": 50 * TONNE,
                                   "PROP": base.RUN_TANK_KG})
    assert h.status[of(state, "electrolysis")[0]["id"]] == "full"
    assert "PROP" not in h.made and not h.used.get("ICE")


def test_a_tank_farm_stores_nothing_without_liquefaction(state, layout):
    stand(state, layout)
    on = {m["id"] for m in state["modules"]}
    assert base.capacities(state, on)[1] == base.RUN_TANK_KG
    farm = base.place(state, layout, "tankfarm", 0, 23, 0, False) \
        if [0, 23] not in layout["rocks"] else \
        base.place(state, layout, "tankfarm", 1, 23, 0, False)
    assert base.capacities(state, on | {farm["id"]})[1] == base.RUN_TANK_KG
    cryo = base.place(state, layout, "cryo", 2, 23, 0, False) \
        if [2, 23] not in layout["rocks"] else \
        base.place(state, layout, "cryo", 3, 23, 0, False)
    assert base.capacities(state, on | {farm["id"], cryo["id"]})[1] == \
        base.RUN_TANK_KG + MODULES["tankfarm"].tank_kg


def test_a_full_yard_stops_the_miners(state, layout):
    stand(state, layout)
    take_down(state, layout, of(state, "electrolysis")[0])
    cap = hour(state, layout).store_kg
    h = hour(state, layout, stock={"ICE": cap})
    assert "ICE" not in h.made
    assert {h.status[m["id"]] for m in of(state, "ice_miner")} == {"full"}


def test_what_is_on_lease_counts_crates_and_all(state, layout):
    kit = sum(MODULES[k].cost for k in base.KIT)
    assert base.leased_value(state) == kit
    stand(state, layout)
    assert base.leased_value(state) == kit and base.owned_value(state) == 0
