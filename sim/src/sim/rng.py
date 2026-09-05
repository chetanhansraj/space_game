"""Seeded randomness that survives the code changing.

CLAUDE.md: "Simulation runs must be reproducible from a seed. A bug report
should be replayable."

The naive approach -- one `random.Random(seed)` threaded through everything --
is reproducible only until someone adds a feature. Insert one extra draw
anywhere and every subsequent number shifts, so a replay of yesterday's bug
diverges from yesterday's world and the report is worthless.

So randomness is drawn from *named streams* instead. A draw is a pure function
of (world seed, stream name, tick, salt), computed by hashing rather than by
advancing shared state. Adding a new stream leaves every existing stream
bit-identical, and any draw can be recomputed later without replaying the
ticks that came before it.
"""

from __future__ import annotations

import hashlib
import struct


class Streams:
    """Deterministic per-stream randomness for one world."""

    def __init__(self, seed: int) -> None:
        self.seed = int(seed)

    def _digest(self, stream: str, tick: int, salt: str) -> bytes:
        material = f"{self.seed}|{stream}|{tick}|{salt}".encode()
        return hashlib.blake2b(material, digest_size=16).digest()

    def unit(self, stream: str, tick: int, salt: str = "") -> float:
        """A float in [0, 1)."""
        (value,) = struct.unpack("<Q", self._digest(stream, tick, salt)[:8])
        return value / 2**64

    def integer(self, stream: str, tick: int, low: int, high: int,
                salt: str = "") -> int:
        """An integer in [low, high]. Inclusive, like a die roll."""
        if high < low:
            raise ValueError(f"empty range [{low}, {high}]")
        span = high - low + 1
        (value,) = struct.unpack("<Q", self._digest(stream, tick, salt)[:8])
        return low + value % span

    def spread(self, stream: str, tick: int, magnitude: float,
               salt: str = "") -> float:
        """A multiplier in [1 - magnitude, 1 + magnitude]."""
        return 1.0 + (self.unit(stream, tick, salt) * 2.0 - 1.0) * magnitude

    def chance(self, stream: str, tick: int, probability: float,
               salt: str = "") -> bool:
        return self.unit(stream, tick, salt) < probability

    def pick(self, stream: str, tick: int, options, salt: str = ""):
        options = list(options)
        if not options:
            raise ValueError("cannot pick from an empty sequence")
        return options[self.integer(stream, tick, 0, len(options) - 1, salt)]
