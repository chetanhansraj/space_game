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

from market.book import ASK, BID
from market.db import transaction
from market.errors import MarketError
from market.money import CREDIT
from orbital.clock import game_seconds, to_jd

from . import TICKS_PER_GAME_DAY, plots, sun
from .earth import ACCOUNT as EARTH
from .errors import GameError
from .routes import NODE_ANCHOR
from .seed_world import PORTS, TONNE, TRANQUILLITATIS
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
#: A town's buildings begin to wear parts once it has a working landing pad
#: and has reached this many people: the city builder's "Base" tier (D82).
#: Until D92 this was also the size a town needed before it could trade.
WEAR_POPULATION = 8
#: How long the lander's air lasts, in game hours. The rules own this number
#: (city/src/sim); it is repeated here only for the letters.
LANDER_HOURS = 160


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
#: What a kilogram of parts landed from Earth costs, against what the
#: Moon's own goods are worth at the port (the seed anchor). Twice: lifting
#: them out of Earth's gravity is the reason anything is made here at all.
#: It is also the most a town would ever pay another for goods, so it is
#: the ceiling of the goods market as Earth's standing bid is its floor.
#: *Invented*, D82.
PARTS_IMPORT_PREMIUM = 2
#: Hours of parts a standing sale leaves in the yard when the owner has not
#: said how much to keep: a lunar night of 354 hours, when no foundry runs,
#: and a few over. *Invented*, D82.
PARTS_KEEP_HOURS = 360
#: And the most it will keep by itself, so a big town's reserve never
#: counts as goods piling up, which stops industry growing (D76).
PARTS_KEEP_MAX = YARD_KG // 2 - 2 * TONNE
#: A town short of parts offers this much a tonne more than the best bid
#: at the port that is not another town's, and never more than its owner's
#: limit or what Earth charges. So a town in need is served before the
#: households and Earth's order, pays no more than it must, and two towns
#: in need share what is sold and do not bid each other up to Earth's
#: price. *Invented*, D83.
PARTS_BID_STEP = 500
#: The most a town bids for at once, in trading lots. The bid is renewed
#: every hour, so this limits how much of the owner's money waits on the
#: book, not how much the town can buy. *Invented*, D83.
PARTS_ORDER_LOTS = 2
#: The Ark's freight line carries a town's goods from its own port to a
#: buyer at another, inside the hour: a hop between any two places on the
#: Moon is under an hour's flight. What it charges for a tonne is the
#: propellant that hop burns to throw a tonne, at propellant's seed
#: price, times this for the vehicle's own mass and the line's costs.
#: The charge is burned: a sink, not anyone's income. *Invented*, D86.
FREIGHT_OVERHEAD = 2.0
#: Exhaust velocity the line's hoppers are costed at, metres a second:
#: hydrogen and oxygen, which is what the Moon's ice makes.
FREIGHT_EXHAUST = 4_400.0


#: A caretaker's wage, in credits a game hour, while one is hired. Burned:
#: the caretaker is not a modelled household, so by D37 this is a sink and
#: not a transfer. *Invented*, D79: 4,800 cr a game day, about what a town
#: of ten pays for its supplies, so it is felt by a small town and is small
#: change to a large one. Eight real hours away costs 96 town credits.
CARETAKER_FEE = 200


#: Companies the world runs, in the order it charters them. Each is an
#: ordinary company: the same grant from the same fund, the same ship and
#: fee, the same town rules, the same seven requests, through the same
#: door. What is different is who is at the controls: the steward, every
#: hour (D77, D81). Their ids are fixed so that a world replayed from its
#: seed founds the same towns on the same ground.
HOUSE = (
    ("house_mare", "Mare Cooperative", "balanced"),
    ("house_serenitatis", "Serenitatis Foundry Co", "foundry"),
    ("house_tycho", "Tycho Settlement Trust", "resort"),
    ("house_imbrium", "Imbrium Works", "works"),
    ("house_fecunditatis", "Fecunditatis Union", "hostel"),
    ("house_shackleton", "Shackleton Ice Company", "icehouse"),
    ("house_korolev", "Korolev Quiet Trust", "observatory"),
)
#: Where each house company's town stands: the place it is named for.
#: Latitude and longitude in degrees, north and east positive. Five on
#: the near side's plains and highlands, one on the south polar rim and
#: one deep on the far side, so the seed of the world covers every kind
#: of ground a person can be given (D84).
HOUSE_PLACE = {
    "house_mare": (0.7, 23.5),            # Mare Tranquillitatis, by Apollo 11
    "house_serenitatis": (28.0, 17.5),
    "house_tycho": (-43.3, -11.4),
    "house_imbrium": (32.8, -15.6),
    "house_fecunditatis": (-7.8, 51.3),
    "house_shackleton": (-89.5, 0.0),
    "house_korolev": (-4.0, -157.4),
}
#: How each kind of house company likes to build once its crew is safe: the
#: most lots of a zone it lays out unasked (r homes, i industry, v
#: commercial), the price level it charges (0 low, 1 fair, 2 high) and the
#: contracts it turns down. A temperament changes what the steward chooses,
#: never what it may do, and what the crew asks for is done regardless.
#: They are what make the Moon's towns different from each other, so that
#: one has goods to spare and another needs them. *Invented*, D83.
TEMPERAMENTS: dict[str, dict] = {
    "balanced": {},
    "foundry": {"lots": {"v": 1}, "price": 0, "refuse": ["broadcast"]},
    "works": {"lots": {"v": 2}, "refuse": ["broadcast"]},
    "resort": {"lots": {"i": 0}, "price": 2, "foundries": 0,
               "refuse": ["works"]},
    "hostel": {"lots": {"i": 1}, "foundries": 1, "refuse": ["works"]},
    "icehouse": {"lots": {"v": 0}, "refuse": ["broadcast"]},
    "observatory": {"lots": {"i": 1}, "refuse": ["works", "oxygen"]},
}
#: What each is called where towns are listed.
TEMPER_NAMES = {"balanced": "Mixed town", "foundry": "Foundry town",
                "works": "Works town", "resort": "Resort",
                "hostel": "Hostel town", "icehouse": "Ice town",
                "observatory": "Observatory town"}
HOUSE_TEMPER = {pid: temper for pid, _, temper in HOUSE}
#: Game days between one house company's chartering and the next, so the
#: Moon's towns are of different ages. *Invented*, D81.
HOUSE_EVERY_DAYS = 2
#: Game days a house company waits before sending a new crew to a town it
#: lost. A relief crew draws on the Ark's fund (D80); this stops a town
#: that keeps failing from draining it. *Invented*, D81.
HOUSE_RETURN_DAYS = 7
#: What a house town may owe before its company recalls the crew: as much
#: as founding a new one costs. A person in that hole can fly cargo to pay
#: it off; a house company has no other business, and the rules stop a
#: town in debt from building, so past this it would only sit there owing
#: more. Measured: towns that recover never owed half of it. D81.
HOUSE_RECALL_DEBT = TOWN_START


