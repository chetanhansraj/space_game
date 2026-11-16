"""A company's base: modules on a site grid, bound by budgets.

The bible, section 7: "Bases are placed module by module on a site grid, bound
by budgets rather than aesthetics: power generated against power drawn, heat
produced against radiator area, crew available against crew required... Place
a smelter without radiators and it throttles. A well-designed base out-earns a
sloppy one built at the same cost."

This module is the physical half of that, and nothing else. It knows what a
module is, where it may stand, which modules run this hour and what they would
make. It does not know what a credit is, never sees the ledger and never
touches the database: `run_hour` takes the base and what it has in stock and
returns the mass movements the hour produced, and `sim.basegame` is what posts
them. That split is what lets every rule here be tested without a world.

Everything is integers and everything is deterministic. The one float is the
deposit's richness, which is `sim.deposits`' and is used exactly as the agent
rigs use it.

Module figures are docs/seed-data.md section 3, transcribed. Every number that
is not from that table is named as a constant below and recorded in
docs/DECISIONS.md D53 to D60, marked where it was invented.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from . import TICKS_PER_GAME_DAY
from .deposits import Deposit

TONNE = 1_000

#: Tiles along one side of a site. *Invented* (D54): big enough that a base
#: has to choose where to stand, small enough to read on one screen.
SITE_SIZE = 24


@dataclass(frozen=True)
class Module:
    """One row of docs/seed-data.md section 3."""

    id: str
    name: str
    group: str
    power_kw: int             # positive generates, negative draws
    heat_kw: int              # positive is load, negative is rejection
    crew: int
    cost: int
    note: str
    berths: int = 0           # crew capacity added
    supports: int = 0         # crew one life-support unit keeps alive
    store_kg: int = 0         # dry storage
    tank_kg: int = 0          # propellant storage
    buffer_kwh: int = 0
    extract_kg_per_day: int = 0
    feed_kg_per_day: int = 0
    assemble_hours: int = 1   # invented, D58


def _m(*a, **kw) -> Module:
    return Module(*a, **kw)


#: docs/seed-data.md section 3. Build 1 carries the modules a polar propellant
#: works needs; the rest of the table arrives with the sites that use them.
MODULES: dict[str, Module] = {m.id: m for m in (
    _m("solar", "Solar array, 50 kW", "power", 50, 2, 0, 180_000,
       "Fifty kilowatts in sunlight. Keep it clear of the diggers' dust."),
    _m("battery", "Battery bank", "power", 0, 6, 0, 140_000,
       "A 200 kWh buffer for the hours generation falls short.",
       buffer_kwh=200),
    _m("radiator", "Radiator panel", "thermal", -4, -120, 0, 95_000,
       "Rejects 120 kW of heat. The constraint everyone forgets."),
    _m("hab", "Pressurised hab, 6-berth", "crew", -25, 30, 0, 620_000,
       "Berths for six.", berths=6, assemble_hours=2),
    _m("airlock", "Airlock", "crew", -8, 6, 0, 210_000,
       "One is required before anyone can live here."),
    _m("eclss", "ECLSS unit", "crew", -45, 55, 1, 480_000,
       "Air and water for eight. Needs one of them to run it.",
       supports=8, assemble_hours=2),
    _m("warehouse", "Cargo warehouse", "storage", -4, 3, 0, 160_000,
       "2,000 t of dry storage.", store_kg=2_000 * TONNE),
    _m("tankfarm", "Cryo tank farm", "storage", -40, 45, 0, 340_000,
       "800 t of propellant. Needs a liquefaction plant running.",
       tank_kg=800 * TONNE, assemble_hours=2),
    _m("cryo", "Cryo liquefaction", "storage", -200, 220, 0, 1_100_000,
       "Required to store propellant in a tank farm.", assemble_hours=2),
    _m("ice_miner", "Ice miner, automated", "industry", -90, 70, 0, 1_500_000,
       "12 t of ice a day at richness 1.0. Must stand on ice.",
       extract_kg_per_day=12 * TONNE, assemble_hours=4),
    _m("electrolysis", "Electrolysis plant", "industry", -280, 240, 1,
       1_800_000, "Turns 30 t of ice a day into 27 t of propellant.",
       feed_kg_per_day=30 * TONNE, assemble_hours=4),
    _m("command", "Command post", "control", -20, 18, 2, 390_000,
       "Required. One per site. Everything links back to it.",
       assemble_hours=2),
    _m("comms", "Comms relay", "control", -15, 10, 0, 130_000,
       "Required for remote operation: standing orders run through it."),
)}

#: The order modules are switched on when power or crew is short. Control
#: and life support first, then heat rejection and storage, then the plant,
#: and the diggers last: a base that cannot run everything keeps people
#: breathing before it keeps mining. *Invented*, D55.
PRIORITY = ("command", "comms", "airlock", "eclss", "hab", "radiator", "cryo",
            "tankfarm", "warehouse", "electrolysis", "ice_miner")
PRODUCERS = ("electrolysis", "ice_miner")

#: Propellant per tonne of ice. The agent plants' figure (sim/seed_world.py).
YIELD_NUMERATOR, YIELD_DENOMINATOR = 9, 10

#: What an electrolysis plant can hold in its own run tank when there is no
#: tank farm to send it to. *Invented* (D56): enough to make a trading lot,
#: little enough that storing propellant is something you have to build.
RUN_TANK_KG = 5 * TONNE

#: Dry stock a base can hold on the ground before it has a warehouse.
#: *Invented* (D56), for the same reason.
YARD_KG = 20 * TONNE

#: Dust. A solar array within this many tiles of a digger gives this much of
#: its nameplate. *Invented* (D57): the cheapest rule that makes where things
#: stand matter, and a real problem on the real Moon.
DUST_RADIUS = 2
DUST_NUMERATOR, DUST_DENOMINATOR = 1, 2

#: A conduit tile. Carries the link, costs no power. *Invented*, D58.
CONDUIT_COST = 1_000

#: The Ark's starter kit, leased: a small propellant works. D53.
KIT: tuple[str, ...] = (
    ("command", "hab", "airlock", "eclss", "comms", "warehouse",
     "electrolysis", "ice_miner", "ice_miner")
    + ("radiator",) * 5 + ("solar",) * 13)

#: Sites a company may be chartered. One per company in build 1.
SITES = {
    "shackleton_rim": {
        "name": "Shackleton Rim",
        "node": "shackleton_depot",
        "asset": "ICE",
        "polar": True,
        "blurb": "Permanent sunlight on the rim, ice in the shadowed ground "
                 "below it, and the Depot's market a short haul away.",
    },
}

#: Ice patches on a site, and how they compare. Richer ground lies further
#: from the middle. *Invented*, D54.
PATCH_GRADES = (70, 85, 100, 125, 150)   # percent of nameplate
PATCH_SCALE_KG = 3_000 * TONNE           # D38's figure for an ice claim


def _h(*parts) -> int:
    text = "|".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def site_layout(seed: str, size: int = SITE_SIZE) -> dict:
    """The ground a company was given: rocks and ice. Fixed by ``seed``.

    Derived, never stored: the same seed gives the same ground forever, so
    the database holds only what the company did to it.
    """
    mid = size // 2
    taken: set[tuple[int, int]] = set()
    patches = []
    # Five patches on a ring around the middle, further out as they get
    # richer, so the best ice is the longest conduit run.
    start = _h(seed, "ring") % 360
    for i, grade in enumerate(PATCH_GRADES):
        angle = (start + i * 72 + _h(seed, "jit", i) % 40) % 360
        reach = 4 + i + _h(seed, "reach", i) % 2
        # Integer trig is overkill for five points: a 24-step table will do.
        dx, dy = _RING[(angle // 15) % 24]
        cx = max(2, min(size - 3, mid + dx * reach // 10))
        cy = max(2, min(size - 3, mid + dy * reach // 10))
        tiles = []
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                t = (cx + ox, cy + oy)
                corner = ox != 0 and oy != 0
                if t in taken or (corner and _h(seed, "p", i, ox, oy) % 3 == 0):
                    continue
                tiles.append(t)
                taken.add(t)
        patches.append({"id": i, "grade": grade,
                        "tiles": [list(t) for t in sorted(tiles)]})
    rocks = []
    for x in range(size):
        for y in range(size):
            if (x, y) in taken or (abs(x - mid) <= 3 and abs(y - mid) <= 3):
                continue
            if _h(seed, "rock", x, y) % 100 < 7:
                rocks.append([x, y])
    return {"size": size, "rocks": rocks, "patches": patches}


#: (cos, sin) x 10 at 15 degree steps.
_RING = ((10, 0), (10, 3), (9, 5), (7, 7), (5, 9), (3, 10), (0, 10), (-3, 10),
         (-5, 9), (-7, 7), (-9, 5), (-10, 3), (-10, 0), (-10, -3), (-9, -5),
         (-7, -7), (-5, -9), (-3, -10), (0, -10), (3, -10), (5, -9), (7, -7),
         (9, -5), (10, -3))


def new_state(site: str, seed: str, tick: int) -> dict:
    """A bare site with the Ark's kit standing in crates beside it."""
    if site not in SITES:
        raise BaseError("There is no site by that name.")
    return {
        "v": 1, "site": site, "seed": seed, "size": SITE_SIZE,
        "created_tick": tick, "seq": 1,
        "modules": [], "conduits": [], "crates": list(KIT),
        "patches": [0] * len(PATCH_GRADES),     # kg extracted from each
        "battery_kwh": 0,
        "carry": {},                            # module id -> remainder
        "report": None,
    }


