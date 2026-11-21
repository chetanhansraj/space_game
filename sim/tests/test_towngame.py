"""A town in the world: the city builder on one clock and one wallet.

What is being defended, worst first.

1. The town never creates a credit. What its rules pay it comes out of
   Earth's account; what it spends is burned or goes to the Ark's fund.
2. One clock. A town moves one game hour per world tick, no more, whoever
   asks and whatever they send.
3. One town failing does not stop the world.
4. It is the same game: the rules are the city builder's, not a copy.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from market.money import CREDIT

from sim import towngame
from sim.earth import ACCOUNT as EARTH
from sim.game import DEV_FUND, Game, GameError
from sim.persist import default_routes
from sim.town import Engine, TownError
from sim.towngame import KCR, TOWN_GRANT

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def routes():
    return default_routes()


@pytest.fixture
def game(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    yield g
    assert g.db.execute("SELECT COALESCE(SUM(faults), 0) FROM town"
                        ).fetchone()[0] == 0, "a town failed an hour"
    g.db.close()


@pytest.fixture
def town(game):
    player, _ = game.signup("Tranquility Co")
    game.found_town(player)
    return game.player(player.id)


def run(g, ticks):
    for _ in range(ticks):
        g.step()


def cash(g, account):
    return g.world.ledger.balance(account, CREDIT)


def state(g, player) -> dict:
    return json.loads(g.town_state(player))


def place(g, player, kind, near=(18, 18)):
    """Stand a building on the first tile near the lander the rules allow."""
    cx, cy = near
    tiles = sorted(((x, y) for x in range(4, 32) for y in range(4, 32)),
                   key=lambda t: abs(t[0] - cx) + abs(t[1] - cy))
    for x, y in tiles:
        try:
            g.town_intent(player, {"k": "place", "type": kind, "x": x, "y": y})
            return x, y
        except GameError:
            continue
    raise AssertionError(f"nowhere to stand a {kind}")


def minted(g):
    return g.world.ledger.credits_in_existence()


# -- founding -----------------------------------------------------------------------

def test_founding_lands_the_city_builders_crew_with_the_companys_wallet(game):
    player, _ = game.signup("Tranquility Co")
    fund, made, before = cash(game, DEV_FUND), minted(game), cash(game, player.account)
    meta = game.found_town(player)
    s = state(game, player)
    assert [c["name"] for c in s["crew"]] == [
        "Asha Rao", "Kenji Mori", "Lena Okafor", "Rafael Costa"]
    assert s["t"] == 0 and s["phase"] == "playing" and s["size"] == 36
    assert [b["type"] for b in s["buildings"]] == ["lander"]
    # The grant is a transfer from the fund, and the town holds no money.
    assert cash(game, player.account) == before + TOWN_GRANT
    assert cash(game, DEV_FUND) == fund - TOWN_GRANT and minted(game) == made
    assert s["materials"] == pytest.approx((before + TOWN_GRANT) / KCR)
    assert meta["founded"] and meta["summary"]["population"] == 4
    assert meta["trade"] == {"open": False, "pad": False, "population": 4}
    assert "town_charter" in [m["kind"] for m in game.inbox(player)]


def test_one_town_per_company(game, town):
    with pytest.raises(GameError, match="already"):
        game.found_town(town)
    other, _ = game.signup("Second Co")
    with pytest.raises(GameError, match="not founded"):
        game.town_intent(other, {"k": "price", "level": 1})
    assert game.town_meta(other)["founded"] is False
    assert game.town_state(other) is None


def test_two_companies_get_different_ground(game, town):
    other, _ = game.signup("Second Co")
    game.found_town(other)
    assert state(game, town)["ground"] != state(game, other)["ground"]


# -- one clock ----------------------------------------------------------------------

def test_a_town_moves_one_hour_a_tick_and_only_with_the_world(game, town):
    assert state(game, town)["t"] == 0
    run(game, 5)
    assert state(game, town)["t"] == pytest.approx(5.0)
    # Nothing a player can send moves the clock.
    place(game, town, "solar")
    game.town_intent(town, {"k": "price", "level": 2})
    assert state(game, town)["t"] == pytest.approx(5.0)
    for bad in ({"k": "tick"}, {"k": "skip", "hours": 100},
                {"k": "place", "type": "lander", "x": 3, "y": 3},
                {"k": "place", "type": "__proto__", "x": 3, "y": 3}):
        with pytest.raises(GameError):
            game.town_intent(town, bad)
    assert state(game, town)["t"] == pytest.approx(5.0)
    run(game, 1)
    assert state(game, town)["t"] == pytest.approx(6.0)


def test_a_town_runs_whether_or_not_anyone_is_there(game, town):
    """Left alone, the lander's canisters run out and the crew are lost."""
    run(game, 230)
    meta = game.town_meta(town)
    assert meta["summary"]["phase"] == "lost" and meta["summary"]["crew"] == 0
    assert "town_lost" in [m["kind"] for m in game.inbox(town)]
    frozen = game.town_state(town)
    run(game, 5)
    assert game.town_state(town) == frozen          # a silent town stays so
    with pytest.raises(GameError, match="over"):
        game.town_intent(town, {"k": "price", "level": 1})
    game.refound_town(town)
    s = state(game, town)
    assert s["t"] == 0 and s["phase"] == "playing" and len(s["crew"]) == 4
    run(game, 3)
    assert state(game, town)["t"] == pytest.approx(3.0)
    with pytest.raises(GameError, match="still alive"):
        game.refound_town(town)


