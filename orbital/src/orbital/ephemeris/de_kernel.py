"""JPL DE binary SPK kernel backend. DE440 in production.

This is the committed choice from the bible. It needs the kernel file, which
``scripts/fetch_kernels.py`` downloads at build time from NAIF. The file is
large and reproducible, so it is not committed -- ``orbital/kernels/`` is
gitignored.

Kernel choice and its consequence for world lifetime:

  DE440   1550-2650. At the 60x clock that is about ten real years of sky
          coverage from a 2026 launch.
  DE441   -13200 to +17191. Effectively unlimited, but ~3 GB.

Start on DE440. The health endpoint reports the sky date at which coverage
runs out, so this can never fail silently -- it fails as a monitored
expiry date years in advance.
"""

from __future__ import annotations

import numpy as np

from ..frames import km_per_day_to_m_per_s, km_to_m
from . import EARTH_MOON, JUPITER, MARS, MERCURY, SATURN, SUN, VENUS, State

# NAIF integer IDs, reached from the solar system barycentre (0).
_NAIF = {
    MERCURY: 1,
    VENUS: 2,
    EARTH_MOON: 3,
    MARS: 4,
    JUPITER: 5,
    SATURN: 6,
    SUN: 10,
}


class KernelBackend:
    name = "de-kernel"

    def __init__(self, path: str) -> None:
        from jplephem.spk import SPK

        self.path = path
        self._spk = SPK.open(path)
        self.name = f"de-kernel:{path.rsplit('/', 1)[-1]}"

    def _ssb(self, body: str, jd_tt: float) -> tuple[np.ndarray, np.ndarray]:
        segment = self._spk[0, _NAIF[body]]
        pos, vel = segment.compute_and_differentiate(jd_tt)
        return np.asarray(pos, dtype=float), np.asarray(vel, dtype=float)

    def state(self, body: str, jd_tt: float) -> State:
        if body not in _NAIF:
            raise ValueError(f"kernel backend has no body {body!r}")
        body_r, body_v = self._ssb(body, jd_tt)
        sun_r, sun_v = self._ssb(SUN, jd_tt)
        return State(
            r=km_to_m(body_r - sun_r),
            v=km_per_day_to_m_per_s(body_v - sun_v),
        )

    def coverage(self) -> tuple[float, float]:
        starts = [seg.start_jd for seg in self._spk.segments]
        ends = [seg.end_jd for seg in self._spk.segments]
        return (max(starts), min(ends))