def _ticks_in(real_seconds: float) -> int:
    """Whole game hours in a stretch of real time, at the world's one rate."""
    return max(1, round(game_seconds(real_seconds) / 3_600))


#: Game hours in a real minute, for the town's rules to size the waits a
#: person must answer (city/src/sim/contracts.ts OFFER_MINUTES).
PACE = game_seconds(60) / 3_600
#: What the Ark pays a company when its first landing pad comes into work,
#: once. Building to the pad empties a new company's account, and nothing
#: comes back until ships can land: measured, a careful owner sat near
#: nothing from the pad to well after the first shuttle. This is not new
#: money. It leaves the Ark's development fund, which is finite, like the
#: founding grant it is the size of. *Invented*, D93.
PAD_GRANT = TOWN_GRANT
#: An owner who has not been at their town for this long is away, and the
#: crew keeps watch: each hour they do what is urgent and nothing else, as
#: a caretaker would, without the wage. Ten real minutes. *Invented*, D93.
WATCH_AFTER = _ticks_in(10 * 60)
#: How long the crew keeps watch before the town is on its own: twelve real
#: hours, a night's sleep and a morning. At the world's pace that is four
#: lunar days, which an unwatched young town does not always survive
#: (measured, D93). Past it a hired caretaker is what keeps a town.
#: *Invented*, D93.
WATCH_FOR = _ticks_in(12 * 3_600)
#: The owner's last visit is written down at most this often: five real
#: minutes. A visit is a read, and this keeps reads from becoming writes.
SEEN_EVERY = _ticks_in(5 * 60)
# A town that stood before the pad's blast zone existed is given this long
# before a landing clears it (D96): three real days, in game hours.
BLAST_NOTICE = _ticks_in(3 * 24 * 3_600)
#: The order of a town's standing, for saying when it has grown. The rules
#: own the names (city/src/sim TIERS); only their order is repeated here.
TIER_RANK = {"Outpost": 0, "Base": 1, "Colony": 2, "Town": 3}


def plot_offers(player_id: str, jd: float | None = None, tick: int = 0
                ) -> list[dict]:
    """The ground a company may found its town on.

    A house company stands where it is named for, so it has one. Anyone
    else is shown three plots and chooses one (D85). Given the sky
    (``jd``), they are three where it is morning now, and they change as
    the sunrise moves on (D93); without it, three drawn from the company's
    id alone.
    """
    if player_id in HOUSE_PLACE:
        return [plots.plot_at(*HOUSE_PLACE[player_id])]
    return plots.offers_for(player_id, jd, tick)


