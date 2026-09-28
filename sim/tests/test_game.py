"""The game layer: a persistent world with people in it.

What is being defended here, in order of how badly it would hurt to get
wrong in a live world:

1. No credit is created by anything a player does, including joining.
2. A tick, or a player action, happens completely or not at all -- in the
   database *and* in memory.
3. The world a restarted server comes back to is the one that stopped.
4. The loop works: buy, fly, arrive, get paid.
"""

from __future__ import annotations

import datetime as dt

import pytest

from market.db import transaction
from market.money import CREDIT

from sim import game as game_mod
from sim.contracts import DEADLINE_TICKS
from sim.game import DEV_FUND, STARTING_GRANT, Game, GameError
from sim.persist import default_routes
from sim.ships import KESTREL, ShipState

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
PEARY, SHACK, TRANQ = "peary_ridge", "shackleton_depot", "tranquillitatis_flats"


@pytest.fixture(scope="module")
def routes():
    return default_routes()


@pytest.fixture
def game(routes):
    g = Game.open(":memory:", now=T0, routes=routes)
    yield g
    g.db.close()


def _credits_outside_the_world(g: Game) -> int:
    return g.world.ledger.credits_in_existence() - g.world.ledger.credits_destroyed()


def _run(g: Game, ticks: int) -> None:
    for _ in range(ticks):
        g.step()


def _fly(g: Game, player, destination: str, **kw) -> None:
    g.dispatch(player, destination, **kw)
    ship = g.ship_of(player)
    while ship.state is ShipState.IN_TRANSIT:
        g.step()
        ship = g.ship_of(player)


# -- money -------------------------------------------------------------------

def test_joining_moves_money_and_creates_none(game):
    minted = game.world.ledger.credits_in_existence()
    fund = game.world.ledger.balance(DEV_FUND, CREDIT)
    player, token = game.signup("Kestrel & Daughters")
    assert game.world.ledger.credits_in_existence() == minted
    assert game.world.ledger.balance(player.account, CREDIT) == STARTING_GRANT
    assert game.world.ledger.balance(DEV_FUND, CREDIT) == fund - STARTING_GRANT
    assert game.world.ledger.balance(player.account, "PROP") == KESTREL.tank_capacity_kg
    assert game.authenticate(token) == player
    assert game.authenticate("not-a-token") is None
    game.world.ledger.assert_conserved()


def test_tokens_are_stored_hashed(game):
    _, token = game.signup("Hashed Holdings")
    stored = [r[0] for r in game.db.execute("SELECT token_hash FROM player")]
    assert token not in stored


def test_company_names_are_unique_and_sane(game):
    game.signup("Vance Freight")
    with pytest.raises(GameError):
        game.signup("vance freight")
    for bad in ("", "x", "<script>", "a" * 40):
        with pytest.raises(GameError):
            game.signup(bad)


def test_the_charter_office_closes_when_the_fund_is_spent(game, monkeypatch):
    monkeypatch.setattr(game_mod, "STARTING_GRANT",
                        game.world.ledger.balance(DEV_FUND, CREDIT) + 1)
    with pytest.raises(GameError, match="charter office"):
        game.signup("Too Late Ltd")


# -- atomicity ---------------------------------------------------------------

def test_a_failed_tick_leaves_no_trace_anywhere(game, monkeypatch):
    player, _ = game.signup("Rollback Co")
    _run(game, 3)
    tick = game.world.tick
    postings = game.db.execute("SELECT COUNT(*) FROM posting").fetchone()[0]
    extracted = {d.id: d.extracted_kg for d in game.world.deposits.values()}

    def explode(now):
        raise RuntimeError("server killed mid-tick")
    monkeypatch.setattr(game.board, "tick", explode)
    with pytest.raises(RuntimeError):
        game.step()

    assert game.world.tick == tick
    assert game.db.execute("SELECT COUNT(*) FROM posting").fetchone()[0] == postings
    assert {d.id: d.extracted_kg for d in game.world.deposits.values()} == extracted
    monkeypatch.undo()
    game.step()
    assert game.world.tick == tick + 1


