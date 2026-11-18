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
from sim.game import DEV_FUND, Game, GameError
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
    assert y["held_kg"] == (y["made_kg"] - y["sold_kg"]
                            - y["parts"]["used_kg"])


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
    before = yard(g, player)
    made, used = before["made_kg"], before["parts"]["used_kg"]
    for _ in range(3):
        g.step()
    s = state(g, player)
    # not a gram over, and under only by the parts the buildings took,
    # which is not room enough to call the shift back
    worn = yard(g, player)["parts"]["used_kg"] - used
    assert 0 < worn < 100 and goods(g, account) == YARD_KG - worn
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
    assert goods(g, account) == (y["made_kg"] + 2 * TONNE - y["sold_kg"]
                                 - y["parts"]["used_kg"])


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
    g.db.execute("ALTER TABLE town DROP COLUMN plot")
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


# -- spare parts (D82) ---------------------------------------------------------------

def consumed(g, account) -> int:
    return g.db.execute(
        "SELECT COALESCE(SUM(-p.amount), 0) FROM posting p JOIN txn t "
        "ON t.id = p.txn_id WHERE p.account_id = ? AND p.asset = ? "
        "AND t.kind = 'consumption'", (account, YARD_ASSET)).fetchone()[0]


def foundries_off(g, player):
    for b in state(g, player)["buildings"]:
        if b["type"] == "printer" and b["on"]:
            g.town_intent(player, {"k": "toggle", "uid": b["uid"]})


def test_a_town_that_trades_wears_parts_out_of_its_own_yard(town):
    """Goods leave the world as mass, on the ledger, and no credit moves."""
    g, player = town
    g.town_policy(player, False, ANCHOR)
    account = stock(g, player, 3 * TONNE)
    y0, made = yard(g, player), g.world.ledger.credits_in_existence()
    assert y0["parts"]["wear"] and y0["parts"]["kg_per_hour"] > 0
    for _ in range(6):
        g.step()
    y = yard(g, player)
    used = y["parts"]["used_kg"] - y0["parts"]["used_kg"]
    assert 5 * y0["parts"]["kg_per_hour"] - 1 <= used
    assert used <= 7 * y["parts"]["kg_per_hour"] + 1
    assert consumed(g, account) == y["parts"]["used_kg"]
    assert y["parts"]["landed_kg"] == y0["parts"]["landed_kg"], \
        "Earth lands nothing while the yard has stock"
    assert goods(g, account) == (y0["held_kg"] + y["made_kg"] - y0["made_kg"]
                                 - used)
    assert g.world.ledger.credits_in_existence() == made
    g.world.ledger.assert_conserved()


