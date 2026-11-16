"""A company's base, joined to the world.

`sim.base` is the physics: which modules run and what they make. This module
is everything that touches value -- the ledger, the port's order book, the
Ark's fund -- and it is where the invariants are kept:

- **Nothing here creates a credit.** A base earns by selling real stock on
  the port's book to whoever is bidding. The Ark's milestone bonuses are
  transfers out of the finite development fund, like the starting grant
  (D44). Modules bought are paid for *into* that fund; leases, upkeep and
  arrears are burned. Invariant 3, invariant 7.
- **Stock is the ledger's.** Ice and propellant sit in the base's own
  account, `base:<player>`, so a Kestrel's hold and a base's tanks are never
  confused. Credits never rest there: every sale is swept to the company's
  one wallet in the same transaction.
- **A base's hour is part of the world's hour.** `_tick_bases` runs inside
  the tick's transaction. Each base runs in its own savepoint, so a base
  that fails loses its own hour and is counted, and the world goes on. A
  live economy must not stop because one company's site hit a bug.
- **Standing orders never rest.** D45 keeps player orders immediate-or-
  cancel because an order left on the book is escrow someone forgot. A
  standing order here is the same immediate-or-cancel order, placed again
  each hour by the base's comms relay.

Every money figure below is *invented* and recorded in docs/DECISIONS.md D59;
the module prices are docs/seed-data.md's.
"""

from __future__ import annotations

import json
import logging

from market.book import ASK, BID
from market.db import transaction
from market.errors import MarketError
from market.money import CREDIT

from . import TICKS_PER_GAME_DAY, base
from .base import MODULES, SITES, TONNE, BaseError
from .contracts import encode
from .errors import GameError
from .firms import Role
from .ships import KESTREL
from .shocks import Event

log = logging.getLogger("solar.base")

#: Basis points of list price, per game day. A leased module costs its lease
#: and its upkeep; an owned one only its upkeep.
LEASE_BP_PER_DAY = 10
UPKEEP_BP_PER_DAY = 3
#: Paid to the port's households, like every other payroll in the world.
WAGE_PER_CREW_DAY = 1_500
#: List price of everything a company may hold on lease at once.
LEASE_CAP = 12_000_000
#: Share of propellant held beyond tank capacity that boils off in an hour.
BOIL_OFF_PERCENT = 2
#: A problem is worth a letter once it has lasted this long.
ALERT_AFTER_HOURS = 6

#: What a base holds and trades.
STOCKED = ("ICE", "PROP")

#: The Ark's development bonuses: (id, what for, credits). Each is paid once,
#: out of the development fund, and only while the fund can afford it.
MILESTONES = (
    ("desk", "Command post staffed", 20_000),
    ("first_prop", "First propellant made", 30_000),
    ("first_sale", "First sale from the base", 30_000),
    ("full_feed", "Thirty tonnes of ice through the plant in a day", 40_000),
    ("own", "First module bought outright", 30_000),
)

NODE_NAMES = {
    "shackleton_depot": "Shackleton Depot",
    "peary_ridge": "Peary Ridge",
    "tranquillitatis_flats": "Tranquillitatis Flats",
}


def lease_per_day(cost: int) -> int:
    return cost * LEASE_BP_PER_DAY // 10_000


def upkeep_per_day(cost: int) -> int:
    return cost * UPKEEP_BP_PER_DAY // 10_000


