"""Building the v1 world from docs/seed-data.md.

The bible's v1: "helium3.app only... a spot market, the Ark Authority, fifty
bulk agents and five named ones. No ships, no travel, no other regions."
docs/seed-data.md ships the first three lunar nodes, so all three exist here
with their own separate order books -- and, with no travel yet, their own
separate prices. That divergence is the setup for v2, when ships arrive and
the gap between two prices becomes the merchant profession.

Named agents are not here. They are `voice/`'s concern and they speak rather
than trade; the fifty below are the bulk agents that give the market depth.

Every number is either from seed-data or recorded in docs/DECISIONS.md.
"""

from __future__ import annotations

from pathlib import Path

from market.authority import ArkAuthority
from market.book import OrderBook
from market.db import transaction
from market.ledger import Ledger
from market.seed import seed_assets
from orbital.anchors import AnchorRegistry
from orbital.ephemeris import get_backend

from .deposits import Deposit
from .earth import EarthMarket
from .firms import Firm, Role
from .routes import RouteBook
from .ships import KESTREL, Ship
from .world import World

TONNE = 1_000

SHACKLETON = "shackleton_depot"
PEARY = "peary_ridge"
TRANQUILLITATIS = "tranquillitatis_flats"
NODES = (SHACKLETON, PEARY, TRANQUILLITATIS)

#: docs/seed-data.md section 2, volatility column. Drives price elasticity.
VOLATILITY = {
    "REGOLITH": "low", "ICE": "medium", "PROP": "high",
    "IRON": "low", "VOLATILE": "very high", "FOOD": "medium",
    "RAREEARTH": "medium", "GOODS": "low", "PGM": "high", "HE3": "very high",
}

#: The single most consequential dial in the world, and the one number the
#: design documents never named. Credits enter only through Earth's standing
#: order and leave only through sinks, so the ratio between them *is* the
#: money supply. See docs/DECISIONS.md D40 and finding F4.
#:
#: seed-data gives exactly one upkeep anchor -- the Kestrel at 400 cr per game
#: day -- and no upkeep figures for installations at all, so the per-firm
#: numbers below were invented. The first measured run had Earth injecting
#: 566,000 cr a day against 942,000 cr of sinks: a ratio of 0.52, an economy
#: quietly draining itself, with the firms' 66 million in capital exhausted in
#: about 145 game days.
#:
#: This scales every invented upkeep figure until the faucet and the drain
#: roughly balance. It is a tuning dial, not a discovered constant, and it is
#: the first thing to revisit when the roster changes.
UPKEEP_SCALE_NUMERATOR = 1
UPKEEP_SCALE_DENOMINATOR = 2


def _upkeep(raw: int) -> int:
    return raw * UPKEEP_SCALE_NUMERATOR // UPKEEP_SCALE_DENOMINATOR


#: Deposit scale: the mass that drops richness to 1/e. Set so a rig at
#: nameplate halves its yield after about 173 game days -- the bible's "a rock
#: that has been mined for six months yields less per hour than it did on day
#: one". See docs/DECISIONS.md D38.
ICE_DEPOSIT_SCALE = 3_000 * TONNE
REGOLITH_DEPOSIT_SCALE = 100_000 * TONNE


def _firm(fid, role, node, **kw) -> Firm:
    return Firm(id=fid, role=role, node=node, account=f"agent:{fid}", **kw)


