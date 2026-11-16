"""Play a base for a while and print the books.

    .venv/bin/python scripts/demo_base.py [game days] [warm-up ticks]

A bot signs up, takes a charter on the Shackleton rim, has the engineer stand
the Ark's kit and leaves the standing orders on. Pass "best" as a third
argument and it then moves the miners to the richest ice, as a player would. This is how the base
figures in docs/DECISIONS.md D59 were tuned: by running it, not by argument.
"""

from __future__ import annotations

import datetime as dt
import sys
from market.money import CREDIT
from sim.game import Game


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    warm = int(sys.argv[2]) if len(sys.argv) > 2 else 168
    best = (sys.argv[3] if len(sys.argv) > 3 else "plain") == "best"
    now = dt.datetime(2026, 11, 16, tzinfo=dt.timezone.utc)
    game = Game.open(":memory:", now=now, warmup_ticks=warm)
    player, _ = game.signup("Demo Works")
    game.charter_base(player, "shackleton_rim")
    game.base_stand_kit(player)
    if best:
        # What a player who read the survey does: both miners to the two
        # richest patches, with conduit run out to them.
        view = game.base_view(player)["base"]
        rich = sorted(view["layout"]["patches"], key=lambda p: -p["grade"])
        miners = [m for m in view["modules"] if m["type"] == "ice_miner"]
        for miner, patch in zip(miners, rich):
            x, y = patch["tiles"][0]
            game.base_move(player, miner["id"], x, y)
        # The engineer knows the way round the rocks: unpack nothing, and
        # take only the conduit from the suggestion.
        import json
        from sim import base
        row = game.db.execute("SELECT state FROM base").fetchone()
        state = json.loads(row["state"])
        _, lay = base.suggest_layout(
            state, base.site_layout(state["seed"], state["size"]))
        if lay:
            game.base_conduit(player, lay)
    ledger = game.world.ledger
    start = ledger.balance(player.account, CREDIT)
    print(f"start {start:,} cr")
    print(" day   credits     net  ice t  prop t  sold t   sales    feed   "
          "lease  upkeep   wages   ICE bid/ask  PROP bid/ask  status")
    last = start
    for day in range(1, days + 1):
        for _ in range(24):
            game.step()
        v = game.base_view(player)
        b = v["base"]
        y = b["books"]["yesterday"]
        cash = v["credits"]
        pr = v["prices"]
        fmt = lambda a: f"{pr.get(a, {}).get('bid')}/{pr.get(a, {}).get('ask')}"
        states = sorted(set(m["status"] for m in b["modules"]))
        print(f"{day:4d} {cash:9,} {cash - last:7,} "
              f"{y.get('made_kg_ICE', 0) / 1000:6.1f} "
              f"{y.get('made_kg_PROP', 0) / 1000:7.1f} "
              f"{y.get('sold_kg_PROP', 0) / 1000:7.1f} "
              f"{y.get('sales', 0):7,} {y.get('feed', 0):7,} "
              f"{y.get('lease', 0):7,} {y.get('upkeep', 0):7,} "
              f"{y.get('wages', 0):7,}   {fmt('ICE'):>11}  {fmt('PROP'):>12}  "
              f"{','.join(states)}")
        last = cash
    row = game.db.execute("SELECT faults, owed FROM base").fetchone()
    print(f"faults {row['faults']}, owed {row['owed']:,}, "
          f"milestones {[m['id'] for m in b['milestones'] if m['done']]}")
    r = b["report"]
    print(f"power {r['power']}, heat {r['heat']}, crew {r['crew']}, "
          f"stock {b['stock']}, capacity {b['capacity']}")
    ledger.assert_conserved()


if __name__ == "__main__":
    main()
