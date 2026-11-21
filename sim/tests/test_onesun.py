"""One Sun, one clock (D93).

Every town keeps time by where the Sun stands over it, a crew only ever
lands in a place's morning, a world that was running on towns' own days is
moved onto the Sun once, and the first landing pad is paid for once from
the Ark's fund.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from market.money import CREDIT
from orbital.clock import to_jd
from sim import plots, sun, towngame
from sim.game import DEV_FUND, Game, GameError
from sim.persist import default_routes
from sim.towngame import HOUSE_PLACE, PAD_GRANT

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
JD0 = to_jd(T0)


@pytest.fixture(scope="module")
def routes():
    return default_routes()


def fresh(routes):
    return Game.open(":memory:", now=T0, routes=routes)


def town_phase(g, pid) -> float:
    """Hours since sunrise, as the town's own rules have it."""
    s = json.loads(g._town_row(pid)["state"])
    return (s["t"] + s["sun"]) % sun.LUNAR_DAY


def sky_phase(g, plot) -> float:
    return sun.phase(plot["lon"], plot["dark"], to_jd(g.sky_time()))


def apart(a, b) -> float:
    """Hours between two times of day, the short way round."""
    return abs((a - b + sun.LUNAR_DAY / 2) % sun.LUNAR_DAY - sun.LUNAR_DAY / 2)


def lose(g, pid, plot=None):
    row = g._town_row(pid)
    dead = json.loads(row["state"])
    dead["phase"] = "lost"
    g.db.execute(
        "UPDATE town SET state = ?, lost_tick = ?, plot = ? WHERE player_id = ?",
        (json.dumps(dead), g.world.tick,
         json.dumps(plot) if plot else row["plot"], pid))
    g.db.commit()


def with_pad(g, pid):
    row = g._town_row(pid)
    s = json.loads(row["state"])
    s["buildings"].append({**s["buildings"][0], "uid": 999, "type": "pad",
                           "progress": 1, "connected": True, "damaged": False})
    g.db.execute("UPDATE town SET state = ? WHERE player_id = ?",
                 (json.dumps(s), pid))
    g.db.commit()


# -- the Sun ------------------------------------------------------------------------

def test_the_sun_goes_round_once_a_lunar_day_and_noon_is_under_it():
    for day in range(0, 60, 7):
        jd = JD0 + day
        under = sun.subsolar_lon(jd)
        assert abs(sun.hours_since_noon(under, jd)) < 1e-6
        # ninety degrees east of it the Sun has a quarter of the day to run
        east = (under + 90 + 180) % 360 - 180
        assert sun.hours_since_noon(east, jd) == pytest.approx(
            sun.LUNAR_DAY / 4, abs=1e-6)
        # at the equator that is where it sets: 354 hours of light, used up
        assert sun.phase(east, 354, jd) == pytest.approx(354, abs=1e-6)
    # and it comes back to the same place in about 29.5 days
    turn = [sun.subsolar_lon(JD0 + 29.53 * k) for k in range(4)]
    assert all(abs((a - turn[0] + 180) % 360 - 180) < 8 for a in turn)


# -- morning plots ------------------------------------------------------------------

def test_every_plot_on_offer_is_early_in_its_morning_whenever_it_is_asked_for():
    kinds = set()
    for hour in range(0, sun.LUNAR_DAY, 37):
        jd = JD0 + hour / 24
        offers = plots.offers_for(f"p_{hour}", jd, hour)
        assert len(offers) == plots.OFFERS
        assert len({(o["lat"], o["lon"]) for o in offers}) == plots.OFFERS
        for o in offers:
            assert plots.in_morning(o, jd)
            assert o["dark"] + plots.MORNING < sun.LUNAR_DAY
            kinds.add(plots.kind_of(o["lat"], o["lon"]))
    assert kinds == set(plots.KINDS), "over a lunar day every kind of ground comes up"


def test_a_list_of_plots_holds_while_it_is_read_and_then_moves_on():
    start = 5 * plots.OFFER_HOLD
    first = plots.offers_for("p_reader", JD0 + start / 24, start)
    for into in range(plots.OFFER_HOLD):
        tick = start + into
        assert plots.offers_for("p_reader", JD0 + tick / 24, tick) == first
        assert all(plots.in_morning(o, JD0 + tick / 24) for o in first), \
            "ground offered at the start of the hold is still morning at its end"
    later = start + plots.OFFER_HOLD
    assert plots.offers_for("p_reader", JD0 + later / 24, later) != first


