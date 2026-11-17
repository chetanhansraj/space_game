"""Towns the world runs (D81).

A house company is an ordinary company with the steward at the controls.
These tests hold it to that: the same charter, the same grant, the same
rules, no money from nowhere, and a world that replays the same way.
"""
from __future__ import annotations

import datetime as dt

import pytest

from market.money import CREDIT
from sim import towngame
from sim.earth import ACCOUNT as EARTH
from sim.game import DEV_FUND, STARTING_GRANT, Game, GameError
from sim.persist import default_routes
from sim.towngame import (HOUSE, HOUSE_EVERY_DAYS, HOUSE_RECALL_DEBT,
                          HOUSE_RETURN_DAYS, TOWN_START, TRADE_POPULATION)

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
DAY = 24


@pytest.fixture(scope="module")
def routes():
    return default_routes()


def fresh(routes):
    return Game.open(":memory:", now=T0, routes=routes)


def run(g, ticks):
    for _ in range(ticks):
        g.step()


def to_next_day(g):
    """Step to the next hour on which the world does its daily business."""
    g.step()
    while g.world.tick % DAY:
        g.step()


def house(g):
    return [r["id"] for r in g.db.execute(
        "SELECT id FROM player WHERE house = 1 ORDER BY created_tick")]


def cash(g, account):
    return g.world.ledger.balance(account, CREDIT)


def events(g, kind):
    return [dict(r) for r in g.db.execute(
        "SELECT subject, detail FROM event_log WHERE kind = ?", (kind,))]


@pytest.fixture(scope="module")
def moon(routes):
    """A world left alone for eleven game days. Read only."""
    g = fresh(routes)
    g.minted_at_start = g.world.ledger.credits_in_existence()
    run(g, 11 * DAY)
    yield g
    g.db.close()


# -- chartering -----------------------------------------------------------------------

def test_the_world_charters_its_companies_one_at_a_time(routes):
    g = fresh(routes)
    assert house(g) == []
    to_next_day(g)
    assert house(g) == [HOUSE[0][0]]
    for _ in range(HOUSE_EVERY_DAYS - 1):
        to_next_day(g)
        assert len(house(g)) == 1, "the next one waits its turn"
    to_next_day(g)
    assert house(g) == [HOUSE[0][0], HOUSE[1][0]]
    g.db.close()


def test_a_house_company_is_chartered_exactly_as_a_person_is(routes):
    """Same fund, same grant, same ship, same town. Nothing extra."""
    g = fresh(routes)
    made = g.world.ledger.credits_in_existence()
    to_next_day(g)
    pid, name = HOUSE[0]
    mare = g.player(pid)
    assert mare.house and mare.name == name
    person, _ = g.signup("A Person Ltd")
    g.found_town(person)

    def granted(account):
        return g.db.execute(
            "SELECT p.asset, SUM(p.amount), COUNT(*) FROM posting p "
            "JOIN txn t ON t.id = p.txn_id WHERE p.account_id = ? "
            "AND t.kind = 'grant' GROUP BY p.asset ORDER BY p.asset",
            (account,)).fetchall()

    theirs, ours = granted(mare.account), granted(person.account)
    assert [tuple(r) for r in theirs] == [tuple(r) for r in ours]
    assert dict((r[0], r[1]) for r in theirs)[CREDIT] == max(
        TOWN_START, STARTING_GRANT + towngame.TOWN_GRANT)
    # and it has already begun to spend it, through the burn like anyone
    assert cash(g, mare.account) < cash(g, person.account)
    assert g.ship_of(mare).ship_class == g.ship_of(g.player(person.id)).ship_class
    assert g.world.ledger.credits_in_existence() == made
    g.world.ledger.assert_conserved()
    said = [e["subject"] for e in events(g, "player_joined")]
    assert pid in said and events(g, "town_founded")[0]["subject"] == pid
    g.db.close()


def test_nobody_can_sign_in_as_a_house_company(routes):
    g = fresh(routes)
    to_next_day(g)
    pid = HOUSE[0][0]
    stored = g.db.execute("SELECT token_hash FROM player WHERE id = ?",
                          (pid,)).fetchone()[0]
    for guess in (stored, pid, f"house:{pid}", ""):
        found = g.authenticate(guess)
        assert found is None or found.id != pid
    g.db.close()


