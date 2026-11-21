"""The ground a town stands on: where it is on the Moon and what that gives.

Every company's town has a plot. A plot is a latitude and longitude and
six readings from 0 to 1 (see ``Plot`` in city/src/sim/sim.ts): sunlight,
water ice, iron and titanium, aluminium and silicon, helium-3, and what
there is to see. Chetan, 18 November 2026: every user is given a plot
somewhere on the Moon, plots differ by where they are, even neighbours
differ, and everyone has equal possibilities; what a person does with
the ground is the game.

Three rules, all here:

1. **Where it is sets the pattern.** Ice near the poles, iron, titanium
   and helium-3 in the dark plains, aluminium in the bright highlands,
   Earth in the sky only on the near side.
2. **Neighbours differ.** Each reading is moved a little by a number
   drawn from the plot's own position, so two plots side by side are
   alike but not the same.
3. **Every plot adds up to the same.** The six readings always total
   ``BUDGET``. No ground is better; each is better at something.

Nothing here is random at run time: the same place always gives the same
ground, so a world replayed from its seed is the same world.

*The map is a sketch, and says so.* The basins are placed at their real
centres with rough sizes, and the rest follows from latitude and
longitude by the simple rules below. Orbiters have measured the real
thing (titanium, iron, hydrogen, sunlight). Replacing this sketch with
those maps changes only ``pattern`` and nothing that calls it. D84.
"""
from __future__ import annotations

import functools
import hashlib
import math

from . import sun

KEYS = ("sun", "ice", "metal", "glass", "he3", "view")
#: What every plot's six readings add up to: a half each, which is the
#: ground the town's rules were first tuned on.
BUDGET = 3.0
#: No reading is ever nothing or everything.
LOW, HIGH = 0.05, 0.95
#: How far a plot's own draw can move a reading from its region's.
#: *Invented*, D84.
NOISE = 0.15
#: The ground the game was tuned on: a half of everything.
REFERENCE = {key: 0.5 for key in KEYS}

#: The dark plains: name, centre latitude and longitude in degrees (north
#: and east positive), and radius in degrees of arc. Centres and
#: diameters are the usual catalogue values, with a degree of arc on the
#: Moon taken as 30.3 km; Procellarum is far from round and is drawn
#: smaller than its catalogue width. Each is treated as a disc, which
#: none of them is.
MARIA = (
    ("Oceanus Procellarum", 18.4, -57.4, 30.0),
    ("Mare Imbrium", 32.8, -15.6, 19.0),
    ("Mare Serenitatis", 28.0, 17.5, 11.0),
    ("Mare Tranquillitatis", 8.5, 31.4, 14.5),
    ("Mare Fecunditatis", -7.8, 51.3, 14.0),
    ("Mare Nubium", -21.3, -16.6, 12.0),
    ("Mare Crisium", 17.0, 59.1, 9.0),
    ("Mare Humorum", -24.4, -38.6, 7.0),
)
#: The South Pole-Aitken basin on the far side: the Moon's largest and
#: oldest impact scar. It stripped the upper crust and laid bare deeper
#: rock, olivine and pyroxene rich in magnesium and iron, so its floor
#: is metal-bearing ground with no plain on it. Centre and radius in
#: degrees; catalogue centre, radius drawn well inside its 2,500 km.
AITKEN = ("South Pole-Aitken basin", -53.0, -169.0, 35.0)
#: How much of a plain's iron the basin floor is worth. *Invented*, D85.
AITKEN_METAL = 0.6
#: The far side never passes through the shelter of Earth's magnetic
#: tail, so the solar wind plants helium-3 there steadily. It has little
#: of the titanium-rich soil that holds it best, so it is worth this
#: share of a plain's. *Invented*, D85.
FAR_HE3 = 0.55

#: A plot is drawn from one of four kinds of ground in turn, so that the
#: Moon's people are spread over all of it. Left to chance four in five
#: would land in the highlands, which cover most of the Moon.
KINDS = ("mare", "near", "polar", "far")


