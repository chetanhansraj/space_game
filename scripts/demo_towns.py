"""Leave a fresh Moon alone and watch the towns the world runs (D81).

    python scripts/demo_towns.py [game days, default 60]

Nobody signs up. Every ten game days it prints each town: people, standing,
buildings, tonnes of goods sold, crews sent. At the end it checks that no
credit was created and prints what each house company holds and what Earth
paid out, with what each town made, fitted as spare parts and had landed
from Earth (D82). The same command prints the same thing every time: the world is
seeded and the house companies have fixed ids.

About two seconds a game day. 120 days is the run quoted in D81.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time

from market.money import CREDIT
from sim.earth import ACCOUNT as EARTH
from sim.game import Game
from sim.persist import default_routes

T0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def main(days: int) -> None:
    game = Game.open(":memory:", now=T0, routes=default_routes())
    ledger = game.world.ledger
    made, earth = ledger.credits_in_existence(), ledger.balance(EARTH, CREDIT)
    owed: dict[str, int] = {}
    started = time.time()
    for day in range(1, days + 1):
        for _ in range(24):
            game.step()
        for row in game.db.execute("SELECT player_id, owed FROM town"):
            owed[row[0]] = max(owed.get(row[0], 0), row[1])
        if day % 10 == 0 or day == days:
            print(f"day {day:3d} ({time.time() - started:4.0f} s)")
            for t in game.towns_view():
                people = "silent" if t["lost"] else f"{t['population']:3d} people"
                print(f"    {t['company']:24s} {people:>10s}  {t['tier']:7s} "
                      f"{t['buildings']:3d} buildings  {t['sold_t']:3d} t sold  "
                      f"crew {t['crews']}")
    assert ledger.credits_in_existence() == made, "credits were created"
    ledger.assert_conserved()
    faults = game.db.execute(
        "SELECT COALESCE(SUM(faults), 0) FROM town").fetchone()[0]
    income = game.db.execute(
        "SELECT COALESCE(SUM(p.amount), 0) FROM posting p JOIN txn t "
        "ON t.id = p.txn_id WHERE t.kind = 'town_income' AND p.amount > 0"
    ).fetchone()[0]
    print(f"\nno credit created; {faults} failed town hours; "
          f"{ledger.credits_destroyed():,} cr burned by sinks")
    print(f"Earth paid {income:,} cr as town income and is down "
          f"{earth - ledger.balance(EARTH, CREDIT):,} cr in all")
    for row in game.db.execute(
            "SELECT p.id, p.name, t.yard FROM player p JOIN town t "
            "ON t.player_id = p.id WHERE p.house = 1 ORDER BY p.created_tick"):
        book = json.loads(row["yard"] or "{}")
        print(f"    {row['name']:24s} holds "
              f"{ledger.balance('player:' + row['id'], CREDIT):>10,} cr, "
              f"owed at most {owed.get(row['id'], 0):>8,}; made "
              f"{book.get('made_kg', 0) / 1000:5.1f} t, fitted "
              f"{book.get('used_kg', 0) / 1000:5.1f} t as parts, Earth "
              f"landed {book.get('landed_kg', 0) / 1000:5.1f} t")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