# -- one wallet ---------------------------------------------------------------------

def test_building_spends_the_companys_credits_into_the_arks_fund(game, town):
    before, fund, made = cash(game, town.account), cash(game, DEV_FUND), minted(game)
    place(game, town, "solar")                       # 12 town credits
    assert cash(game, town.account) == before - 12 * KCR
    assert cash(game, DEV_FUND) == fund + 12 * KCR and minted(game) == made
    s = state(game, town)
    uid = next(b["uid"] for b in s["buildings"] if b["type"] == "solar")
    game.town_intent(town, {"k": "demolish", "uid": uid})   # refunded in full
    assert cash(game, town.account) == before and cash(game, DEV_FUND) == fund


def test_the_town_cannot_spend_what_the_company_has_not_got(game, town):
    ledger = game.world.ledger
    ledger.transfer(town.account, DEV_FUND, CREDIT,
                    cash(game, town.account) - 5 * KCR, kind="test",
                    game_time=game.world.game_time())
    reasons = set()
    for x in range(6, 30, 2):
        for y in range(6, 30, 2):
            with pytest.raises(GameError) as refused:
                game.town_intent(town, {"k": "place", "type": "solar",
                                        "x": x, "y": y})
            reasons.add(str(refused.value))
    assert any("credits" in r for r in reasons), reasons
    assert cash(game, town.account) == 5 * KCR


def test_what_a_ship_earns_the_town_can_spend(game, town):
    """One wallet: credits from anywhere are the town's to build with."""
    ledger = game.world.ledger
    ledger.transfer(DEV_FUND, town.account, CREDIT, 500 * KCR, kind="test",
                    game_time=game.world.game_time())
    run(game, 1)
    assert state(game, town)["materials"] == pytest.approx(
        cash(game, town.account) / KCR, abs=0.01)
    place(game, town, "reactor")                     # 180 town credits


def test_town_income_is_earths_money_and_town_costs_are_burned(game, town):
    """Every credit the rules pay or charge is a real posting, to the credit."""
    ledger = game.world.ledger
    made = minted(game)
    for kind in ("solar", "solar", "o2plant"):
        place(game, town, kind)
    mark = game.db.execute("SELECT COALESCE(MAX(id), 0) FROM txn").fetchone()[0]
    wallet = cash(game, town.account)
    run(game, 48)
    kinds = dict(game.db.execute(
        "SELECT t.kind, SUM(p.amount) FROM posting p JOIN txn t "
        "ON t.id = p.txn_id WHERE p.account_id = ? AND p.asset = ? "
        "AND t.id > ? GROUP BY t.kind", (town.account, CREDIT, mark)).fetchall())
    # The town is paid only by transfers from Earth, and charged only by burns.
    assert set(kinds) <= {"town_income", "sink"}
    assert kinds.get("town_income", 0) > 0
    paid_by = dict(game.db.execute(
        "SELECT p.account_id, SUM(p.amount) FROM posting p JOIN txn t "
        "ON t.id = p.txn_id WHERE t.kind = 'town_income' AND t.id > ? "
        "GROUP BY p.account_id", (mark,)).fetchall())
    # Earth is the only payer, of this town and of any the world runs.
    assert paid_by[town.account] == kinds["town_income"]
    assert [a for a, n in paid_by.items() if n < 0] == [EARTH]
    assert sum(paid_by.values()) == 0
    assert cash(game, town.account) - wallet == sum(kinds.values())
    assert minted(game) == made
    # And the town's own count of its money is the ledger's. The ship's
    # daily upkeep (400 cr) is taken after the town's hour at midnight, so
    # the town sees it an hour later.
    assert state(game, town)["materials"] == pytest.approx(
        cash(game, town.account) / KCR, abs=0.402)
    ledger.assert_conserved()
    assert ledger.verify_checkpoints() == []


