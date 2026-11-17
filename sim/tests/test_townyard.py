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

from sim import towngame
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
    # A company's id is random and its town's ground is drawn from it. These
    # tests want the same town every time: the one the city's own test plays.
    drawn, towngame.town_seed = towngame.town_seed, lambda pid, attempt=0: 1969
    try:
        g.found_town(player)
    finally:
        towngame.town_seed = drawn
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
    steady = 0
    for _ in range(12):
        s0, made0 = state(g, player), yard(g, player)["made_kg"]
        g.step()
        s1, made1 = state(g, player), yard(g, player)["made_kg"]
        part0, part1 = s0["cargo"]["made"], s1["cargo"]["made"]
        assert 0 <= part1 < 1
        rate = s0["flows"]["make"]
        if rate > 0 and abs(rate - s1["flows"]["make"]) < 1e-9:
            # an hour at a steady rate: what was made, to the gram, is the
            # whole kilograms booked plus the change in the part carried
            steady += 1
            assert abs((made1 - made0) + part1 - part0 - rate) < 1e-6
    assert steady >= 3, "the foundries never ran three steady hours"


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
    for column in ("yard", "caretaker", "caretaker_paid"):
        g.db.execute(f"ALTER TABLE town DROP COLUMN {column}")
    g.db.execute("ALTER TABLE player DROP COLUMN house")
    g.db.execute("DELETE FROM sim_schema_version WHERE version >= 4")
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


def test_the_size_to_trade_is_passed_once(routes):
    """A town that shrinks keeps its place at the port. One that never grew
    has none, and nothing leaves without a working pad. D81."""
    g = Game.open(":memory:", now=T0, routes=routes)
    book: dict = {}
    assert not g._trade_open({"pad": True, "population": 7}, book)
    assert not g._trade_open({"pad": False, "population": 8}, book)
    assert g._trade_open({"pad": True, "population": 8}, book)
    assert g._trade_open({"pad": True, "population": 4}, book)
    assert not g._trade_open({"pad": False, "population": 4}, book)
    g.db.close()


def test_a_new_crew_earns_its_place_at_the_port_again(played, tmp_path, routes):
    path, pid = played
    copy = str(tmp_path / "again.db")
    shutil.copy(path, copy)
    g = Game.open(copy, routes=routes)
    row = g.db.execute("SELECT * FROM town WHERE player_id = ?",
                       (pid,)).fetchone()
    assert json.loads(row["yard"]).get("trading") is True
    state = json.loads(row["state"])
    state["phase"] = "lost"
    g.db.execute("UPDATE town SET state = ?, lost_tick = ? WHERE player_id = ?",
                 (json.dumps(state), g.world.tick, pid))
    g.db.commit()
    meta = g.refound_town(g.player(pid))
    assert meta["trade"]["open"] is False
    book = json.loads(g.db.execute("SELECT yard FROM town WHERE player_id = ?",
                                   (pid,)).fetchone()[0])
    assert "trading" not in book and book["sold_kg"] > 0, "the record stays"
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


# -- the caretaker ------------------------------------------------------------------

def test_no_town_has_a_caretaker_until_one_is_hired(town):
    g, player = town
    c = g.town_meta(player)["caretaker"]
    assert c == {"on": False, "fee": 200, "paid": 0}
    burned = g.world.ledger.credits_destroyed()
    g.step()
    wages = g.db.execute(
        "SELECT COUNT(*) FROM txn WHERE memo = 'town caretaker''s wage'"
    ).fetchone()[0]
    assert wages == 0 and g.world.ledger.credits_destroyed() >= burned


def test_a_caretaker_is_paid_every_hour_and_the_wage_leaves_the_world(town):
    g, player = town
    g.town_policy(player, False, ANCHOR)
    stock(g, player, 0 + 1)                     # a mutation, to settle the books
    g.town_caretaker(player, True)
    assert g.town_meta(player)["caretaker"]["on"]
    made = g.world.ledger.credits_in_existence()
    hours = 6
    for _ in range(hours):
        g.step()
    paid = g.town_meta(player)["caretaker"]["paid"]
    assert paid == 200 * hours
    wages = g.db.execute(
        "SELECT COUNT(*), COALESCE(SUM(-p.amount), 0) FROM txn t JOIN posting p "
        "ON p.txn_id = t.id WHERE t.memo = 'town caretaker''s wage' "
        "AND t.kind = 'sink' AND p.account_id = ?", (player.account,)
    ).fetchone()
    assert tuple(wages) == (hours, paid)
    assert g.world.ledger.credits_in_existence() == made
    g.town_caretaker(player, False)
    g.step()
    assert g.town_meta(player)["caretaker"]["paid"] == paid


def test_a_caretaker_who_cannot_be_paid_leaves_and_says_so(town):
    g, player = town
    g.town_policy(player, False, ANCHOR)
    g.town_caretaker(player, True)
    with g._mutation():
        g.world.ledger.burn(player.account, cash(g, player.account),
                            g.world.game_time(), memo="test: ruin")
    g.step()
    assert g.town_meta(player)["caretaker"]["on"] is False
    assert any(m["kind"] == "town_caretaker_left" for m in g.inbox(player))
    with g._mutation():                           # whatever the hour earned
        g.world.ledger.burn(player.account, cash(g, player.account),
                            g.world.game_time(), memo="test: ruin")
    with pytest.raises(GameError, match="paid 200 cr an hour"):
        g.town_caretaker(player, True)


def test_a_caretaker_does_what_is_urgent_and_nothing_that_grows_the_town():
    engine = Engine()
    town = engine.create(1969, 160.0)
    # On the first morning nothing is urgent. A player would start building;
    # a caretaker is not there to found the town for you.
    assert engine.steward(town.state, 160.0, keep=True) == []
    assert engine.steward(town.state, 160.0) != []


def test_a_caretaker_mends_what_breaks_while_the_owner_is_away(town):
    g, player = town
    s = state(g, player)
    target = next(b for b in s["buildings"]
                  if b["type"] == "solar" and b["progress"] >= 1)
    target["damaged"], target["repair"] = True, 0
    g.db.execute("UPDATE town SET state = ? WHERE player_id = ?",
                 (json.dumps(s), player.id))
    g.db.commit()

    def panel():
        return next(b for b in state(g, player)["buildings"]
                    if b["uid"] == target["uid"])

    for _ in range(3):                           # nobody home, nobody hired
        g.step()
    assert panel()["damaged"] and panel()["repair"] == 0

    g.town_caretaker(player, True)
    g.step()
    assert panel()["repair"] > 0                 # the repair is under way
    for _ in range(12):
        g.step()
    assert not panel()["damaged"]
    buildings = len(state(g, player)["buildings"])
    assert g.db.execute("SELECT faults FROM town").fetchone()[0] == 0
    assert buildings >= len(s["buildings"])


def test_a_town_from_before_caretakers_has_none(played, tmp_path, routes):
    path, pid = played
    copy = str(tmp_path / "old.db")
    shutil.copy(path, copy)
    g = Game.open(copy, routes=routes)
    g.db.execute("ALTER TABLE town DROP COLUMN caretaker")
    g.db.execute("ALTER TABLE town DROP COLUMN caretaker_paid")
    g.db.execute("ALTER TABLE player DROP COLUMN house")
    g.db.execute("DELETE FROM sim_schema_version WHERE version >= 5")
    g.db.commit()
    g.db.close()
    g = Game.open(copy, routes=routes)
    assert g.town_meta(g.player(pid))["caretaker"]["on"] is False
    g.step()
    g.db.close()
