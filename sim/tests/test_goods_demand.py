"""Who buys what a town makes.

Two buyers, both spending money that already exists.

Settlement households buy manufactured goods out of savings: only with
credits above their opening capital, so the propellant they cannot do
without is never crowded out. Earth takes a small standing order of parts
at the anchor, from the same finite account that buys helium-3.

Neither creates a credit, which is the point of having them at all.
"""

from __future__ import annotations

import datetime as dt

import pytest

from market.book import ASK
from market.money import CREDIT

from sim import TICKS_PER_GAME_DAY
from sim.earth import ACCOUNT as EARTH, GOODS, GOODS_LOTS_PER_REFRESH
from sim.firms import Role
from sim.game import DEV_FUND, Game
from sim.persist import default_routes
from sim.seed_world import (HOUSEHOLD_GOODS_KG_PER_DAY, HOUSEHOLD_GOODS_STOCK,
                            TRANQUILLITATIS, add_goods_demand)

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
TONNE = 1_000
ANCHOR = 45_000


@pytest.fixture(scope="module")
def routes():
    return default_routes()


@pytest.fixture
def game(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    yield g
    g.db.close()


def households(g, node=None):
    return [f for f in g.world.active_firms()
            if f.role is Role.CONSUMER and (node is None or f.node == node)]


def cash(g, account):
    return g.world.ledger.balance(account, CREDIT)


def goods_bids(g, node, account):
    return [r for r in g.world.books[node].open_orders(account)
            if r["asset"] == GOODS and r["side"] == "BID"]


def give(g, account, amount):
    """Savings, from an account that has them. Nothing is minted."""
    with g._mutation():
        g.world.ledger.transfer(DEV_FUND, account, CREDIT, amount,
                                kind="grant", game_time=g.world.game_time(),
                                memo="test savings")


def test_every_household_wants_goods_as_well_as_propellant(game):
    homes = households(game)
    assert len(homes) == 9
    for home in homes:
        assert home.consumes == "PROP"
        assert home.also_consumes == GOODS
        assert home.also_kg_per_day == HOUSEHOLD_GOODS_KG_PER_DAY
        assert home.targets[GOODS] == HOUSEHOLD_GOODS_STOCK


def test_a_household_with_no_savings_does_not_bid_for_goods(game):
    game.step()
    for home in households(game):
        spare = (cash(game, home.account)
                 + sum(r["price"] * r["remaining_kg"] // TONNE
                       for r in goods_bids(game, home.node, home.account))
                 - game.world.starting_capital[home.id])
        if spare < ANCHOR:
            assert goods_bids(game, home.node, home.account) == []


def test_a_household_bids_only_what_it_has_saved(game):
    home = households(game, TRANQUILLITATIS)[0]
    opening = game.world.starting_capital[home.id]
    short = max(0, opening - cash(game, home.account))
    give(game, home.account, short + 60_000)          # room for one lot only
    game.step()
    bids = goods_bids(game, home.node, home.account)
    assert len(bids) == 1
    assert bids[0]["remaining_kg"] == TONNE           # wants two, affords one
    assert bids[0]["price"] >= ANCHOR
    # paying it in full would still leave the opening capital
    assert cash(game, home.account) >= opening - 8_000   # an hour's propellant


def test_goods_bought_are_used_up_at_the_stated_rate(game):
    home = households(game, TRANQUILLITATIS)[0]
    ledger = game.world.ledger
    with game._mutation():
        ledger.extract(home.account, GOODS, 2 * TONNE, game.world.game_time(),
                       memo="test stores")
    for _ in range(TICKS_PER_GAME_DAY):
        game.step()
    per_tick = HOUSEHOLD_GOODS_KG_PER_DAY // TICKS_PER_GAME_DAY
    assert ledger.balance(home.account, GOODS) == (
        2 * TONNE - per_tick * TICKS_PER_GAME_DAY)
    ledger.assert_conserved()


def test_a_seller_is_paid_by_the_household_and_no_credit_is_made(game):
    home = households(game, TRANQUILLITATIS)[0]
    short = max(0, game.world.starting_capital[home.id]
                - cash(game, home.account))
    give(game, home.account, short + 200_000)
    game.step()
    seller, _ = game.signup("Parts Co")
    ledger, now = game.world.ledger, game.world.game_time()
    made = ledger.credits_in_existence()
    with game._mutation():
        ledger.extract(seller.account, GOODS, TONNE, now, memo="test cargo")
        before = cash(game, seller.account)
        result = game._ioc(TRANQUILLITATIS, GOODS, ASK, ANCHOR, TONNE,
                           seller.account, now)
    assert result.filled_kg == TONNE
    assert cash(game, seller.account) > before
    assert ledger.balance(home.account, GOODS) == TONNE
    assert ledger.credits_in_existence() == made


def test_earth_orders_three_lots_of_parts_at_the_anchor(game):
    while game.world.tick % 6:
        game.step()
    game.step()
    while game.world.tick % 6:
        game.step()
    bids = goods_bids(game, TRANQUILLITATIS, EARTH)
    assert len(bids) == 1
    assert bids[0]["price"] == ANCHOR
    assert bids[0]["remaining_kg"] == GOODS_LOTS_PER_REFRESH * TONNE
    # helium-3 is still on order beside it
    assert any(r["asset"] == "HE3" for r in
               game.world.books[TRANQUILLITATIS].open_orders(EARTH))


def test_a_world_from_before_goods_gains_the_demand_when_opened(routes,
                                                                tmp_path):
    path = str(tmp_path / "old.db")
    g = Game.open(path, now=T0, routes=routes)
    for home in households(g):
        home.also_consumes, home.also_kg_per_day = None, 0
        home.targets = {"PROP": home.targets["PROP"]}
    g.step()                                   # the tick saves the roster
    g.db.close()

    g = Game.open(path, routes=routes)
    assert all(h.also_consumes == GOODS and h.targets[GOODS]
               == HOUSEHOLD_GOODS_STOCK for h in households(g))
    assert add_goods_demand(g.world.firms) == 0          # and only once
    g.step()
    g.db.close()
    g = Game.open(path, routes=routes)                   # and it was saved
    assert all(h.also_consumes == GOODS for h in households(g))
    g.db.close()