class BaseError(Exception):
    """A base request the rules refuse. The message is shown to the player."""


# -- where things may stand -----------------------------------------------------

def _occupied(state: dict) -> dict[tuple[int, int], dict]:
    return {(m["x"], m["y"]): m for m in state["modules"]}


def patch_at(layout: dict, x: int, y: int) -> int | None:
    for p in layout["patches"]:
        if [x, y] in p["tiles"]:
            return p["id"]
    return None


def check_tile(state: dict, layout: dict, x, y, *, moving: int | None = None
               ) -> None:
    """Refuse a tile nothing can stand on."""
    if (not isinstance(x, int) or not isinstance(y, int)
            or isinstance(x, bool) or isinstance(y, bool)
            or not (0 <= x < state["size"] and 0 <= y < state["size"])):
        raise BaseError("That is off the edge of your site.")
    if [x, y] in layout["rocks"]:
        raise BaseError("Boulders. Nothing can stand there.")
    there = _occupied(state).get((x, y))
    if there is not None and there["id"] != moving:
        raise BaseError("Something already stands there.")


def place(state: dict, layout: dict, kind: str, x: int, y: int, tick: int,
          leased: bool) -> dict:
    """Stand a module on a tile. Returns the new module."""
    spec = MODULES.get(kind)
    if spec is None:
        raise BaseError("The Ark's yard does not build that.")
    check_tile(state, layout, x, y)
    if kind == "command" and any(m["type"] == "command"
                                 for m in state["modules"]):
        raise BaseError("A site has one command post.")
    module = {"id": state["seq"], "type": kind, "x": x, "y": y,
              "leased": bool(leased), "ready": tick + spec.assemble_hours}
    state["seq"] += 1
    state["modules"].append(module)
    if [x, y] in state["conduits"]:
        state["conduits"].remove([x, y])
    return module