class BaseOps:
    """What `Game` can do with bases. Mixed into `sim.game.Game`."""

    dev_fund_account: str

    # -- storage ---------------------------------------------------------

    def _base_row(self, pid: str):
        return self.db.execute("SELECT * FROM base WHERE player_id = ?",
                               (pid,)).fetchone()

    def _base(self, player):
        row = self._base_row(player.id)
        if row is None:
            raise GameError("Your company has no base yet.")
        return row, json.loads(row["state"])

    def _save_base(self, pid: str, state: dict, owed: int | None = None
                   ) -> None:
        if owed is None:
            self.db.execute("UPDATE base SET state = ? WHERE player_id = ?",
                            (encode(state), pid))
        else:
            self.db.execute(
                "UPDATE base SET state = ?, owed = ? WHERE player_id = ?",
                (encode(state), owed, pid))

    # -- small books: what the base made, sold and paid ---------------------

    @staticmethod
    def _tally(state: dict, key: str, amount: int) -> None:
        if not amount:
            return
        for book in (state["books"]["today"], state["away"]):
            book[key] = book.get(key, 0) + amount

    def _roll_books(self, state: dict) -> None:
        day = self.world.tick // TICKS_PER_GAME_DAY
        books = state["books"]
        if books["day"] != day:
            books["yesterday"] = books["today"] if books["day"] == day - 1 else {}
            books["today"], books["day"] = {}, day

    # -- the Ark's fund ----------------------------------------------------

    def _pay_ark(self, player, amount: int, now: str, memo: str) -> None:
        self.world.ledger.transfer(
            player.account, self.dev_fund_account, CREDIT, amount,
            kind="purchase", game_time=now, ref=player.id, memo=memo)

    def _afford(self, player, amount: int, what: str) -> None:
        cash = self.world.ledger.balance(player.account, CREDIT)
        if cash < amount:
            raise GameError(f"{what} costs {amount:,} cr; you have {cash:,}.")

    def _milestone(self, state: dict, player, mid: str, now: str
                   ) -> list[Event]:
        """Pay a development bonus, once, if the fund can."""
        if mid in state["milestones"]:
            return []
        title, bonus = next((t, b) for i, t, b in MILESTONES if i == mid)
        ledger = self.world.ledger
        if ledger.balance(self.dev_fund_account, CREDIT) < bonus:
            return []           # the fund is spent; the bonus waits for it
        ledger.transfer(self.dev_fund_account, player.account, CREDIT, bonus,
                        kind="grant", game_time=now, ref=player.id,
                        memo=f"development bonus: {title}")
        state["milestones"].append(mid)
        self._tally(state, "bonus", bonus)
        self._message(player.id, "ark_development_office", "base_milestone",
                      {"milestone": mid, "title": title, "bonus": bonus})
        if mid != "first_prop":
            return []
        site = SITES[state["site"]]["name"]
        return [Event(tick=self.world.tick, kind="base_milestone",
                      subject=player.id,
                      detail=f"{player.name} made its first propellant on "
                             f"{site}",
                      data={"player": player.id, "company": player.name,
                            "milestone": mid, "site": state["site"]})]

    # -- founding ----------------------------------------------------------

    def charter_base(self, player, site: str) -> dict:
        """Take the Ark's charter on a site. One per company."""
        if site not in SITES:
            raise GameError("There is no site by that name.")
        if self._base_row(player.id) is not None:
            raise GameError("Your company already holds a site.")
        spec = SITES[site]
        tick, now = self.world.tick, self.world.game_time()
        account = f"base:{player.id}"
        state = base.new_state(site, seed=player.id, tick=tick)
        anchor = {a: self.world.ledger.asset(a).base_value for a in STOCKED}
        state.update(
            policy={
                "PROP": {"sell": True, "min_price": anchor["PROP"] * 60 // 100,
                         "keep_t": 0},
                "ICE": {"sell": False, "min_price": anchor["ICE"] * 60 // 100,
                        "keep_t": 0, "buy": True,
                        "max_price": anchor["ICE"] * 175 // 100,
                        "target_t": 10},
            },
            milestones=[], alerts={}, told=[],
            books={"day": tick // TICKS_PER_GAME_DAY, "today": {},
                   "yesterday": {}},
            away={"since": tick})
        with self._mutation():
            self.world.ledger.open_account(account, "player", now,
                                           label=f"{player.name} base")
            self.db.execute(
                "INSERT INTO base (player_id, site, node, account, "
                "created_tick, state) VALUES (?, ?, ?, ?, ?, ?)",
                (player.id, site, spec["node"], account, tick, encode(state)))
            self._message(player.id, "ark_development_office", "base_charter",
                          {"company": player.name, "site": site,
                           "site_name": spec["name"], "node": spec["node"],
                           "kit_value": base.leased_value(state),
                           "kit_modules": len(base.KIT),
                           "lease_per_day": lease_per_day(
                               base.leased_value(state)),
                           "lease_cap": LEASE_CAP})
            self._log([Event(
                tick=tick, kind="base_chartered", subject=player.id,
                detail=f"{player.name} took a charter on {spec['name']}",
                data={"player": player.id, "company": player.name,
                      "site": site, "node": spec["node"]})])
        return self.base_view(player)

    # -- building ----------------------------------------------------------

    def base_build(self, player, kind: str, x: int, y: int,
                   how: str = "buy") -> dict:
        """Stand a module: from its crate, on lease, or bought outright."""
        row, state = self._base(player)
        spec = MODULES.get(kind)
        if spec is None:
            raise GameError("The Ark's yard does not build that.")
        layout = base.site_layout(state["seed"], state["size"])
        tick, now = self.world.tick, self.world.game_time()
        try:
            if how == "crate":
                if kind not in state["crates"]:
                    raise GameError("There is no crate of those left.")
                base.place(state, layout, kind, x, y, tick, leased=True)
                state["crates"].remove(kind)
            elif how == "lease":
                if base.leased_value(state) + spec.cost > LEASE_CAP:
                    raise GameError(
                        f"The Ark leases a company {LEASE_CAP:,} cr of plant "
                        f"and no more. Buy this one, or buy out something "
                        f"you lease.")
                base.place(state, layout, kind, x, y, tick, leased=True)
            elif how == "buy":
                self._afford(player, spec.cost, f"A {spec.name}")
                base.place(state, layout, kind, x, y, tick, leased=False)
            else:
                raise GameError("Build from a crate, on lease, or buy.")
        except BaseError as exc:
            raise GameError(str(exc)) from exc
        with self._mutation():
            events = []
            if how == "buy":
                self._pay_ark(player, spec.cost, now,
                              f"{spec.name} for {state['site']}")
                self._roll_books(state)
                self._tally(state, "purchases", spec.cost)
                events = self._milestone(state, player, "own", now)
            self._save_base(player.id, state)
            self._log(events)
        return self.base_view(player)

    def base_stand_kit(self, player) -> dict:
        """Stand every crate still packed, the way the engineer would.

        A working layout, not a good one (`base.suggest_layout`). Crates are
        leased, so standing them is free; the conduit is paid for, and if
        the company cannot afford all of it, as much as it can.
        """
        row, state = self._base(player)
        if not state["crates"]:
            raise GameError("Every crate is already standing.")
        layout = base.site_layout(state["seed"], state["size"])
        plan, lay = base.suggest_layout(state, layout)
        tick, now = self.world.tick, self.world.game_time()
        try:
            for kind, x, y in plan:
                base.place(state, layout, kind, x, y, tick, leased=True)
                state["crates"].remove(kind)
            cash = self.world.ledger.balance(player.account, CREDIT)
            lay = lay[:max(0, cash // base.CONDUIT_COST)]
            laid = base.lay_conduit(state, layout, lay) if lay else 0
        except BaseError as exc:
            raise GameError(str(exc)) from exc
        with self._mutation():
            if laid:
                cost = laid * base.CONDUIT_COST
                self._pay_ark(player, cost, now, f"{laid} tiles of conduit")
                self._roll_books(state)
                self._tally(state, "purchases", cost)
            self._save_base(player.id, state)
        return self.base_view(player)

    def base_move(self, player, module_id: int, x: int, y: int) -> dict:
        row, state = self._base(player)
        layout = base.site_layout(state["seed"], state["size"])
        try:
            base.move(state, layout, module_id, x, y, self.world.tick)
        except BaseError as exc:
            raise GameError(str(exc)) from exc
        with self._mutation():
            self._save_base(player.id, state)
        return self.base_view(player)

    def base_remove(self, player, module_id: int) -> dict:
        """Take a module down. A leased one goes back; an owned one is scrap."""
        row, state = self._base(player)
        try:
            base.remove(state, module_id)
        except BaseError as exc:
            raise GameError(str(exc)) from exc
        with self._mutation():
            self._save_base(player.id, state)
        return self.base_view(player)

    def base_buyout(self, player, module_id: int) -> dict:
        """Buy a leased module from the Ark at list price."""
        row, state = self._base(player)
        try:
            module = base.find(state, module_id)
        except BaseError as exc:
            raise GameError(str(exc)) from exc
        if not module["leased"]:
            raise GameError("You already own that.")
        spec = MODULES[module["type"]]
        self._afford(player, spec.cost, f"Buying out the {spec.name}")
        now = self.world.game_time()
        module["leased"] = False
        with self._mutation():
            self._pay_ark(player, spec.cost, now,
                          f"buy-out of leased {spec.name}")
            self._roll_books(state)
            self._tally(state, "purchases", spec.cost)
            events = self._milestone(state, player, "own", now)
            self._save_base(player.id, state)
            self._log(events)
        return self.base_view(player)

    def base_conduit(self, player, tiles: list) -> dict:
        row, state = self._base(player)
        layout = base.site_layout(state["seed"], state["size"])
        try:
            laid = base.lay_conduit(state, layout, tiles)
        except BaseError as exc:
            raise GameError(str(exc)) from exc
        if not laid:
            raise GameError("Nowhere there to lay conduit.")
        cost = laid * base.CONDUIT_COST
        self._afford(player, cost, f"{laid} tiles of conduit")
        with self._mutation():
            self._pay_ark(player, cost, self.world.game_time(),
                          f"{laid} tiles of conduit")
            self._roll_books(state)
            self._tally(state, "purchases", cost)
            self._save_base(player.id, state)
        return self.base_view(player)

    def base_lift_conduit(self, player, x: int, y: int) -> dict:
        row, state = self._base(player)
        try:
            base.lift_conduit(state, x, y)
        except BaseError as exc:
            raise GameError(str(exc)) from exc
        with self._mutation():
            self._save_base(player.id, state)
        return self.base_view(player)

    # -- trading from the base ----------------------------------------------

    def _base_order(self, state: dict, player, account: str, node: str,
                    asset: str, side: str, price: int, qty_kg: int, now: str):
        """One immediate-or-cancel order from the base. Credits end swept.

        A bid is funded from the company's wallet for exactly as long as the
        order takes, and whatever is not spent goes straight back, so the
        base account never holds money between calls.
        """
        ledger = self.world.ledger
        lot = ledger.asset(asset).lot_mass_kg
        lots = qty_kg // lot
        if side == BID:
            lots = min(lots, ledger.balance(player.account, CREDIT) // price)
        if lots < 1:
            return None
        if side == BID:
            ledger.transfer(player.account, account, CREDIT, price * lots,
                            kind="float", game_time=now, ref=player.id,
                            memo=f"base {asset} bid, funded")
        try:
            result = self._ioc(node, asset, side, price, lots * lot, account,
                               now)
        finally:
            left = ledger.balance(account, CREDIT)
            if left > 0:
                ledger.transfer(account, player.account, CREDIT, left,
                                kind="sweep", game_time=now, ref=player.id,
                                memo="base takings to the company")
        value = sum(f.value for f in result.fills)
        if result.filled_kg:
            if side == ASK:
                self._tally(state, f"sold_kg_{asset}", result.filled_kg)
                self._tally(state, "sales", value)
            else:
                self._tally(state, f"bought_kg_{asset}", result.filled_kg)
                self._tally(state, "feed", value)
        return result

    def _room(self, row, state: dict, asset: str) -> int:
        report = state.get("report") or {}
        cap = (report.get("tank_kg", 0) if asset == "PROP"
               else report.get("store_kg", base.YARD_KG))
        return max(0, cap - self.world.ledger.balance(row["account"], asset))

    def base_sell(self, player, asset: str, qty_t: int, limit: int) -> dict:
        row, state = self._base(player)
        if asset not in STOCKED:
            raise GameError("Your base does not handle that.")
        qty, limit = self._tonnes(qty_t), self._price(limit)
        held = self.world.ledger.balance(row["account"], asset)
        if qty > held:
            raise GameError(f"The base holds {held // TONNE} t of that.")
        now = self.world.game_time()
        with self._mutation():
            self._roll_books(state)
            try:
                result = self._base_order(state, player, row["account"],
                                          row["node"], asset, ASK, limit, qty,
                                          now)
            except MarketError as exc:
                raise GameError(str(exc)) from exc
            if result is None:
                raise GameError("That is less than one trading lot.")
            events = []
            if result.filled_kg:
                events = self._milestone(state, player, "first_sale", now)
            self._save_base(player.id, state)
            self._log(events)
        return self._fill_report(result, "sold", asset)

    def base_buy(self, player, asset: str, qty_t: int, limit: int) -> dict:
        row, state = self._base(player)
        if asset not in STOCKED:
            raise GameError("Your base does not handle that.")
        qty, limit = self._tonnes(qty_t), self._price(limit)
        room = self._room(row, state, asset)
        if qty > room:
            raise GameError(f"Only {room // TONNE} t of room for that at "
                            f"the base.")
        self._afford(player, limit * qty_t, "That order")
        now = self.world.game_time()
        with self._mutation():
            self._roll_books(state)
            try:
                result = self._base_order(state, player, row["account"],
                                          row["node"], asset, BID, limit, qty,
                                          now)
            except MarketError as exc:
                raise GameError(str(exc)) from exc
            if result is None:
                raise GameError("That is less than one trading lot.")
            self._save_base(player.id, state)
        return self._fill_report(result, "bought", asset)

    def base_policy(self, player, asset: str, **rule) -> dict:
        """Set the standing orders for one good."""
        row, state = self._base(player)
        if asset not in STOCKED:
            raise GameError("Your base does not handle that.")
        current = state["policy"][asset]
        for key, value in rule.items():
            if value is None or key not in current:
                continue
            if key in ("sell", "buy"):
                current[key] = bool(value)
            elif key in ("min_price", "max_price"):
                current[key] = self._price(value)
            else:                                   # keep_t, target_t
                if (not isinstance(value, int) or isinstance(value, bool)
                        or not 0 <= value <= 100_000):
                    raise GameError("A stock level is a whole number of "
                                    "tonnes.")
                current[key] = value
        with self._mutation():
            self._save_base(player.id, state)
        return self.base_view(player)

    def _standing_orders(self, state: dict, player, row, hour, now: str
                         ) -> list[Event]:
        ledger = self.world.ledger
        account, node = row["account"], row["node"]
        book = self.world.books[node]
        events: list[Event] = []
        ice = state["policy"]["ICE"]
        if ice.get("buy"):
            held = ledger.balance(account, "ICE")
            short = ice["target_t"] * TONNE - held
            want = min(short, hour.store_kg - held)
            if want >= TONNE and (book.best_ask("ICE") or 0) and \
                    book.best_ask("ICE") <= ice["max_price"]:
                self._try_order(state, player, account, node, "ICE", BID,
                                ice["max_price"], want, now)
        for asset in STOCKED:
            rule = state["policy"][asset]
            if not rule.get("sell"):
                continue
            spare = ledger.balance(account, asset) - rule["keep_t"] * TONNE
            bid = book.best_bid(asset)
            if spare < TONNE or not bid or bid < rule["min_price"]:
                continue
            result = self._try_order(state, player, account, node, asset, ASK,
                                     rule["min_price"], spare, now)
            if result is not None and result.filled_kg:
                events += self._milestone(state, player, "first_sale", now)
        return events

    def _try_order(self, *args):
        """A standing order that the book refuses is skipped, not fatal."""
        try:
            with transaction(self.db):
                return self._base_order(*args)
        except MarketError:
            return None

    # -- ship and base -------------------------------------------------------

    def _ship_here(self, player, row):
        ship = self._docked(player)
        if ship.location != row["node"]:
            raise GameError(f"Your ship is not at "
                            f"{NODE_NAMES.get(row['node'], row['node'])}.")
        return ship

    def base_load(self, player, asset: str, qty_t: int) -> dict:
        """Move stock from the base into the ship docked at its port."""
        row, state = self._base(player)
        ship = self._ship_here(player, row)
        if asset not in STOCKED:
            raise GameError("Your base does not handle that.")
        qty = self._tonnes(qty_t)
        ledger = self.world.ledger
        held = ledger.balance(row["account"], asset)
        if qty > held:
            raise GameError(f"The base holds {held // TONNE} t of that.")
        room = KESTREL.cargo_capacity_kg - self.hold_used(player)
        if asset == "PROP":
            room += max(0, KESTREL.tank_capacity_kg
                        - ledger.balance(player.account, "PROP"))
        if qty > room:
            raise GameError(f"Only {room // TONNE} t of space aboard.")
        with self._mutation():
            ledger.transfer(row["account"], player.account, asset, qty,
                            kind="stow", game_time=self.world.game_time(),
                            ref=player.id, memo=f"{ship.id} loads from base")
            ship.loaded[asset] = ship.loaded.get(asset, 0) + qty
        return self.base_view(player)

    def base_unload(self, player, asset: str, qty_t: int) -> dict:
        """Move cargo from the ship docked at the port into the base."""
        row, state = self._base(player)
        ship = self._ship_here(player, row)
        if asset not in STOCKED:
            raise GameError("Your base does not handle that.")
        qty = self._tonnes(qty_t)
        ledger = self.world.ledger
        held = ledger.balance(player.account, asset)
        if qty > held:
            raise GameError(f"You have {held // TONNE} t of that aboard.")
        room = self._room(row, state, asset)
        if qty > room:
            raise GameError(f"Only {room // TONNE} t of room for that at "
                            f"the base.")
        with self._mutation():
            ledger.transfer(player.account, row["account"], asset, qty,
                            kind="stow", game_time=self.world.game_time(),
                            ref=player.id, memo=f"{ship.id} unloads to base")
            if asset in ship.loaded:
                ship.loaded[asset] = max(0, ship.loaded[asset] - qty)
        return self.base_view(player)

    # -- the hour ------------------------------------------------------------

    def _tick_bases(self, now: str) -> list[Event]:
        """Every base's hour, inside the world's. One failure stops one base."""
        events: list[Event] = []
        rows = self.db.execute(
            "SELECT * FROM base ORDER BY created_tick, player_id").fetchall()
        for row in rows:
            try:
                with transaction(self.db):
                    events += self._tick_base(row, now)
            except Exception:
                log.exception("base of %s failed its hour at tick %d",
                              row["player_id"], self.world.tick)
                self.db.execute("UPDATE base SET faults = faults + 1 "
                                "WHERE player_id = ?", (row["player_id"],))
        return events

    def _tick_base(self, row, now: str) -> list[Event]:
        pid, account, node = row["player_id"], row["account"], row["node"]
        state = json.loads(row["state"])
        player = self.player(pid)
        ledger, tick = self.world.ledger, self.world.tick
        layout = base.site_layout(state["seed"], state["size"])
        self._roll_books(state)
        events: list[Event] = []

        owed = row["owed"]
        if owed and ledger.balance(player.account, CREDIT) >= owed:
            ledger.burn(player.account, owed, now, ref=pid,
                        memo="base arrears settled")
            self._tally(state, "arrears_paid", owed)
            owed = 0

        stock = {a: ledger.balance(account, a) for a in STOCKED}
        hour = base.run_hour(state, layout, tick, stock,
                             flaring=self.world.weather.flaring(tick),
                             suspended=owed > 0)
        for op in hour.ops:
            if op.kind == "extract":
                ledger.extract(account, op.asset, op.kg, now, memo=op.memo)
            else:
                ledger.consume(account, op.asset, op.kg, now, memo=op.memo)
        for asset, kg in hour.made.items():
            self._tally(state, f"made_kg_{asset}", kg)
        self._tally(state, "used_kg_ICE", hour.used.get("ICE", 0))

        over = ledger.balance(account, "PROP") - hour.tank_kg
        if over > 0:
            lost = min(over, max(1, over * BOIL_OFF_PERCENT // 100))
            ledger.consume(account, "PROP", lost, now, memo="boil-off")
            self._tally(state, "boiled_kg", lost)

        if hour.comms and not owed:
            events += self._standing_orders(state, player, row, hour, now)

        status = set(hour.status.values())
        command = next((m for m in state["modules"]
                        if m["type"] == "command"), None)
        if command and hour.status.get(command["id"]) == "on":
            events += self._milestone(state, player, "desk", now)
        if hour.made.get("PROP"):
            events += self._milestone(state, player, "first_prop", now)
        if (state["books"]["today"].get("used_kg_ICE", 0)
                >= MODULES["electrolysis"].feed_kg_per_day):
            events += self._milestone(state, player, "full_feed", now)

        if tick % TICKS_PER_GAME_DAY == 0:
            owed = self._daily_charges(state, player, node, hour, owed, now)

        self._alerts(state, pid, status, hour, owed, tick)
        state["report"] = base.report(state, hour, tick)
        self._save_base(pid, state, owed)
        return events

    def _daily_charges(self, state: dict, player, node: str, hour, owed: int,
                       now: str) -> int:
        """Payroll, wear and the lease, at game midnight. Returns what is owed.

        Payroll goes to the port's households, as every firm's does. Wear and
        the lease are burned. What cannot be paid is recorded as owed and the
        works stand down until it is settled; the ledger never goes negative.
        """
        ledger = self.world.ledger
        standing = state["modules"]
        lease = sum(lease_per_day(MODULES[m["type"]].cost)
                    for m in standing if m["leased"])
        upkeep = sum(upkeep_per_day(MODULES[m["type"]].cost)
                     for m in standing)
        wages = WAGE_PER_CREW_DAY * hour.crew_working
        cash = ledger.balance(player.account, CREDIT)

        households = [f for f in self.world.active_firms()
                      if f.role is Role.CONSUMER and f.node == node]
        share = wages // len(households) if households else 0
        if share and cash >= share * len(households):
            for household in households:
                ledger.transfer(player.account, household.account, CREDIT,
                                share, kind="wages", game_time=now,
                                ref=player.id, memo=f"{player.name} payroll")
            paid = share * len(households)
            cash -= paid
            self._tally(state, "wages", paid)
        elif share:
            owed += share * len(households)

        due = lease + upkeep
        paid = min(due, cash)
        if paid:
            ledger.burn(player.account, paid, now, ref=player.id,
                        memo=f"{player.name} base lease and upkeep")
            self._tally(state, "lease", min(paid, lease))
            self._tally(state, "upkeep", max(0, paid - lease))
        return owed + (due - paid)

    def _alerts(self, state: dict, pid: str, status: set, hour, owed: int,
                tick: int) -> None:
        """Write home about a problem once it has lasted, and only once."""
        if "desk" not in state["milestones"]:
            return                      # still unpacking; nothing to report
        now_wrong = {c for c in ("unlinked", "no_power", "no_crew", "hot",
                                 "no_feed", "full", "no_ice", "worked_out")
                     if c in status}
        if owed:
            now_wrong.add("arrears")
        alerts = {c: t for c, t in state["alerts"].items() if c in now_wrong}
        for code in now_wrong:
            alerts.setdefault(code, tick)
        told = [c for c in state["told"] if c in now_wrong]
        for code, since in sorted(alerts.items()):
            if code not in told and tick - since >= ALERT_AFTER_HOURS:
                told.append(code)
                self._message(pid, "base_commander", "base_alert",
                              {"code": code, "hours": tick - since,
                               "owed": owed,
                               "site_name": SITES[state["site"]]["name"]})
        state["alerts"], state["told"] = alerts, told

    # -- views ---------------------------------------------------------------

    def base_seen(self, player) -> dict:
        """Record a visit. Returns what the base did since the last one."""
        row, state = self._base(player)
        away = state["away"]
        state["away"] = {"since": self.world.tick}
        with self._mutation():
            self._save_base(player.id, state)
        return {**away, "hours": self.world.tick - away.get("since",
                                                            self.world.tick)}

    @staticmethod
    def base_catalog() -> list[dict]:
        return [{"id": m.id, "name": m.name, "group": m.group,
                 "power_kw": m.power_kw, "heat_kw": m.heat_kw, "crew": m.crew,
                 "cost": m.cost, "note": m.note, "hours": m.assemble_hours,
                 "lease_per_day": lease_per_day(m.cost),
                 "upkeep_per_day": upkeep_per_day(m.cost)}
                for m in MODULES.values()]

    def base_view(self, player) -> dict:
        """Everything the client draws. Nothing in it is computed there."""
        world = self.world
        clock = {"tick": world.tick, "date": self.display_date(),
                 "tick_started_at": self.tick_starts_at(world.tick).isoformat(),
                 "tick_seconds": (self.tick_starts_at(1)
                                  - self.tick_starts_at(0)).total_seconds(),
                 "flaring": world.weather.flaring(world.tick)}
        ledger = world.ledger
        credits = ledger.balance(player.account, CREDIT)
        row = self._base_row(player.id)
        if row is None:
            return {"base": None, "company": player.name, "credits": credits,
                    "sites": [{"id": k, **v, "node_name":
                               NODE_NAMES.get(v["node"], v["node"]),
                               "prices": self.prices(v["node"])}
                              for k, v in SITES.items()],
                    "kit": list(base.KIT), "catalog": self.base_catalog(),
                    "lease_cap": LEASE_CAP, **clock}
        state = json.loads(row["state"])
        layout = base.site_layout(state["seed"], state["size"])
        for p in layout["patches"]:
            body = base.deposit(state, layout, p["id"])
            p["richness"] = round(body.richness, 3)
            p["extracted_kg"] = body.extracted_kg
        report = state.get("report") or {}
        status = report.get("status", {})
        standing = state["modules"]
        ship = self.ship_of(player)
        docked = (ship.state.value == "docked"
                  and ship.location == row["node"])
        aboard = ledger.holdings(player.account)
        return {
            "base": {
                "site": state["site"], "site_name": SITES[state["site"]]["name"],
                "node": row["node"],
                "node_name": NODE_NAMES.get(row["node"], row["node"]),
                "created_tick": row["created_tick"], "faults": row["faults"],
                "layout": layout,
                "modules": [{**m, "status": status.get(str(m["id"]),
                                                       "assembling"
                                                       if m["ready"] > world.tick
                                                       else "new")}
                            for m in standing],
                "conduits": state["conduits"], "crates": state["crates"],
                "report": report,
                "stock": {a: ledger.balance(row["account"], a)
                          for a in STOCKED},
                "capacity": {"ICE": report.get("store_kg", base.YARD_KG),
                             "PROP": report.get("tank_kg", 0)},
                "policy": state["policy"],
                "milestones": [{"id": i, "title": t, "bonus": b,
                                "done": i in state["milestones"]}
                               for i, t, b in MILESTONES],
                "alerts": state["alerts"],
                "books": state["books"], "away": state["away"],
                "money": {
                    "owed": row["owed"],
                    "lease_per_day": sum(
                        lease_per_day(MODULES[m["type"]].cost)
                        for m in standing if m["leased"]),
                    "upkeep_per_day": sum(
                        upkeep_per_day(MODULES[m["type"]].cost)
                        for m in standing),
                    "wages_per_day": WAGE_PER_CREW_DAY
                    * (report.get("crew") or [0])[0],
                    "leased_value": base.leased_value(state),
                    "owned_value": base.owned_value(state),
                    "lease_cap": LEASE_CAP,
                    "conduit_cost": base.CONDUIT_COST,
                },
                "ship": {"id": ship.id, "docked_here": docked,
                         "state": ship.state.value, "location": ship.location,
                         "aboard": {a: aboard.get(a, 0) for a in STOCKED},
                         "hold_room_kg": KESTREL.cargo_capacity_kg
                         - self.hold_used(player)},
            },
            "company": player.name, "credits": credits,
            "prices": self.prices(row["node"]),
            "catalog": self.base_catalog(), **clock,
        }
