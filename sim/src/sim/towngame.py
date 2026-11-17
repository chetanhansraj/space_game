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
import json
import logging
import math

from market.book import ASK
from market.db import transaction
from market.errors import MarketError
from market.money import CREDIT

from . import TICKS_PER_GAME_DAY
from .earth import ACCOUNT as EARTH
from .errors import GameError
from .seed_world import TONNE, TRANQUILLITATIS
from .ships import KESTREL
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
#: What a town is founded with, at least: the 160 town credits the game was
#: balanced for. A new company has exactly this after the grant. A company
#: that has been in the world a while and has less (its stake spent, or
#: eaten by charter fees while its owner was away) is brought up to it, once,
#: when it founds its town, and its capped arrears are covered so that the
#: first midnight does not take the difference back. This hands out nothing
#: a new company would not get: anyone can have 160,000 cr from the same
#: fund by founding one. *Invented*, D78.
TOWN_START = 160_000
#: A town may use the market once it has a working landing pad and this
#: many people: the city builder's "Base" tier. D71.
TRADE_POPULATION = 8


#: Every town stands on the equatorial flats, so its goods come to market at
#: that port. When towns can be founded elsewhere this becomes a column.
TOWN_NODE = TRANQUILLITATIS
#: What a town's foundries make: sintered parts, fittings, structural
#: sections. The market's "manufactured goods". D75.
YARD_ASSET = "GOODS"
#: What the yard beside the landing pad holds. When it is full the
#: foundries stop and their shifts are sent home. *Invented*, D75: about two
#: game days of what Earth will take, so a town that stops selling has days,
#: not hours, before its industry stands idle.
YARD_KG = 20 * TONNE


