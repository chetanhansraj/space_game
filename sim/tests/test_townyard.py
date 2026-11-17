"""A town's yard: what its foundries make is cargo, and cargo is sold.

What is being defended, worst first.

1. Making goods makes no money. A foundry's hour puts kilograms in the yard
   and not one credit anywhere. Credits arrive only when a buyer with money
   of its own pays for the goods, and exactly as many as it paid.
2. Nothing leaves the yard until the town has earned the market: a landing
   pad and eight people.
3. A yard that is full stops the foundries. Unsold goods are not quietly
   thrown away and are not quietly paid for.
4. The owner's instruction is kept: hold means hold, and a floor is a floor.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil

import pytest

from market.money import CREDIT

from sim.earth import ACCOUNT as EARTH
from sim.game import Game, GameError
from sim.persist import default_routes
from sim.town import Engine
from sim.towngame import (TOWN_NODE, TRADE_POPULATION, YARD_ASSET, YARD_KG)

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
TONNE = 1_000
ANCHOR = 45_000


@pytest.fixture(scope="module")
def routes():
    return default_routes()


def steward_hour(g, player):
    """Do what a careful player would this hour, through the player's door."""
    row = g._town_row(player.id)
    for intent in g.town_engine.steward(
            row["state"], g._town_wallet(player, row["owed"])):
        try:
            g.town_intent(player, intent)
        except GameError:
            pass


def play(g, player, hours):
    for _ in range(hours):
        steward_hour(g, player)
        g.step()


@pytest.fixture(scope="module")
def played(tmp_path_factory, routes):
    """A world file holding one town, played to the morning it can trade.

    Played once and copied for each test, because growing a town takes
    hundreds of real hours of rules and every test wants to start from one.
    """
    path = tmp_path_factory.mktemp("yard") / "played.db"
    g = Game.open(str(path), now=T0, routes=routes)
    player, _ = g.signup("Foundry Row")
    g.found_town(player)
    for _ in range(40):
        play(g, player, 10)
        if g.town_meta(player)["trade"]["open"]:
            break
    meta = g.town_meta(player)
    assert meta["trade"]["open"], "the steward never opened trade"
    assert meta["summary"]["foundries"] >= 1
    g.db.close()
    return str(path), player.id


@pytest.fixture
def town(played, tmp_path, routes):
    path, pid = played
    copy = str(tmp_path / "world.db")
    shutil.copy(path, copy)
    g = Game.open(copy, routes=routes)
    yield g, g.player(pid)
    assert g.db.execute("SELECT COALESCE(SUM(faults), 0) FROM town"
                        ).fetchone()[0] == 0, "a town failed an hour"
    g.db.close()


def yard(g, player) -> dict:
    return g.town_meta(player)["yard"]


def goods(g, account) -> int:
    return g.world.ledger.balance(account, YARD_ASSET)


def cash(g, account) -> int:
    return g.world.ledger.balance(account, CREDIT)


def stock(g, player, kg):
    """Put goods in the yard, as a foundry would, without waiting for one."""
    account = g._yard_account(player)
    with g._mutation():
        g.world.ledger.extract(account, YARD_ASSET, kg, g.world.game_time(),
                               memo="test stock")
    return account


def state(g, player) -> dict:
    return json.loads(g.town_state(player))


# -- making -------------------------------------------------------------------------

def test_foundries_make_goods_and_earth_no_longer_pays_for_them(town):
    g, player = town
    y, s = yard(g, player), state(g, player)
    assert y["made_kg"] > 0
    # the rules' own account of income has nothing under foundries
    assert s["flows"]["earn"]["foundry"] == 0
    assert s["cargo"]["cap"] == YARD_KG
    # every kilogram ever in the yard came out of the ground, on the ledger
    account = f"town:{player.id}"
    extracted = g.db.execute(
        "SELECT COALESCE(SUM(p.amount), 0) FROM posting p JOIN txn t "
        "ON t.id = p.txn_id WHERE p.account_id = ? AND p.asset = ? "
        "AND t.kind = 'extraction'", (account, YARD_ASSET)).fetchone()[0]
    assert extracted == y["made_kg"]
    assert y["held_kg"] == y["made_kg"] - y["sold_kg"]


def test_an_hour_of_foundry_work_creates_no_credit(town):
    g, player = town
    g.town_policy(player, False, ANCHOR)          # hold, so nothing is sold
    made = g.world.ledger.credits_in_existence()
    before = yard(g, player)
    for _ in range(12):
        g.step()
    after = yard(g, player)
    assert after["made_kg"] > before["made_kg"]
    assert after["sold_kg"] == before["sold_kg"]
    assert g.world.ledger.credits_in_existence() == made
    # and the yard account itself never holds money
    assert cash(g, f"town:{player.id}") == 0


