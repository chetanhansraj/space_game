"""Ephemeris backends.

All backends answer one question: where is a body, and how fast is it going,
at a given instant. All of them answer in the same frame and units --
heliocentric ICRF equatorial, metres and metres per second -- so they are
interchangeable and can be cross-validated against each other.

Three exist:

``de_kernel``   JPL DE binary SPK kernel (DE440 in production). The committed
                choice. Requires the kernel file, fetched at build time.
``de_legacy``   The older ``de421`` PyPI package, which ships its Chebyshev
                coefficients as importable data. No download required, so it
                works in sealed build environments and CI.
``analytic``    ERFA's VSOP87-derived series. No data files at all. Accurate
                to tens of arcseconds over the span we care about, which is
                inside the arcminute target. Serves as the always-available
                fallback and, more usefully, as a genuinely independent
                implementation to test the kernel backends against.

Having more than one is not indecision. Two independent sources agreeing to
arcseconds is the strongest evidence available that the frame handling and
unit conversions are right, and that check runs without network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

# Canonical body names. Anchors refer to bodies by these strings.
EARTH_MOON = "earth_moon_barycentre"
MARS = "mars_barycentre"
SUN = "sun"
JUPITER = "jupiter_barycentre"
VENUS = "venus_barycentre"
MERCURY = "mercury_barycentre"
SATURN = "saturn_barycentre"


@dataclass(frozen=True)
class State:
    """Heliocentric ICRF equatorial state. Metres, metres per second."""

    r: np.ndarray
    v: np.ndarray

    def __post_init__(self) -> None:
        if self.r.shape != (3,) or self.v.shape != (3,):
            raise ValueError("state vectors must be shape (3,)")

    @property
    def radius(self) -> float:
        return float(np.linalg.norm(self.r))

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.v))


class Backend(Protocol):
    """An ephemeris source."""

    name: str

    def state(self, body: str, jd_tt: float) -> State:
        """Heliocentric equatorial state of ``body`` at Julian Date ``jd_tt``."""
        ...

    def coverage(self) -> tuple[float, float]:
        """(first_jd, last_jd) this backend can answer for."""
        ...


def get_backend(kind: str = "auto", **kwargs) -> Backend:
    """Resolve a backend by name.

    ``auto`` prefers a real JPL kernel if one is configured, falls back to the
    bundled DE421 coefficients, and finally to the analytic series. The
    fallback chain never silently degrades accuracy without saying so: the
    chosen backend's ``name`` is reported by the service's health endpoint and
    stamped into every generated transfer table.
    """
    if kind == "kernel":
        from .de_kernel import KernelBackend

        return KernelBackend(**kwargs)
    if kind == "legacy":
        from .de_legacy import LegacyBackend

        return LegacyBackend(**kwargs)
    if kind == "analytic":
        from .analytic import AnalyticBackend

        return AnalyticBackend(**kwargs)
    if kind == "auto":
        import os

        path = os.environ.get("ORBITAL_KERNEL")
        if path and os.path.exists(path):
            from .de_kernel import KernelBackend

            return KernelBackend(path=path)
        try:
            from .de_legacy import LegacyBackend

            return LegacyBackend()
        except ImportError:
            from .analytic import AnalyticBackend

            return AnalyticBackend()
    raise ValueError(f"unknown ephemeris backend: {kind!r}")