def test_a_name_somebody_already_holds_is_left_to_them(routes):
    g = fresh(routes)
    person, _ = g.signup(HOUSE[0][1])
    to_next_day(g)
    assert house(g) == [HOUSE[1][0]]
    assert not g.player(person.id).house
    g.db.close()


def test_a_fund_that_cannot_charter_charters_nobody(routes):
    g = fresh(routes)
    ledger = g.world.ledger
    ledger.transfer(DEV_FUND, EARTH, CREDIT, cash(g, DEV_FUND) - 1000,
                    kind="test", game_time=g.world.game_time())
    made = ledger.credits_in_existence()
    to_next_day(g)
    assert house(g) == []
    assert ledger.credits_in_existence() == made
    assert g.db.execute("SELECT COUNT(*) FROM town").fetchone()[0] == 0
    g.db.close()


def test_a_world_read_back_from_disk_still_has_them(routes, tmp_path):
    path = str(tmp_path / "moon.db")
    g = Game.open(path, now=T0, routes=routes)
    to_next_day(g)
    pid = HOUSE[0][0]
    tick, ships = g.world.tick, len(g.world.ships)
    g.db.close()
    g = Game.open(path, routes=routes)
    assert g.world.tick == tick and len(g.world.ships) == ships
    assert g.ship_of(g.player(pid)).owner == pid
    run(g, HOUSE_EVERY_DAYS * DAY)
    assert house(g) == [HOUSE[0][0], HOUSE[1][0]], "one each, never twice"
    assert g.db.execute("SELECT COALESCE(SUM(faults), 0) FROM town"
                        ).fetchone()[0] == 0
    g.db.close()


def test_a_person_is_not_a_house_company(routes):
    g = fresh(routes)
    person, _ = g.signup("Only Human Co")
    assert g.player(person.id).house is False
    assert g.world_view()["house_companies"] == 0
    g.db.close()


# -- playing --------------------------------------------------------------------------

def test_the_steward_plays_them_and_they_grow(moon):
    towns = {r["player_id"]: r for r in moon.db.execute("SELECT * FROM town")}
    assert set(towns) == set(house(moon)) and len(towns) >= 5
    first = moon.town_engine.summary(towns[HOUSE[0][0]]["state"])
    assert first["phase"] == "playing" and first["buildings"] > 10
    assert first["population"] >= TRADE_POPULATION
    assert sum(r["faults"] for r in towns.values()) == 0


def test_what_they_have_they_were_given_by_the_fund_or_paid_by_a_buyer(moon):
    """Invariant 3. A house company's credits all come from somewhere real."""
    ledger = moon.world.ledger
    assert ledger.credits_in_existence() == moon.minted_at_start
    ledger.assert_conserved()
    for pid in house(moon):
        kinds = {r[0] for r in moon.db.execute(
            "SELECT DISTINCT t.kind FROM posting p JOIN txn t "
            "ON t.id = p.txn_id WHERE p.account_id = ? AND p.asset = ? "
            "AND p.amount > 0", (f"player:{pid}", CREDIT))}
        assert kinds <= {"grant", "town_income", "sweep"}, (pid, kinds)


def test_a_town_that_grows_is_news_and_so_is_its_first_sale(moon):
    pid = HOUSE[0][0]
    grew = [e for e in events(moon, "town_grew") if e["subject"] == pid]
    assert grew and "base" in grew[0]["detail"]
    assert any(e["subject"] == pid for e in events(moon, "town_first_sale"))
    assert any(e["kind"] == "town_grew" for e in moon.feed(limit=200))


def test_every_town_is_listed_most_people_first(moon):
    league = moon.towns_view()
    assert len(league) == len(house(moon))
    assert all(t["house"] and not t["lost"] for t in league)
    people = [t["population"] for t in league]
    assert people == sorted(people, reverse=True)
    assert league[0]["company"] == HOUSE[0][1] and league[0]["sold_t"] >= 1
    assert moon.world_view()["house_companies"] == len(league)


