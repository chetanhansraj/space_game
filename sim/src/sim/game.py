"""The game: one world, its clock, and the people flying in it.

`World` is the economy -- firms, books, ships -- advancing an hour at a time.
This module wraps it in everything a live, shared, persistent world needs:

- **A clock.** The world is always at the tick the wall clock says it should
  be. A server that was down for an hour runs the missed hour when it comes
  back, because offline is absent, not paused (invariant 5).
- **Atomic ticks.** Each tick -- the world's hour, contract settlement,
  upkeep, the event log and the snapshot -- is one database transaction. A
  crash loses the hour cleanly and it runs again; it can never half-happen.
- **Players.** A person gets a company, a chartered Kestrel and a stake from
  the Ark's development fund, and from then on submits intent: buy, sell,
  fly, take a contract. Every one of those is validated here, on the server,
  and executed through `market` like any agent's order (invariant 1).
- **The inbox and the event log.** Structured facts only. `voice/` turns them
  into prose when they are read, so if it is down the facts still arrive.

Nothing here creates money. The development fund is minted once, at world
creation, in one auditable genesis transaction; every credit a player
receives after that is a transfer from something that already existed.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from market.book import ASK, BID
from market.db import connect, transaction
from market.errors import MarketError
from market.money import CREDIT
from orbital.clock import DISPLAY_OFFSET_YEARS, real_seconds

from . import TICKS_PER_GAME_DAY, persist, schema
from .contracts import ContractBoard, ContractError, encode
from .routes import DOCKING_FEE, NODE_ANCHOR
from .seed_world import NODES, SHACKLETON, TONNE, build
from .ships import KESTREL, Ship, ShipState
from .shocks import Event

_UTC = _dt.timezone.utc

#: One tick is one game hour. How long that is in real seconds is the
#: clock's business, not ours -- the 60x factor lives in orbital.clock only.
TICK_REAL_SECONDS = real_seconds(3_600)

DEFAULT_SEED = 20260904

#: The Ark's development office: where a new company's stake comes from.
#: docs/DECISIONS.md D44. Funded once at world creation from genesis, like
#: the Authority's treasury, and finite: when it is spent, the charter
#: office closes. Every grant is a transfer out of it, never a mint.
DEV_FUND = "institution:ark_development_fund"
DEV_FUND_TREASURY = 30_000_000
DEV_FUND_PROPELLANT_KG = 10_000 * TONNE
STARTING_GRANT = 120_000

#: Where every new company starts. The Ark's home, and where fuel is made.
START_NODE = SHACKLETON

#: What a player may trade. The same list the agent haulers carry.
TRADEABLE = ("ICE", "PROP", "REGOLITH", "HE3", "IRON", "VOLATILE",
             "GOODS", "FOOD")

#: Auto-sale on arrival will not go below this share of the going rate.
#: A pilot who comes back to find their cargo dumped for nothing at a thin
#: book will not come back again.
ARRIVAL_SALE_FLOOR_PERCENT = 90

#: Fold the ledger into its balance cache once a game day.
CHECKPOINT_EVERY_TICKS = TICKS_PER_GAME_DAY

NODE_NAMES = {
    "shackleton_depot": "Shackleton Depot",
    "peary_ridge": "Peary Ridge",
    "tranquillitatis_flats": "Tranquillitatis Flats",
}

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'&-]{1,30}[A-Za-z0-9.]$")

#: Event kinds worth a line in the world feed. Agent departures and
#: arrivals happen dozens of times a day and are shown on the map instead.
FEED_KINDS = ("solar_flare", "equipment_failure", "insolvency", "spinoff",
              "contract_posted", "contract_fulfilled", "player_joined",
              "player_departure", "player_arrival")


class GameError(Exception):
    """A request the game refuses. The message is shown to the player."""


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    account: str
    ship_id: str
    created_tick: int
    last_seen_tick: int
    upkeep_owed: int

    @classmethod
    def from_row(cls, row) -> "Player":
        return cls(id=row["id"], name=row["name"], account=row["account"],
                   ship_id=row["ship_id"], created_tick=row["created_tick"],
                   last_seen_tick=row["last_seen_tick"],
                   upkeep_owed=row["upkeep_owed"])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Game:
    """One world, persisted, on a clock, with players in it."""

    def __init__(self, db, world, launch_real: _dt.datetime) -> None:
        self.db = db
        self.world = world
        self.launch_real = launch_real
        self.board = ContractBoard(world, db)
        self._saved = persist.dumps(world)
        #: Bumped on every committed change, so readers can cache views.
        self.version = 0

    # -- opening ---------------------------------------------------------

    @classmethod
    def open(cls, path: str = ":memory:", seed: int = DEFAULT_SEED,
             now: _dt.datetime | None = None, routes=None,
             threadsafe: bool = False) -> "Game":
        """Open the world at ``path``, creating it if it does not exist."""
        db = connect(path, threadsafe=threadsafe)
        schema.migrate(db)
        row = db.execute(
            "SELECT state FROM world_snapshot WHERE id = 1").fetchone()
        if row is not None:
            world = persist.loads(db, row["state"], routes)
            launch = _dt.datetime.fromisoformat(cls._meta(db, "launch_real"))
            return cls(db, world, launch)

        launch = (now or _dt.datetime.now(tz=_UTC)).astimezone(_UTC)
        # World creation is one transaction, like a tick: a server killed
        # half-way through founding the world leaves no world at all.
        with transaction(db):
            world = build(db, seed=seed, routes=routes)
            founded = world.game_time()
            world.ledger.open_account(DEV_FUND, "institution", founded,
                                      label="Ark development office")
            world.ledger.mint(DEV_FUND, DEV_FUND_TREASURY, founded,
                              memo="Ark development fund, world genesis")
            world.ledger.extract(DEV_FUND, "PROP", DEV_FUND_PROPELLANT_KG,
                                 founded, memo="Ark development fund stores")
            db.executemany(
                "INSERT INTO world_meta (key, value) VALUES (?, ?)",
                [("launch_real", launch.isoformat()), ("seed", str(seed))])
            game = cls.__new__(cls)
            game.db, game.world, game.launch_real = db, world, launch
            game.board = ContractBoard(world, db)
            game.version = 0
            text = game._write_snapshot()
        game._saved = text
        return game

    @staticmethod
    def _meta(db, key: str) -> str:
        return db.execute("SELECT value FROM world_meta WHERE key = ?",
                          (key,)).fetchone()["value"]

    # -- the clock -------------------------------------------------------

    def due_tick(self, now: _dt.datetime | None = None) -> int:
        """The tick the world should be at, by the wall clock."""
        now = now or _dt.datetime.now(tz=_UTC)
        elapsed = (now - self.launch_real).total_seconds()
        return max(0, int(elapsed // TICK_REAL_SECONDS))

    def tick_starts_at(self, tick: int) -> _dt.datetime:
        return self.launch_real + _dt.timedelta(seconds=tick * TICK_REAL_SECONDS)

    def sky_time(self, tick: int | None = None) -> _dt.datetime:
        """Where the ephemerides are evaluated. One tick is one game hour."""
        tick = self.world.tick if tick is None else tick
        return self.launch_real + _dt.timedelta(hours=tick)

    def display_date(self, tick: int | None = None) -> str:
        """The fictional calendar. Cosmetic only; never computed with."""
        sky = self.sky_time(tick)
        return sky.replace(year=sky.year + DISPLAY_OFFSET_YEARS).strftime(
            "%Y-%m-%d %H:00")

    # -- atomicity -------------------------------------------------------

    def _write_snapshot(self) -> str:
        text = persist.dumps(self.world)
        self.db.execute(
            "INSERT OR REPLACE INTO world_snapshot (id, tick, saved_at, state) "
            "VALUES (1, ?, ?, ?)",
            (self.world.tick, _dt.datetime.now(tz=_UTC).isoformat(), text))
        return text

    @contextmanager
    def _mutation(self) -> Iterator[None]:
        """Change the world all at once, or not at all.

        The database rolls itself back on failure. The Python objects do
        not, so on failure they are rebuilt from the last committed
        snapshot -- which, because every mutation commits one, is exactly
        the state the database just rolled back to.
        """
        try:
            with transaction(self.db):
                yield
                text = self._write_snapshot()
        except BaseException:
            self._reload()
            raise
        self._saved = text
        self.version += 1

    def _reload(self) -> None:
        self.world = persist.loads(self.db, self._saved,
                                   routes=self.world.routes)
        self.board = ContractBoard(self.world, self.db)

    # -- the tick --------------------------------------------------------

    def step(self) -> list[Event]:
        """Advance one game hour. Everything, or nothing."""
        with self._mutation():
            world = self.world
            events = world.run_tick()
            now = world.game_time()
            for event in list(events):
                if event.kind == "player_arrival":
                    events += self._settle_arrival(event, now)
            events += self.board.tick(now)
            if world.tick % TICKS_PER_GAME_DAY == 0:
                events += self._charge_upkeep(now)
            self._route_messages(events)
            self._log(events)
            if world.tick % CHECKPOINT_EVERY_TICKS == 0:
                world.ledger.checkpoint()
        return events

    def catch_up(self, now: _dt.datetime | None = None,
                 limit: int | None = None) -> int:
        """Run every tick the wall clock says is due. Returns how many."""
        ran = 0
        while self.world.tick < self.due_tick(now):
            if limit is not None and ran >= limit:
                break
            self.step()
            ran += 1
        return ran

    def _log(self, events: list[Event]) -> None:
        self.db.executemany(
            "INSERT INTO event_log (tick, kind, subject, detail, data) "
            "VALUES (?, ?, ?, ?, ?)",
            [(e.tick, e.kind, e.subject, e.detail, encode(e.data))
             for e in events])

    # -- players: joining ------------------------------------------------

    def signup(self, name: str) -> tuple[Player, str]:
        """Found a company. Returns the player and their secret token.

        The token is shown once and stored only as a hash: a leaked database
        must not be a list of working logins.
        """
        name = " ".join((name or "").split())
        if not _NAME.match(name):
            raise GameError("A company name is 3 to 32 letters, numbers, "
                            "spaces or . , ' & -")
        if self.db.execute("SELECT 1 FROM player WHERE name = ?",
                           (name,)).fetchone():
            raise GameError("A company by that name is already registered.")
        ledger = self.world.ledger
        if (ledger.balance(DEV_FUND, CREDIT) < STARTING_GRANT
                or ledger.balance(DEV_FUND, "PROP")
                < KESTREL.tank_capacity_kg):
            raise GameError("The Ark's charter office has no more ships to "
                            "lease. Check back later.")

        pid = f"p_{secrets.token_hex(6)}"
        token = secrets.token_urlsafe(24)
        account = f"player:{pid}"
        ship = Ship(id=f"{pid}_kestrel", owner=pid, account=account,
                    ship_class=KESTREL, location=START_NODE,
                    player_owned=True)
        now = self.world.game_time()
        with self._mutation():
            ledger.open_account(account, "player", now, label=name)
            ledger.transfer(DEV_FUND, account, CREDIT, STARTING_GRANT,
                            kind="grant", game_time=now, ref=pid,
                            memo=f"development grant to {name}")
            ledger.transfer(DEV_FUND, account, "PROP",
                            KESTREL.tank_capacity_kg, kind="grant",
                            game_time=now, ref=pid,
                            memo=f"opening tank for {ship.id}")
            self.db.execute(
                "INSERT INTO player (id, name, account, ship_id, token_hash, "
                "created_tick, created_at, last_seen_tick) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, name, account, ship.id, hash_token(token),
                 self.world.tick, _dt.datetime.now(tz=_UTC).isoformat(),
                 self.world.tick))
            self.world.ships.append(ship)

            # The first thing a new pilot reads is never an empty board.
            events = []
            if not self.board.open():
                events += self.board.post_new(now, force=True)
            offers = [c.id for c in self.board.open()][:3]
            self._message(pid, "archivist", "welcome",
                          {"company": name, "node": START_NODE,
                           "ship": ship.id})
            self._message(pid, "ark_development_office", "charter",
                          {"company": name, "grant": STARTING_GRANT,
                           "fuel_kg": KESTREL.tank_capacity_kg,
                           "upkeep_per_day": KESTREL.upkeep_per_day,
                           "node": START_NODE})
            if offers:
                first = self.board.get(offers[0])
                self._message(pid, first.issuer, "offers",
                              {"contracts": offers})
            events.append(Event(
                tick=self.world.tick, kind="player_joined", subject=pid,
                detail=f"{name} founded at {START_NODE}",
                data={"player": pid, "company": name, "node": START_NODE}))
            self._route_messages(events)
            self._log(events)
        return self.player(pid), token

    def authenticate(self, token: str | None) -> Player | None:
        if not token:
            return None
        row = self.db.execute("SELECT * FROM player WHERE token_hash = ?",
                              (hash_token(token),)).fetchone()
        return Player.from_row(row) if row else None

    def player(self, pid: str) -> Player:
        row = self.db.execute("SELECT * FROM player WHERE id = ?",
                              (pid,)).fetchone()
        if row is None:
            raise GameError("No such company.")
        return Player.from_row(row)

    def players(self) -> list[Player]:
        return [Player.from_row(r) for r in
                self.db.execute("SELECT * FROM player ORDER BY created_tick")]

    def ship_of(self, player: Player) -> Ship:
        for ship in self.world.ships:
            if ship.id == player.ship_id:
                return ship
        raise GameError("Your ship is missing. This is a bug; report it.")

    # -- players: what is aboard -----------------------------------------

    def hold_used(self, player: Player) -> int:
        """Kilograms of cargo space in use.

        Propellant in the tank is fuel; propellant beyond a full tank is
        cargo. One asset, one account -- the ledger does not know which
        tonne of propellant is in which tank, and does not need to.
        """
        used = 0
        for asset, held in self.world.ledger.holdings(player.account).items():
            if asset == CREDIT or held <= 0:
                continue
            if asset == "PROP":
                used += max(0, held - KESTREL.tank_capacity_kg)
            else:
                used += held
        return used

    def _docked(self, player: Player) -> Ship:
        ship = self.ship_of(player)
        if ship.state is not ShipState.DOCKED:
            raise GameError("Your ship is in flight. Trade when it docks.")
        return ship

    @staticmethod
    def _tonnes(qty_t) -> int:
        if not isinstance(qty_t, int) or isinstance(qty_t, bool) or qty_t < 1:
            raise GameError("Quantity must be a whole number of tonnes.")
        return qty_t * TONNE

    @staticmethod
    def _price(price) -> int:
        if (not isinstance(price, int) or isinstance(price, bool)
                or price < 1 or price > 100_000_000):
            raise GameError("A price is a whole number of credits.")
        return price

    def _ioc(self, node: str, asset: str, side: str, price: int, qty: int,
             account: str, now: str):
        """Immediate or cancel: take what the book offers now, rest nothing.

        Players are offline most of the time. An order left resting while
        they sleep is escrow they forgot about, so v1 has none.
        """
        book = self.world.books[node]
        result = book.place(asset, side, price, qty, account, now)
        if result.resting_kg:
            book.cancel(result.order_id, now)
        return result

    # -- players: trading ------------------------------------------------

    def buy(self, player: Player, asset: str, qty_t: int, limit: int) -> dict:
        ship = self._docked(player)
        if asset not in TRADEABLE:
            raise GameError("That is not traded here.")
        qty, limit = self._tonnes(qty_t), self._price(limit)
        room = (KESTREL.cargo_capacity_kg - self.hold_used(player))
        if asset == "PROP":
            room += max(0, KESTREL.tank_capacity_kg - self.world.ledger.balance(
                player.account, "PROP"))
        if qty > room:
            raise GameError(f"Only {room // TONNE} t of space aboard.")
        cash = self.world.ledger.balance(player.account, CREDIT)
        if limit * qty_t > cash:
            raise GameError(f"That needs {limit * qty_t:,} cr in escrow; "
                            f"you have {cash:,}.")
        now = self.world.game_time()
        with self._mutation():
            try:
                result = self._ioc(ship.location, asset, BID, limit, qty,
                                   player.account, now)
            except MarketError as exc:
                raise GameError(str(exc)) from exc
            if result.filled_kg:
                ship.loaded[asset] = ship.loaded.get(asset, 0) + result.filled_kg
        return self._fill_report(result, "bought", asset)

    def sell(self, player: Player, asset: str, qty_t: int, limit: int) -> dict:
        ship = self._docked(player)
        if asset not in TRADEABLE:
            raise GameError("That is not traded here.")
        qty, limit = self._tonnes(qty_t), self._price(limit)
        held = self.world.ledger.balance(player.account, asset)
        if qty > held:
            raise GameError(f"You hold {held // TONNE} t of that.")
        now = self.world.game_time()
        with self._mutation():
            try:
                result = self._ioc(ship.location, asset, ASK, limit, qty,
                                   player.account, now)
            except MarketError as exc:
                raise GameError(str(exc)) from exc
            if result.filled_kg and asset in ship.loaded:
                ship.loaded[asset] = max(0, ship.loaded[asset]
                                         - result.filled_kg)
        return self._fill_report(result, "sold", asset)

    @staticmethod
    def _fill_report(result, verb: str, asset: str) -> dict:
        value = sum(f.value for f in result.fills)
        kg = result.filled_kg
        return {"verb": verb, "asset": asset, "kg": kg, "value": value,
                "average": (value * TONNE // kg) if kg else None,
                "fills": [{"price": f.price, "kg": f.qty_kg}
                          for f in result.fills]}

    # -- players: flying -------------------------------------------------

    def plan(self, player: Player, destination: str):
        """What flying to ``destination`` right now would take."""
        ship = self.ship_of(player)
        leg = self.world.routes.leg(ship.location, destination)
        if leg is None:
            return None
        cargo = self.hold_used(player)
        return {
            "destination": destination,
            "dv": round(leg.dv),
            "ticks": leg.ticks(),
            "fuel_kg": KESTREL.fuel_for(leg.dv, cargo),
            "fee": DOCKING_FEE.get(destination, 0),
            "cargo_kg": cargo,
        }

    def dispatch(self, player: Player, destination: str,
                 sell_on_arrival: bool = True) -> dict:
        ship = self._docked(player)
        if destination not in self.world.books:
            raise GameError("There is no port by that name.")
        if destination == ship.location:
            raise GameError("You are already docked there.")
        if self.world.weather.flaring(self.world.tick):
            raise GameError("Solar flare in progress. All launches are "
                            "grounded until it passes.")
        plan = self.plan(player, destination)
        if plan is None:
            raise GameError("That route cannot be flown from here.")
        ledger = self.world.ledger
        fuel = ledger.balance(player.account, "PROP")
        if fuel < plan["fuel_kg"]:
            raise GameError(f"That flight burns {plan['fuel_kg']:,} kg of "
                            f"propellant; you have {fuel:,} kg.")
        owed = player.upkeep_owed
        cash = ledger.balance(player.account, CREDIT)
        if cash < plan["fee"] + owed:
            if owed:
                raise GameError(f"Grounded: {owed:,} cr of charter upkeep "
                                f"is owed. Sell cargo to settle it.")
            raise GameError(f"The docking fee at {NODE_NAMES[destination]} "
                            f"is {plan['fee']:,} cr, paid in advance.")

        now = self.world.game_time()
        origin = ship.location
        with self._mutation():
            if owed:
                ledger.burn(player.account, owed, now, ref=player.id,
                            memo=f"{ship.id} charter upkeep arrears")
                self.db.execute("UPDATE player SET upkeep_owed = 0 "
                                "WHERE id = ?", (player.id,))
            if plan["fee"]:
                ledger.burn(player.account, plan["fee"], now, ref=player.id,
                            memo=f"{ship.id} docking fee at {destination}, "
                                 f"prepaid")
            ledger.consume(player.account, "PROP", plan["fuel_kg"], now,
                           memo=f"{ship.id} transit burn")
            holdings = {a: q for a, q in ledger.holdings(player.account).items()
                        if a not in (CREDIT, "PROP") and q > 0}
            main = max(holdings.items(), key=lambda kv: kv[1], default=None)
            ship.state = ShipState.IN_TRANSIT
            ship.destination = destination
            ship.depart_tick = self.world.tick
            ship.arrive_tick = self.world.tick + plan["ticks"]
            ship.leg_dv = float(plan["dv"])
            ship.manifest = main
            ship.sell_on_arrival = bool(sell_on_arrival)
            ship.prepaid_fee = plan["fee"]
            ship.loaded = {}
            ship.log.append(f"T{self.world.tick} depart {origin} -> "
                            f"{destination}")
            del ship.log[:-20]
            event = Event(
                tick=self.world.tick, kind="player_departure",
                subject=ship.id,
                detail=f"{player.name} departs {origin} for {destination}",
                data={"player": player.id, "company": player.name,
                      "origin": origin, "destination": destination,
                      "cargo": holdings, "fuel_kg": plan["fuel_kg"],
                      "fee": plan["fee"], "arrive_tick": ship.arrive_tick})
            self._log([event])
        return {**plan, "arrive_tick": ship.arrive_tick,
                "arrives_at": self.tick_starts_at(ship.arrive_tick).isoformat()}

    def _settle_arrival(self, event: Event, now: str) -> list[Event]:
        """Deliver contracts, then sell the hold if asked. Inside the tick."""
        pid = event.data["owner"]
        player = self.player(pid)
        ship = self.ship_of(player)
        node = event.data["node"]
        ledger = self.world.ledger
        out: list[Event] = []
        report = {"node": node, "origin": event.data.get("origin"),
                  "fee": event.data.get("fee", 0), "delivered": [],
                  "sold": [], "kept": {}}

        for c in self.board.held_by(pid):
            if c.node != node:
                continue
            if ledger.balance(player.account, c.asset) < c.qty_kg:
                continue
            done = self.board.deliver(c, player.account, now)
            out.append(done)
            report["delivered"].append({"contract": c.id, "issuer": c.issuer,
                                        "asset": c.asset, "kg": c.qty_kg,
                                        "payment": done.data["payment"]})

        if ship.sell_on_arrival:
            for asset, held in sorted(ledger.holdings(player.account).items()):
                if asset == CREDIT or held <= 0:
                    continue
                qty = held - KESTREL.tank_capacity_kg if asset == "PROP" else held
                spec = ledger.asset(asset)
                qty -= qty % spec.lot_mass_kg
                if qty < spec.lot_mass_kg:
                    continue
                book = self.world.books[node]
                going = book.last_price(asset) or book.best_bid(asset)
                if not going or not book.best_bid(asset):
                    continue
                floor = max(1, going * ARRIVAL_SALE_FLOOR_PERCENT // 100)
                try:
                    result = self._ioc(node, asset, ASK, floor, qty,
                                       player.account, now)
                except MarketError:
                    continue
                if result.filled_kg:
                    report["sold"].append(self._fill_report(result, "sold",
                                                            asset))

        for asset, held in ledger.holdings(player.account).items():
            if asset not in (CREDIT, "PROP") and held > 0:
                report["kept"][asset] = held
        report["credits"] = ledger.balance(player.account, CREDIT)
        report["fuel_kg"] = ledger.balance(player.account, "PROP")
        self._message(pid, f"port:{node}", "arrival", report)
        return out

    def _charge_upkeep(self, now: str) -> list[Event]:
        """The charter fee on every player's Kestrel. Invariant 7's drain.

        Paid in full when the money is there. When it is not, what cannot be
        paid is recorded as owed and the ship is grounded until it is
        settled -- the ledger never goes negative, and the charge becomes a
        ledger entry only when it is actually paid.
        """
        events: list[Event] = []
        ledger = self.world.ledger
        for player in self.players():
            due = KESTREL.upkeep_per_day + player.upkeep_owed
            cash = ledger.balance(player.account, CREDIT)
            paid = min(due, cash)
            if paid > 0:
                ledger.burn(player.account, paid, now, ref=player.id,
                            memo=f"{player.ship_id} charter upkeep")
            owed = due - paid
            self.db.execute("UPDATE player SET upkeep_owed = ? WHERE id = ?",
                            (owed, player.id))
            if owed and not player.upkeep_owed:
                self._message(player.id, "ark_development_office",
                              "arrears", {"owed": owed})
        return events

    # -- players: contracts ----------------------------------------------

    def accept(self, player: Player, contract_id: int) -> dict:
        with self._mutation():
            try:
                c = self.board.accept(contract_id, player.id)
            except ContractError as exc:
                raise GameError(str(exc)) from exc
        return c.as_dict()

    def abandon(self, player: Player, contract_id: int) -> dict:
        with self._mutation():
            try:
                c = self.board.abandon(contract_id, player.id)
            except ContractError as exc:
                raise GameError(str(exc)) from exc
        return c.as_dict()

    def deliver(self, player: Player, contract_id: int) -> dict:
        """Hand over goods that arrived aboard, while docked at the issuer."""
        ship = self._docked(player)
        try:
            c = self.board.get(contract_id)
        except ContractError as exc:
            raise GameError(str(exc)) from exc
        if c.status != "ACCEPTED" or c.taker != player.id:
            raise GameError("That is not one of your contracts.")
        if ship.location != c.node:
            raise GameError(f"Deliver at {NODE_NAMES[c.node]}.")
        held = self.world.ledger.balance(player.account, c.asset)
        carried = held - ship.loaded.get(c.asset, 0)
        if carried < c.qty_kg:
            raise GameError(
                f"You need {c.qty_kg // TONNE} t of {c.asset} that came in "
                f"aboard. Goods bought here are not a delivery.")
        now = self.world.game_time()
        with self._mutation():
            event = self.board.deliver(c, player.account, now)
            self._route_messages([event])
            self._log([event])
        return {"contract": c.id, "payment": event.data["payment"]}

    # -- messages --------------------------------------------------------

    def _message(self, pid: str, sender: str, kind: str, data: dict) -> None:
        self.db.execute(
            "INSERT INTO message (player_id, tick, sender, kind, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (pid, self.world.tick, sender, kind, encode(data)))

    def _route_messages(self, events: list[Event]) -> None:
        """Turn world events into letters for the players they concern."""
        for e in events:
            taker = e.data.get("taker")
            if e.kind == "contract_fulfilled" and taker:
                self._message(taker, e.data["issuer"], "contract_paid",
                              e.data)
            elif e.kind == "contract_expired" and taker:
                self._message(taker, e.data["issuer"], "contract_lapsed",
                              e.data)

    def inbox(self, player: Player, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM message WHERE player_id = ? ORDER BY id DESC "
            "LIMIT ?", (player.id, limit)).fetchall()
        return [{"id": r["id"], "tick": r["tick"], "sender": r["sender"],
                 "kind": r["kind"], "data": json.loads(r["data"]),
                 "read": bool(r["read"])} for r in rows]

    def mark_read(self, player: Player, upto: int | None = None) -> None:
        with transaction(self.db):
            self.db.execute(
                "UPDATE message SET read = 1 WHERE player_id = ? AND id <= ?",
                (player.id, upto if upto is not None else 2**62))

    def touch(self, player: Player) -> dict:
        """Record a visit. Returns what happened while they were away."""
        since = player.last_seen_tick
        rows = self.db.execute(
            "SELECT kind, COUNT(*) AS n FROM event_log WHERE tick > ? "
            "GROUP BY kind", (since,)).fetchall()
        unread = self.db.execute(
            "SELECT COUNT(*) FROM message WHERE player_id = ? AND read = 0",
            (player.id,)).fetchone()[0]
        with transaction(self.db):
            self.db.execute("UPDATE player SET last_seen_tick = ? WHERE id = ?",
                            (self.world.tick, player.id))
        return {"since_tick": since, "hours": self.world.tick - since,
                "unread": unread,
                "world": {r["kind"]: r["n"] for r in rows}}

    # -- views -----------------------------------------------------------

    def node_info(self) -> list[dict]:
        out = []
        registry = self.world.routes.registry
        for node in NODES:
            anchor = registry[NODE_ANCHOR[node]]
            site = anchor.site
            out.append({"id": node, "name": NODE_NAMES[node],
                        "lat": site.lat_deg if site else 0.0,
                        "lon": site.lon_deg if site else 0.0,
                        "fee": DOCKING_FEE.get(node, 0)})
        return out

    def prices(self, node: str) -> dict:
        book = self.world.books[node]
        out = {}
        for asset in TRADEABLE:
            bid, ask, last = (book.best_bid(asset), book.best_ask(asset),
                              book.last_price(asset))
            if bid or ask or last:
                out[asset] = {"bid": bid, "ask": ask, "last": last}
        return out

    def ships_view(self) -> list[dict]:
        names = {p.id: p.name for p in self.players()}
        out = []
        for s in self.world.ships:
            out.append({
                "id": s.id, "owner": s.owner,
                "company": names.get(s.owner) if s.player_owned else None,
                "player": s.player_owned, "state": s.state.value,
                "location": s.location, "destination": s.destination,
                "depart_tick": s.depart_tick, "arrive_tick": s.arrive_tick,
                "manifest": list(s.manifest) if s.manifest else None,
                "voyages": s.voyages,
            })
        return out

    def feed(self, limit: int = 40, since_tick: int = 0) -> list[dict]:
        marks = ",".join("?" * len(FEED_KINDS))
        rows = self.db.execute(
            f"SELECT * FROM event_log WHERE kind IN ({marks}) AND tick > ? "
            f"ORDER BY id DESC LIMIT ?", (*FEED_KINDS, since_tick, limit)
        ).fetchall()
        return [{"id": r["id"], "tick": r["tick"], "kind": r["kind"],
                 "subject": r["subject"], "detail": r["detail"],
                 "data": json.loads(r["data"])} for r in rows]

    def world_view(self) -> dict:
        w = self.world
        return {
            "tick": w.tick,
            "date": self.display_date(),
            "sky_time": self.sky_time().isoformat(),
            "tick_started_at": self.tick_starts_at(w.tick).isoformat(),
            "tick_seconds": TICK_REAL_SECONDS,
            "flare_until": (w.weather.flare_until
                            if w.weather.flaring(w.tick) else None),
            "nodes": [{**n, "prices": self.prices(n["id"]),
                       "contracts": len(self.board.open(n["id"]))}
                      for n in self.node_info()],
            "ships": self.ships_view(),
            "companies": len(self.players()),
        }

    def market_view(self, node: str) -> dict:
        if node not in self.world.books:
            raise GameError("There is no port by that name.")
        book = self.world.books[node]
        assets = {}
        for asset in TRADEABLE:
            bids, asks = book.depth(asset, BID, 8), book.depth(asset, ASK, 8)
            last = book.last_price(asset)
            if not (bids or asks or last):
                continue
            tape = self.db.execute(
                "SELECT price, qty_kg, game_time FROM trade WHERE node = ? "
                "AND asset = ? ORDER BY id DESC LIMIT 40",
                (node, asset)).fetchall()
            assets[asset] = {
                "name": self.world.ledger.asset(asset).name,
                "bids": bids, "asks": asks, "last": last,
                "history": [r["price"] for r in reversed(tape)],
            }
        return {"node": node, "name": NODE_NAMES[node], "assets": assets}

    def company_view(self, player: Player) -> dict:
        player = self.player(player.id)
        ship = self.ship_of(player)
        ledger = self.world.ledger
        holdings = ledger.holdings(player.account)
        cargo = {a: q for a, q in holdings.items()
                 if a not in (CREDIT, "PROP") and q > 0}
        prop = holdings.get("PROP", 0)
        routes = []
        if ship.state is ShipState.DOCKED:
            for node in NODES:
                if node == ship.location:
                    continue
                plan = self.plan(player, node)
                if plan:
                    routes.append(plan)
        return {
            "id": player.id, "name": player.name,
            "credits": holdings.get(CREDIT, 0),
            "upkeep_owed": player.upkeep_owed,
            "upkeep_per_day": KESTREL.upkeep_per_day,
            "ship": {
                "id": ship.id, "class": ship.ship_class.name,
                "state": ship.state.value, "location": ship.location,
                "destination": ship.destination,
                "depart_tick": ship.depart_tick,
                "arrive_tick": ship.arrive_tick,
                "sell_on_arrival": ship.sell_on_arrival,
                "voyages": ship.voyages,
                "cargo": cargo,
                "cargo_prop_kg": max(0, prop - KESTREL.tank_capacity_kg),
                "fuel_kg": min(prop, KESTREL.tank_capacity_kg),
                "hold_used_kg": self.hold_used(player),
                "hold_kg": KESTREL.cargo_capacity_kg,
                "tank_kg": KESTREL.tank_capacity_kg,
                "loaded_here": ship.loaded,
                "log": ship.log[-8:],
            },
            "routes": routes,
            "contracts": [c.as_dict() for c in self.board.held_by(player.id)],
            "history": [c.as_dict() for c in self.board.history_of(player.id)],
        }

    def contracts_view(self) -> list[dict]:
        return [c.as_dict() for c in self.board.open()]