def build(db, seed: int = 20260904, game_time: str = "2190-01-01T00:00:00Z"
          ) -> World:
    """Create the v1 world. Deterministic for a given seed."""
    ledger = Ledger(db)
    with transaction(db):
        ledger.bootstrap(game_time)
        seed_assets(ledger)

    books = {node: OrderBook(db, ledger, node) for node in NODES}
    authorities = {node: ArkAuthority(db, ledger, books[node]) for node in NODES}
    earth = EarthMarket(ledger, books)

    firms: list[Firm] = []
    deposits: dict[str, Deposit] = {}
    capital: dict[str, int] = {}

    def extractor(fid, node, asset, nameplate, scale, wage):
        deposit_id = f"claim:{fid}"
        deposits[deposit_id] = Deposit(id=deposit_id, node=node, asset=asset,
                                       scale_kg=scale)
        firms.append(_firm(
            fid, Role.EXTRACTOR, node, deposit_id=deposit_id,
            nameplate_kg_per_day=nameplate,
            targets={asset: nameplate * 2},
            upkeep_per_day=_upkeep(9_000), wages_per_day=wage,
        ))
        capital[fid] = 400_000

    # -- Peary Ridge: ice extraction ------------------------------------
    for i in range(8):
        extractor(f"peary_ice_{i}", PEARY, "ICE", 12 * TONNE,
                  ICE_DEPOSIT_SCALE, 6_000)
    for i in range(2):
        firms.append(_firm(f"peary_household_{i}", Role.CONSUMER, PEARY,
                           consumes="PROP", consumption_kg_per_day=6 * TONNE,
                           targets={"PROP": 20 * TONNE}, upkeep_per_day=0))
        capital[f"peary_household_{i}"] = 300_000
    firms.append(_firm("peary_trader_0", Role.TRADER, PEARY,
                       trades="ICE", targets={"ICE": 60 * TONNE},
                       upkeep_per_day=4_000))
    capital["peary_trader_0"] = 1_500_000

    # -- Shackleton Depot: ice, refining, demand ------------------------
    # Ten miners at 12 t/day feed four plants at 30 t/day exactly. The first
    # run of this world had six of each, so feedstock demand ran two and a
    # half times supply and ice settled at six times its anchor -- correct
    # price formation over an incoherent roster. seed-data's own numbers
    # define the ratio: 2.5 ice miners per electrolysis plant.
    for i in range(10):
        extractor(f"shack_ice_{i}", SHACKLETON, "ICE", 12 * TONNE,
                  ICE_DEPOSIT_SCALE, 6_000)
    for i in range(4):
        fid = f"shack_electrolysis_{i}"
        firms.append(_firm(
            fid, Role.REFINER, SHACKLETON,
            input_asset="ICE", output_asset="PROP",
            conversion_rate=30 * TONNE,          # seed-data: 30 t/day
            yield_numerator=9, yield_denominator=10,
            targets={"ICE": 40 * TONNE, "PROP": 20 * TONNE},
            upkeep_per_day=_upkeep(45_000), wages_per_day=18_000,
        ))
        capital[fid] = 2_500_000
    for i in range(5):
        fid = f"shack_household_{i}"
        firms.append(_firm(fid, Role.CONSUMER, SHACKLETON,
                           consumes="PROP", consumption_kg_per_day=8 * TONNE,
                           targets={"PROP": 24 * TONNE}, upkeep_per_day=0))
        capital[fid] = 400_000
    for i in range(2):
        fid = f"shack_ice_trader_{i}"
        firms.append(_firm(fid, Role.TRADER, SHACKLETON, trades="ICE",
                           targets={"ICE": 80 * TONNE}, upkeep_per_day=4_000))
        capital[fid] = 2_000_000
    for i in range(2):
        fid = f"shack_prop_trader_{i}"
        firms.append(_firm(fid, Role.TRADER, SHACKLETON, trades="PROP",
                           targets={"PROP": 40 * TONNE}, upkeep_per_day=4_000))
        capital[fid] = 3_000_000

    # -- Tranquillitatis Flats: regolith and helium-3 -------------------
    for i in range(8):
        extractor(f"tranq_regolith_{i}", TRANQUILLITATIS, "REGOLITH",
                  400 * TONNE, REGOLITH_DEPOSIT_SCALE, 8_000)
    for i in range(4):
        fid = f"tranq_separator_{i}"
        firms.append(_firm(
            fid, Role.REFINER, TRANQUILLITATIS,
            input_asset="REGOLITH", output_asset="HE3",
            conversion_rate=400 * TONNE,         # seed-data: 400 t/day feed
            yield_numerator=3, yield_denominator=2_000_000,  # 0.6 kg per 400 t
            # No helium-3 inventory target. A separator yields 0.025 kg an
            # hour, so even a 2 kg target means hoarding eighty hours of
            # output before offering any -- which delayed the world's only
            # source of credits by the same margin. Producers sell what they
            # make; they are not stockists.
            targets={"REGOLITH": 800 * TONNE, "HE3": 0},
            upkeep_per_day=_upkeep(120_000), wages_per_day=40_000,
        ))
        capital[fid] = 6_000_000
    for i in range(2):
        fid = f"tranq_household_{i}"
        firms.append(_firm(fid, Role.CONSUMER, TRANQUILLITATIS,
                           consumes="PROP", consumption_kg_per_day=7 * TONNE,
                           targets={"PROP": 20 * TONNE}, upkeep_per_day=0))
        capital[fid] = 400_000
    for i in range(2):
        fid = f"tranq_trader_{i}"
        firms.append(_firm(fid, Role.TRADER, TRANQUILLITATIS, trades="HE3",
                           targets={"HE3": 12}, upkeep_per_day=4_000))
        capital[fid] = 8_000_000

    # -- haulers: the v2 addition ---------------------------------------
    #
    # The bible's v1 is fifty bulk agents and no ships. These six are what
    # turns two prices into a trade: "the moment there are two places with
    # different prices, the game becomes trade, and that is the real
    # product." Two based at each node so no single depot owns the traffic.
    ships: list[Ship] = []
    for node, n in ((SHACKLETON, 2), (PEARY, 2), (TRANQUILLITATIS, 2)):
        for i in range(n):
            fid = f"hauler_{node.split('_')[0]}_{i}"
            firms.append(_firm(fid, Role.HAULER, node,
                               upkeep_per_day=KESTREL.upkeep_per_day))
            capital[fid] = 900_000
            ships.append(Ship(id=f"{fid}_kestrel", owner=fid,
                              account=f"agent:{fid}", ship_class=KESTREL,
                              location=node))

    # -- open and fund every account ------------------------------------
    with transaction(db):
        for firm in firms:
            ledger.open_account(firm.account, "agent", game_time, label=firm.id)
            ledger.mint(firm.account, capital[firm.id], game_time,
                        memo=f"{firm.id} opening capital")

        # Ships arrive in the world fuelled. A hauler that has to buy its
        # first tank before it can reach anywhere selling fuel never moves.
        for ship in ships:
            ledger.extract(ship.account, "PROP", ship.ship_class.tank_capacity_kg,
                           game_time, memo=f"{ship.id} opening tank")

        # Settlements open with stores of what they burn. Without this, a
        # node with no local supply spends its first game day bidding into an
        # empty book, and the ratchet that produces sets a price the market
        # then anchors to: Peary propellant reached 17,874 against an 1,800
        # anchor before the first delivery ever arrived.
        for firm in firms:
            if firm.role is Role.CONSUMER and firm.consumes:
                ledger.extract(firm.account, firm.consumes,
                               firm.targets.get(firm.consumes, 0), game_time,
                               memo=f"{firm.id} opening stores")

        for node in NODES:
            authorities[node].establish(game_time, treasury=40_000_000)
        earth.establish(game_time, funding=2_000_000_000)

        # Opening inventory so the Authority's ask is real from tick one.
        authorities[SHACKLETON].endow("ICE", 400 * TONNE, game_time)
        authorities[SHACKLETON].endow("PROP", 200 * TONNE, game_time)
        authorities[PEARY].endow("ICE", 300 * TONNE, game_time)
        authorities[TRANQUILLITATIS].endow("REGOLITH", 2_000 * TONNE, game_time)

        # Separators open with a full hopper. A plant that starts empty burns
        # 160,000 cr a day producing nothing until the regolith market forms,
        # which is a startup artifact rather than an economic fact -- and it
        # delayed the first gram of helium-3, and therefore the first credits
        # entering the world, by roughly 200 ticks.
        for firm in firms:
            if firm.output_asset == "HE3":
                ledger.extract(firm.account, "REGOLITH", 800 * TONNE,
                               game_time, memo=f"{firm.id} opening feedstock")

    world = World(
        ledger=ledger, books=books, authorities=authorities, earth=earth,
        firms=firms, deposits=deposits, seed=seed,
        ships=ships,
        routes=RouteBook(AnchorRegistry.load(
            get_backend("auto"),
            Path(__file__).resolve().parents[3] / "orbital/data/anchors.toml",
            Path(__file__).resolve().parents[3] / "orbital/data/smallbody_elements.json",
        )),
        volatility=VOLATILITY,
        earth_assets={TRANQUILLITATIS: "HE3"},
        quoted_assets={
            SHACKLETON: ["ICE", "PROP"],
            PEARY: ["ICE"],
            TRANQUILLITATIS: ["REGOLITH"],
        },
        starting_capital=capital,
    )

    for node, assets in world.quoted_assets.items():
        for asset in assets:
            authorities[node].quote(asset, game_time, bid_lots=60, ask_lots=60)
    earth.refresh(TRANQUILLITATIS, "HE3", game_time)

    return world
