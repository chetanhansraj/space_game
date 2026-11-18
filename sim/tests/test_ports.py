"""Many ports, and the freight line between them (D86)."""
from __future__ import annotations

import json
import shutil

import pytest

from market.book import BID
from market.money import CREDIT
from sim import plots, towngame
from sim.game import DEV_FUND, Game, GameError
from sim.seed_world import FURTHER_PORTS, NODES, PORTS, TONNE
from sim.towngame import TOWN_NODE, YARD_ASSET

from test_townyard import ANCHOR, T0, goods, played, routes, stock, yard  # noqa: F401

TYCHO = plots.plot_at(-43.3, -11.4)


def cash(g, account):
    return g.world.ledger.balance(account, CREDIT)


@pytest.fixture
def far_town(played, tmp_path, routes):
    """The played town, moved to ground by Tycho: its port is Tycho Station."""
    path, pid = played
    copy = str(tmp_path / "far.db")
    shutil.copy(path, copy)
    g = Game.open(copy, routes=routes)
    g.db.execute("UPDATE town SET plot = ? WHERE player_id = ?",
                 (json.dumps(TYCHO), pid))
    g.db.commit()
    yield g, g.player(pid)
    g.db.close()


def test_there_are_eleven_ports_and_every_pair_can_be_flown(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    assert len(PORTS) == 11 and set(NODES) < set(PORTS)
    assert set(g.world.books) == set(PORTS)
    assert {n["id"] for n in g.node_info()} == set(PORTS)
    for a in PORTS:
        for b in PORTS:
            leg = g.world.routes.leg(a, b)
            assert (leg is None) == (a == b)
            if leg:
                assert leg.kind == "hop" and 0 < leg.dv < 3_500
                assert leg.tof_s < 3_600, "any hop on the Moon is inside the hour"
    g.db.close()


def test_a_town_trades_at_the_port_nearest_its_ground(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    near = {(-89.5, 0.0): "shackleton_depot", (88.0, 30.0): "peary_ridge",
            (0.7, 23.5): "tranquillitatis_flats", (-43.3, -11.4): "tycho_station",
            (-4.0, -157.4): "korolev_field", (32.8, -15.6): "imbrium_landing",
            (-53.0, -169.0): "aitken_deep", (17.0, 59.1): "crisium_anchorage"}
    for (lat, lon), port in near.items():
        assert g._port_at(lat, lon) == port
    # and a town on the ground the rules were tuned on is where towns always were
    person, _ = g.signup("Old Ground Ltd")
    g.found_town(person)
    assert g._port(person.id) == TOWN_NODE
    assert g.town_meta(person)["yard"]["port"] == "Tranquillitatis Flats"
    g.db.close()


def test_freight_is_nothing_at_home_and_more_the_further_it_goes(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    home = "tranquillitatis_flats"
    assert g._freight(home, home) == 0
    near, far = g._freight(home, "crisium_anchorage"), g._freight(home, "korolev_field")
    assert 0 < near < far and near % 100 == 0
    assert g._freight("korolev_field", home) == far
    assert far < ANCHOR, "carrying goods must not cost more than the goods"
    g.db.close()


def test_goods_go_to_the_best_bid_on_the_moon_and_the_freight_is_burned(far_town):
    g, player = far_town
    home = g._port(player.id)
    assert home == "tycho_station" and not g.world.books[home].best_bid(YARD_ASSET)
    g.town_policy(player, False, ANCHOR, keep_t=0, buy=False)
    account = stock(g, player, 3 * TONNE - goods(g, f"town:{player.id}"))
    port, bid, freight = g._best_market(home, 0)
    assert port != home and freight == g._freight(home, port) > 0
    view = yard(g, player)
    assert view["bid"] == bid - freight and view["freight"] == freight
    assert view["port"] == "Tycho Station" and view["bid_port"]
    made, burned = g.world.ledger.credits_in_existence(), g.world.ledger.credits_destroyed()
    wallet = cash(g, player.account)
    meta = g.town_sell(player, 2, 1)
    sold = meta["yard"]["sold_kg"] - view["sold_kg"]
    assert sold == 2 * TONNE and goods(g, account) == TONNE
    paid = meta["yard"]["freight_paid"] - view["freight_paid"]
    assert paid == 2 * freight
    assert g.world.ledger.credits_destroyed() - burned == paid
    assert g.world.ledger.credits_in_existence() == made, "none created"
    assert cash(g, player.account) - wallet >= 2 * (bid - freight) - 2 * 5_000
    assert cash(g, account) == 0
    g.world.ledger.assert_conserved()


def test_a_buyer_at_home_wins_when_freight_eats_the_difference(far_town):
    g, player = far_town
    home = g._port(player.id)
    g.town_policy(player, False, ANCHOR, keep_t=0, buy=False)
    stock(g, player, 2 * TONNE - goods(g, f"town:{player.id}"))
    port, bid, freight = g._best_market(home, 0)
    buyer, _ = g.signup("Tycho Outfitters")
    with g._mutation():
        g.world.ledger.transfer(DEV_FUND, buyer.account, CREDIT, 500_000,
                                kind="test", game_time=g.world.game_time())
        g.world.books[home].place(YARD_ASSET, BID, bid - freight + 1_000, TONNE,
                                  buyer.account, g.world.game_time())
    assert g._best_market(home, 0)[0] == home
    burned = g.world.ledger.credits_destroyed()
    g.town_sell(player, 1, 1)
    assert goods(g, buyer.account) == TONNE, "the neighbour got it"
    assert g.world.ledger.credits_destroyed() == burned, "and nothing was carried"


def test_a_floor_is_a_floor_after_freight(far_town):
    g, player = far_town
    home = g._port(player.id)
    g.town_policy(player, False, ANCHOR, keep_t=0, buy=False)
    account = stock(g, player, 2 * TONNE - goods(g, f"town:{player.id}"))
    port, bid, freight = g._best_market(home, 0)
    assert g._best_market(home, bid - freight + 1) is None
    meta = g.town_sell(player, 1, bid - freight + 1)
    assert goods(g, account) == 2 * TONNE and meta["yard"]["held_kg"] == 2 * TONNE


def test_a_towns_bid_for_parts_rests_at_its_own_port(far_town):
    g, player = far_town
    home = g._port(player.id)
    account = g._yard_account(player)
    with g._mutation():
        g.world.ledger.consume(account, YARD_ASSET, goods(g, account),
                               g.world.game_time(), memo="test: yard emptied")
        g.world.ledger.transfer(DEV_FUND, player.account, CREDIT, 600_000,
                                kind="test", game_time=g.world.game_time())
    for b in json.loads(g.town_state(player))["buildings"]:
        if b["type"] == "printer" and b["on"]:
            g.town_intent(player, {"k": "toggle", "uid": b["uid"]})
    g.town_policy(player, True, ANCHOR, keep_t=3)
    g.step()
    mine = [o for o in g.world.books[home].open_orders(account) if o["side"] == "BID"]
    assert len(mine) == 1
    assert not [o for o in g.world.books[TOWN_NODE].open_orders(account)]


def test_the_ship_loads_at_the_towns_own_port(far_town):
    g, player = far_town
    stock(g, player, 2 * TONNE)
    with pytest.raises(GameError, match="Tycho Station"):
        g.town_load(player, 1)


def test_a_world_from_before_the_further_ports_gains_their_books(tmp_path, routes):
    path = str(tmp_path / "old.db")
    g = Game.open(path, now=T0, routes=routes)
    g.step()
    snap = json.loads(g.db.execute(
        "SELECT state FROM world_snapshot WHERE id = 1").fetchone()[0])
    snap["nodes"] = list(NODES)
    g.db.execute("UPDATE world_snapshot SET state = ? WHERE id = 1",
                 (json.dumps(snap),))
    g.db.commit()
    g.db.close()
    g = Game.open(path, routes=routes)
    assert set(g.world.books) == set(PORTS)
    for port in FURTHER_PORTS:
        assert g.world.books[port].best_bid(YARD_ASSET) is None
    g.step()
    g.db.close()
