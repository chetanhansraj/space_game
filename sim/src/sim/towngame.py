"""A company's town, joined to the world.

The town is the city builder (`sim.town` runs its rules). This module is the
boundary between those rules and everything of value, and it keeps four
promises.

**One clock.** A town advances exactly one game hour per world tick, inside
the tick's transaction. It cannot be paused and it cannot be run forward, by
its owner or by anyone, and it advances whether or not its owner is there.
docs/DECISIONS.md D64: a promise to deliver in five days means nothing if a
town can run its own clock to meet it.

**One wallet.** The town has no money of its own. Its rules count in town
credits; one town credit is a thousand credits (D70). Before the rules run
they are handed the company's balance, and afterwards the difference is
posted to the ledger. So what a ship earns can build a habitat, and what a
foundry earns can buy propellant.

**No money from nothing.** When the town's rules pay the town (fares,
rents, contracts with agencies and companies on Earth, what Earth pays for
foundry output) the credits come out of Earth's account, the one faucet the
economy has (D40), and only while Earth can pay. When the rules charge the
town (supplies, upkeep, penalties, evacuations) the credits are burned.
What is spent building goes to the Ark's development fund, and a demolition
refund comes back out of it. Invariants 3 and 7.

**One town cannot stop the world.** Each town's hour runs in its own
savepoint. A failure costs that town its hour, is counted in `town.faults`,
and the world goes on.

A town may owe: the rules allow a base to run into debt, and the ledger
does not allow a balance below zero. So what a town cannot pay is recorded
as owed, the rules see the wallet as that much below zero (which is what
makes them stop building and sours the mood), and it is taken first from
whatever the company earns next.
"""

from __future__ import annotations

import hashlib
import logging
import math

from market.db import transaction
from market.money import CREDIT

from .earth import ACCOUNT as EARTH
from .errors import GameError
from .shocks import Event
from .town import Engine, TownError

log = logging.getLogger("solar.town")

#: Credits in one town credit. The city builder's prices (a solar array is
#: 12, a habitat 30) become thousands of credits: its economy sits about
#: where a new company's 120,000 cr stake does. *Invented*, D70.
KCR = 1_000
#: Paid by the Ark's development fund when a town is founded, so that a new
#: company starts the town with the 160 town credits the game was balanced
#: for. *Invented*, D70.
TOWN_GRANT = 40_000
#: A town may use the market once it has a working landing pad and this
#: many people: the city builder's "Base" tier. D71.
TRADE_POPULATION = 8