def test_a_town_that_cannot_pay_owes_and_its_rules_see_the_debt(game, town):
    """The ledger never goes below zero; the shortfall is owed and settles."""
    ledger = game.world.ledger
    now = game.world.game_time()
    ledger.transfer(town.account, DEV_FUND, CREDIT,
                    cash(game, town.account) - 2 * KCR, kind="test",
                    game_time=now)
    burned = ledger.credits_destroyed()
    # The rules charged six town credits; the company has two.
    owed, carry = game._town_settle(town, 2.0, -4.0, 0, 0.0, now,
                                    building=False)
    assert owed == 4 * KCR and carry == 0
    assert cash(game, town.account) == 0
    assert ledger.credits_destroyed() == burned + 2 * KCR
    game.db.execute("UPDATE town SET owed = ?", (owed,))
    assert game._town_wallet(town, owed) == -4.0
    run(game, 1)
    assert state(game, town)["materials"] < 0       # the rules know
    # Whatever the company earns next goes to the debt first.
    ledger.transfer(DEV_FUND, town.account, CREDIT, 50 * KCR, kind="test",
                    game_time=game.world.game_time())
    still = game.db.execute("SELECT owed FROM town").fetchone()["owed"]
    assert 0 < still <= 4 * KCR + 1 * KCR
    run(game, 1)
    assert game.db.execute("SELECT owed FROM town").fetchone()["owed"] == 0
    assert 50 * KCR - still - KCR <= cash(game, town.account) <= 50 * KCR


def test_fractions_of_a_credit_are_carried_not_lost(game, town):
    now = game.world.game_time()
    before = cash(game, town.account)
    owed, carry = 0, 0.0
    for _ in range(10):                              # 0.0003 town credits a go
        owed, carry = game._town_settle(town, 1.0, 1.0003, owed, carry, now,
                                        building=False)
    # Ten times 0.3 of a credit is three credits, in the account or carried.
    assert cash(game, town.account) - before + carry == pytest.approx(3.0)
    assert cash(game, town.account) - before in (2, 3)


# -- survival of the world ----------------------------------------------------------

def test_a_town_that_breaks_loses_its_own_hour_and_the_world_goes_on(
        game, town, monkeypatch):
    run(game, 3)
    saved, purse, tick = game.town_state(town), cash(game, town.account), game.world.tick

    def broken(*a, **kw):
        raise TownError("the engine fell over")

    monkeypatch.setattr(game.town_engine, "tick", broken)
    game.step()
    assert game.world.tick == tick + 1
    row = game.db.execute("SELECT faults, state FROM town").fetchone()
    assert row["faults"] == 1 and row["state"] == saved
    assert cash(game, town.account) == purse
    monkeypatch.undo()
    game.db.execute("UPDATE town SET faults = 0")
    game.step()
    assert state(game, town)["t"] == pytest.approx(4.0)   # one hour was lost


def test_a_town_survives_a_restart(routes, tmp_path):
    path = str(tmp_path / "world.db")
    g = Game.open(path, now=T0, routes=routes)
    player, _ = g.signup("Tranquility Co")
    g.found_town(player)
    place(g, player, "solar")
    run(g, 6)
    before = g.town_state(player)
    g.db.close()
    g = Game.open(path, routes=routes)
    player = g.player(player.id)
    assert g.town_state(player) == before
    run(g, 2)
    assert json.loads(g.town_state(player))["t"] == pytest.approx(8.0)
    g.db.close()


# -- the same game ------------------------------------------------------------------

def test_the_engine_is_deterministic():
    a, b = Engine(), Engine()
    one, two = a.create(77, 160), b.create(77, 160)
    assert one.state == two.state
    for _ in range(50):
        one, two = a.tick(one.state, 1.0, one.credits), b.tick(two.state, 1.0, two.credits)
    assert one.state == two.state and one.credits == two.credits


def test_the_engine_recovers_from_a_failure():
    e = Engine()
    made = e.create(5, 160)
    with pytest.raises(TownError):
        e.tick("{not json", 1.0, 160)
    again = e.tick(made.state, 1.0, 160)            # rebuilt, and working
    assert again.summary["t"] == pytest.approx(1.0)


