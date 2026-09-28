"""Saving the world, and bringing it back.

The ledger already persists itself: every credit and kilogram is a row in the
database the moment it moves. What it does not hold is the part of the world
that is not value -- which firms exist, how worked each deposit is, where
every ship is, which rigs are down. That lives in Python objects, and before
this module it died with the process.

So once per tick, inside the same transaction as the tick itself, those
objects are written out as one JSON document. On start-up the document is
read back and the objects rebuilt around the ledger that is already there.
Because the snapshot and the ledger commit together, they can never disagree
about which hour it is: a server killed mid-tick loses the whole hour, both
halves of it, and replays it cleanly.

The snapshot holds no money. If it did, there would be two places a balance
could be read from, and the ledger would stop being the truth.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from market.authority import ArkAuthority
from market.book import OrderBook
from market.ledger import Ledger

from .deposits import Deposit
from .earth import EarthMarket
from .firms import Firm, Role
from .routes import RouteBook
from .ships import CLASSES, Ship, ShipState
from .world import World

#: Bumped whenever the shape below changes. A snapshot from a newer server
#: is refused rather than half-read.
STATE_VERSION = 1

#: How much of a ship's log survives a restart.
SHIP_LOG_KEPT = 20


def default_routes() -> RouteBook:
    """The route book every world uses: orbital's anchors, from the repo."""
    from orbital.anchors import AnchorRegistry
    from orbital.ephemeris import get_backend

    root = Path(__file__).resolve().parents[3]
    return RouteBook(AnchorRegistry.load(
        get_backend("auto"),
        root / "orbital/data/anchors.toml",
        root / "orbital/data/smallbody_elements.json",
    ))


def world_state(world: World) -> dict:
    """Everything about the world that the ledger does not already hold."""
    firms = []
    for firm in world.firms:
        row = asdict(firm)
        row["role"] = firm.role.value
        firms.append(row)

    ships = []
    for ship in world.ships:
        ships.append({
            "id": ship.id, "owner": ship.owner, "account": ship.account,
            "class": ship.ship_class.id, "location": ship.location,
            "state": ship.state.value, "destination": ship.destination,
            "depart_tick": ship.depart_tick, "arrive_tick": ship.arrive_tick,
            "leg_dv": ship.leg_dv,
            "manifest": list(ship.manifest) if ship.manifest else None,
            "voyages": ship.voyages, "log": ship.log[-SHIP_LOG_KEPT:],
            "player_owned": ship.player_owned,
            "sell_on_arrival": ship.sell_on_arrival,
            "prepaid_fee": ship.prepaid_fee,
            "loaded": ship.loaded,
        })

    return {
        "version": STATE_VERSION,
        "seed": world.seed,
        "tick": world.tick,
        "spinoff_count": world._spinoff_count,
        "firms": firms,
        "deposits": [
            {"id": d.id, "node": d.node, "asset": d.asset,
             "scale_kg": d.scale_kg, "extracted_kg": d.extracted_kg,
             "history": d.history[-30:]}
            for d in world.deposits.values()
        ],
        "ships": ships,
        "weather": {
            "flare_until": world.weather.flare_until,
            "rig_down_until": world.weather.rig_down_until,
        },
        "volatility": world.volatility,
        "earth_assets": world.earth_assets,
        "quoted_assets": world.quoted_assets,
        "starting_capital": world.starting_capital,
        "nodes": list(world.books),
    }


def dumps(world: World) -> str:
    return json.dumps(world_state(world), separators=(",", ":"),
                      sort_keys=True)


def restore(db, state: dict, routes: RouteBook | None = None) -> World:
    """Rebuild a world around the ledger already in ``db``.

    Nothing is minted, extracted or quoted here. The books, the Authority's
    treasury and every balance are exactly as the last committed tick left
    them; this only puts the non-monetary state back beside them.
    """
    if state.get("version") != STATE_VERSION:
        raise ValueError(
            f"snapshot is version {state.get('version')}, this server reads "
            f"{STATE_VERSION}"
        )

    ledger = Ledger(db)
    books = {node: OrderBook(db, ledger, node) for node in state["nodes"]}
    authorities = {node: ArkAuthority(db, ledger, books[node])
                   for node in state["nodes"]}
    earth = EarthMarket(ledger, books)

    firms = []
    for row in state["firms"]:
        row = dict(row)
        row["role"] = Role(row["role"])
        firms.append(Firm(**row))

    deposits = {}
    for row in state["deposits"]:
        deposits[row["id"]] = Deposit(
            id=row["id"], node=row["node"], asset=row["asset"],
            scale_kg=row["scale_kg"], extracted_kg=row["extracted_kg"],
            history=[tuple(h) for h in row.get("history", [])],
        )

    ships = []
    for row in state["ships"]:
        ships.append(Ship(
            id=row["id"], owner=row["owner"], account=row["account"],
            ship_class=CLASSES[row["class"]], location=row["location"],
            state=ShipState(row["state"]), destination=row["destination"],
            depart_tick=row["depart_tick"], arrive_tick=row["arrive_tick"],
            leg_dv=row["leg_dv"],
            manifest=tuple(row["manifest"]) if row["manifest"] else None,
            voyages=row["voyages"], log=list(row["log"]),
            player_owned=row.get("player_owned", False),
            sell_on_arrival=row.get("sell_on_arrival", True),
            prepaid_fee=row.get("prepaid_fee", 0),
            loaded=dict(row.get("loaded", {})),
        ))

    world = World(
        ledger=ledger, books=books, authorities=authorities, earth=earth,
        firms=firms, deposits=deposits, seed=state["seed"], ships=ships,
        routes=routes or default_routes(),
        volatility=state["volatility"],
        earth_assets=state["earth_assets"],
        quoted_assets=state["quoted_assets"],
        starting_capital=state["starting_capital"],
        tick=state["tick"],
    )
    world._spinoff_count = state["spinoff_count"]
    world.weather.flare_until = state["weather"]["flare_until"]
    world.weather.rig_down_until = dict(state["weather"]["rig_down_until"])
    return world


def loads(db, text: str, routes: RouteBook | None = None) -> World:
    return restore(db, json.loads(text), routes)
