"""The one clock.

Invariant 5: one simulation clock, 60x real time, shared by everyone. The 60x
factor appears in this module and nowhere else in the repository. If you find
yourself writing `* 60` anywhere outside this file, stop.

Three distinct times, deliberately separated because conflating them is the
bug that would be hardest to find later:

  real time   Wall clock. What the server's OS thinks.
  sky time    What instant the ephemerides are evaluated at. Advances at 60x
              real time from world launch. This is what determines where the
              planets actually are.
  game date   The fictional calendar shown to players. Sky time plus a fixed
              cosmetic offset. Never used in a computation.

Why sky time starts at the real launch instant rather than at the fictional
year 2190: ephemeris kernels have finite coverage. Starting the sky at the
real present and running it forward at 60x means DE440 (valid to 2650) gives
roughly ten real years of runway, and DE441 effectively unlimited. Starting
the sky in 2190 would burn 164 years of coverage before the first player
logs in, and would force asteroid elements to be propagated across a span
where two-body propagation is no longer accurate to arcminutes.

The player never sees sky time, so the fiction costs nothing.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from .constants import DAY, JD_J2000

#: Game seconds per real second. The only place this number exists.
TIME_RATE = 60

#: Cosmetic offset applied to sky time to produce the displayed game calendar.
#: 164 years places a sky time of 2026 in the fictional year 2190.
DISPLAY_OFFSET_YEARS = 164

_UTC = _dt.timezone.utc


def _to_jd(when: _dt.datetime) -> float:
    """Convert an aware UTC datetime to a Julian Date.

    The game clock is treated as TT (Terrestrial Time) directly rather than
    UTC. This dodges the leap-second table entirely, which matters because
    the world runs into a fictional future where no leap second schedule
    exists. TDB - TT stays under 2 milliseconds, which is far below the
    arcminute accuracy target, so the distinction is not worth carrying.
    """
    if when.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    delta = when.astimezone(_UTC) - _dt.datetime(2000, 1, 1, 12, tzinfo=_UTC)
    return JD_J2000 + delta.total_seconds() / DAY


def _from_jd(jd: float) -> _dt.datetime:
    seconds = (jd - JD_J2000) * DAY
    return _dt.datetime(2000, 1, 1, 12, tzinfo=_UTC) + _dt.timedelta(seconds=seconds)


@dataclass(frozen=True)
class Clock:
    """Maps real time to sky time. Immutable; construct once per world.

    ``launch_real`` and ``launch_sky`` are equal for a world created normally.
    They are kept separate so a test or a replay can pin the sky to a fixed
    instant while real time moves.
    """

    launch_real: _dt.datetime
    launch_sky: _dt.datetime

    @classmethod
    def starting_now(cls) -> "Clock":
        now = _dt.datetime.now(tz=_UTC)
        return cls(launch_real=now, launch_sky=now)

    @classmethod
    def pinned(cls, sky: _dt.datetime) -> "Clock":
        """A clock whose sky time is fixed. For deterministic tests."""
        return cls(launch_real=sky, launch_sky=sky)

    def sky_time(self, real: _dt.datetime) -> _dt.datetime:
        """The instant to evaluate ephemerides at, for a given real instant."""
        elapsed = (real.astimezone(_UTC) - self.launch_real).total_seconds()
        return self.launch_sky + _dt.timedelta(seconds=elapsed * TIME_RATE)

    def sky_jd(self, real: _dt.datetime) -> float:
        return _to_jd(self.sky_time(real))

    def real_time(self, sky: _dt.datetime) -> _dt.datetime:
        """Inverse of :meth:`sky_time`."""
        elapsed = (sky.astimezone(_UTC) - self.launch_sky).total_seconds()
        return self.launch_real + _dt.timedelta(seconds=elapsed / TIME_RATE)

    def display_date(self, sky: _dt.datetime) -> _dt.datetime:
        """The fictional calendar date shown to players. Cosmetic only."""
        return sky.replace(year=sky.year + DISPLAY_OFFSET_YEARS)


def game_seconds(real_seconds: float) -> float:
    """Real duration -> game duration."""
    return real_seconds * TIME_RATE


def real_seconds(game_seconds_: float) -> float:
    """Game duration -> real duration."""
    return game_seconds_ / TIME_RATE


to_jd = _to_jd
from_jd = _from_jd