def town_seed(player_id: str, attempt: int = 0) -> int:
    digest = hashlib.sha256(f"town|{player_id}|{attempt}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


class TownOps:
    """What `Game` can do with towns. Mixed into `sim.game.Game`."""

    dev_fund_account: str
    arrears_cap: int
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

    # -- the yard ------------------------------------------------------------

    def _yard_account(self, player) -> str:
        """The ledger account that holds a town's unsold goods. Made once.

        Separate from the company's own account, which is its ship: goods
        in the yard are not in the hold until they are loaded.
        """
        account = f"town:{player.id}"
        exists = self.db.execute("SELECT 1 FROM account WHERE id = ?",
                                 (account,)).fetchone()
        if not exists:
            self.world.ledger.open_account(
                account, "player", self.world.game_time(),
                label=f"{player.name} town yard")
        return account

    def _yard_book(self, row) -> dict:
        """The standing instruction and the running totals. Defaults filled."""
        book = json.loads(row["yard"] or "{}")
        anchor = self.world.ledger.asset(YARD_ASSET).base_value
        book.setdefault("sell", True)
        book.setdefault("min_price", anchor)
        for key in ("made_kg", "sold_kg", "sales", "day", "made_today",
                    "sold_today", "sales_today", "made_yesterday",
                    "sold_yesterday", "sales_yesterday"):
            book.setdefault(key, 0)
        book.setdefault("first_sale", False)
        return book

    def _yard_roll(self, book: dict) -> None:
        """Start a new game day's totals when the day has turned."""
        day = self.world.tick // TICKS_PER_GAME_DAY
        if book["day"] != day:
            fresh = book["day"] == day - 1
            for key in ("made", "sold", "sales"):
                book[f"{key}_yesterday"] = book[f"{key}_today"] if fresh else 0
                book[f"{key}_today"] = 0
            book["day"] = day

    def _trade_open(self, summary: dict) -> bool:
        return bool(summary["pad"]
                    and summary["population"] >= TRADE_POPULATION)

    def _yard_sell(self, player, account: str, book: dict, qty_kg: int,
                   limit: int, now: str):
        """Sell from the yard into the port's order book, now or not at all.

        Whole trading lots only, to whoever is bidding most, at their
        price and never below ``limit``. The takings go straight to the
        company. Nothing rests on the book afterwards: an order a player
        forgot about is not left standing in their name.
        """
        ledger = self.world.ledger
        lot = ledger.asset(YARD_ASSET).lot_mass_kg
        lots = min(qty_kg, ledger.balance(account, YARD_ASSET)) // lot
        if lots < 1:
            return None
        try:
            result = self._ioc(TOWN_NODE, YARD_ASSET, ASK, limit, lots * lot,
                               account, now)
        finally:
            takings = ledger.balance(account, CREDIT)
            if takings > 0:
                ledger.transfer(account, player.account, CREDIT, takings,
                                kind="sweep", game_time=now, ref=player.id,
                                memo="yard takings to the company")
        if result.filled_kg:
            value = sum(f.value for f in result.fills)
            book["sold_kg"] += result.filled_kg
            book["sold_today"] += result.filled_kg
            book["sales"] += value
            book["sales_today"] += value
        return result

    def _save_yard(self, pid: str, book: dict) -> None:
        self.db.execute("UPDATE town SET yard = ? WHERE player_id = ?",
                        (json.dumps(book, separators=(",", ":")), pid))

    def _town_trading(self, player):
        """The town's row, for a request that needs the market open."""
        row = self._town(player)
        summary = self.town_engine.summary(row["state"])
        if summary["phase"] == "lost":
            raise GameError("Your town has fallen silent.")
        if not self._trade_open(summary):
            raise GameError(
                "Nothing leaves the yard until the town has a working "
                f"landing pad and {TRADE_POPULATION} people.")
        return row

    def town_sell(self, player, qty_t: int, limit: int) -> dict:
        """Sell goods from the yard at the port, by hand."""
        row = self._town_trading(player)
        qty, limit = self._tonnes(qty_t), self._price(limit)
        account = self._yard_account(player)
        held = self.world.ledger.balance(account, YARD_ASSET)
        if qty > held:
            raise GameError(f"The yard holds {held // TONNE} t.")
        now = self.world.game_time()
        book = self._yard_book(row)
        with self._mutation():
            self._yard_roll(book)
            try:
                result = self._yard_sell(player, account, book, qty, limit,
                                         now)
            except MarketError as exc:
                raise GameError(str(exc)) from exc
            events = self._first_sale(player, book, result)
            self._save_yard(player.id, book)
            self._log(events)
        report = self._fill_report(result, "sold", YARD_ASSET)
        return {**self.town_meta(player), "report": report}

    def town_policy(self, player, sell: bool, min_price: int) -> dict:
        """Set the standing instruction: sell what is made, or hold it."""
        row = self._town(player)
        if not isinstance(sell, bool):
            raise GameError("Say whether to sell or to hold.")
        book = self._yard_book(row)
        book["sell"], book["min_price"] = sell, self._price(min_price)
        with self._mutation():
            self._save_yard(player.id, book)
        return self.town_meta(player)

    def _first_sale(self, player, book: dict, result) -> list[Event]:
        if book["first_sale"] or result is None or not result.filled_kg:
            return []
        book["first_sale"] = True
        return [Event(
            tick=self.world.tick, kind="town_first_sale", subject=player.id,
            detail=f"{player.name}'s town sold its first goods at the Flats",
            data={"player": player.id, "company": player.name,
                  "kg": result.filled_kg})]

    def _town_ship(self, player):
        ship = self._docked(player)
        if ship.location != TOWN_NODE:
            raise GameError("Your ship is not at Tranquillitatis Flats.")
        return ship

    def town_load(self, player, qty_t: int) -> dict:
        """Move goods from the yard into the company's ship at the port."""
        self._town_trading(player)
        ship = self._town_ship(player)
        qty = self._tonnes(qty_t)
        ledger, account = self.world.ledger, self._yard_account(player)
        held = ledger.balance(account, YARD_ASSET)
        if qty > held:
            raise GameError(f"The yard holds {held // TONNE} t.")
        room = KESTREL.cargo_capacity_kg - self.hold_used(player)
        if qty > room:
            raise GameError(f"Only {room // TONNE} t of space aboard.")
        with self._mutation():
            ledger.transfer(account, player.account, YARD_ASSET, qty,
                            kind="stow", game_time=self.world.game_time(),
                            ref=player.id, memo=f"{ship.id} loads from town")
            ship.loaded[YARD_ASSET] = ship.loaded.get(YARD_ASSET, 0) + qty
        return self.town_meta(player)

    def town_unload(self, player, qty_t: int) -> dict:
        """Put goods from the ship back in the yard."""
        self._town(player)
        ship = self._town_ship(player)
        qty = self._tonnes(qty_t)
        ledger, account = self.world.ledger, self._yard_account(player)
        aboard = ledger.balance(player.account, YARD_ASSET)
        if qty > aboard:
            raise GameError(f"You have {aboard // TONNE} t aboard.")
        room = YARD_KG - ledger.balance(account, YARD_ASSET)
        if qty > room:
            raise GameError(f"Only {room // TONNE} t of room in the yard.")
        with self._mutation():
            ledger.transfer(player.account, account, YARD_ASSET, qty,
                            kind="stow", game_time=self.world.game_time(),
                            ref=player.id, memo=f"{ship.id} unloads to town")
            if YARD_ASSET in ship.loaded:
                ship.loaded[YARD_ASSET] = max(0, ship.loaded[YARD_ASSET] - qty)
        return self.town_meta(player)

    # -- founding ----------------------------------------------------------

    def found_town(self, player) -> dict:
        """Land four people on an equatorial plot at sunrise. One per company."""
        if self._town_row(player.id) is not None:
            raise GameError("Your company already has a town.")
        ledger, tick, now = self.world.ledger, self.world.tick, self.world.game_time()
        arrears = min(player.upkeep_owed, self.arrears_cap)
        grant = max(TOWN_GRANT, TOWN_START + arrears
                    - ledger.balance(player.account, CREDIT))
        with self._mutation():
            if ledger.balance(self.dev_fund_account, CREDIT) >= grant:
                ledger.transfer(self.dev_fund_account, player.account, CREDIT,
                                grant, kind="grant", game_time=now,
                                ref=player.id, memo="town founding grant")
            seed = town_seed(player.id)
            made = self._engine_call(
                "create", seed, self._town_wallet(player, 0))
            self.db.execute(
                "INSERT INTO town (player_id, founded_tick, seed, attempt, "
                "state) VALUES (?, ?, ?, 0, ?)",
                (player.id, tick, seed, made.state))
            self._message(player.id, "ark_development_office", "town_charter",
                          {"company": player.name, "grant": grant,
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
        # Whoever sells first gets the best bid, so the first place moves
        # round by one each hour: no town is always at the front.
        turn = self.world.tick % len(rows) if rows else 0
        for row in rows[turn:] + rows[:turn]:
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
        ledger, account = self.world.ledger, self._yard_account(player)
        held = ledger.balance(account, YARD_ASSET)
        before = self._town_wallet(player, row["owed"])
        result = self.town_engine.tick(row["state"], 1.0, before,
                                       {"cap": YARD_KG, "held": held})
        owed, carry = self._town_settle(
            player, before, result.credits, row["owed"], row["carry"], now,
            building=False)
        lost = result.summary["phase"] == "lost"
        self.db.execute(
            "UPDATE town SET state = ?, owed = ?, carry = ?, lost_tick = ? "
            "WHERE player_id = ?",
            (result.state, owed, carry, self.world.tick if lost else None,
             player.id))

        # What the foundries made this hour is cargo, at the port, on the
        # ledger. No credits are created here: it is worth what somebody
        # with money of their own will pay for it, and nothing until then.
        events: list[Event] = []
        book = self._yard_book(row)
        self._yard_roll(book)
        made = min(result.made, YARD_KG - held)
        if made > 0:
            ledger.extract(account, YARD_ASSET, made, now,
                           memo=f"{player.name} town foundries")
            book["made_kg"] += made
            book["made_today"] += made
        if (not lost and book["sell"] and self._trade_open(result.summary)):
            bid = self.world.books[TOWN_NODE].best_bid(YARD_ASSET)
            if bid and bid >= book["min_price"]:
                try:
                    with transaction(self.db):
                        sold = self._yard_sell(
                            player, account, book,
                            ledger.balance(account, YARD_ASSET),
                            book["min_price"], now)
                    events += self._first_sale(player, book, sold)
                except MarketError:
                    pass    # the book refused it this hour; try the next
        self._save_yard(player.id, book)
        if not lost:
            return events
        self._message(player.id, "ark_development_office", "town_lost",
                      {"company": player.name,
                       "hours": int(result.summary["t"])})
        return events + [Event(
            tick=self.world.tick, kind="town_lost", subject=player.id,
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
            trade={"open": self._trade_open(summary),
                   "pad": bool(summary["pad"]),
                   "population": summary["population"],
                   "needs_population": TRADE_POPULATION},
            yard=self._yard_view(player, row, summary))
        return meta

    def _yard_view(self, player, row, summary: dict) -> dict:
        """The yard as the screen shows it. Reads only."""
        ledger = self.world.ledger
        spec = ledger.asset(YARD_ASSET)
        market = self.world.books[TOWN_NODE]
        account = f"town:{player.id}"
        book = self._yard_book(row)
        day = self.world.tick // TICKS_PER_GAME_DAY
        today = book["day"] == day
        ship = self.ship_of(player)
        docked = (ship.state.value == "docked" and ship.location == TOWN_NODE)
        return {
            "asset": YARD_ASSET, "name": spec.name, "node": TOWN_NODE,
            "held_kg": ledger.balance(account, YARD_ASSET),
            "cap_kg": YARD_KG, "lot_kg": spec.lot_mass_kg,
            "anchor": spec.base_value,
            "make_kg_per_hour": summary.get("make", 0),
            "foundries": summary.get("foundries", 0),
            "full": bool(summary.get("yardFull")),
            "bid": market.best_bid(YARD_ASSET),
            "last": market.last_price(YARD_ASSET),
            "sell": book["sell"], "min_price": book["min_price"],
            "made_kg": book["made_kg"], "sold_kg": book["sold_kg"],
            "sales": book["sales"],
            "made_today": book["made_today"] if today else 0,
            "sold_today": book["sold_today"] if today else 0,
            "sales_today": book["sales_today"] if today else 0,
            "sold_yesterday": (book["sold_today"] if book["day"] == day - 1
                               else book["sold_yesterday"] if today else 0),
            "sales_yesterday": (book["sales_today"] if book["day"] == day - 1
                                else book["sales_yesterday"] if today else 0),
            "ship": {"here": docked,
                     "aboard_kg": ledger.balance(player.account, YARD_ASSET),
                     "room_kg": max(0, KESTREL.cargo_capacity_kg
                                    - self.hold_used(player))},
        }

    def town_state(self, player) -> str | None:
        """The town itself, as the JSON text the rules produced."""
        row = self._town_row(player.id)
        return None if row is None else row["state"]