def find(state: dict, module_id) -> dict:
    for m in state["modules"]:
        if m["id"] == module_id:
            return m
    raise BaseError("There is no such module on your site.")


def move(state: dict, layout: dict, module_id, x: int, y: int, tick: int
         ) -> dict:
    """Pick a module up and stand it somewhere else. It is down meanwhile."""
    module = find(state, module_id)
    if (module["x"], module["y"]) == (x, y):
        raise BaseError("It is already standing there.")
    check_tile(state, layout, x, y, moving=module_id)
    module["x"], module["y"] = x, y
    module["ready"] = tick + MODULES[module["type"]].assemble_hours
    if [x, y] in state["conduits"]:
        state["conduits"].remove([x, y])
    return module


def remove(state: dict, module_id) -> dict:
    module = find(state, module_id)
    state["modules"].remove(module)
    state["carry"].pop(str(module_id), None)
    return module


def lay_conduit(state: dict, layout: dict, tiles: list) -> int:
    """Lay conduit on every free tile in ``tiles``. Returns how many."""
    if not isinstance(tiles, list) or len(tiles) > 64:
        raise BaseError("Lay at most 64 tiles of conduit at a time.")
    occupied = _occupied(state)
    laid = 0
    for tile in tiles:
        if (not isinstance(tile, (list, tuple)) or len(tile) != 2):
            raise BaseError("That is not a tile.")
        x, y = tile
        try:
            check_tile(state, layout, x, y)
        except BaseError:
            continue
        if (x, y) in occupied or [x, y] in state["conduits"]:
            continue
        state["conduits"].append([x, y])
        laid += 1
    return laid


