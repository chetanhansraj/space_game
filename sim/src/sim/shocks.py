"""Scheduled and random disruption.

The bible: "Left alone, agent economies calcify or concentrate. Scheduled and
random disruption is a launch feature, not a later addition."

Frequencies and magnitudes were left open in docs/seed-data.md and are decided
in docs/DECISIONS.md D39. Two shocks ship in v1, both of which the bible names
explicitly. Convoy loss, claim expiry, policy changes and cartel formation all
need systems that do not exist yet.

Every roll goes through the named-stream RNG, so a shock is a pure function of
(world seed, tick). A bug report that says "the flare at tick 4,120 broke it"
is replayable exactly, without simulating the 4,119 ticks before it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rng import Streams

#: Roughly one solar flare per 30 game days, which at the 60x clock is about
#: two per real day. Frequent enough to be part of planning, rare enough to
#: still be news.
FLARE_PROBABILITY_PER_TICK = 1 / (30 * 24)
FLARE_MIN_HOURS = 6
FLARE_MAX_HOURS = 18

#: Roughly one rig failure per firm per 60 game days.
FAILURE_PROBABILITY_PER_TICK = 1 / (60 * 24)
FAILURE_MIN_HOURS = 12
FAILURE_MAX_HOURS = 48
REPAIR_COST = 25_000


@dataclass
class Event:
    """Something that happened. `voice/` turns these into prose.

    ``detail`` is a plain English line for logs and tests. ``data`` carries
    the same facts as structured values, which is what `voice/` writes from
    and what the game client reads -- so no one ever has to parse a number
    back out of a sentence.
    """

    tick: int
    kind: str
    subject: str
    detail: str
    until_tick: int | None = None
    data: dict = field(default_factory=dict)


class Weather:
    """Rolls disruption and remembers what is currently broken."""

    def __init__(self, streams: Streams) -> None:
        self.streams = streams
        self.flare_until: int = -1
        self.rig_down_until: dict[str, int] = {}

    def flaring(self, tick: int) -> bool:
        """Solar flares halt transit and surface work. The bible's first shock."""
        return tick < self.flare_until

    def rig_down(self, firm_id: str, tick: int) -> bool:
        return tick < self.rig_down_until.get(firm_id, -1)

    def roll(self, tick: int, firm_ids: list[str]) -> list[Event]:
        events: list[Event] = []

        if not self.flaring(tick) and self.streams.chance(
            "flare", tick, FLARE_PROBABILITY_PER_TICK
        ):
            hours = self.streams.integer("flare_len", tick,
                                         FLARE_MIN_HOURS, FLARE_MAX_HOURS)
            self.flare_until = tick + hours
            events.append(Event(
                tick=tick, kind="solar_flare", subject="all_nodes",
                detail=f"surface work halted for {hours} game hours",
                until_tick=self.flare_until,
                data={"hours": hours},
            ))

        for firm_id in firm_ids:
            if self.rig_down(firm_id, tick):
                continue
            if not self.streams.chance("failure", tick,
                                       FAILURE_PROBABILITY_PER_TICK,
                                       salt=firm_id):
                continue
            hours = self.streams.integer("failure_len", tick, FAILURE_MIN_HOURS,
                                         FAILURE_MAX_HOURS, salt=firm_id)
            self.rig_down_until[firm_id] = tick + hours
            events.append(Event(
                tick=tick, kind="equipment_failure", subject=firm_id,
                detail=f"rig down for {hours} game hours, {REPAIR_COST:,} cr to repair",
                until_tick=tick + hours,
                data={"hours": hours, "repair_cost": REPAIR_COST},
            ))

        return events