def test_a_fraction_of_a_kilogram_is_carried_not_lost(town):
    g, player = town
    g.town_policy(player, False, ANCHOR)
    rate = state(g, player)["flows"]["make"]
    assert rate > 0 and rate != int(rate), "want a rate that is not whole"
    before = yard(g, player)["made_kg"]
    hours = 10
    for _ in range(hours):
        g.step()
    made = yard(g, player)["made_kg"] - before
    part = state(g, player)["cargo"]["made"]
    assert 0 <= part < 1
    # over ten hours the yard is within a kilogram or two of rate x hours,
    # not ten truncations short of it
    assert made >= int(rate * hours * 0.8)


def test_a_full_yard_stops_the_foundries_and_sends_the_shift_home(town):
    g, player = town
    g.town_policy(player, False, ANCHOR)
    jobs = state(g, player)["flows"]["jobs"]
    account = stock(g, player, YARD_KG - goods(g, f"town:{player.id}"))
    made = yard(g, player)["made_kg"]
    for _ in range(3):
        g.step()
    s = state(g, player)
    assert goods(g, account) == YARD_KG                 # not a gram over
    assert yard(g, player)["made_kg"] == made
    assert s["flows"]["yardFull"] and s["flows"]["make"] == 0
    assert s["flows"]["jobs"] < jobs                    # the shift went home
    assert yard(g, player)["full"]


# -- the gate -----------------------------------------------------------------------

