#!/usr/bin/env python3
"""A watchable market at Shackleton Depot.

This is a DEMO HARNESS, not `sim/`. The real world tick -- agent utility
functions, depletion curves, shocks, named agents -- is not built yet. What
this does is wire the finished pieces together so the market can be watched
doing something, which is the v1 question from the bible:

    "Can you watch this market for ten minutes, with zero other players,
     and find it interesting?"

The agents here are deliberately stupid: a miner that digs and sells, a
refiner that buys ice and sells propellant, and a hauler that consumes.
None of them reason. They are here to generate order flow, not to be the
agent model.

Everything below the surface is real: the same ledger, the same escrowed
order books, the same Ark Authority as the tests. Conservation is checked
after every single tick and printed, so if the economy ever leaked a credit
you would watch it happen.

    python scripts/demo_market.py --ticks 40
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "market" / "src"))

from market.authority import ACCOUNT as ARK
from market.authority import ArkAuthority
from market.book import ASK, BID, OrderBook
from market.db import connect, transaction
from market.errors import MarketError
from market.ledger import Ledger
from market.money import CREDIT, format_credits, format_mass
from market.seed import seed_assets

NODE = "shackleton_depot"
TONNE = 1_000

# lunarark.com's palette, approximately, as ANSI 256.
V = "\033[38;5;141m"   # violet
C = "\033[38;5;80m"    # cyan
G = "\033[38;5;77m"    # live green
A = "\033[38;5;214m"   # amber
R = "\033[38;5;203m"   # critical
D = "\033[38;5;245m"   # dim
W = "\033[38;5;255m"   # bright
X = "\033[0m"
B = "\033[1m"


def label(text: str) -> str:
    return f"{C}{text.upper()}{X}"


class Demo:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.db = connect(":memory:")
        self.ledger = Ledger(self.db)
        self.book = OrderBook(self.db, self.ledger, NODE)
        self.ark = ArkAuthority(self.db, self.ledger, self.book)
        self.tick = 0
        self.bankrupt: set[str] = set()

    def build_world(self) -> None:
        t = self.time()
        with transaction(self.db):
            self.ledger.bootstrap(t)
            seed_assets(self.ledger)
            self.ark.establish(t, treasury=200_000_000)
            self.ark.endow("ICE", 2_000 * TONNE, t)
            self.ark.endow("PROP", 400 * TONNE, t)

            for name in ("miner_a", "miner_b", "miner_c"):
                self.ledger.open_account(name, "agent", t, label=name)
                self.ledger.mint(name, 200_000, t, memo=f"{name} opening capital")
            for name in ("refinery_a", "refinery_b"):
                self.ledger.open_account(name, "agent", t, label=name)
                self.ledger.mint(name, 2_000_000, t, memo=f"{name} opening capital")
            for name in ("hauler_a", "hauler_b"):
                self.ledger.open_account(name, "agent", t, label=name)
                self.ledger.mint(name, 1_500_000, t, memo=f"{name} opening capital")

        for symbol in ("ICE", "PROP"):
            self.ark.quote(symbol, t, bid_lots=120, ask_lots=120)

    def time(self) -> str:
        return f"2190-01-01T{self.tick // 60:02d}:{self.tick % 60:02d}:00Z"

    # -- the agents, such as they are ---------------------------------

    def run_tick(self) -> None:
        self.tick += 1
        t = self.time()

        for miner in ("miner_a", "miner_b", "miner_c"):
            dug = self.rng.randrange(8, 25) * TONNE
            with transaction(self.db):
                self.ledger.extract(miner, "ICE", dug, t, memo="ice extraction")
            self._pay(miner, 300, "site upkeep")
            self._offer(miner, "ICE", ASK, self._near("ICE", ASK), dug)

        for refinery in ("refinery_a", "refinery_b"):
            self._offer(refinery, "ICE", BID, self._near("ICE", BID),
                        self.rng.randrange(10, 30) * TONNE)
            held = self.ledger.balance(refinery, "ICE")
            if held >= 10 * TONNE:
                converted = (held // TONNE) * TONNE
                with transaction(self.db):
                    self.ledger.consume(refinery, "ICE", converted, t,
                                        memo="electrolysis feedstock")
                    # 30 t/day water -> LOX/LH2, seed-data. Lossy on purpose.
                    self.ledger.extract(refinery, "PROP", converted * 3 // 4, t,
                                        memo="electrolysis output")
                self._pay(refinery, 2_000, "plant power")
                self._offer(refinery, "PROP", ASK, self._near("PROP", ASK),
                            converted * 3 // 4)

        for hauler in ("hauler_a", "hauler_b"):
            self._offer(hauler, "PROP", BID, self._near("PROP", BID),
                        self.rng.randrange(5, 18) * TONNE)
            burned = self.ledger.balance(hauler, "PROP")
            if burned >= 5 * TONNE:
                with transaction(self.db):
                    self.ledger.consume(hauler, "PROP", (burned // TONNE) * TONNE,
                                        t, memo="transit burn")
                self._pay(hauler, 800, "docking fee")

        if self.tick % 6 == 0:
            for symbol in ("ICE", "PROP"):
                self.ark.quote(symbol, t, bid_lots=120, ask_lots=120)

        self.ledger.assert_conserved()

    def _pay(self, who: str, amount: int, memo: str) -> None:
        """Pay a cost into the sink, or go bankrupt trying.

        An agent that cannot pay its upkeep is broke. That is an event in the
        world, not an error: the ledger refuses to let any account go
        negative, so the attempt simply fails and the agent is recorded as
        insolvent. Getting this wrong is what made the first long run of this
        demo crash at tick 76 rather than showing two haulers quietly running
        out of money, which is far more interesting.
        """
        try:
            with transaction(self.db):
                self.ledger.burn(who, amount, self.time(), memo=memo)
        except MarketError:
            self.bankrupt.add(who)

    def _near(self, symbol: str, side: str) -> int:
        """Quote a little inside the current market, with some noise."""
        asset = self.ledger.asset(symbol)
        reference = (self.book.last_price(symbol)
                     or self.book.best_bid(symbol)
                     or asset.base_value)
        drift = self.rng.uniform(0.90, 1.10)
        edge = 0.97 if side == ASK else 1.03
        return max(1, int(reference * drift * edge))

    def _offer(self, who: str, symbol: str, side: str, price: int,
               qty_kg: int) -> None:
        if qty_kg <= 0:
            return
        try:
            self.book.place(symbol, side, price, qty_kg, who, self.time())
        except MarketError:
            pass  # refused for want of funds or goods; the agent simply waits

    # -- the view ------------------------------------------------------

    def render(self) -> None:
        print(f"\n{V}{B}{'─' * 74}{X}")
        print(f"{V}{B} SHACKLETON DEPOT {X}{D}· spot market ·{X} "
              f"{G}● LIVE{X}  {D}tick{X} {W}{self.tick:>4}{X}  "
              f"{D}game time{X} {W}{self.time()[11:16]}{X}")
        print(f"{V}{'─' * 74}{X}")

        for symbol in ("ICE", "PROP"):
            self._render_book(symbol)

        credits = self.ledger.credits_in_existence()
        burned = self.ledger.credits_destroyed()
        if self.bankrupt:
            print(f"\n {label('insolvent')} {R}{', '.join(sorted(self.bankrupt))}{X}"
                  f"  {D}cannot meet upkeep{X}")
        print(f"\n {label('credits in world')} {W}{format_credits(credits - burned):>12}{X}"
              f"   {label('destroyed by sinks')} {A}{format_credits(burned):>11}{X}"
              f"   {label('conserved')} {G}✓{X}")

    def _render_book(self, symbol: str) -> None:
        asset = self.ledger.asset(symbol)
        bid, ask = self.book.best_bid(symbol), self.book.best_ask(symbol)
        last = self.book.last_price(symbol)
        share = self.ark.share_of_volume(symbol)

        row = self.db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(qty_kg),0) v FROM trade "
            "WHERE node = ? AND asset = ?", (NODE, symbol)
        ).fetchone()

        print(f"\n {V}{B}{asset.name.upper()}{X}  {D}lot {format_mass(asset.lot_mass_kg)}"
              f" · seed {asset.base_value} cr{X}")
        print(f"   {label('bid'):<22} {G}{bid if bid else '--':>9}{X}"
              f"   {label('ask'):<22} {R}{ask if ask else '--':>9}{X}")
        print(f"   {label('last'):<22} {W}{last if last else '--':>9}{X}"
              f"   {label('trades'):<22} {W}{row['n']:>9}{X}")
        print(f"   {label('volume'):<22} {W}{format_mass(row['v']):>9}{X}"
              f"   {label('ark share of volume'):<22} "
              f"{(A if share > 0.5 else G)}{share:>8.0%}{X}")

        depth_bid = self.book.depth(symbol, BID, 3)
        depth_ask = self.book.depth(symbol, ASK, 3)
        print(f"   {D}depth{X}  ", end="")
        for price, qty in depth_bid:
            print(f"{G}{price}{D}×{qty // asset.lot_mass_kg}{X} ", end="")
        print(f"{D}|{X} ", end="")
        for price, qty in depth_ask:
            print(f"{R}{price}{D}×{qty // asset.lot_mass_kg}{X} ", end="")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=30)
    parser.add_argument("--every", type=int, default=5,
                        help="render every N ticks")
    parser.add_argument("--seed", type=int, default=20260904,
                        help="RNG seed; the same seed replays identically")
    args = parser.parse_args()

    demo = Demo(args.seed)
    demo.build_world()
    print(f"{D}seed {args.seed} · replaying this seed gives an identical run{X}")
    demo.render()

    for _ in range(args.ticks):
        demo.run_tick()
        if demo.tick % args.every == 0:
            demo.render()

    print(f"\n{V}{'─' * 74}{X}")
    print(f" {label('final holdings')}")
    for name in ("miner_a", "refinery_a", "hauler_a", ARK):
        holdings = demo.ledger.holdings(name)
        cash = format_credits(holdings.pop(CREDIT, 0))
        goods = "  ".join(f"{k} {format_mass(v)}" for k, v in sorted(holdings.items()))
        print(f"   {W}{name:<28}{X} {cash:>14}   {D}{goods}{X}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
