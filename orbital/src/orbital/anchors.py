"""The anchor registry: the only thing the orbital service knows about places.

An anchor is a physical location the service can compute a state vector for,
plus the fixed delta-v budgets for getting off it and onto it. That is all.

It is deliberately NOT a game node. The service has never heard of a docking
fee, a commodity, an order book or a settlement. The game maps
"Shackleton Depot" onto the anchor ``luna_south`` in its own configuration,
and the orbital service stays a pure function of physics as the architecture
requires.

Fixed budgets are the patched-conic stitch: the cost of climbing out of a
local gravity well, which does not vary with where the planets are. Charging
them separately from the heliocentric arc is what lets the expensive part
(the Lambert sweep) be shared across every node sitting on the same body.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .ephemeris import Backend, State
from .lunar import Site, suborbital_hop
from .smallbody import Elements, load_elements


@dataclass(frozen=True)
class Anchor:
    """A place the service can cost a transfer to or from."""

    id: str
    kind: str            # "ephemeris" | "smallbody" | "lunar_surface" | "lunar_orbit"
    body: str            # ephemeris body name or smallbody key
    dv_escape: float     # m/s to reach interplanetary space from here
    dv_capture: float    # m/s to arrive here from interplanetary space
    site: Site | None = None   # lunar surface coordinates, if applicable
    note: str = ""

    @property
    def is_lunar(self) -> bool:
        return self.kind in ("lunar_surface", "lunar_orbit")


class AnchorRegistry:
    """Loaded anchors plus the ephemeris needed to evaluate them."""

    def __init__(
        self,
        anchors: dict[str, Anchor],
        backend: Backend,
        elements: dict[str, Elements] | None = None,
    ) -> None:
        self.anchors = anchors
        self.backend = backend
        self.elements = elements or {}

    @classmethod
    def load(
        cls,
        backend: Backend,
        anchors_path: str | Path,
        elements_path: str | Path | None = None,
    ) -> "AnchorRegistry":
        raw = tomllib.loads(Path(anchors_path).read_text())
        anchors: dict[str, Anchor] = {}
        for anchor_id, rec in raw["anchors"].items():
            site = None
            if "lat_deg" in rec:
                site = Site(name=anchor_id, lat_deg=rec["lat_deg"],
                            lon_deg=rec["lon_deg"])
            anchors[anchor_id] = Anchor(
                id=anchor_id,
                kind=rec["kind"],
                body=rec.get("body", ""),
                dv_escape=float(rec.get("dv_escape", 0.0)),
                dv_capture=float(rec.get("dv_capture", 0.0)),
                site=site,
                note=rec.get("note", ""),
            )
        elements = load_elements(elements_path) if elements_path else {}
        return cls(anchors=anchors, backend=backend, elements=elements)

    def __getitem__(self, anchor_id: str) -> Anchor:
        return self.anchors[anchor_id]

    def __contains__(self, anchor_id: str) -> bool:
        return anchor_id in self.anchors

    def ids(self) -> list[str]:
        return sorted(self.anchors)

    def state(self, anchor_id: str, jd_tt: float) -> State:
        """Heliocentric equatorial state of an anchor.

        Lunar anchors return the Earth-Moon barycentre. That is the bible's
        stated dodge and it is sound: the Moon's 384,000 km orbit is under
        0.003 AU, which is inside the arcminute accuracy target at
        interplanetary distances, and the cost of being on the Moon rather
        than at the barycentre is carried by the fixed budgets instead.
        """
        from .smallbody import state_from_elements

        anchor = self.anchors[anchor_id]
        if anchor.kind in ("ephemeris", "lunar_surface", "lunar_orbit"):
            return self.backend.state(anchor.body, jd_tt)
        if anchor.kind == "smallbody":
            return state_from_elements(self.elements[anchor.body], jd_tt)
        raise ValueError(f"unknown anchor kind {anchor.kind!r}")

    def same_well(self, a: str, b: str) -> bool:
        """True if both anchors sit in the same local gravity well.

        Transfers inside one well are analytic and geometry-independent, so
        they skip the Lambert machinery entirely.
        """
        return self.anchors[a].is_lunar and self.anchors[b].is_lunar

    def local_transfer(self, a: str, b: str) -> tuple[float, float]:
        """(delta-v, time of flight) for a transfer inside one gravity well."""
        from .lunar import DV_SURFACE_TO_LLO

        first, second = self.anchors[a], self.anchors[b]
        if not (first.is_lunar and second.is_lunar):
            raise ValueError("local_transfer is for same-well pairs only")

        if first.kind == "lunar_surface" and second.kind == "lunar_surface":
            hop = suborbital_hop(first.site, second.site)
            return hop.dv_total, hop.tof
        # Surface to orbit or orbit to surface: a flat budget. Time of flight
        # is roughly half a low lunar orbit period, near enough for a game
        # where this leg takes well under a real minute.
        return DV_SURFACE_TO_LLO, 3_249.0

    def fixed_budget(self, origin: str, destination: str) -> float:
        """Combined well-exit and well-entry cost for an interplanetary leg."""
        return self.anchors[origin].dv_escape + self.anchors[destination].dv_capture