def test_a_refused_action_changes_nothing(game):
    player, _ = game.signup("Careful Carriers")
    before = game.world.ledger.holdings(player.account)
    with pytest.raises(GameError):
        game.buy(player, "ICE", 41, 500)              # hold is 40 t
    with pytest.raises(GameError):
        game.sell(player, "HE3", 1, 1)                # holds none
    with pytest.raises(GameError):
        game.dispatch(player, SHACK)                  # already there
    assert game.world.ledger.holdings(player.account) == before


# -- persistence -------------------------------------------------------------

def test_a_reopened_world_is_the_one_that_stopped(tmp_path, routes):
    path = tmp_path / "world.db"
    g = Game.open(str(path), now=T0, routes=routes)
    player, token = g.signup("Persistent Ltd")
    _run(g, 30)
    g.dispatch(player, PEARY)
    state = (g.world.tick, g.world.ledger.holdings(player.account),
             g.ship_of(player).state, g.world.books[SHACK].last_price("ICE"))
    g.db.close()

    again = Game.open(str(path), routes=routes)
    me = again.authenticate(token)
    assert me is not None and me.id == player.id
    assert (again.world.tick, again.world.ledger.holdings(me.account),
            again.ship_of(me).state,
            again.world.books[SHACK].last_price("ICE")) == state
    assert again.launch_real == T0
    again.step()
    assert again.ship_of(me).state is ShipState.DOCKED
    again.world.ledger.assert_conserved()


def test_catching_up_runs_every_missed_hour(game):
    later = T0 + dt.timedelta(seconds=game_mod.TICK_REAL_SECONDS * 5 + 1)
    assert game.due_tick(later) == 5
    assert game.catch_up(later) == 5
    assert game.world.tick == 5
    assert game.catch_up(later) == 0


# -- the loop ----------------------------------------------------------------

def test_buy_fly_and_sell_on_arrival(game):
    player, _ = game.signup("First Run")
    _run(game, 24)
    ask = game.world.books[SHACK].best_ask("ICE")
    assert ask
    bought = game.buy(player, "ICE", 10, ask)
    assert bought["kg"] > 0
    cash_before = game.world.ledger.balance(player.account, CREDIT)
    burned_before = game.world.ledger.credits_destroyed()

    plan = game.plan(player, PEARY)
    _fly(game, player, PEARY)

    ship = game.ship_of(player)
    assert ship.location == PEARY
    # The docking fee left the world, not just the player's account.
    assert game.world.ledger.credits_destroyed() - burned_before >= plan["fee"]
    letters = game.inbox(player)
    arrival = next(m for m in letters if m["kind"] == "arrival")
    assert arrival["data"]["node"] == PEARY
    # Whatever sold, the money came from a real buyer on a real book.
    sold = sum(s["value"] for s in arrival["data"]["sold"])
    assert game.world.ledger.balance(player.account, CREDIT) == \
        cash_before - plan["fee"] + sold
    game.world.ledger.assert_conserved()


def test_a_flare_grounds_every_launch(game):
    player, _ = game.signup("Grounded Goods")
    game.world.weather.flare_until = game.world.tick + 5
    with pytest.raises(GameError, match="flare"):
        game.dispatch(player, PEARY)


def test_a_ship_in_flight_cannot_trade(game):
    player, _ = game.signup("Mid Air")
    game.dispatch(player, TRANQ)
    with pytest.raises(GameError, match="flight"):
        game.buy(player, "ICE", 1, 500)


# -- contracts ---------------------------------------------------------------

def _post_until(game: Game, node: str | None = None):
    for _ in range(200):
        game.board.post_new(game.world.game_time(), force=True)
        found = game.board.open(node)
        if found:
            return found[0]
        game.step()
    pytest.skip("no firm was short enough to post a contract")