def test_a_choice_says_where_it_is_and_only_offered_ground_is_taken():
    tick = 5 * plots.OFFER_HOLD + 3
    jd = JD0 + tick / 24
    offers = towngame._plot_for_real  # the real chooser, whatever the tests' ground
    now = plots.offers_for("p_chooser", jd, tick)
    assert offers("p_chooser", 0, jd, tick, (now[2]["lat"], now[2]["lon"])) == now[2]
    # a plot from the list before this one is still good while it is still morning there
    before = plots.offers_for("p_chooser", jd - plots.OFFER_HOLD / 24,
                              tick - plots.OFFER_HOLD)
    for old in before:
        if plots.in_morning(old, jd):
            assert offers("p_chooser", 0, jd, tick, (old["lat"], old["lon"])) == old
        else:
            with pytest.raises(GameError, match="sunrise has moved on"):
                offers("p_chooser", 0, jd, tick, (old["lat"], old["lon"]))
    with pytest.raises(GameError, match="sunrise has moved on"):
        offers("p_chooser", 0, jd, tick, (12.3, 45.6))


# -- towns under it -----------------------------------------------------------------

@pytest.mark.usefixtures("real_ground", "one_sun")
def test_every_town_keeps_time_by_the_sun_over_it(routes):
    g = fresh(routes)
    people = [g.signup(name)[0] for name in ("First Light", "Second Light")]
    for i, person in enumerate(people):
        meta = g.found_town(person, i)
        assert sky_phase(g, meta["plot"]) <= plots.MORNING
    for _ in range(30):
        g.step()
    for person in people:
        plot = json.loads(g._town_row(person.id)["plot"])
        assert apart(town_phase(g, person.id), sky_phase(g, plot)) < 1.5, \
            "a town's hour is the Sun's, to within the hour it is told in"
    # the two stand at different longitudes, so it is not the same hour in both
    a, b = (json.loads(g._town_row(p.id)["plot"]) for p in people)
    want = ((a["lon"] - b["lon"]) / 360 * sun.LUNAR_DAY
            + (a["dark"] - b["dark"]) / -2)
    got = town_phase(g, people[0].id) - town_phase(g, people[1].id)
    assert apart(got, want) < 3
    assert g.db.execute("SELECT COALESCE(SUM(faults), 0) FROM town").fetchone()[0] == 0
    g.db.close()


@pytest.mark.usefixtures("one_sun")
def test_a_house_company_is_chartered_in_its_own_morning(routes):
    g = fresh(routes)
    for _ in range(12 * 24):
        g.step()
        if g.db.execute("SELECT COUNT(*) FROM player WHERE house = 1"
                        ).fetchone()[0] >= 2:
            break
    made = g.db.execute(
        "SELECT id, created_tick FROM player WHERE house = 1").fetchall()
    assert made, "no house company found its morning in twelve days"
    for row in made:
        plot = plots.plot_at(*HOUSE_PLACE[row["id"]])
        when = to_jd(g.sky_time(row["created_tick"]))
        assert sun.phase(plot["lon"], plot["dark"], when) <= plots.MORNING
    g.db.close()


@pytest.mark.usefixtures("real_ground", "one_sun")
def test_a_new_crew_waits_for_sunrise_or_takes_new_ground(routes):
    g = fresh(routes)
    person, _ = g.signup("Second Try Ltd")
    g.found_town(person)
    # the town's ground, moved to where it is the middle of the night
    jd = to_jd(g.sky_time())
    night = plots.plot_at(0.5, round((sun.subsolar_lon(jd) + 180 + 180) % 360 - 180, 1))
    assert not plots.in_morning(night, jd)
    lose(g, person.id, night)
    player = g.player(person.id)
    with pytest.raises(GameError, match=r"Sun rises there in \d+ hours, about \d+ minutes"):
        g.refound_town(player)
    meta = g.town_meta(player)
    hours = meta["relief"]["hours"]
    assert 0 < hours < sun.LUNAR_DAY
    assert meta["relief"]["minutes"] == round(hours / towngame.PACE)
    assert len(meta["offers"]) == 3
    want = meta["offers"][1]
    moved = g.refound_town(player, 0, (want["lat"], want["lon"]))
    assert (moved["plot"]["lat"], moved["plot"]["lon"]) == (want["lat"], want["lon"])
    assert moved["summary"]["phase"] == "playing" and "relief" not in moved
    assert town_phase(g, person.id) <= plots.MORNING + 1
    # and on ground that is in its morning, the crew goes to the company's own
    lose(g, person.id)
    again = g.refound_town(g.player(person.id))
    assert again["plot"] == moved["plot"]
    g.db.close()