def town_seed(player_id: str, attempt: int = 0) -> int:
    digest = hashlib.sha256(f"town|{player_id}|{attempt}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


class TownOps:
    """What `Game` can do with towns. Mixed into `sim.game.Game`."""

    dev_fund_account: str
    _town_engine: Engine | None = None

    @property
    def town_engine(self) -> Engine:
        if self._town_engine is None:
            self._town_engine = Engine()
        return self._town_engine

    # -- storage ---------------------------------------------------------

    def _town_row(self, pid: str):
        return self.db.execute("SELECT * FROM town WHERE player_id = ?",
                               (pid,)).fetchone()

    def _town(self, player):
        row = self._town_row(player.id)
        if row is None:
            raise GameError("Your company has not founded a town yet.")
        return row

    # -- the wallet --------------------------------------------------------

    def _town_wallet(self, player, owed: int) -> float:
        """The company's balance as the town's rules see it, in town credits."""
        return (self.world.ledger.balance(player.account, CREDIT) - owed) / KCR

    def _town_settle(self, player, before: float, after: float, owed: int,
                     carry: float, now: str, *, building: bool
                     ) -> tuple[int, float]:
        """Post what the rules did to the wallet. Returns (owed, carry).

        ``carry`` is the fraction of a credit left over from last time, so
        that an income of a third of a credit an hour is a credit every
        three hours and not nothing for ever.
        """
        ledger = self.world.ledger
        exact = (after - before) * KCR + carry
        whole = math.floor(exact)
        carry = exact - whole
        if whole > 0:
            payer = self.dev_fund_account if building else EARTH
            paid = min(whole, ledger.balance(payer, CREDIT))
            if paid:
                ledger.transfer(
                    payer, player.account, CREDIT, paid,
                    kind="refund" if building else "town_income",
                    game_time=now, ref=player.id,
                    memo="demolition refund" if building
                    else "town income: fares, rents, contracts, exports")
        elif whole < 0:
            cost = -whole
            pay = min(cost, ledger.balance(player.account, CREDIT))
            if pay and building:
                ledger.transfer(player.account, self.dev_fund_account, CREDIT,
                                pay, kind="purchase", game_time=now,
                                ref=player.id, memo="town construction")
            elif pay:
                ledger.burn(player.account, pay, now, ref=player.id,
                            memo="town costs: supplies, upkeep, penalties")
            owed += cost - pay
        if owed:
            clear = min(owed, ledger.balance(player.account, CREDIT))
            if clear:
                ledger.burn(player.account, clear, now, ref=player.id,
                            memo="town debt settled")
                owed -= clear
        return owed, carry

    # -- founding ----------------------------------------------------------

    def found_town(self, player) -> dict:
        """Land four people on an equatorial plot at sunrise. One per company."""
        if self._town_row(player.id) is not None:
            raise GameError("Your company already has a town.")
        ledger, tick, now = self.world.ledger, self.world.tick, self.world.game_time()
        with self._mutation():
            if ledger.balance(self.dev_fund_account, CREDIT) >= TOWN_GRANT:
                ledger.transfer(self.dev_fund_account, player.account, CREDIT,
                                TOWN_GRANT, kind="grant", game_time=now,
                                ref=player.id, memo="town founding grant")
            seed = town_seed(player.id)
            made = self._engine_call(
                "create", seed, self._town_wallet(player, 0))
            self.db.execute(
                "INSERT INTO town (player_id, founded_tick, seed, attempt, "
                "state) VALUES (?, ?, ?, 0, ?)",
                (player.id, tick, seed, made.state))
            self._message(player.id, "ark_development_office", "town_charter",
                          {"company": player.name, "grant": TOWN_GRANT,
                           "trade_population": TRADE_POPULATION})
            self._log([Event(
                tick=tick, kind="town_founded", subject=player.id,
                detail=f"{player.name} founded a town on the lunar equator",
                data={"player": player.id, "company": player.name})])
        return self.town_meta(player)

    def refound_town(self, player) -> dict:
        """Send a new crew to a town that has fallen silent."""
        row = self._town(player)
        if self.town_engine.summary(row["state"])["phase"] != "lost":
            raise GameError("Your town is still alive.")
        attempt = row["attempt"] + 1
        seed = town_seed(player.id, attempt)
        with self._mutation():
            made = self._engine_call(
                "create", seed, self._town_wallet(player, row["owed"]))
            self.db.execute(
                "UPDATE town SET state = ?, seed = ?, attempt = ?, "
                "founded_tick = ?, carry = 0, lost_tick = NULL "
                "WHERE player_id = ?",
                (made.state, seed, attempt, self.world.tick, player.id))
        return self.town_meta(player)

    def _engine_call(self, name: str, *args):
        try:
            return getattr(self.town_engine, name)(*args)
        except TownError as exc:
            log.error("%s", exc)
            raise GameError("The town could not take that just now.") from exc

    # -- a request from the player -------------------------------------------

    def town_intent(self, player, intent: dict) -> dict:
        """One of the game's own requests: place, zone, demolish and so on.

        The rules decide. This only hands them the wallet and posts what
        they did with it.
        """
        row = self._town(player)
        before = self._town_wallet(player, row["owed"])
        result, reason = self._engine_call("apply", row["state"], intent,
                                           before)
        if result is None:
            raise GameError(reason)
        now = self.world.game_time()
        with self._mutation():
            owed, carry = self._town_settle(
                player, before, result.credits, row["owed"], row["carry"],
                now, building=True)
            self.db.execute(
                "UPDATE town SET state = ?, owed = ?, carry = ? "
                "WHERE player_id = ?",
                (result.state, owed, carry, player.id))
        return self.town_meta(player)

    # -- the hour ------------------------------------------------------------

    def _tick_towns(self, now: str) -> list[Event]:
        """Every town's hour, inside the world's. One failure stops one town."""
        events: list[Event] = []
        rows = self.db.execute(
            "SELECT * FROM town WHERE lost_tick IS NULL "
            "ORDER BY founded_tick, player_id").fetchall()
        for row in rows:
            try:
                with transaction(self.db):
                    events += self._tick_town(row, now)
            except Exception:
                log.exception("town of %s failed its hour at tick %d",
                              row["player_id"], self.world.tick)
                self.db.execute("UPDATE town SET faults = faults + 1 "
                                "WHERE player_id = ?", (row["player_id"],))
        return events

    def _tick_town(self, row, now: str) -> list[Event]:
        player = self.player(row["player_id"])
        before = self._town_wallet(player, row["owed"])
        result = self.town_engine.tick(row["state"], 1.0, before)
        owed, carry = self._town_settle(
            player, before, result.credits, row["owed"], row["carry"], now,
            building=False)
        lost = result.summary["phase"] == "lost"
        self.db.execute(
            "UPDATE town SET state = ?, owed = ?, carry = ?, lost_tick = ? "
            "WHERE player_id = ?",
            (result.state, owed, carry, self.world.tick if lost else None,
             player.id))
        if not lost:
            return []
        self._message(player.id, "ark_development_office", "town_lost",
                      {"company": player.name,
                       "hours": int(result.summary["t"])})
        return [Event(tick=self.world.tick, kind="town_lost",
                      subject=player.id,
                      detail=f"{player.name}'s town has fallen silent",
                      data={"player": player.id, "company": player.name})]

    # -- views ---------------------------------------------------------------

    def town_meta(self, player) -> dict:
        """Everything about a town except its state, which is sent as it is."""
        world = self.world
        row = self._town_row(player.id)
        meta = {
            "company": player.name,
            "credits": world.ledger.balance(player.account, CREDIT),
            "kcr": KCR, "grant": TOWN_GRANT,
            "tick": world.tick, "date": self.display_date(),
            "tick_started_at": self.tick_starts_at(world.tick).isoformat(),
            "tick_seconds": (self.tick_starts_at(1)
                             - self.tick_starts_at(0)).total_seconds(),
            "founded": row is not None,
        }
        if row is None:
            return meta
        summary = self.town_engine.summary(row["state"])
        meta.update(
            founded_tick=row["founded_tick"], owed=row["owed"],
            faults=row["faults"], attempt=row["attempt"],
            wallet=self._town_wallet(player, row["owed"]),
            summary=summary,
            trade={"open": bool(summary["pad"]
                               and summary["population"] >= TRADE_POPULATION),
                   "pad": bool(summary["pad"]),
                   "population": summary["population"],
                   "needs_population": TRADE_POPULATION})
        return meta

    def town_state(self, player) -> str | None:
        """The town itself, as the JSON text the rules produced."""
        row = self._town_row(player.id)
        return None if row is None else row["state"]
