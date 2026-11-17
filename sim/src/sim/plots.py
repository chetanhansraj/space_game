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

import hashlib
import math

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
    return "Near-side highlands" if abs(lon) < 90 else "Far-side highlands"


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
    return {
        "sun": 0.35 + 0.6 * pole,           # polar rims are lit most of the year
        "ice": 0.05 + 0.9 * pole * pole,    # cold traps in polar craters
        "metal": 0.15 + 0.8 * mare,         # basalt: iron and titanium
        "glass": 0.15 + 0.8 * (1.0 - mare),  # highland feldspar: aluminium
        # the solar wind's helium-3 is held best by old titanium-rich soil,
        # and falls most where the Sun stands high
        "he3": 0.10 + 0.8 * mare * math.cos(math.radians(lat)),
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


def _budget(raw: dict[str, float]) -> dict[str, float]:
    """Move the soil and sunlight readings together until all six total BUDGET.

    Moving, not scaling, keeps what makes a place itself: the difference
    between its readings. A reading that reaches the floor or the ceiling
    stays there and the others take up the rest.
    """
    values = dict(raw)
    for _ in range(40):
        gap = BUDGET - sum(values.values())
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


def plot_at(lat: float, lon: float) -> dict:
    """The plot at a place: its readings, where it is and what it is called."""
    lat, lon = round(float(lat), 1), round(float(lon), 1)
    base = pattern(lat, lon)
    raw = {key: min(HIGH, max(LOW, base[key] + NOISE * _draw(lat, lon, key)))
           for key in KEYS}
    return {**_budget(raw), "lat": lat, "lon": lon, "name": region(lat, lon)}


def kind_of(lat: float, lon: float) -> str:
    """Which of the four kinds of ground a place is."""
    if abs(lat) >= 75:
        return "polar"
    if _mare(lat, lon)[0] >= 0.5:
        return "mare"
    return "near" if abs(lon) < 90 else "far"


def place_for(token: str) -> tuple[float, float]:
    """A place on the Moon drawn from a name.

    The name picks the kind of ground, then points are drawn evenly over
    the sphere, each from the name and its turn, until one is that kind.
    The same name always gives the same place.
    """
    first = hashlib.sha256(f"kind:{token}".encode()).digest()
    want = KINDS[first[0] % len(KINDS)]
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