# -- the move to the one Sun --------------------------------------------------------

def test_a_world_from_before_the_one_sun_has_its_batteries_filled_once(routes):
    g = fresh(routes)
    assert g.db.execute("SELECT 1 FROM world_meta WHERE key = 'one_sun'").fetchone(), \
        "a world founded under the one Sun has nothing to move"
    a, b = (g.signup(name)[0] for name in ("Old Town Co", "Older Town Co"))
    g.found_town(a)
    g.found_town(b)
    with_pad(g, b.id)
    for pid in (a.id, b.id):
        s = json.loads(g._town_row(pid)["state"])
        s["charge"] = 0
        g.db.execute("UPDATE town SET state = ? WHERE player_id = ?",
                     (json.dumps(s), pid))
    g.db.execute("DELETE FROM world_meta WHERE key = 'one_sun'")
    g.db.commit()
    minted = g.world.ledger.credits_in_existence()
    with g._mutation():
        g._to_one_sun()
    for pid in (a.id, b.id):
        s = json.loads(g._town_row(pid)["state"])
        assert s["charge"] == s["flows"]["battCap"] > 0
    assert g.world.ledger.credits_in_existence() == minted, "energy, not money"
    # a pad that already stood is past what the grant is for
    assert g._town_row(a.id)["pad_grant"] is None
    assert g._town_row(b.id)["pad_grant"] == 0
    # once
    s = json.loads(g._town_row(a.id)["state"])
    s["charge"] = 0
    g.db.execute("UPDATE town SET state = ? WHERE player_id = ?",
                 (json.dumps(s), a.id))
    g.db.commit()
    with g._mutation():
        g._to_one_sun()
    assert json.loads(g._town_row(a.id)["state"])["charge"] == 0
    g.db.close()


# -- the first pad ------------------------------------------------------------------

def grants(g, pid):
    return g.db.execute(
        "SELECT COUNT(*), COALESCE(SUM(p.amount), 0) FROM txn t JOIN posting p "
        "ON p.txn_id = t.id WHERE t.memo = 'first landing pad grant' "
        "AND p.account_id = ?", (g.player(pid).account,)).fetchone()


def test_the_first_landing_pad_is_paid_for_once_out_of_the_arks_fund(routes):
    g = fresh(routes)
    person, _ = g.signup("Pad One Ltd")
    g.found_town(person)
    g.step()
    assert tuple(grants(g, person.id)) == (0, 0), "nothing before there is a pad"
    assert g.town_meta(g.player(person.id))["pad_grant"] is None
    with_pad(g, person.id)
    fund, minted = g.world.ledger.balance(DEV_FUND, CREDIT), g.world.ledger.credits_in_existence()
    g.step()
    assert tuple(grants(g, person.id)) == (1, PAD_GRANT)
    assert g.world.ledger.balance(DEV_FUND, CREDIT) == fund - PAD_GRANT
    assert g.world.ledger.credits_in_existence() == minted, \
        "the grant is the fund's money, not new money"
    assert g.town_meta(g.player(person.id))["pad_grant"] == PAD_GRANT
    assert any(m["kind"] == "town_pad_grant" for m in g.inbox(g.player(person.id)))
    g.step()
    assert tuple(grants(g, person.id)) == (1, PAD_GRANT)
    # a second crew's pad is not a first pad
    lose(g, person.id)
    g.refound_town(g.player(person.id))
    with_pad(g, person.id)
    g.step()
    assert tuple(grants(g, person.id)) == (1, PAD_GRANT)
    g.world.ledger.assert_conserved()
    g.db.close()


def test_a_fund_that_cannot_pay_the_grant_owes_it_until_it_can(routes):
    g = fresh(routes)
    person, _ = g.signup("Pad Two Ltd")
    g.found_town(person)
    with_pad(g, person.id)
    held = g.world.ledger.balance(DEV_FUND, CREDIT)
    with g._mutation():
        g.world.ledger.burn(DEV_FUND, held - PAD_GRANT + 1, g.world.game_time(),
                            memo="test: an empty fund")
    g.step()
    assert tuple(grants(g, person.id)) == (0, 0)
    assert g._town_row(person.id)["pad_grant"] is None
    with g._mutation():
        g.world.ledger.mint(DEV_FUND, PAD_GRANT, g.world.game_time(),
                            memo="test: the fund refilled")
    g.step()
    assert tuple(grants(g, person.id)) == (1, PAD_GRANT)
    g.db.close()