def lift_conduit(state: dict, x: int, y: int) -> None:
    if [x, y] not in state["conduits"]:
        raise BaseError("There is no conduit there.")
    state["conduits"].remove([x, y])


def leased_value(state: dict) -> int:
    """List price of everything on lease: standing, or still in its crate."""
    return (sum(MODULES[m["type"]].cost for m in state["modules"]
                if m["leased"])
            + sum(MODULES[c].cost for c in state["crates"]))


def owned_value(state: dict) -> int:
    return sum(MODULES[m["type"]].cost for m in state["modules"]
               if not m["leased"])


# -- the hour -------------------------------------------------------------------

@dataclass
class Op:
    """One movement of mass the hour produced. `basegame` posts it."""

    kind: str          # "extract" or "consume"
    asset: str
    kg: int
    memo: str


@dataclass
class Hour:
    ops: list[Op] = field(default_factory=list)
    status: dict[int, str] = field(default_factory=dict)
    power_gen: int = 0
    power_use: int = 0
    heat_load: int = 0
    heat_reject: int = 0
    crew_cap: int = 0
    crew_need: int = 0
    crew_working: int = 0
    throttle: tuple[int, int] = (1, 1)
    store_kg: int = 0
    tank_kg: int = 0
    comms: bool = False
    made: dict[str, int] = field(default_factory=dict)
    used: dict[str, int] = field(default_factory=dict)


def linked(state: dict) -> set[int]:
    """Ids of modules joined to the command post by modules and conduit."""
    by_tile = _occupied(state)
    conduit = {tuple(c) for c in state["conduits"]}
    start = [m for m in state["modules"] if m["type"] == "command"]
    if not start:
        return set()
    seen = {(start[0]["x"], start[0]["y"])}
    frontier = list(seen)
    while frontier:
        x, y = frontier.pop()
        for t in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if t not in seen and (t in by_tile or t in conduit):
                seen.add(t)
                frontier.append(t)
    return {m["id"] for tile, m in by_tile.items() if tile in seen}


def deposit(state: dict, layout: dict, patch: int, node: str = "") -> Deposit:
    return Deposit(id=f"patch:{patch}", node=node, asset="ICE",
                   scale_kg=PATCH_SCALE_KG,
                   extracted_kg=state["patches"][patch])


def capacities(state: dict, on: set[int]) -> tuple[int, int]:
    """(dry storage, propellant storage) in kg, from what is running."""
    mods = [m for m in state["modules"] if m["id"] in on]
    dry = YARD_KG + sum(MODULES[m["type"]].store_kg for m in mods)
    plants = sum(1 for m in state["modules"]
                 if m["type"] == "electrolysis")
    tank = RUN_TANK_KG * plants
    if any(m["type"] == "cryo" for m in mods):
        tank += sum(MODULES[m["type"]].tank_kg for m in mods)
    return dry, tank