def test_a_town_too_small_to_trade_still_has_its_founding_spares(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    player, _ = g.signup("New Ground")
    g.found_town(player)
    account = stock(g, player, 500)
    for _ in range(5):
        g.step()
    parts = yard(g, player)["parts"]
    assert parts["wear"] is False and parts["kg_per_hour"] == 0
    assert parts["used_kg"] == 0 and parts["landed_kg"] == 0
    assert goods(g, account) == 500 and consumed(g, account) == 0
    g.db.close()


def test_an_empty_yard_is_filled_from_earth_at_twice_the_price(town):
    """To the credit: what Earth lands is what the buildings needed and the
    yard did not have, and it costs twice the port's price for goods."""
    g, player = town
    foundries_off(g, player)
    row = g._town_row(player.id)
    engine, credits = g.town_engine, 500.0
    price = g._parts_price() / TONNE / 1000
    assert g._parts_price() == 2 * ANCHOR

    def hour(held, wear):
        return engine.tick(row["state"], 1.0, credits,
                           {"cap": YARD_KG, "held": held, "wear": wear,
                            "importAt": price})

    plain, stocked, dry = hour(0, False), hour(5000, True), hour(0, True)
    need = stocked.summary["parts"]
    assert need > 0 and plain.summary["make"] == 0
    assert plain.used == 0 and plain.landed == 0
    assert stocked.landed == 0 and need - 1 <= stocked.used <= need + 1
    assert stocked.credits == pytest.approx(plain.credits, abs=1e-9)
    assert dry.used == 0 and dry.landed == pytest.approx(need, rel=1e-6)
    assert plain.credits - dry.credits == pytest.approx(dry.landed * price,
                                                        abs=1e-9)


def test_what_earth_lands_is_counted_and_paid_through_the_ordinary_sink(town):
    g, player = town
    foundries_off(g, player)
    account = g._yard_account(player)
    with g._mutation():
        g.world.ledger.consume(account, YARD_ASSET, goods(g, account),
                               g.world.game_time(), memo="test: yard emptied")
    made = g.world.ledger.credits_in_existence()
    for _ in range(4):
        g.step()
    parts = yard(g, player)["parts"]
    assert parts["landed_kg"] == pytest.approx(4 * parts["kg_per_hour"],
                                               rel=0.1)
    assert goods(g, account) == 0, "landed parts are fitted, not stored"
    assert g.world.ledger.credits_in_existence() == made
    assert any("spare parts" in a["msg"]
               for a in state(g, player)["alerts"])


def test_a_standing_sale_never_sells_the_parts_the_town_needs(town):
    g, player = town
    y = yard(g, player)
    keep = y["parts"]["keep_kg"]
    assert y["parts"]["keep_t"] is None and keep == y["parts"]["auto_kg"]
    assert 0 < keep <= towngame.PARTS_KEEP_MAX
    account = stock(g, player, keep + 2 * TONNE + 500 - goods(
        g, f"town:{player.id}"))
    sold = y["sold_kg"]
    for _ in range(8):
        g.step()
        assert goods(g, account) >= yard(g, player)["parts"]["keep_kg"] - 5
    assert yard(g, player)["sold_kg"] >= sold + 2 * TONNE

    # Told to keep nothing, it sells every whole tonne.
    g.town_policy(player, True, ANCHOR, keep_t=0)
    assert yard(g, player)["parts"]["keep_kg"] == 0
    for _ in range(8):
        g.step()
    assert goods(g, account) < TONNE


def test_how_much_to_keep_is_the_owners_to_say(town):
    g, player = town
    for bad in (-1, 21, 1.5, True, "3"):
        with pytest.raises(GameError):
            g.town_policy(player, True, ANCHOR, keep_t=bad)
    meta = g.town_policy(player, True, ANCHOR, keep_t=3)
    assert meta["yard"]["parts"]["keep_kg"] == 3 * TONNE
    assert meta["yard"]["parts"]["keep_t"] == 3
    meta = g.town_policy(player, True, ANCHOR)
    assert meta["yard"]["parts"]["keep_t"] is None


def test_a_yard_kept_full_sends_the_shift_home_though_parts_are_taken(town):
    """Buildings taking a few kilograms an hour is not room worth working for."""
    g, player = town
    g.town_policy(player, False, ANCHOR)
    stock(g, player, YARD_KG - goods(g, f"town:{player.id}"))
    for _ in range(3):
        g.step()
    s = state(g, player)
    assert s["cargo"]["full"] and s["flows"]["yardFull"]
    assert s["flows"]["make"] == 0


# -- buying parts at the port (D83) --------------------------------------------------

def bids(g, account):
    return [dict(r) for r in g.world.books[TOWN_NODE].open_orders(account)
            if r["side"] == "BID"]


def rival_bid(g) -> int:
    return g.db.execute(
        "SELECT MAX(price) FROM book_order WHERE node = ? AND asset = ? "
        "AND side = 'BID' AND status = 'OPEN' AND account_id NOT LIKE 'town:%'",
        (TOWN_NODE, YARD_ASSET)).fetchone()[0]


def short_town(g, player):
    """A town with no goods and no working foundry, and money: it must buy."""
    foundries_off(g, player)
    account = g._yard_account(player)
    with g._mutation():
        g.world.ledger.transfer(DEV_FUND, player.account, CREDIT, 600_000,
                                kind="test", game_time=g.world.game_time())
        g.world.ledger.consume(account, YARD_ASSET, goods(g, account),
                               g.world.game_time(), memo="test: yard emptied")
    return account


def test_a_town_short_of_parts_bids_at_the_port_just_above_the_rest(town):
    g, player = town
    account = short_town(g, player)
    g.town_policy(player, True, ANCHOR, keep_t=3)
    wallet = cash(g, player.account)
    g.step()
    mine = bids(g, account)
    assert len(mine) == 1
    order = mine[0]
    assert order["remaining_kg"] == towngame.PARTS_ORDER_LOTS * TONNE
    assert order["price"] == rival_bid(g) + towngame.PARTS_BID_STEP
    assert order["price"] <= g._parts_price()
    # paid for in full when placed, out of the company's own credits
    paid = order["price"] * towngame.PARTS_ORDER_LOTS
    assert cash(g, account) == 0
    assert cash(g, player.account) <= wallet - paid + 5000
    y = yard(g, player)["parts"]
    assert y["buy"] and y["on_order_kg"] == order["remaining_kg"]
    # and it is renewed, not stacked: an hour later there is still one
    g.step()
    assert len(bids(g, account)) == 1


def test_another_towns_sale_fills_it_and_the_money_goes_to_the_seller(town):
    g, player = town
    account = short_town(g, player)
    g.town_policy(player, True, ANCHOR, keep_t=3)
    g.step()
    price = bids(g, account)[0]["price"]
    made = g.world.ledger.credits_in_existence()
    seller, _ = g.signup("Next Door Foundry")
    with g._mutation():
        g.world.ledger.extract(seller.account, YARD_ASSET, TONNE,
                               g.world.game_time(), memo="test: a neighbour's goods")
        before = cash(g, seller.account)
        result = g._ioc(TOWN_NODE, YARD_ASSET, "ASK", ANCHOR, TONNE,
                        seller.account, g.world.game_time())
    assert result.filled_kg == TONNE
    assert cash(g, seller.account) - before == price, "the best bid was the town's"
    assert goods(g, account) == TONNE
    g.step()
    y = yard(g, player)["parts"]
    assert y["bought_kg"] == TONNE and y["spent"] == price
    assert cash(g, account) == 0, "no credit stays in the yard"
    assert g.world.ledger.credits_in_existence() == made
    g.world.ledger.assert_conserved()


def test_the_owners_limit_and_earths_price_are_never_passed(town):
    g, player = town
    account = short_town(g, player)
    g.town_policy(player, True, ANCHOR, keep_t=3, max_price=46_000)
    g.step()
    assert bids(g, account)[0]["price"] == 46_000
    assert yard(g, player)["parts"]["max_price"] == 46_000
    # an owner who would pay anything still pays no more than Earth asks
    g.town_policy(player, True, ANCHOR, keep_t=3, max_price=500_000)
    g.step()
    assert bids(g, account)[0]["price"] <= g._parts_price()


def test_told_to_stop_the_bid_comes_off_at_once_and_the_money_comes_home(town):
    g, player = town
    account = short_town(g, player)
    g.town_policy(player, True, ANCHOR, keep_t=3)
    g.step()
    locked = bids(g, account)[0]["price"] * towngame.PARTS_ORDER_LOTS
    wallet = cash(g, player.account)
    meta = g.town_policy(player, True, ANCHOR, keep_t=3, buy=False)
    assert bids(g, account) == [] and cash(g, account) == 0
    assert cash(g, player.account) == wallet + locked
    assert meta["yard"]["parts"]["buy"] is False
    for _ in range(3):
        g.step()
    assert bids(g, account) == []
    with pytest.raises(GameError):
        g.town_policy(player, True, ANCHOR, buy="yes")


def test_a_town_with_its_reserve_in_the_yard_bids_for_nothing(town):
    g, player = town
    account = stock(g, player, 5 * TONNE)
    for _ in range(3):
        g.step()
        assert bids(g, account) == []


def test_a_lost_town_leaves_nothing_on_the_book(town):
    g, player = town
    account = short_town(g, player)
    g.town_policy(player, True, ANCHOR, keep_t=3)
    g.step()
    assert bids(g, account)
    row = g._town_row(player.id)
    dead = json.loads(row["state"])
    for member in dead["crew"]:
        member["alive"], member["health"] = False, 0
    g.db.execute("UPDATE town SET state = ? WHERE player_id = ?",
                 (json.dumps(dead), player.id))
    g.db.commit()
    g.step()
    assert g._town_row(player.id)["lost_tick"] is not None
    assert bids(g, account) == [] and cash(g, account) == 0


# -- temperaments (D83) --------------------------------------------------------------

def test_a_temperament_changes_what_the_steward_chooses(town):
    g, player = town
    row = g._town_row(player.id)
    engine, wallet = g.town_engine, 400.0
    plain = engine.steward(row["state"], wallet)
    assert not any(i["k"] == "price" for i in plain)
    dear = engine.steward(row["state"], wallet, style={"price": 2})
    assert {"k": "price", "level": 2} in dear
    # asking is still asking: the same question gets the same answer
    assert engine.steward(row["state"], wallet, style={"price": 2}) == dear
    # a caretaker has no temperament
    assert engine.steward(row["state"], wallet, keep=True,
                          style={"price": 2}) == engine.steward(
                              row["state"], wallet, keep=True)


def test_a_resort_shuts_its_foundries_once_the_crew_has_had_theirs(town):
    g, player = town
    state_ = json.loads(g._town_row(player.id)["state"])
    running = [b["uid"] for b in state_["buildings"]
               if b["type"] == "printer" and b["on"] and b["progress"] >= 1]
    assert running
    engine, style = g.town_engine, {"foundries": 0}
    state_["mission"] = 10          # the crew still wants a foundry on ore
    early = engine.steward(json.dumps(state_), 400.0, style=style)
    assert not any(i["k"] == "toggle" for i in early)
    state_["mission"] = 20
    late = engine.steward(json.dumps(state_), 400.0, style=style)
    assert sorted(i["uid"] for i in late if i["k"] == "toggle") == sorted(running)
    one = engine.steward(json.dumps(state_), 400.0, style={"foundries": 1})
    assert len([i for i in one if i["k"] == "toggle"]) == len(running) - 1


def test_a_temperament_that_wants_no_more_of_a_zone_lays_none(town):
    g, player = town
    state_ = json.loads(g._town_row(player.id)["state"])
    state_["mission"] = 23          # nothing left that the crew asks for
    none = {"lots": {"r": 0, "i": 0, "v": 0}}
    engine = g.town_engine
    for _ in range(30):
        asked = engine.steward(json.dumps(state_), 900.0, style=none)
        assert not any(i["k"] == "zone" for i in asked), asked
        state_ = json.loads(engine.tick(json.dumps(state_), 1.0, 900.0).state)


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
    g.db.execute("ALTER TABLE town DROP COLUMN plot")
    g.db.execute("DELETE FROM sim_schema_version WHERE version >= 5")
    g.db.commit()
    g.db.close()
    g = Game.open(copy, routes=routes)
    assert g.town_meta(g.player(pid))["caretaker"]["on"] is False
    g.step()
    g.db.close()