def plot_for(player_id: str, choice: int = 0, jd: float | None = None,
             tick: int = 0, at: tuple[float, float] | None = None) -> dict:
    """The plot a company chose, of those it was offered.

    ``at`` is where the chosen plot is, if the company said: the list moves
    on with the sunrise, and a choice made by its place in the list could
    land on ground the company never looked at. A plot offered in the last
    list is still good while it is still morning there.
    """
    offers = plot_offers(player_id, jd, tick)
    if at is not None:
        older = (plot_offers(player_id, jd - plots.OFFER_HOLD / 24.0,
                             tick - plots.OFFER_HOLD)
                 if jd is not None and tick >= plots.OFFER_HOLD else [])
        for plot in offers + [p for p in older if plots.in_morning(p, jd)]:
            if (plot["lat"], plot["lon"]) == (round(at[0], 1), round(at[1], 1)):
                return plot
        raise GameError("The sunrise has moved on from that ground. "
                        "Choose one of the plots on offer now.")
    if isinstance(choice, bool) or not isinstance(choice, int) \
            or not 0 <= choice < len(offers):
        raise GameError("Choose one of the plots you were offered.")
    return offers[choice]


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

    # -- the one Sun (D93) -------------------------------------------------

    def _sun_jd(self) -> float:
        """The sky's own date, which is where the Sun is asked for."""
        return to_jd(self.sky_time())

    def _town_lon(self, plot: dict) -> float:
        """The longitude a town keeps time by. A town from before plots is
        at the Flats, where every town used to be."""
        if "lon" in plot:
            return plot["lon"]
        return self.world.routes.registry[NODE_ANCHOR[TOWN_NODE]].site.lon_deg

    def _town_dark(self, plot: dict) -> float:
        return plot.get("dark", sun.LUNAR_DAY / 2)

    def _world_hour(self, plot: dict) -> dict:
        """What the world tells a town's rules of the hour: where the Sun
        stands over it, and how fast the one clock runs."""
        noon = sun.hours_since_noon(self._town_lon(plot), self._sun_jd())
        return {"noon": round(noon, 3), "pace": PACE}

    def _morning(self, plot: dict) -> bool:
        """Is it morning there: early enough in the day to land a crew?"""
        return sun.phase(self._town_lon(plot), self._town_dark(plot),
                         self._sun_jd()) <= plots.MORNING

    def _to_sunrise(self, plot: dict) -> int:
        """Whole hours until the Sun next rises there."""
        phase = sun.phase(self._town_lon(plot), self._town_dark(plot),
                          self._sun_jd())
        return math.ceil(sun.LUNAR_DAY - phase)

    def plot_offers(self, player_id: str) -> list[dict]:
        """The plots on offer to a company this hour, each with the hours of
        daylight it has left."""
        jd = self._sun_jd()
        out = []
        for plot in plot_offers(player_id, jd, self.world.tick):
            light = (sun.LUNAR_DAY - plot["dark"]
                     - sun.phase(plot["lon"], plot["dark"], jd))
            out.append({**plot, "light": max(0, round(light))})
        return out

    def _chosen_plot(self, player_id: str, choice: int, at) -> dict:
        if at is not None:
            try:
                at = (float(at[0]), float(at[1]))
            except (TypeError, ValueError, IndexError):
                raise GameError("Choose one of the plots you were offered.")
        return plot_for(player_id, choice, self._sun_jd(), self.world.tick, at)

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
                    "sold_yesterday", "sales_yesterday", "used_kg",
                    "landed_kg"):
            book.setdefault(key, 0)
        book.setdefault("first_sale", False)
        book.setdefault("keep_t", None)     # None: the yard decides (D82)
        book.setdefault("buy", True)        # bid at the port when short (D83)
        book.setdefault("max_price", None)  # None: up to Earth's price
        book.setdefault("bought_kg", 0)
        book.setdefault("spent", 0)
        return book

    def _parts_price(self) -> int:
        """Credits a tonne for parts landed from Earth."""
        return (self.world.ledger.asset(YARD_ASSET).base_value
                * PARTS_IMPORT_PREMIUM)

    # -- ports and freight (D86) ------------------------------------------------

    def _port_at(self, lat: float, lon: float) -> str:
        """The port nearest a place on the Moon."""
        registry = self.world.routes.registry

        def far(node: str) -> float:
            site = registry[NODE_ANCHOR[node]].site
            return plots._arc(lat, lon, site.lat_deg, site.lon_deg)
        return min(PORTS, key=lambda node: (far(node), node))

    def _port_name(self, node: str) -> str:
        return getattr(self, "node_names", {}).get(node, node)

    def _port(self, player_id: str) -> str:
        """The port a company's town trades at: the one nearest its plot.

        A town from before plots, or on the reference ground the tests
        use, is at the Flats, where every town used to be.
        """
        row = self._town_row(player_id)
        plot = json.loads(row["plot"] or "{}") if row is not None else {}
        if "lat" not in plot:
            return TOWN_NODE
        return self._port_at(plot["lat"], plot["lon"])

    def _freight(self, origin: str, destination: str) -> int:
        """Credits a tonne to carry goods between two ports. Nothing at home."""
        if origin == destination:
            return 0
        leg = self.world.routes.leg(origin, destination)
        if leg is None:
            raise GameError("The freight line does not fly that way.")
        fuel = math.exp(leg.dv / FREIGHT_EXHAUST) - 1.0     # tonnes a tonne
        price = self.world.ledger.asset("PROP").base_value
        return int(math.ceil(fuel * FREIGHT_OVERHEAD * price / 100.0)) * 100

    def _best_market(self, home: str, limit: int) -> tuple[str, int, int] | None:
        """Where a town's goods fetch most after freight: port, bid, freight.

        Every port's best bid is looked at, less what it costs to carry a
        tonne there. ``None`` if nowhere nets the town its price.
        """
        best = None
        for port in PORTS:
            bid = self.world.books[port].best_bid(YARD_ASSET)
            if not bid:
                continue
            freight = self._freight(home, port)
            net = bid - freight
            if net >= limit and (best is None or net > best[1] - best[2]
                                 or (net == best[1] - best[2]
                                     and freight < best[2])):
                best = (port, bid, freight)
        return best

    def _parts_settle(self, player, account: str, book: dict, now: str
                      ) -> None:
        """Take the town's bid off the book and bring its money home.

        What the bid bought is already in the yard. What it did not spend
        goes back to the company, so no credit is ever left in the yard.
        """
        ledger = self.world.ledger
        last = book.pop("order", None)
        if last:
            row = self.db.execute(
                "SELECT remaining_kg, status FROM book_order WHERE id = ?",
                (last["id"],)).fetchone()
            # An order closed long enough ago may have left for the ledger
            # archive (market/archive.py). Then it is closed, its escrow was
            # empty, and what it bought was counted when it was open.
            if row is not None and row["status"] == "OPEN":
                self.world.books[last.get("port", TOWN_NODE)].cancel(
                    last["id"], now)
            left = ledger.balance(account, CREDIT)
            book["bought_kg"] += (last["kg"] - row["remaining_kg"]
                                  if row is not None else 0)
            book["spent"] += last["funded"] - left
        left = ledger.balance(account, CREDIT)
        if left > 0:
            ledger.transfer(account, player.account, CREDIT, left,
                            kind="sweep", game_time=now, ref=player.id,
                            memo="parts order money returned")

    def _parts_order(self, player, account: str, book: dict, summary: dict,
                     now: str) -> None:
        """Bid at the port for the parts the yard is short of.

        A resting bid, like a household's or Earth's, that another town's
        sale can fill: this is how one town buys from another. It is for
        whole lots up to the reserve, never above the owner's price or
        what Earth charges, and it is paid for in full when placed, from
        the company's own credits. Renewed every hour, so it never stands
        on the book after the town that placed it has stopped needing it.
        """
        ledger = self.world.ledger
        spec = ledger.asset(YARD_ASSET)
        lot = spec.lot_mass_kg
        home = self._port(player.id)
        held = ledger.balance(account, YARD_ASSET)
        short = min(self._keep_kg(book, summary), YARD_KG) - held
        # What the best buyer who is not a town pays, wherever on the Moon
        # that is, plus what it costs to carry a tonne from there to here:
        # a seller beside that buyer must do at least as well by coming
        # to this port. Then a step more.
        best = self.db.execute(
            "SELECT price, node FROM book_order WHERE asset = ? "
            "AND side = 'BID' AND status = 'OPEN' "
            "AND account_id NOT LIKE 'town:%' ORDER BY price DESC, id "
            "LIMIT 1", (YARD_ASSET,)).fetchone()
        rival = (best["price"] + self._freight(best["node"], home)
                 if best else spec.base_value)
        price = min(book["max_price"] or self._parts_price(),
                    self._parts_price(), rival + PARTS_BID_STEP)
        lots = min(short // lot, PARTS_ORDER_LOTS,
                   ledger.balance(player.account, CREDIT) // price)
        if lots < 1:
            return
        cost = spec.cost(price, lots * lot)
        ledger.transfer(player.account, account, CREDIT, cost, kind="sweep",
                        game_time=now, ref=player.id,
                        memo="parts order paid in")
        placed = self.world.books[home].place(
            YARD_ASSET, BID, price, lots * lot, account, now)
        book["order"] = {"id": placed.order_id, "kg": lots * lot,
                         "funded": cost, "port": home}

    def _yard_close(self, player, now: str) -> None:
        """A town that has stopped: nothing of its is left on the book."""
        row = self._town_row(player.id)
        book = self._yard_book(row)
        self._parts_settle(player, self._yard_account(player), book, now)
        self._save_yard(player.id, book)

    def _keep_kg(self, book: dict, summary: dict) -> int:
        """What a standing sale leaves in the yard for the town's own use."""
        if book.get("keep_t") is not None:
            return min(book["keep_t"] * TONNE, YARD_KG)
        return min(math.ceil(summary.get("parts", 0) * PARTS_KEEP_HOURS),
                   PARTS_KEEP_MAX)

    def _yard_roll(self, book: dict) -> None:
        """Start a new game day's totals when the day has turned."""
        day = self.world.tick // TICKS_PER_GAME_DAY
        if book["day"] != day:
            fresh = book["day"] == day - 1
            for key in ("made", "sold", "sales"):
                book[f"{key}_yesterday"] = book[f"{key}_today"] if fresh else 0
                book[f"{key}_today"] = 0
            book["day"] = day

    def _trade_open(self, summary: dict, book: dict) -> bool:
        """May the town trade? A working landing pad, and nothing else (D92).

        It used to need eight people as well (D71). That number was invented,
        and it kept a town with a pad standing on it shut out of the market.
        A pad is something a player builds and can see; a head count was not.

        The head count still marks one thing, as it did: a town with a pad
        that has once reached it is a going concern, and from then on its
        buildings wear parts (D82). That is passed once and kept in the book,
        so a town that shrinks does not stop wearing. A small town with a new
        pad may trade and is not yet charged for wear.
        """
        if summary["pad"] and summary["population"] >= WEAR_POPULATION:
            book["trading"] = True
        return bool(summary["pad"])

    def trade_clearance(self, player) -> None:
        """Refuse unless this company's town has a working landing pad.

        The market is for everyone to watch and for a town with a pad to
        use: its own yard, and its company's ship. One rule for both, held
        here and not in a screen (D92). House companies are played by the
        steward inside the world and do not come this way.
        """
        row = self._town_row(player.id)
        if row is None or row["lost_tick"] is not None:
            raise GameError("The market is open to watch. To trade in it, "
                            "found your town and build a landing pad.")
        if not self.town_engine.summary(row["state"])["pad"]:
            raise GameError("The market is open to watch. To trade in it, "
                            "your town needs a working landing pad.")

    def _yard_sell(self, player, account: str, book: dict, qty_kg: int,
                   limit: int, now: str):
        """Sell from the yard to the best bid on the Moon, now or not at all.

        Whole trading lots only, to whoever is bidding most once the
        freight to their port is taken off, at their price, and never for
        less than ``limit`` after freight. The freight line is paid out of
        the takings and what it is paid is burned. The rest goes straight
        to the company. Nothing rests on the book afterwards: an order a
        player forgot about is not left standing in their name.
        """
        ledger = self.world.ledger
        lot = ledger.asset(YARD_ASSET).lot_mass_kg
        lots = min(qty_kg, ledger.balance(account, YARD_ASSET)) // lot
        if lots < 1:
            return None
        home = self._port(player.id)
        market = self._best_market(home, limit)
        # nowhere nets the price: ask at home, which will fill nothing, and
        # say so the way an unfilled order always has
        port, freight = (market[0], market[2]) if market else (home, 0)
        try:
            result = self._ioc(port, YARD_ASSET, ASK, limit + freight,
                               lots * lot, account, now)
            carried = freight * (result.filled_kg // lot)
            if carried:
                ledger.burn(account, carried, now, ref=player.id,
                            memo=f"freight to {port}")
                book["freight"] = book.get("freight", 0) + carried
        finally:
            takings = ledger.balance(account, CREDIT)
            if takings > 0:
                ledger.transfer(account, player.account, CREDIT, takings,
                                kind="sweep", game_time=now, ref=player.id,
                                memo="yard takings to the company")
        if result.filled_kg:
            value = sum(f.value for f in result.fills) - carried
            book["sold_kg"] += result.filled_kg
            book["sold_today"] += result.filled_kg
            book["sales"] += value
            book["sales_today"] += value
            book["sold_at"] = port
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
        if not self._trade_open(summary, self._yard_book(row)):
            raise GameError(
                "Nothing leaves the yard until the town has a working "
                "landing pad.")
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

    def town_policy(self, player, sell: bool, min_price: int,
                    keep_t: int | None = None, buy: bool | None = None,
                    max_price: int | None = None) -> dict:
        """Set the standing instruction: sell what is made, or hold it.

        ``keep_t`` is how many tonnes a standing sale leaves in the yard
        for the town's own buildings. Left out, the yard keeps a lunar
        night's worth of parts by itself. ``buy`` is whether to bid at the
        port when the yard is short of that, and ``max_price`` the most to
        offer a tonne; left out, they stay as they are.
        """
        row = self._town(player)
        if not isinstance(sell, bool):
            raise GameError("Say whether to sell or to hold.")
        if keep_t is not None and (isinstance(keep_t, bool)
                                   or not isinstance(keep_t, int)
                                   or not 0 <= keep_t <= YARD_KG // TONNE):
            raise GameError("Keep a whole number of tonnes, no more than "
                            "the yard holds.")
        book = self._yard_book(row)
        if buy is not None and not isinstance(buy, bool):
            raise GameError("Say whether to buy parts at the port or not.")
        book["sell"], book["min_price"] = sell, self._price(min_price)
        book["keep_t"] = keep_t
        if buy is not None:
            book["buy"] = buy
        if max_price is not None:
            book["max_price"] = self._price(max_price)
        with self._mutation():
            if not book["buy"]:     # told to stop: the bid comes off now
                self._parts_settle(player, self._yard_account(player), book,
                                   self.world.game_time())
            self._save_yard(player.id, book)
        return self.town_meta(player)

    def _first_sale(self, player, book: dict, result) -> list[Event]:
        if book["first_sale"] or result is None or not result.filled_kg:
            return []
        book["first_sale"] = True
        return [Event(
            tick=self.world.tick, kind="town_first_sale", subject=player.id,
            detail=f"{player.name}'s town sold its first goods at "
                   f"{self._port_name(book.get('sold_at', TOWN_NODE))}",
            data={"player": player.id, "company": player.name,
                  "kg": result.filled_kg})]

    def _town_ship(self, player):
        ship = self._docked(player)
        home = self._port(player.id)
        if ship.location != home:
            raise GameError(f"Your ship is not at {self._port_name(home)}, "
                            "your town's port.")
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

    def found_town(self, player, choice: int = 0, at=None) -> dict:
        """Land four people, in the morning, on the plot the company chose
        of the three it was offered. One town per company.

        ``at`` is the chosen plot's latitude and longitude, which a screen
        sends with its choice so that a list that has moved on with the
        sunrise cannot found a town on ground nobody chose.
        """
        if self._town_row(player.id) is not None:
            raise GameError("Your company already has a town.")
        plot = self._chosen_plot(player.id, choice, at)   # refuses one not offered
        with self._mutation():
            self._log([self._found_town(player, self.world.game_time(), plot)])
        return self.town_meta(player)

    def _found_town(self, player, now: str, plot: dict | None = None) -> Event:
        """Found a company's town on the plot it chose. Call inside a transaction."""
        ledger, tick = self.world.ledger, self.world.tick
        arrears = min(player.upkeep_owed, self.arrears_cap)
        grant = max(TOWN_GRANT, TOWN_START + arrears
                    - ledger.balance(player.account, CREDIT))
        if ledger.balance(self.dev_fund_account, CREDIT) >= grant:
            ledger.transfer(self.dev_fund_account, player.account, CREDIT,
                            grant, kind="grant", game_time=now,
                            ref=player.id, memo="town founding grant")
        seed = town_seed(player.id)
        if plot is None:
            plot = plot_for(player.id, 0, self._sun_jd(), tick)
        made = self._engine_call("create", seed, self._town_wallet(player, 0),
                                 plot, self._world_hour(plot))
        self.db.execute(
            "INSERT INTO town (player_id, founded_tick, seed, attempt, "
            "state, plot) VALUES (?, ?, ?, 0, ?, ?)",
            (player.id, tick, seed, made.state,
             json.dumps(plot, sort_keys=True)))
        if not player.house:
            self._message(player.id, "ark_development_office", "town_charter",
                          {"company": player.name, "grant": grant})
        return Event(
            tick=tick, kind="town_founded", subject=player.id,
            detail=f"{player.name} founded a town at {plot['name']}"
                   if plot.get("name") else f"{player.name} founded a town",
            data={"player": player.id, "company": player.name})

    def refound_town(self, player, choice: int = 0, at=None) -> dict:
        """Send a new crew to a town that has fallen silent.

        The new crew lands with stores: a company that has less than the
        floor a town is founded with is brought up to it from the Ark's
        fund, with its capped arrears covered, and what the lost town owed
        is written off. Without this a company whose town died with an
        empty account could never start again, which is how the first
        town on the live world ended, on its first day (D80).

        Nothing above the floor is given, so a company with money pays for
        its own second start, and what was built and lost stays lost.

        A crew lands in the morning or not at all (D93). If it is morning
        on the company's own ground the crew goes there. If it is not, the
        company may wait for its sunrise, or say where (``at``) among the
        plots on offer now and take new ground: nobody is made to sit out
        a night to play again.
        """
        row = self._town(player)
        if self.town_engine.summary(row["state"])["phase"] != "lost":
            raise GameError("Your town is still alive.")
        plot = json.loads(row["plot"] or "{}")
        if not plot:
            # A town from before plots chooses its ground now, once.
            plot = self._chosen_plot(player.id, choice, at)
        elif not self._morning(plot):
            if at is None:
                hours = self._to_sunrise(plot)
                raise GameError(
                    f"It is not morning on your ground. The Sun rises there "
                    f"in {hours} hours, about {self._real_minutes(hours)} "
                    "minutes. Wait for it, or choose new ground to land now.")
            plot = self._chosen_plot(player.id, choice, at)
        with self._mutation():
            self._refound_town(player, row, self.world.game_time(), plot)
        return self.town_meta(player)

    def _refound_town(self, player, row, now: str, plot: dict | None = None
                      ) -> None:
        """Land a new crew. Call inside a transaction."""
        attempt = row["attempt"] + 1
        seed = town_seed(player.id, attempt)
        ledger = self.world.ledger
        book = self._yard_book(row)     # the company's record stays; the
        for key in ("pop", "buildings", "tier", "peak", "trading"):
            book.pop(key, None)         # town's standing starts again
        # Anything the lost town still had on the book comes home first, so
        # the relief is measured against all the company really has.
        self._parts_settle(player, self._yard_account(player), book, now)
        arrears = min(player.upkeep_owed, self.arrears_cap)
        relief = max(0, TOWN_START + arrears
                     - ledger.balance(player.account, CREDIT))
        if relief and ledger.balance(self.dev_fund_account, CREDIT) >= relief:
            ledger.transfer(self.dev_fund_account, player.account, CREDIT,
                            relief, kind="grant", game_time=now,
                            ref=player.id, memo="town relief crew stores")
        else:
            relief = 0
        # The ground is the company's own unless it chose new ground to
        # land in daylight. A town from before plots is given its ground now.
        if plot is None:
            plot = json.loads(row["plot"] or "{}") or plot_for(
                player.id, 0, self._sun_jd(), self.world.tick)
        made = self._engine_call("create", seed, self._town_wallet(player, 0),
                                 plot, self._world_hour(plot))
        self.db.execute(
            "UPDATE town SET state = ?, seed = ?, attempt = ?, "
            "founded_tick = ?, owed = 0, carry = 0, lost_tick = NULL, "
            "caretaker = 0, yard = ?, plot = ? WHERE player_id = ?",
            (made.state, seed, attempt, self.world.tick,
             json.dumps(book, separators=(",", ":")),
             json.dumps(plot, sort_keys=True), player.id))
        if not player.house:
            self._message(player.id, "ark_development_office", "town_relief",
                          {"company": player.name, "relief": relief,
                           "hours": LANDER_HOURS})

    @staticmethod
    def _real_minutes(hours: float) -> int:
        """Game hours as whole real minutes, for telling a person how long."""
        return max(1, round(hours / PACE))

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
        with self._mutation():
            self._post_intent(player, row, before, result,
                              self.world.game_time())
        return self.town_meta(player)

    def _post_intent(self, player, row, before: float, result, now: str
                     ) -> None:
        """Keep what the rules allowed, and post what it cost."""
        owed, carry = self._town_settle(
            player, before, result.credits, row["owed"], row["carry"], now,
            building=True)
        self.db.execute(
            "UPDATE town SET state = ?, owed = ?, carry = ? "
            "WHERE player_id = ?", (result.state, owed, carry, player.id))

    def _apply_intent(self, player, row, intent: dict, now: str) -> bool:
        """One request from inside the hour. True if the rules allowed it.

        The same door a player's request comes through: the same rules
        judge it and the same settlement posts it.
        """
        before = self._town_wallet(player, row["owed"])
        try:
            result, _ = self.town_engine.apply(row["state"], intent, before)
        except TownError as exc:
            log.error("%s", exc)
            return False
        if result is None:
            return False
        self._post_intent(player, row, before, result, now)
        return True

    # -- the caretaker ---------------------------------------------------------

    def town_caretaker(self, player, on: bool) -> dict:
        """Hire a caretaker for the town, or let one go."""
        row = self._town(player)
        if not isinstance(on, bool):
            raise GameError("Say whether to hire or to dismiss.")
        if on and self.world.ledger.balance(player.account,
                                            CREDIT) < CARETAKER_FEE:
            raise GameError(f"A caretaker is paid {CARETAKER_FEE} cr an hour, "
                            "in advance.")
        with self._mutation():
            self.db.execute("UPDATE town SET caretaker = ? WHERE player_id = ?",
                            (1 if on else 0, player.id))
        return self.town_meta(player)

    def _caretake(self, player, row, now: str):
        """A hired caretaker's hour: paid first, then what is urgent is done.

        Returns the town's row as it stands afterwards. The caretaker sends
        the same requests a player can and the rules judge them the same
        way; what it builds is paid for by the town like anything else. It
        deals with what is urgent and nothing more: it will keep a town
        alive and it will not grow one (D73, D79).
        """
        ledger = self.world.ledger
        if ledger.balance(player.account, CREDIT) < CARETAKER_FEE:
            self.db.execute("UPDATE town SET caretaker = 0 WHERE player_id = ?",
                            (player.id,))
            self._message(player.id, "ark_development_office",
                          "town_caretaker_left", {"company": player.name,
                                                  "fee": CARETAKER_FEE})
            return self._town_row(player.id)
        ledger.burn(player.account, CARETAKER_FEE, now, ref=player.id,
                    memo="town caretaker's wage")
        self.db.execute("UPDATE town SET caretaker_paid = caretaker_paid + ? "
                        "WHERE player_id = ?", (CARETAKER_FEE, player.id))
        return self._steward_hour(player, row, now, keep=True)

    def _steward_hour(self, player, row, now: str, keep: bool):
        """Ask the steward what to do this hour and put each answer to the rules.

        Returns the town's row as it stands afterwards. With ``keep`` only
        what is urgent is asked for; without it the steward plays the town
        as a careful owner would. Either way every request goes through the
        door a player's does.
        """
        style = None if keep else TEMPERAMENTS.get(
            HOUSE_TEMPER.get(player.id, ""))
        try:
            asked = self.town_engine.steward(
                row["state"], self._town_wallet(player, row["owed"]),
                keep=keep, style=style)
        except TownError as exc:
            log.error("%s", exc)
            asked = []
        for intent in asked:
            self._apply_intent(player, self._town_row(player.id), intent, now)
        return self._town_row(player.id)

    # -- towns the world runs --------------------------------------------------

    def _house_business(self, now: str) -> list[Event]:
        """Once a game day: charter the next house company, recall a crew
        from a town that cannot recover, relieve a lost one.

        A world with nobody in it is not a market. The firms the Moon was
        seeded with did not last (F9), so the world founds towns of its own
        and plays them by the rules a person plays by.
        """
        tick = self.world.tick
        if tick % TICKS_PER_GAME_DAY:
            return []
        events: list[Event] = []
        have = {r["id"]: r["created_tick"] for r in self.db.execute(
            "SELECT id, created_tick FROM player WHERE house = 1")}
        gap = HOUSE_EVERY_DAYS * TICKS_PER_GAME_DAY
        if all(tick - made >= gap for made in have.values()):
            for pid, name, _ in HOUSE:
                if pid in have or self.db.execute(
                        "SELECT 1 FROM player WHERE name = ?",
                        (name,)).fetchone():
                    continue
                # A crew lands in the morning. A company whose ground is in
                # the afternoon or the dark waits, and the next is asked.
                if not self._morning(plots.plot_at(*HOUSE_PLACE[pid])):
                    continue
                try:
                    self._charter_office_open()
                except GameError:
                    break
                ships = len(self.world.ships)
                try:
                    with transaction(self.db):
                        self._charter_company(pid, name, f"house:{pid}", now,
                                              house=True)
                        founded = self._found_town(self.player(pid), now)
                    events += [self._joined(pid, name), founded]
                except Exception:
                    del self.world.ships[ships:]    # the books rolled back
                    log.exception("could not charter %s", name)
                break
        for row in self.db.execute(
                "SELECT t.player_id, p.name FROM town t JOIN player p "
                "ON p.id = t.player_id WHERE p.house = 1 "
                "AND t.lost_tick IS NULL AND t.owed > ?",
                (HOUSE_RECALL_DEBT,)).fetchall():
            self.db.execute("UPDATE town SET lost_tick = ? WHERE player_id = ?",
                            (tick, row["player_id"]))
            self._yard_close(self.player(row["player_id"]), now)
            events.append(Event(
                tick=tick, kind="town_lost", subject=row["player_id"],
                detail=f"{row['name']} has recalled its crew: the town "
                       "owed more than a new one costs",
                data={"player": row["player_id"], "company": row["name"],
                      "recalled": True}))
        wait = HOUSE_RETURN_DAYS * TICKS_PER_GAME_DAY
        for row in self.db.execute(
                "SELECT t.* FROM town t JOIN player p ON p.id = t.player_id "
                "WHERE p.house = 1 AND t.lost_tick IS NOT NULL").fetchall():
            if tick - row["lost_tick"] >= wait and self._morning(
                    json.loads(row["plot"] or "{}")):
                player = self.player(row["player_id"])
                try:
                    with transaction(self.db):
                        self._refound_town(player, row, now)
                    events.append(Event(
                        tick=tick, kind="town_founded", subject=player.id,
                        detail=f"{player.name} sent a new crew to its town",
                        data={"player": player.id, "company": player.name}))
                except Exception:
                    log.exception("could not relieve %s", player.name)
        return events

    def towns_view(self) -> list[dict]:
        """Every town on the Moon, most people first. Public."""
        out = []
        day = TICKS_PER_GAME_DAY
        for row in self.db.execute(
                "SELECT t.player_id, t.founded_tick, t.lost_tick, t.attempt, "
                "t.yard, t.plot, p.name, p.house FROM town t "
                "JOIN player p ON p.id = t.player_id").fetchall():
            book = json.loads(row["yard"] or "{}")
            if "pop" not in book:           # not yet through an hour
                seen = self.town_engine.summary(
                    self._town_row(row["player_id"])["state"])
                book.update(pop=seen["population"], tier=seen["tier"],
                            buildings=seen["buildings"])
            lost = row["lost_tick"] is not None
            out.append({
                "company": row["name"], "house": bool(row["house"]),
                "kind": TEMPER_NAMES.get(
                    HOUSE_TEMPER.get(row["player_id"], ""), ""),
                "plot": json.loads(row["plot"] or "{}"),
                "port": self._port_name(self._port(row["player_id"])),
                "lost": lost, "crews": row["attempt"] + 1,
                "age_days": (self.world.tick - row["founded_tick"]) // day,
                "population": 0 if lost else book["pop"],
                "tier": book["tier"], "buildings": book["buildings"],
                "sold_t": book.get("sold_kg", 0) // TONNE,
            })
        out.sort(key=lambda t: (t["lost"], -t["population"], -t["sold_t"],
                                t["company"]))
        return out

    # -- the hour ------------------------------------------------------------

    def _tick_towns(self, now: str) -> list[Event]:
        """Every town's hour, inside the world's. One failure stops one town."""
        events: list[Event] = []
        try:
            self._to_one_sun()
        except Exception:
            log.exception("the move to the one Sun failed at tick %d",
                          self.world.tick)
        try:
            self._to_blast_zone()
        except Exception:
            log.exception("giving notice of the blast zone failed at tick %d",
                          self.world.tick)
        try:
            events += self._house_business(now)
        except Exception:
            log.exception("house business failed at tick %d", self.world.tick)
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

    def _to_one_sun(self) -> None:
        """Once, when a world moves onto the one Sun (D93): fill every
        living town's batteries.

        Until now each town kept a day of its own, counted from its
        founding. From this hour its day is the Sun's, so some towns wake
        to find it is suddenly night, having had no warning to store for
        it. A full battery is the warning they did not get. It is energy,
        not credits, and it is given once.

        A company whose pad already stands is past what the pad grant is
        for, so that is marked as settled without paying it.
        """
        if self.db.execute("SELECT 1 FROM world_meta WHERE key = 'one_sun'"
                           ).fetchone():
            return
        for row in self.db.execute(
                "SELECT * FROM town WHERE lost_tick IS NULL").fetchall():
            plot = json.loads(row["plot"] or "{}")
            try:
                filled = self.town_engine.topup(row["state"],
                                                self._world_hour(plot))
            except TownError as exc:
                log.error("%s", exc)
                continue
            self.db.execute(
                "UPDATE town SET state = ?, pad_grant = CASE WHEN ? THEN 0 "
                "ELSE pad_grant END WHERE player_id = ?",
                (filled.state, 1 if filled.summary["pad"] else 0,
                 row["player_id"]))
        self.db.execute(
            "INSERT INTO world_meta (key, value) VALUES ('one_sun', ?)",
            (str(self.world.tick),))

    def _to_blast_zone(self) -> None:
        """Once, when a world gets the landing pad's blast zone (D96):
        give every town that already stands its notice.

        The rules now say a landing destroys what stands in the red ring
        round a pad and knocks offline what stands in the amber. Every
        town built before that has its pad among its buildings, because
        nothing said not to. A town's state names the hour the rule
        starts for it (`blast`). A new town has it from its first hour.
        A town without it is not under the rule at all, so the safe thing
        happens if this never runs.

        Each living town gets BLAST_NOTICE hours from now, and its owner
        a letter. The towns the world runs move their own pads: that is
        in the steward's rules. A pad that still stands among buildings
        when the notice ends is moved clear by the town rules themselves,
        once and free (`standOff`): rehearsed on towns built the old way,
        doing nothing lost ten to fourteen buildings at the first landing
        and killed two towns in three. Nothing is paid and nothing is
        taken here.
        """
        if self.db.execute("SELECT 1 FROM world_meta WHERE key = 'blast_zone'"
                           ).fetchone():
            return
        for row in self.db.execute(
                "SELECT * FROM town WHERE lost_tick IS NULL").fetchall():
            state = json.loads(row["state"])
            if "blast" in state:
                continue
            state["blast"] = state["t"] + BLAST_NOTICE
            self.db.execute("UPDATE town SET state = ? WHERE player_id = ?",
                            (json.dumps(state, separators=(",", ":")),
                             row["player_id"]))
            player = self.player(row["player_id"])
            if not player.house:
                self._message(player.id, "ark_development_office",
                              "town_blast_notice",
                              {"company": player.name,
                               "hours": BLAST_NOTICE,
                               "days": round(self._real_minutes(BLAST_NOTICE)
                                             / 1_440)})
        self.db.execute(
            "INSERT INTO world_meta (key, value) VALUES ('blast_zone', ?)",
            (str(self.world.tick),))

    def town_seen(self, player) -> None:
        """The owner is at their town. Written down every few minutes at
        most; the crew's watch is counted from it (WATCH_AFTER)."""
        row = self._town_row(player.id)
        if row is None:
            return
        tick = self.world.tick
        if row["seen_tick"] is None or tick - row["seen_tick"] >= SEEN_EVERY:
            with transaction(self.db):
                self.db.execute(
                    "UPDATE town SET seen_tick = ? WHERE player_id = ?",
                    (tick, player.id))

    def _on_watch(self, row) -> bool:
        """Is the crew keeping watch this hour? From when the owner has been
        gone WATCH_AFTER, for WATCH_FOR. A town whose owner has never been
        seen at it (one from before the watch, or one the world runs) has
        none: there is nobody for the crew to be standing in for."""
        if row["seen_tick"] is None:
            return False
        away = self.world.tick - row["seen_tick"]
        return WATCH_AFTER <= away < WATCH_AFTER + WATCH_FOR

    def _pad_grant(self, player, row, summary: dict, now: str) -> None:
        """Pay a company for its first working landing pad, once (PAD_GRANT).

        From the Ark's fund, which is finite: if it cannot pay this hour
        the grant waits. Not paid to the towns the world runs, whose money
        has to be earned (invariant 3).
        """
        if row["pad_grant"] is not None or not summary["pad"]:
            return
        if player.house:
            paid = 0
        else:
            ledger = self.world.ledger
            if ledger.balance(self.dev_fund_account, CREDIT) < PAD_GRANT:
                return
            ledger.transfer(self.dev_fund_account, player.account, CREDIT,
                            PAD_GRANT, kind="grant", game_time=now,
                            ref=player.id, memo="first landing pad grant")
            self._message(player.id, "ark_development_office",
                          "town_pad_grant",
                          {"company": player.name, "grant": PAD_GRANT})
            paid = PAD_GRANT
        self.db.execute("UPDATE town SET pad_grant = ? WHERE player_id = ?",
                        (paid, player.id))

    def _tick_town(self, row, now: str) -> list[Event]:
        player = self.player(row["player_id"])
        if player.house:
            row = self._steward_hour(player, row, now, keep=False)
        elif self._on_watch(row):
            # The owner is away and the crew is keeping watch: what is
            # urgent is done, by the rules, from the town's own money.
            row = self._steward_hour(player, row, now, keep=True)
        elif row["caretaker"]:
            row = self._caretake(player, row, now)
        ledger, account = self.world.ledger, self._yard_account(player)
        held = ledger.balance(account, YARD_ASSET)
        before = self._town_wallet(player, row["owed"])
        # A town big enough to trade is past its founding spares: from then
        # on its buildings wear, and what they wear out is goods (D82).
        wear = bool(json.loads(row["yard"] or "{}").get("trading"))
        result = self.town_engine.tick(
            row["state"], 1.0, before,
            {"cap": YARD_KG, "held": held, "wear": wear,
             "importAt": self._parts_price() / TONNE / KCR},
            self._world_hour(json.loads(row["plot"] or "{}")))
        owed, carry = self._town_settle(
            player, before, result.credits, row["owed"], row["carry"], now,
            building=False)
        lost = result.summary["phase"] == "lost"
        self.db.execute(
            "UPDATE town SET state = ?, owed = ?, carry = ?, lost_tick = ? "
            "WHERE player_id = ?",
            (result.state, owed, carry, self.world.tick if lost else None,
             player.id))
        self._pad_grant(player, row, result.summary, now)

        # What the foundries made this hour is cargo, at the port, on the
        # ledger. No credits are created here: it is worth what somebody
        # with money of their own will pay for it, and nothing until then.
        events: list[Event] = []
        book = self._yard_book(row)
        self._yard_roll(book)
        seen = result.summary
        rank = TIER_RANK.get(seen["tier"], 0)
        if "peak" in book and rank > book["peak"]:
            events.append(Event(
                tick=self.world.tick, kind="town_grew", subject=player.id,
                detail=f"{player.name} has grown into a "
                       f"{seen['tier'].lower()} of {seen['population']} people",
                data={"player": player.id, "company": player.name,
                      "tier": seen["tier"],
                      "population": seen["population"]}))
        book.update(pop=seen["population"], buildings=seen["buildings"],
                    tier=seen["tier"], peak=max(rank, book.get("peak", 0)))
        used = min(result.used, held + result.made)
        made = min(result.made, YARD_KG - held + used)
        if made > 0:
            ledger.extract(account, YARD_ASSET, made, now,
                           memo=f"{player.name} town foundries")
            book["made_kg"] += made
            book["made_today"] += made
        # What the buildings wore out leaves the world as mass, the way
        # propellant burned does. Parts Earth landed instead were paid for
        # in the hour's credits, above, and never touch the yard.
        if used > 0:
            ledger.consume(account, YARD_ASSET, used, now,
                           memo=f"{player.name} spare parts fitted")
            book["used_kg"] += used
        if result.landed:
            book["landed_kg"] = round(book["landed_kg"] + result.landed, 3)
        # Last hour's bid for parts comes off the book and its change comes
        # home. If the town still stands and its yard is still short, a
        # fresh one goes on, which another town's sale can fill (D83).
        self._parts_settle(player, account, book, now)
        if self._trade_open(result.summary, book) and not lost and book["buy"]:
            try:
                with transaction(self.db):
                    self._parts_order(player, account, book, result.summary,
                                      now)
            except MarketError:
                pass    # the book refused it this hour; try the next
        if self._trade_open(result.summary, book) and not lost and book["sell"]:
            spare = (ledger.balance(account, YARD_ASSET)
                     - self._keep_kg(book, result.summary))
            if spare > 0 and self._best_market(self._port(player.id),
                                               book["min_price"]):
                try:
                    with transaction(self.db):
                        sold = self._yard_sell(
                            player, account, book, spare,
                            book["min_price"], now)
                    events += self._first_sale(player, book, sold)
                except MarketError:
                    pass    # the book refused it this hour; try the next
        self._save_yard(player.id, book)
        if not lost:
            return events
        if not player.house:
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
        meta["pace"] = PACE
        plot = json.loads(row["plot"] or "{}") if row is not None else {}
        if row is None or (row["lost_tick"] is not None and not plot):
            # nothing founded yet, or a lost town from before plots: the
            # company is shown its three plots and chooses one
            meta["offers"] = self.plot_offers(player.id)
        elif row["lost_tick"] is not None and not self._morning(plot):
            # A lost town whose ground is not in its morning: a crew can
            # wait for the sunrise there, or land now on new ground (D93).
            hours = self._to_sunrise(plot)
            meta["relief"] = {"hours": hours,
                              "minutes": self._real_minutes(hours)}
            meta["offers"] = self.plot_offers(player.id)
        if row is None:
            return meta
        summary = self.town_engine.summary(row["state"])
        meta.update(
            founded_tick=row["founded_tick"], owed=row["owed"],
            faults=row["faults"], attempt=row["attempt"],
            wallet=self._town_wallet(player, row["owed"]),
            summary=summary,
            trade={"open": self._trade_open(summary, self._yard_book(row)),
                   "pad": bool(summary["pad"]),
                   "population": summary["population"]},
            yard=self._yard_view(player, row, summary),
            caretaker={"on": bool(row["caretaker"]), "fee": CARETAKER_FEE,
                       "paid": row["caretaker_paid"]},
            watch={"after_minutes": self._real_minutes(WATCH_AFTER),
                   "for_hours": round(WATCH_FOR / PACE / 60)},
            pad_grant=row["pad_grant"],
            company=player.name, league=self.towns_view(),
            plot=json.loads(row["plot"] or "{}"))
        return meta

    def _yard_view(self, player, row, summary: dict) -> dict:
        """The yard as the screen shows it. Reads only."""
        ledger = self.world.ledger
        spec = ledger.asset(YARD_ASSET)
        home = self._port(player.id)
        market = self.world.books[home]
        best = self._best_market(home, 0)   # where a sale would go now
        account = f"town:{player.id}"
        book = self._yard_book(row)
        day = self.world.tick // TICKS_PER_GAME_DAY
        today = book["day"] == day
        ship = self.ship_of(player)
        docked = (ship.state.value == "docked" and ship.location == home)
        return {
            "asset": YARD_ASSET, "name": spec.name, "node": home,
            "port": self._port_name(home),
            "held_kg": ledger.balance(account, YARD_ASSET),
            "cap_kg": YARD_KG, "lot_kg": spec.lot_mass_kg,
            "anchor": spec.base_value,
            "make_kg_per_hour": summary.get("make", 0),
            "foundries": summary.get("foundries", 0),
            "full": bool(summary.get("yardFull")),
            # the best price on the Moon after freight, and where it is
            "bid": best[1] - best[2] if best else None,
            "bid_port": self._port_name(best[0]) if best else None,
            "freight": best[2] if best else 0,
            "freight_paid": book.get("freight", 0),
            "last": market.last_price(YARD_ASSET),
            "sell": book["sell"], "min_price": book["min_price"],
            "parts": {
                "wear": bool(book.get("trading")),
                "kg_per_hour": summary.get("parts", 0),
                "keep_kg": self._keep_kg(book, summary),
                "keep_t": book["keep_t"],
                "auto_kg": self._keep_kg({"keep_t": None}, summary),
                "used_kg": book["used_kg"],
                "landed_kg": book["landed_kg"],
                "import": self._parts_price(),
                "buy": book["buy"],
                "max_price": book["max_price"] or self._parts_price(),
                "bought_kg": book["bought_kg"], "spent": book["spent"],
                "on_order_kg": (book.get("order") or {}).get("kg", 0),
            },
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