def test_nothing_leaves_the_yard_before_the_town_can_trade(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    player, _ = g.signup("Early Days")
    g.found_town(player)
    player = g.player(player.id)
    account = stock(g, player, 3 * TONNE)
    assert not g.town_meta(player)["trade"]["open"]
    with pytest.raises(GameError, match=f"landing pad and {TRADE_POPULATION}"):
        g.town_sell(player, 1, ANCHOR)
    with pytest.raises(GameError, match="landing pad"):
        g.town_load(player, 1)
    for _ in range(12):                 # the standing order is on by default
        g.step()
    assert g.world.books[TOWN_NODE].best_bid(YARD_ASSET) is not None
    assert goods(g, account) >= 3 * TONNE
    assert yard(g, player)["sold_kg"] == 0
    g.db.close()


# -- selling ------------------------------------------------------------------------

def test_a_sale_is_paid_by_the_buyer_and_by_nobody_else(town):
    g, player = town
    g.town_policy(player, False, ANCHOR)
    account = stock(g, player, 3 * TONNE)
    held = goods(g, account)
    bid = g.world.books[TOWN_NODE].best_bid(YARD_ASSET)
    assert bid is not None and bid >= ANCHOR
    made, burned = (g.world.ledger.credits_in_existence(),
                    g.world.ledger.credits_destroyed())
    wallet = cash(g, player.account)
    reply = g.town_sell(player, 1, ANCHOR)
    report = reply["report"]
    assert report["kg"] == TONNE and report["value"] >= ANCHOR
    assert cash(g, player.account) == wallet + report["value"]
    assert goods(g, account) == held - TONNE
    assert cash(g, account) == 0
    assert g.world.ledger.credits_in_existence() == made
    assert g.world.ledger.credits_destroyed() == burned
    g.world.ledger.assert_conserved()
    y = yard(g, player)
    assert y["sold_today"] >= TONNE and y["sales_today"] >= report["value"]


def test_the_standing_order_sells_whole_tonnes_while_the_owner_is_away(town):
    g, player = town
    account = stock(g, player, 2 * TONNE)
    sold, wallet = yard(g, player)["sold_kg"], cash(g, player.account)
    for _ in range(8):
        g.step()
    y = yard(g, player)
    assert y["sold_kg"] >= sold + TONNE
    assert y["sold_kg"] % TONNE == 0
    assert y["sales"] > 0 and y["last"] is not None
    assert goods(g, account) == y["made_kg"] + 2 * TONNE - y["sold_kg"]


def test_hold_means_hold_and_a_floor_is_a_floor(town):
    g, player = town
    account = stock(g, player, 2 * TONNE)
    held, sold = goods(g, account), yard(g, player)["sold_kg"]
    g.town_policy(player, False, ANCHOR)
    for _ in range(8):
        g.step()
    assert yard(g, player)["sold_kg"] == sold and goods(g, account) >= held

    bid = g.world.books[TOWN_NODE].best_bid(YARD_ASSET)
    g.town_policy(player, True, bid * 3)                # nobody pays this
    for _ in range(8):
        g.step()
    assert yard(g, player)["sold_kg"] == sold
    report = g.town_sell(player, 1, bid * 3)["report"]  # nor by hand
    assert report["kg"] == 0

    g.town_policy(player, True, ANCHOR)
    for _ in range(8):
        g.step()
    assert yard(g, player)["sold_kg"] > sold


def test_selling_more_than_the_yard_holds_is_refused(town):
    g, player = town
    with pytest.raises(GameError, match="yard holds"):
        g.town_sell(player, 500, ANCHOR)
    with pytest.raises(GameError):
        g.town_sell(player, 0, ANCHOR)
    with pytest.raises(GameError):
        g.town_policy(player, "yes", ANCHOR)


def test_earth_takes_parts_at_the_anchor_and_no_more_than_its_order(town):
    g, player = town
    # leave only Earth on the bid side: households pay more when they can
    book = g.world.books[TOWN_NODE]
    while g.world.tick % 6:
        g.step()
    for firm in g.world.firms:
        firm.also_consumes = None
    for _ in range(6):
        g.step()
    assert book.best_bid(YARD_ASSET) == ANCHOR
    g.town_policy(player, False, ANCHOR)
    stock(g, player, YARD_KG - goods(g, f"town:{player.id}"))
    earth_cash, earth_goods = cash(g, EARTH), goods(g, EARTH)
    report = g.town_sell(player, 10, ANCHOR)["report"]
    assert 0 < report["kg"] <= 3 * TONNE                 # three lots a refresh
    assert report["average"] == ANCHOR
    assert goods(g, EARTH) == earth_goods + report["kg"]
    assert cash(g, EARTH) + sum(
        r["price"] * r["remaining_kg"] // TONNE
        for r in book.open_orders(EARTH) if r["asset"] == YARD_ASSET
    ) <= earth_cash


# -- the ship -----------------------------------------------------------------------

def test_goods_go_from_the_yard_to_the_hold_and_back(town):
    g, player = town
    g.town_policy(player, False, ANCHOR)
    account = stock(g, player, 5 * TONNE)
    with pytest.raises(GameError, match="not at Tranquillitatis"):
        g.town_load(player, 1)
    ship = g.ship_of(player)
    ship.location = TOWN_NODE
    held = goods(g, account)
    g.town_load(player, 3)
    assert goods(g, player.account) == 3 * TONNE
    assert goods(g, account) == held - 3 * TONNE
    assert yard(g, player)["ship"]["aboard_kg"] == 3 * TONNE
    with pytest.raises(GameError, match="yard holds"):
        g.town_load(player, 200)
    with pytest.raises(GameError, match="aboard"):
        g.town_unload(player, 4)
    g.town_unload(player, 2)
    assert goods(g, player.account) == TONNE
    assert goods(g, account) == held - TONNE
    g.world.ledger.assert_conserved()


# -- growth -------------------------------------------------------------------------

def test_no_company_builds_a_foundry_beside_a_yard_that_is_filling(town):
    g, player = town
    g.town_policy(player, False, ANCHOR)
    stock(g, player, YARD_KG * 3 // 4 - goods(g, f"town:{player.id}"))
    foundries = sum(1 for b in state(g, player)["buildings"]
                    if b["type"] == "printer")
    for _ in range(30):
        g.step()
    s = state(g, player)
    assert sum(1 for b in s["buildings"] if b["type"] == "printer") == foundries
    if s["want"]["i"] >= 0.15:
        assert s["block"]["i"] == "goods are piling up in the yard"


# -- worlds from before -------------------------------------------------------------

def test_a_town_from_before_yards_gains_one(played, tmp_path, routes):
    path, pid = played
    copy = str(tmp_path / "old.db")
    shutil.copy(path, copy)
    g = Game.open(copy, routes=routes)
    g.db.execute("ALTER TABLE town DROP COLUMN yard")
    g.db.execute("DELETE FROM sim_schema_version WHERE version = 4")
    g.db.commit()
    g.db.close()
    g = Game.open(copy, routes=routes)
    player = g.player(pid)
    y = yard(g, player)
    assert y["sell"] is True and y["min_price"] == ANCHOR and y["sold_kg"] == 0
    for _ in range(3):
        g.step()
    assert g.db.execute("SELECT faults FROM town").fetchone()[0] == 0
    g.db.close()


# -- the steward --------------------------------------------------------------------

def test_the_steward_only_ever_asks_for_what_a_player_may():
    engine = Engine()
    town = engine.create(1969, 160.0)
    asked = engine.steward(town.state, 160.0)
    assert asked and asked[0]["k"] == "place" and asked[0]["type"] == "solar"
    assert all(i["k"] in ("place", "zone", "demolish", "toggle", "repair",
                          "price", "offer") for i in asked)
    # asking changes nothing: the same question gets the same answer
    assert engine.steward(town.state, 160.0) == asked
    # and a steward with no money asks for nothing that costs any
    assert engine.steward(town.state, 0.0) == []