def test_a_person_sees_the_same_list_with_their_own_town_in_it(routes):
    g = fresh(routes)
    person, _ = g.signup("Tranquility Co")
    meta = g.found_town(person)
    assert [t["company"] for t in meta["league"]] == ["Tranquility Co"]
    assert meta["league"][0]["house"] is False
    to_next_day(g)
    meta = g.town_meta(g.player(person.id))
    assert {t["company"] for t in meta["league"]} == {"Tranquility Co",
                                                      HOUSE[0][1]}
    g.db.close()


def test_the_same_world_founds_the_same_towns(routes):
    """Seeded and replayable: two worlds left alone are the same world."""
    states = []
    for _ in range(2):
        g = fresh(routes)
        run(g, 4 * DAY)
        states.append([(r["player_id"], r["seed"], r["state"], r["yard"])
                       for r in g.db.execute(
                           "SELECT * FROM town ORDER BY player_id")])
        g.db.close()
    assert states[0] == states[1] and len(states[0]) == 2


# -- losing one -----------------------------------------------------------------------

def test_a_lost_house_town_gets_a_new_crew_only_after_the_wait(routes):
    g = fresh(routes)
    to_next_day(g)
    pid = HOUSE[0][0]
    run(g, 3)
    made = g.world.ledger.credits_in_existence()
    g.db.execute("UPDATE town SET lost_tick = ?, owed = 5000 "
                 "WHERE player_id = ?", (g.world.tick, pid))
    g.db.commit()
    lost_at = g.world.tick
    while g.world.tick - lost_at < HOUSE_RETURN_DAYS * DAY - 1:
        g.step()
        row = g.db.execute("SELECT * FROM town WHERE player_id = ?",
                           (pid,)).fetchone()
        assert row["lost_tick"] == lost_at and row["attempt"] == 0
    to_next_day(g)
    row = g.db.execute("SELECT * FROM town WHERE player_id = ?",
                       (pid,)).fetchone()
    assert row["lost_tick"] is None and row["attempt"] == 1
    assert row["owed"] < 5000, "what the lost town owed was written off"
    assert g.world.ledger.credits_in_existence() == made
    assert any("new crew" in e["detail"] for e in events(g, "town_founded"))
    listed = {t["company"]: t for t in g.towns_view()}[HOUSE[0][1]]
    assert listed["crews"] == 2 and not listed["lost"]
    g.db.close()


def test_a_house_company_recalls_a_crew_from_a_town_past_saving(routes):
    """Owing more than a new town costs, with no other business to pay it
    from, the company gives the town up. A person's town is never recalled."""
    g = fresh(routes)
    person, _ = g.signup("Tranquility Co")
    g.found_town(person)
    to_next_day(g)
    pid = HOUSE[0][0]
    g.db.execute("UPDATE town SET owed = ?", (HOUSE_RECALL_DEBT,))
    g.db.commit()
    to_next_day(g)
    assert g.db.execute("SELECT COUNT(*) FROM town WHERE lost_tick IS NOT NULL"
                        ).fetchone()[0] == 0, "at the line is not past it"
    g.db.execute("UPDATE town SET owed = ?", (HOUSE_RECALL_DEBT + 50_000,))
    g.db.commit()
    to_next_day(g)
    lost = [r["player_id"] for r in g.db.execute(
        "SELECT player_id FROM town WHERE lost_tick IS NOT NULL")]
    assert lost == [pid]
    assert any("recalled" in e["detail"] and e["subject"] == pid
               for e in events(g, "town_lost"))
    listed = {t["company"]: t for t in g.towns_view()}
    assert listed[HOUSE[0][1]]["lost"] and listed[HOUSE[0][1]]["population"] == 0
    assert not listed["Tranquility Co"]["lost"]
    g.db.close()


def test_a_person_cannot_send_a_crew_to_a_living_town_still(routes):
    g = fresh(routes)
    person, _ = g.signup("Tranquility Co")
    g.found_town(person)
    with pytest.raises(GameError):
        g.refound_town(g.player(person.id))
    g.db.close()
