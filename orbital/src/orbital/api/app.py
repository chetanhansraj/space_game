"""HTTP surface. Lookups only.

There is deliberately no import path from this module to ``lambert``,
``curve`` or ``transfer``'s solver entry points. ``tests/test_no_solver.py``
asserts it. That is how invariant 4 stops being a rule people remember and
starts being a property of the code.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from ..table.store import OutsideCoverage, TransferTable

app = FastAPI(
    title="orbital",
    summary="Transfer costs between anchors. Precomputed, never solved on request.",
)

_TABLE: TransferTable | None = None


def table() -> TransferTable:
    global _TABLE
    if _TABLE is None:
        path = os.environ.get("ORBITAL_TABLE", "orbital/data/transfers.sqlite")
        _TABLE = TransferTable(path)
    return _TABLE


def _as_dict(transfer) -> dict[str, Any]:
    return {
        "tof_s": transfer.tof,
        "tof_game_days": transfer.tof / 86400.0,
        "dv_total": transfer.dv_total,
        "dv_depart": transfer.dv_depart,
        "dv_arrive": transfer.dv_arrive,
        "dv_fixed": transfer.dv_fixed,
        "revolutions": transfer.revolutions,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    """Provenance and coverage. Everything needed to trust a number."""
    store = table()
    start, end = store.coverage
    return {
        "status": "ok",
        "table": store.meta,
        "coverage_jd": {"start": start, "end": end},
        "pairs": len(store.pairs()),
    }


@app.get("/transfers")
def transfers(
    origin: str = Query(...),
    destination: str = Query(...),
    departure_jd: float = Query(...),
) -> dict[str, Any]:
    """The full cost curve for a departure.

    Returns the Pareto frontier: every transfer where nothing else is both
    faster and cheaper. Naming points on it -- minimum-energy, torch, hard
    burn -- is the game's decision, not this service's.
    """
    store = table()
    local = store.local(origin, destination)
    if local is not None:
        return {
            "origin": origin,
            "destination": destination,
            "kind": "local",
            "points": [{
                "tof_s": local.tof,
                "tof_game_days": local.tof / 86400.0,
                "dv_total": local.dv_total,
                "dv_depart": 0.0, "dv_arrive": 0.0,
                "dv_fixed": local.dv_total, "revolutions": 0,
            }],
        }
    try:
        curve = store.curve(origin, destination, departure_jd)
    except OutsideCoverage as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "departure outside precomputed coverage",
                "requested_jd": exc.requested,
                "coverage_jd": {"start": exc.start, "end": exc.end},
            },
        ) from None
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    return {
        "origin": origin,
        "destination": destination,
        "kind": "interplanetary",
        "points": [_as_dict(t) for t in curve],
    }
