"""The ground a town stands on (D84)."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from sim import plots, towngame
from sim.game import Game
from sim.persist import default_routes
from sim.plots import BUDGET, HIGH, KEYS, LOW, place_for, plot_at
from sim.town import Engine
from sim.towngame import HOUSE, HOUSE_PLACE

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
SAMPLE = [plot_at(*place_for(f"company-{i}")) for i in range(600)]


def total(plot) -> float:
    return sum(plot[key] for key in KEYS)


def test_every_plot_adds_up_to_the_same():
    """Equal possibilities: no ground has more to give than another."""
    for plot in SAMPLE:
        assert total(plot) == pytest.approx(BUDGET, abs=0.005), plot
        assert all(LOW <= plot[key] <= HIGH for key in KEYS), plot


def test_the_same_place_is_always_the_same_ground():
    assert plot_at(8.5, 31.4) == plot_at(8.5, 31.4)
    assert place_for("p_abc") == place_for("p_abc")
    assert place_for("p_abc") != place_for("p_abd")


def test_neighbours_are_alike_but_not_the_same():
    here, there = plot_at(8.5, 31.4), plot_at(8.6, 31.4)
    assert here["name"] == there["name"] == "Mare Tranquillitatis"
    apart = [abs(here[key] - there[key]) for key in KEYS]
    assert max(apart) > 0.02, "next door is not a copy"
    assert max(apart) < 0.45, "and not another world"


def test_where_a_plot_is_decides_what_it_is_good_for():
    plain = plot_at(28.0, 17.5)          # Mare Serenitatis
    pole = plot_at(-89.5, 0.0)           # Shackleton
    high = plot_at(-43.3, -11.4)         # Tycho, in the bright highlands
    far = plot_at(-4.0, -157.4)          # Korolev, deep on the far side
    assert plain["name"] == "Mare Serenitatis" and pole["name"] == "South polar rim"
    assert high["name"] == "Near-side highlands" and far["name"] == "Far-side highlands"
    # iron and titanium are in the plains, aluminium in the highlands
    assert plain["metal"] > 0.7 > 0.5 > high["metal"] and pole["metal"] < 0.3
    assert high["glass"] > 0.7 > 0.3 > plain["glass"]
    # helium-3 is held by the plains' old titanium-rich soil
    assert plain["he3"] > 0.6 and pole["he3"] < 0.2
    # ice is at the poles and nowhere else, whatever the budget would like
    assert pole["ice"] > 0.7
    assert max(plain["ice"], high["ice"], far["ice"]) < 0.25
    assert pole["sun"] > plain["sun"]
    # Earth over the near side, silence for observatories on the far side,
    # and neither from a pole
    assert plain["view"] > 0.5 and far["view"] > 0.5 and pole["view"] < 0.3


def test_ice_and_outlook_are_never_handed_out_to_balance_the_books():
    for plot in SAMPLE:
        if abs(plot["lat"]) < 55:
            assert plot["ice"] <= LOW + plots.NOISE + 0.001, plot


def test_people_are_spread_over_every_kind_of_ground():
    kinds = [plots.kind_of(p["lat"], p["lon"]) for p in SAMPLE]
    for kind in plots.KINDS:
        assert 0.18 < kinds.count(kind) / len(kinds) < 0.32, kind
    assert len({(p["lat"], p["lon"]) for p in SAMPLE}) > 0.98 * len(SAMPLE)


def test_the_ground_changes_what_the_rules_give():
    """Same town, same hour, different ground: the readings are not decoration."""
    engine = Engine()

    def played(plot, hours=60):
        """The steward's first hours on this ground: arrays up, sun on them."""
        town = engine.create(1969, 160.0, plot)
        assert (json.loads(town.state).get("plot") or {}) == (plot or {})
        state, credits = town.state, 160.0
        for _ in range(hours):
            for intent in engine.steward(state, credits):
                done, _ = engine.apply(state, intent, credits)
                if done:
                    state, credits = done.state, done.credits
            town = engine.tick(state, 1.0, credits)
            state, credits = town.state, town.credits
        return json.loads(state)

    even = dict.fromkeys(KEYS, 0.5)
    plain, same = played(None), played({**even, "ice": 0.05})
    assert same["flows"]["gen"] == pytest.approx(plain["flows"]["gen"])
    assert same["materials"] == pytest.approx(plain["materials"])
    arrays = lambda s: sum(b["type"] == "solar" and b["progress"] >= 1   # noqa: E731
                           for b in s["buildings"])
    bright, dim = played({**even, "sun": 0.95}, 30), played({**even, "sun": 0.05}, 30)
    assert arrays(bright) and arrays(dim)
    per = lambda s: (s["flows"]["gen"] - 1.5) / arrays(s)    # noqa: E731
    assert per(bright) > 4 * per(dim) > 0


@pytest.mark.usefixtures("real_ground")
def test_a_company_is_given_its_ground_once_and_keeps_it():
    g = Game.open(":memory:", now=T0, routes=default_routes())
    person, _ = g.signup("Tranquility Co")
    meta = g.found_town(person)
    plot = meta["plot"]
    assert plot == towngame.plot_for(person.id)
    assert total(plot) == pytest.approx(BUDGET, abs=0.005)
    assert json.loads(g.town_state(person))["plot"] == plot
    assert meta["league"][0]["plot"] == plot
    # a new crew lands on the same ground
    row = g._town_row(person.id)
    dead = json.loads(row["state"])
    dead["phase"] = "lost"
    g.db.execute("UPDATE town SET state = ?, lost_tick = 1 WHERE player_id = ?",
                 (json.dumps(dead), person.id))
    g.db.commit()
    assert g.refound_town(g.player(person.id))["plot"] == plot
    g.db.close()


@pytest.mark.usefixtures("real_ground")
def test_house_companies_stand_where_they_are_named_for():
    assert set(HOUSE_PLACE) == {pid for pid, _, _ in HOUSE}
    names = {pid: towngame.plot_for(pid)["name"] for pid in HOUSE_PLACE}
    assert names["house_mare"] == "Mare Tranquillitatis"
    assert names["house_serenitatis"] == "Mare Serenitatis"
    assert names["house_imbrium"] == "Mare Imbrium"
    assert names["house_fecunditatis"] == "Mare Fecunditatis"
    assert names["house_tycho"] == "Near-side highlands"


def test_a_town_from_before_plots_plays_on_as_it_was(tmp_path):
    path = str(tmp_path / "old.db")
    g = Game.open(path, now=T0, routes=default_routes())
    person, _ = g.signup("Old Ground Ltd")
    g.found_town(person)
    g.db.execute("ALTER TABLE town DROP COLUMN plot")
    g.db.execute("DELETE FROM sim_schema_version WHERE version >= 7")
    g.db.commit()
    g.db.close()
    g = Game.open(path, routes=default_routes())
    assert g.town_meta(g.player(person.id))["plot"] == {}
    for _ in range(3):
        g.step()
    assert g.db.execute("SELECT faults FROM town").fetchone()[0] == 0
    g.db.close()