def _arc(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Degrees of arc between two places on the Moon."""
    a, b = math.radians(lat1), math.radians(lat2)
    cosine = (math.sin(a) * math.sin(b)
              + math.cos(a) * math.cos(b) * math.cos(math.radians(lon1 - lon2)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _mare(lat: float, lon: float) -> tuple[float, str]:
    """How much of a dark plain this is, 0 to 1, and which."""
    best, name = 0.0, ""
    for mare, mlat, mlon, radius in MARIA:
        # nearly all plain inside the rim, falling away quickly outside it
        here = 1.0 / (1.0 + (_arc(lat, lon, mlat, mlon) / radius) ** 6)
        if here > best:
            best, name = here, mare
    return best, name


def region(lat: float, lon: float) -> str:
    """What this part of the Moon is called."""
    if abs(lat) >= 75:
        return "South polar rim" if lat < 0 else "North polar rim"
    mare, name = _mare(lat, lon)
    if mare >= 0.5:
        return name
    if _aitken(lat, lon) >= 0.5:
        return AITKEN[0]
    return "Near-side highlands" if abs(lon) < 90 else "Far-side highlands"


def _aitken(lat: float, lon: float) -> float:
    """How much of the South Pole-Aitken basin's floor this is, 0 to 1."""
    return 1.0 / (1.0 + (_arc(lat, lon, AITKEN[1], AITKEN[2]) / AITKEN[3]) ** 6)


def pattern(lat: float, lon: float) -> dict[str, float]:
    """What a place gives before its own draw and before the budget."""
    mare, _ = _mare(lat, lon)
    pole = max(0.0, (abs(lat) - 60.0) / 30.0)
    # Earth hangs over the middle of the near side and is never seen from
    # the far side. The far side has what the near side cannot: no radio
    # from Earth, which is what an observatory comes for. Either brings
    # people; the edge between them has neither.
    facing = math.cos(math.radians(_arc(lat, lon, 0.0, 0.0)))
    draw = abs(facing)
    far = max(0.0, -facing)
    # iron: the plains' basalt, or the deep rock the great basin laid bare
    iron = max(mare, AITKEN_METAL * _aitken(lat, lon))
    high = math.cos(math.radians(lat))     # where the Sun stands high
    return {
        "sun": 0.35 + 0.6 * pole,           # polar rims are lit most of the year
        "ice": 0.05 + 0.9 * pole * pole,    # cold traps in polar craters
        "metal": 0.15 + 0.8 * iron,
        "glass": 0.15 + 0.8 * (1.0 - iron),  # highland feldspar: aluminium
        # the solar wind's helium-3 is held best by the plains' old
        # titanium-rich soil, falls most where the Sun stands high, and
        # reaches the far side without Earth's magnetic tail in the way
        "he3": 0.10 + 0.8 * high * max(mare, FAR_HE3 * far),
        "view": 0.10 + 0.8 * draw,
    }


def _draw(lat: float, lon: float, key: str) -> float:
    """A number from -1 to 1 that belongs to this place and reading."""
    digest = hashlib.sha256(f"plot:{lat:.1f}:{lon:.1f}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 63 - 1.0


#: The readings the budget may move. Ice and what there is to see are
#: facts of where a place is: there is no ice at the equator and no Earth
#: in the far side's sky, and no budget will say otherwise. Soil and
#: sunlight do differ from one crater to the next, so what a place lacks
#: in ice or outlook it is given in ground.
FLEX = ("sun", "metal", "glass", "he3")


def _budget(raw: dict[str, float], spent: float = 0.0) -> dict[str, float]:
    """Move the soil and sunlight readings together until all six, and what
    the plot has already been given in daylight (``spent``), total BUDGET.

    Moving, not scaling, keeps what makes a place itself: the difference
    between its readings. A reading that reaches the floor or the ceiling
    stays there and the others take up the rest.
    """
    values = dict(raw)
    for _ in range(40):
        gap = BUDGET - spent - sum(values.values())
        if abs(gap) < 1e-9:
            break
        free = [k for k in FLEX
                if (values[k] < HIGH if gap > 0 else values[k] > LOW)]
        if not free:
            break
        step = gap / len(free)
        for key in free:
            values[key] = min(HIGH, max(LOW, values[key] + step))
    return {key: round(values[key], 3) for key in KEYS}


#: Hours of dark in a lunar day of 708 hours: half of it across nearly
#: all the Moon, whatever the latitude, because the Moon hardly tilts and
#: has no seasons to speak of.
NIGHT = 354
#: On a polar rim the Sun circles the horizon and high ground is lit
#: most of the year. From POLAR_FROM degrees the dark shortens, down to
#: POLAR_NIGHT hours at the pole itself: lit about nine tenths of the
#: time, which is what the best real rims get. *Invented* as a rule, D85.
POLAR_FROM, POLAR_NIGHT = 75.0, 180


#: What a night shorter than the usual is worth, out of the same budget
#: every plot has: a pole with almost no night gives up this many points
#: of soil and sunlight for it. A short night is the most valuable thing
#: ground can have, because the dark is what a town is built against.
#: Measured before this was counted: polar towns ended nearly three
#: times as rich as any other. *Invented*, tuned by measuring, D85.
NIGHT_WORTH = 1.5


def night_worth(dark: int) -> float:
    """Budget points a plot has already been given in daylight."""
    return NIGHT_WORTH * (NIGHT - dark) / NIGHT


def dark_hours(lat: float) -> int:
    """How long the night is at this latitude."""
    if abs(lat) <= POLAR_FROM:
        return NIGHT
    share = (abs(lat) - POLAR_FROM) / (90.0 - POLAR_FROM)
    return round(NIGHT - share * (NIGHT - POLAR_NIGHT))


def plot_at(lat: float, lon: float) -> dict:
    """The plot at a place: its readings, where it is and what it is called."""
    lat, lon = round(float(lat), 1), round(float(lon), 1)
    base = pattern(lat, lon)
    raw = {key: min(HIGH, max(LOW, base[key] + NOISE * _draw(lat, lon, key)))
           for key in KEYS}
    dark = dark_hours(lat)
    return {**_budget(raw, night_worth(dark)), "lat": lat, "lon": lon,
            "name": region(lat, lon), "dark": dark}


def kind_of(lat: float, lon: float) -> str:
    """Which of the four kinds of ground a place is."""
    if abs(lat) >= 75:
        return "polar"
    if _mare(lat, lon)[0] >= 0.5:
        return "mare"
    return "near" if abs(lon) < 90 else "far"


#: How many plots a new company is shown, to choose one. Chetan, 18
#: November 2026: "given 3 options player chooses 1".
OFFERS = 3


#: A new crew is only ever landed in a place's morning: at most this many
#: hours after its sunrise, so that it has most of a day to get ready for
#: its first night. The first night is what a new town is built against,
#: and under the one Sun (D93) a place chosen blind could be an hour from
#: dark. *Invented*, D93: a quarter of the usual day.
MORNING = 90
#: Hours one set of three plots stays on offer before the sunrise has moved
#: on and three new ones are drawn. Long enough to read three cards and
#: choose; the offered ground is early enough in its morning that it is
#: still morning when the hold ends. *Invented*, D93.
OFFER_HOLD = 60


def in_morning(plot: dict, jd: float) -> bool:
    """Is it still morning at this plot?"""
    return sun.phase(plot["lon"], plot["dark"], jd) <= MORNING


def offers_for(token: str, jd: float | None = None, tick: int = 0
               ) -> list[dict]:
    """The plots a company may choose between.

    Without a sky (``jd`` is None) they are drawn from the company's name
    alone: three of the four kinds of ground, starting from one the name
    picks, the same three however often it asks.

    With one, they are drawn where it is morning (D93): the sunrise line
    sweeps the Moon once a lunar day and the offered ground follows it.
    A set holds for OFFER_HOLD hours, then three new plots are drawn from
    the name and the hour. As many different kinds of ground as have their
    morning now are offered; the poles always do, the plains only while
    the sunrise is over the near side.
    """
    if jd is None:
        first = hashlib.sha256(f"kind:{token}".encode()).digest()[0]
        return [plot_at(*place_for(f"{token}:{turn}",
                                   KINDS[(first + turn) % len(KINDS)]))
                for turn in range(OFFERS)]
    watch, into = divmod(int(tick), OFFER_HOLD)
    return [dict(p) for p in _morning_offers(token, watch,
                                             round(jd - into / 24.0, 6))]


@functools.lru_cache(maxsize=1024)
def _morning_offers(token: str, watch: int, jd: float) -> tuple[dict, ...]:
    first = hashlib.sha256(f"kind:{token}:{watch}".encode()).digest()[0]
    order = [KINDS[(first + turn) % len(KINDS)] for turn in range(len(KINDS))]
    out: list[dict] = []
    for again in range(6):              # one of each kind, then more of those that have a morning
        # The poles always have a morning somewhere. Left to the turn they
        # would fill every spare place, so past the first pass they go last.
        for kind in (order if again == 0 else
                     [k for k in order if k != "polar"] + ["polar"]):
            place = _morning_place(f"{token}:{watch}:{kind}:{again}", kind, jd)
            if place is None:
                continue
            plot = plot_at(*place)
            if all((plot["lat"], plot["lon"]) != (o["lat"], o["lon"]) for o in out):
                out.append(plot)
            if len(out) == OFFERS:
                return tuple(out)
    return tuple(out)


def _morning_place(token: str, kind: str, jd: float
                   ) -> tuple[float, float] | None:
    """A place of this kind of ground that is early in its morning at ``jd``,
    drawn from a name, or None if no ground of that kind is."""
    early = MORNING - OFFER_HOLD        # hours past sunrise, at most, when the hold begins
    under = sun.subsolar_lon(jd)
    for turn in range(3000):
        digest = hashlib.sha256(f"morning:{token}:{turn}".encode()).digest()
        u = int.from_bytes(digest[:8], "big") / 2 ** 64
        v = int.from_bytes(digest[8:16], "big") / 2 ** 64
        lat = round(math.degrees(math.asin(2.0 * u - 1.0)), 1)
        dark = dark_hours(lat)
        rise = -(sun.LUNAR_DAY - dark) / 2 / sun.LUNAR_DAY * 360.0   # the Sun's angle from noon at this place's sunrise
        lon = under + rise + v * early / sun.LUNAR_DAY * 360.0
        lon = round((lon + 540.0) % 360.0 - 180.0, 1)
        if kind_of(lat, lon) == kind and sun.phase(lon, dark, jd) <= early:
            return lat, lon
    return None


def place_for(token: str, kind: str | None = None) -> tuple[float, float]:
    """A place on the Moon drawn from a name.

    The name picks the kind of ground unless one is asked for, then
    points are drawn evenly over the sphere, each from the name and its
    turn, until one is that kind. The same name always gives the same
    place.
    """
    first = hashlib.sha256(f"kind:{token}".encode()).digest()
    want = kind or KINDS[first[0] % len(KINDS)]
    lat = lon = 0.0
    for turn in range(2000):
        digest = hashlib.sha256(f"place:{token}:{turn}".encode()).digest()
        u = int.from_bytes(digest[:8], "big") / 2 ** 64
        v = int.from_bytes(digest[8:16], "big") / 2 ** 64
        lat = round(math.degrees(math.asin(2.0 * u - 1.0)), 1)
        lon = round(360.0 * v - 180.0, 1)
        if kind_of(lat, lon) == want:
            break
    return lat, lon