def run_hour(state: dict, layout: dict, tick: int, stock: dict[str, int], *,
             flaring: bool = False, suspended: bool = False) -> Hour:
    """Advance the base one game hour.

    Mutates ``state`` (battery, ground worked, remainders) and returns the
    hour: which modules ran and why the others did not, the budgets, and the
    mass movements for the ledger. ``stock`` is what the base holds now.
    """
    hour = Hour()
    stock = dict(stock)
    net = linked(state)
    has_command = any(m["type"] == "command" for m in state["modules"])
    order = {k: i for i, k in enumerate(PRIORITY)}
    mods = sorted(state["modules"],
                  key=lambda m: (order.get(m["type"], 99), m["id"]))

    def idle(m, why):
        hour.status[m["id"]] = why

    ready = []
    for m in mods:
        if m["ready"] > tick:
            idle(m, "assembling")
        elif not has_command:
            idle(m, "no_command")
        elif m["id"] not in net:
            idle(m, "unlinked")
        else:
            ready.append(m)

    # -- power: what the arrays give, dust taken into account
    diggers = [(m["x"], m["y"]) for m in ready if m["type"] == "ice_miner"]
    for m in ready:
        spec = MODULES[m["type"]]
        if spec.power_kw <= 0:
            continue
        out = spec.power_kw
        if any(max(abs(m["x"] - dx), abs(m["y"] - dy)) <= DUST_RADIUS
               for dx, dy in diggers):
            out = out * DUST_NUMERATOR // DUST_DENOMINATOR
            hour.status[m["id"]] = "dusty"
        else:
            hour.status[m["id"]] = "on"
        hour.power_gen += out
    bank = sum(MODULES[m["type"]].buffer_kwh for m in ready)
    for m in ready:
        if m["type"] == "battery":
            hour.status[m["id"]] = "on"
    available = hour.power_gen + min(state["battery_kwh"], bank)

    # -- life support first: people breathe before anything else runs
    LIFE = ("airlock", "eclss", "hab")
    staffed: list[dict] = []

    def fits(m) -> bool:
        return hour.power_use - MODULES[m["type"]].power_kw <= available

    def switch_on(m) -> None:
        hour.power_use -= MODULES[m["type"]].power_kw
        staffed.append(m)

    for m in ready:
        if m["type"] not in LIFE:
            continue
        if fits(m):
            switch_on(m)
        else:
            idle(m, "no_power")
    kinds = [m["type"] for m in staffed]
    pool = (sum(MODULES[k].berths for k in kinds)
            if "airlock" in kinds else 0)
    tended = min(kinds.count("eclss"), pool)        # each unit needs one hand
    hour.crew_cap = min(pool, tended * MODULES["eclss"].supports)
    free = hour.crew_cap - tended
    untended = kinds.count("eclss") - tended
    for m in reversed(list(staffed)):
        if untended and m["type"] == "eclss":
            staffed.remove(m)
            hour.power_use += MODULES["eclss"].power_kw
            idle(m, "no_crew")
            untended -= 1

    # -- then everything else, in priority order, while power and hands last
    desk = False
    for m in ready:
        spec = MODULES[m["type"]]
        if spec.power_kw >= 0 or m["type"] in LIFE:
            continue
        if m["type"] in PRODUCERS:
            if flaring or suspended or not desk:
                idle(m, "flare" if flaring else
                     "suspended" if suspended else "no_command")
                continue
        if not fits(m):
            idle(m, "no_power")
            continue
        if spec.crew > free:
            idle(m, "no_crew")
            continue
        free -= spec.crew
        switch_on(m)
        desk = desk or m["type"] == "command"
    hour.crew_need = sum(MODULES[m["type"]].crew for m in ready)
    hour.crew_working = sum(MODULES[m["type"]].crew for m in staffed)

    # -- battery
    spare = hour.power_gen - hour.power_use
    state["battery_kwh"] = max(0, min(bank, state["battery_kwh"] + spare))

    # -- heat: everything running is load; radiators reject; producers throttle
    running = {m["id"] for m in staffed}
    hour.heat_reject = sum(-MODULES[m["type"]].heat_kw for m in staffed
                           if MODULES[m["type"]].heat_kw < 0)
    passive = [m for m in ready if MODULES[m["type"]].power_kw >= 0]
    fixed = (sum(MODULES[m["type"]].heat_kw for m in passive)
             + sum(MODULES[m["type"]].heat_kw for m in staffed
                   if m["type"] not in PRODUCERS
                   and MODULES[m["type"]].heat_kw > 0))
    work = sum(MODULES[m["type"]].heat_kw for m in staffed
               if m["type"] in PRODUCERS)
    hour.heat_load = fixed + work
    if work and fixed + work > hour.heat_reject:
        hour.throttle = (max(0, hour.heat_reject - fixed), work)
    num, den = hour.throttle

    for m in staffed:
        hour.status[m["id"]] = "on"
    hour.comms = any(m["type"] == "comms" for m in staffed)
    hour.store_kg, hour.tank_kg = capacities(state, running)

    # -- the diggers
    for m in staffed:
        if m["type"] != "ice_miner":
            continue
        patch = patch_at(layout, m["x"], m["y"])
        if patch is None:
            idle(m, "no_ice")
            continue
        body = deposit(state, layout, patch)
        grade = layout["patches"][patch]["grade"]
        rate = MODULES["ice_miner"].extract_kg_per_day // TICKS_PER_GAME_DAY
        won = body.yield_for(rate * grade // 100) * num // den
        room = hour.store_kg - stock.get("ICE", 0)
        if room <= 0:
            idle(m, "full")
            continue
        won = min(won, room)
        if won < 1:
            idle(m, "worked_out" if num else "hot")
            continue
        state["patches"][patch] += won
        stock["ICE"] = stock.get("ICE", 0) + won
        hour.made["ICE"] = hour.made.get("ICE", 0) + won
        hour.ops.append(Op("extract", "ICE", won,
                           f"ice miner {m['id']} works patch {patch}"))
        if num < den:
            hour.status[m["id"]] = "hot"

    # -- the plant
    for m in staffed:
        if m["type"] != "electrolysis":
            continue
        wanted = (MODULES["electrolysis"].feed_kg_per_day
                  // TICKS_PER_GAME_DAY) * num // den
        room = hour.tank_kg - stock.get("PROP", 0)
        # Never take more ice than there is room for the propellant from.
        fits = max(0, room) * YIELD_DENOMINATOR // YIELD_NUMERATOR
        feed = min(wanted, stock.get("ICE", 0), fits)
        if feed < 1:
            idle(m, "hot" if not num else
                 "full" if fits < 1 else "no_feed")
            continue
        key = str(m["id"])
        carry = state["carry"].get(key, 0) + feed * YIELD_NUMERATOR
        made = carry // YIELD_DENOMINATOR
        state["carry"][key] = carry - made * YIELD_DENOMINATOR
        stock["ICE"] -= feed
        hour.used["ICE"] = hour.used.get("ICE", 0) + feed
        hour.ops.append(Op("consume", "ICE", feed,
                           f"electrolysis {m['id']} feedstock"))
        if made >= 1:
            stock["PROP"] = stock.get("PROP", 0) + made
            hour.made["PROP"] = hour.made.get("PROP", 0) + made
            hour.ops.append(Op("extract", "PROP", made,
                               f"electrolysis {m['id']} output"))
        if num < den:
            hour.status[m["id"]] = "hot"
    return hour


def report(state: dict, hour: Hour, tick: int) -> dict:
    """The hour as plain data, kept on the base for the client to draw."""
    return {
        "tick": tick,
        "status": {str(k): v for k, v in hour.status.items()},
        "power": [hour.power_use, hour.power_gen],
        "heat": [hour.heat_load, hour.heat_reject],
        "crew": [hour.crew_working, hour.crew_cap, hour.crew_need],
        "throttle": list(hour.throttle),
        "store_kg": hour.store_kg, "tank_kg": hour.tank_kg,
        "comms": hour.comms,
        "made": hour.made, "used": hour.used,
    }


# -- a layout that works ----------------------------------------------------------

def suggest_layout(state: dict, layout: dict
                   ) -> tuple[list[tuple[str, int, int]], list[list[int]]]:
    """Where a careful, unimaginative engineer would stand the crates.

    Returns (modules to stand, conduit to lay). The result always links and
    always runs, and it is deliberately not the best: the miners go on the
    nearest ice, not the richest, and nothing is done about how far the
    conduit runs. Finding the better layout is the player's game.
    """
    size = state["size"]
    rocks = {tuple(r) for r in layout["rocks"]}
    taken = {(m["x"], m["y"]) for m in state["modules"]}
    conduit = {tuple(c) for c in state["conduits"]}
    crates = list(state["crates"])
    command = next(((m["x"], m["y"]) for m in state["modules"]
                    if m["type"] == "command"), None)
    home = command or (size // 2, size // 2)

    def near(t) -> tuple:
        return (abs(t[0] - home[0]) + abs(t[1] - home[1]), t[0], t[1])

    # The miners first, because the solar arrays have to keep out of their dust.
    plan: list[tuple[str, int, int]] = []
    digs = [(m["x"], m["y"]) for m in state["modules"]
            if m["type"] == "ice_miner"]
    ice = sorted((tuple(t) for p in layout["patches"] for t in p["tiles"]
                  if tuple(t) not in taken), key=near)
    worked = {patch_at(layout, x, y) for x, y in digs}
    for _ in range(crates.count("ice_miner")):
        # One miner to a patch while there are fresh patches to be had.
        spot = next((t for t in ice if t not in digs
                     and patch_at(layout, *t) not in worked), None) \
            or next((t for t in ice if t not in digs), None)
        if spot is None:
            break
        digs.append(spot)
        worked.add(patch_at(layout, *spot))
        plan.append(("ice_miner", spot[0], spot[1]))
        crates.remove("ice_miner")

    def dusty(t) -> bool:
        return any(max(abs(t[0] - x), abs(t[1] - y)) <= DUST_RADIUS
                   for x, y in digs)

    cluster = set(taken) - set(digs)
    planned = {(x, y) for _, x, y in plan}
    order = sorted((c for c in crates if c != "ice_miner"),
                   key=lambda k: (k != "command", k == "solar", k))
    for kind in order:
        if kind == "command" and command is not None:
            continue
        if not cluster:
            edge = [home]
        else:
            edge = {(x + dx, y + dy) for x, y in cluster
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
        spots = sorted((t for t in edge
                        if 0 <= t[0] < size and 0 <= t[1] < size
                        and t not in rocks and t not in cluster
                        and t not in planned
                        and patch_at(layout, *t) is None
                        and not (kind == "solar" and dusty(t))), key=near)
        if not spots:
            continue
        x, y = spots[0]
        plan.append((kind, x, y))
        cluster.add((x, y))

    # Conduit from the cluster out to each miner, shortest way round the rocks.
    lay: list[list[int]] = []
    linked_tiles = set(cluster) | conduit
    for dig in digs:
        if not linked_tiles:
            break
        prev: dict = {t: None for t in linked_tiles}
        frontier = list(linked_tiles)
        while frontier and dig not in prev:
            nxt = []
            for x, y in frontier:
                for t in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if (t in prev or t in rocks or not 0 <= t[0] < size
                            or not 0 <= t[1] < size
                            or (t in digs and t != dig)):
                        continue
                    prev[t] = (x, y)
                    nxt.append(t)
            frontier = nxt
        step = prev.get(dig)
        while step is not None and step not in linked_tiles:
            lay.append([step[0], step[1]])
            linked_tiles.add(step)
            step = prev[step]
        linked_tiles.add(dig)
    return plan, lay