def test_trade_opens_with_a_pad_and_eight_people(game, town):
    meta = game.town_meta(town)
    assert meta["trade"]["open"] is False
    s = state(game, town)
    s["residents"] = 6
    s["buildings"].append({**s["buildings"][0], "uid": 999, "type": "pad",
                           "progress": 1, "connected": True, "damaged": False})
    game.db.execute("UPDATE town SET state = ?", (json.dumps(s),))
    trade = game.town_meta(town)["trade"]
    assert trade == {"open": True, "pad": True, "population": 10}


def test_an_old_company_with_nothing_left_can_still_found_a_town(game):
    """The live world's first company: no money, and weeks of unpaid fees."""
    from sim.game import ARREARS_CAP
    player, _ = game.signup("Back Again")
    with game._mutation():
        game.world.ledger.burn(player.account, cash(game, player.account),
                               game.world.game_time(), memo="test: ruin")
    game.db.execute("UPDATE player SET upkeep_owed = 1000000 WHERE id = ?",
                    (player.id,))
    player = game.player(player.id)
    fund, made = cash(game, DEV_FUND), minted(game)
    meta = game.found_town(player)
    grant = towngame.TOWN_START + ARREARS_CAP
    assert cash(game, DEV_FUND) == fund - grant           # paid, not minted
    assert minted(game) == made
    assert meta["wallet"] * KCR == grant
    while game.world.tick % 24 != 23:
        game.step()
    game.step()                                           # the first midnight
    me = game.player(player.id)
    assert me.upkeep_owed == 0
    # what is left is the start the game was balanced for, less a day's
    # costs and whatever the first hours earned
    assert meta_wallet(game, me) >= 150


def test_a_rich_company_gets_the_ordinary_grant_and_no_more(game):
    player, _ = game.signup("Old Money")
    with game._mutation():
        game.world.ledger.transfer(DEV_FUND, player.account, CREDIT, 500_000,
                                   kind="grant",
                                   game_time=game.world.game_time(),
                                   memo="test: a good year of trading")
    before = cash(game, player.account)
    game.found_town(game.player(player.id))
    assert cash(game, player.account) == before + TOWN_GRANT


def meta_wallet(g, player) -> float:
    return g.town_meta(player)["wallet"]


def test_a_new_crew_lands_with_stores_when_the_company_has_nothing(game):
    """How the first town on the live world ended, and what follows it."""
    from sim.game import ARREARS_CAP
    player, _ = game.signup("Second Wind")
    game.found_town(player)
    run(game, 230)                                        # nobody came
    assert game.town_meta(player)["summary"]["phase"] == "lost"
    with game._mutation():
        game.world.ledger.burn(player.account, cash(game, player.account),
                               game.world.game_time(), memo="test: ruin")
    game.db.execute("UPDATE player SET upkeep_owed = 1000000 WHERE id = ?",
                    (player.id,))
    game.db.execute("UPDATE town SET owed = 55000, caretaker = 1 "
                    "WHERE player_id = ?", (player.id,))
    player = game.player(player.id)
    fund, made = cash(game, DEV_FUND), minted(game)
    meta = game.refound_town(player)
    relief = towngame.TOWN_START + ARREARS_CAP
    assert cash(game, DEV_FUND) == fund - relief          # paid, not minted
    assert minted(game) == made
    assert meta["owed"] == 0 and meta["caretaker"]["on"] is False
    assert meta["wallet"] * KCR == relief
    assert meta["summary"]["phase"] == "playing" and meta["summary"]["t"] == 0
    assert "town_relief" in [m["kind"] for m in game.inbox(player)]
    while game.world.tick % 24 != 23:
        game.step()
    game.step()                                           # the first midnight
    assert game.player(player.id).upkeep_owed == 0
    assert meta_wallet(game, game.player(player.id)) >= 150


def test_a_new_crew_is_paid_for_by_a_company_that_can_afford_one(game):
    player, _ = game.signup("Deep Pockets")
    game.found_town(player)
    run(game, 230)
    with game._mutation():
        game.world.ledger.transfer(DEV_FUND, player.account, CREDIT, 400_000,
                                   kind="grant",
                                   game_time=game.world.game_time(),
                                   memo="test: other business went well")
    fund, before = cash(game, DEV_FUND), cash(game, player.account)
    game.refound_town(game.player(player.id))
    assert cash(game, DEV_FUND) == fund                   # nothing given
    assert cash(game, player.account) == before