def test_a_contract_escrows_real_money_and_pays_it_out(game):
    player, _ = game.signup("Contract Carriers")
    minted = game.world.ledger.credits_in_existence()
    c = _post_until(game)
    assert game.world.ledger.balance(c.escrow_account, CREDIT) == c.payment
    game.accept(player, c.id)

    # Give the pilot the goods somewhere else, then fly them in.
    elsewhere = next(n for n in (SHACK, PEARY, TRANQ) if n != c.node)
    ship = game.ship_of(player)
    ship.location = elsewhere
    with transaction(game.db):
        game.world.ledger.extract(player.account, c.asset, c.qty_kg,
                                  game.world.game_time(), memo="test cargo")
        for asset, held in game.world.ledger.holdings(player.account).items():
            if asset not in (CREDIT, "PROP", c.asset):
                game.world.ledger.consume(player.account, asset, held, "t")
    game._saved = game._write_snapshot()

    cash = game.world.ledger.balance(player.account, CREDIT)
    _fly(game, player, c.node, sell_on_arrival=False)
    done = game.board.get(c.id)
    assert done.status == "FULFILLED"
    paid = game.world.ledger.balance(player.account, CREDIT) - cash
    assert paid == c.payment - game_mod.DOCKING_FEE[c.node]
    assert game.world.ledger.balance(c.escrow_account, CREDIT) == 0
    assert game.world.ledger.credits_in_existence() == minted
    assert any(m["kind"] == "contract_paid" for m in game.inbox(player))
    game.world.ledger.assert_conserved()


def test_goods_bought_at_the_door_are_not_a_delivery(game):
    player, _ = game.signup("Door Dash")
    c = _post_until(game)
    game.accept(player, c.id)
    ship = game.ship_of(player)
    ship.location = c.node
    # Someone at the issuer's own port is selling exactly what it wants.
    now = game.world.game_time()
    with transaction(game.db):
        game.world.ledger.open_account("test:seller", "agent", now)
        game.world.ledger.extract("test:seller", c.asset, c.qty_kg, now)
    book = game.world.books[c.node]
    price = (book.best_bid(c.asset) or 1) + 1       # rests; crosses nobody
    book.place(c.asset, "ASK", price, c.qty_kg, "test:seller", now)
    game._saved = game._write_snapshot()
    game.buy(player, c.asset, c.qty_kg // 1000, price)
    assert game.world.ledger.balance(player.account, c.asset) >= c.qty_kg
    with pytest.raises(GameError, match="aboard"):
        game.deliver(player, c.id)
    assert game.board.get(c.id).status == "ACCEPTED"


def test_an_untaken_contract_refunds_its_issuer_at_the_deadline(game):
    c = _post_until(game)
    minted = game.world.ledger.credits_in_existence()
    while game.world.tick < c.deadline_tick:
        game.step()
    assert game.board.get(c.id).status == "EXPIRED"
    assert game.world.ledger.balance(c.escrow_account, CREDIT) == 0
    assert game.world.ledger.credits_in_existence() == minted
    assert c.deadline_tick - c.posted_tick == DEADLINE_TICKS
    game.world.ledger.assert_conserved()


# -- upkeep ------------------------------------------------------------------

def test_unpaid_upkeep_grounds_the_ship_and_never_overdraws(game):
    player, _ = game.signup("Broke Bros")
    with transaction(game.db):
        game.world.ledger.burn(player.account,
                               game.world.ledger.balance(player.account, CREDIT),
                               game.world.game_time(), memo="test: ruin")
    while game.world.tick % 24 != 23:
        game.step()
    game.step()
    me = game.player(player.id)
    assert me.upkeep_owed == KESTREL.upkeep_per_day
    assert game.world.ledger.balance(player.account, CREDIT) == 0
    with pytest.raises(GameError, match="Grounded"):
        game.dispatch(me, PEARY)
    assert any(m["kind"] == "arrears" for m in game.inbox(me))


def test_a_new_world_can_open_with_a_history_and_on_time(routes):
    g = Game.open(":memory:", now=T0, routes=routes, warmup_ticks=6)
    assert g.world.tick == 6
    assert g.due_tick(T0) == 6          # exactly on time, not ahead or behind
    assert g.catch_up(T0) == 0
    g.world.ledger.assert_conserved()
    g.db.close()
