"""A restored world is the same world.

The world runs continuously on a server that will be restarted -- for
deploys, for crashes, for a kernel update. The promise is that a restart is
invisible: the world that comes back is exactly the one that stopped, and it
goes on to do exactly what the original would have done.

The test is the strongest form of that promise. Snapshot a running world,
restore it into a copy of its database, run both forward, and require that
every balance, every price and every ship agrees at the end.
"""

from __future__ import annotations

import json

from market.db import connect, transaction

from sim import persist


def _fingerprint(world) -> dict:
    db = world.ledger.db
    accounts = [r["id"] for r in db.execute(
        "SELECT id FROM account WHERE kind IN ('agent','institution','player') "
        "ORDER BY id")]
    prices = {}
    for node, book in world.books.items():
        for asset in ("ICE", "PROP", "REGOLITH", "HE3"):
            prices[f"{node}/{asset}"] = (book.last_price(asset),
                                         book.best_bid(asset),
                                         book.best_ask(asset))
    return {
        "tick": world.tick,
        "balances": {a: world.ledger.holdings(a) for a in accounts},
        "prices": prices,
        "ships": [(s.id, s.state.value, s.location, s.destination,
                   s.arrive_tick, s.manifest) for s in world.ships],
        "firms": [(f.id, f.insolvent, f.yield_buffer) for f in world.firms],
        "deposits": {d.id: d.extracted_kg for d in world.deposits.values()},
        "credits": world.ledger.credits_in_existence(),
        "destroyed": world.ledger.credits_destroyed(),
    }


def test_the_snapshot_round_trips_through_json(world):
    for _ in range(12):
        world.run_tick()
    text = persist.dumps(world)
    again = persist.loads(world.ledger.db, text, routes=world.routes)
    assert persist.dumps(again) == text


def test_a_restored_world_continues_exactly_as_the_original(world):
    for _ in range(40):
        with transaction(world.ledger.db):
            world.run_tick()

    saved = persist.dumps(world)
    copy = connect(":memory:")
    world.ledger.db.backup(copy)
    restored = persist.loads(copy, saved, routes=world.routes)

    for _ in range(40):
        with transaction(world.ledger.db):
            world.run_tick()
        with transaction(copy):
            restored.run_tick()

    assert _fingerprint(restored) == _fingerprint(world)
    restored.ledger.assert_conserved()


def test_the_snapshot_holds_no_money(world):
    """Balances live in the ledger. A second copy would be a second truth."""
    for _ in range(6):
        world.run_tick()
    text = json.dumps(persist.world_state(world))
    for word in ("balance", "credits", "CREDIT", "treasury"):
        assert word not in text
