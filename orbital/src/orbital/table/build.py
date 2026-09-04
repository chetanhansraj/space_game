"""Generating the transfer table.

Runs on a schedule, never in a request. Two stages:

1. Sweep. For every ordered anchor pair and every gridded departure date,
   sweep time of flight and cost each arc.
2. Reduce. Keep only the Pareto frontier -- the points where no other
   transfer is both faster and cheaper.

The reduction is what makes the table small. A full sweep is dozens of
samples per departure; the frontier is typically 25 to 40 of them, and the
dominated points carry no information a player could act on.

Sizing, measured rather than estimated, at the defaults in
``docs/DECISIONS.md`` D15. Ten anchors is 90 ordered pairs; departures every
6 sky hours across a 2 sky year horizon is 2,920 grid points; the frontier
comes out at 27 points per departure on average. That is 7.1 million rows at
119 bytes each, so roughly 850 MB, built from 262,800 curve solves at 11 ms
each: 48 minutes on one core, about 6 on eight. Halving the departure grid to
12 sky hours halves both.

The build parallelises across pairs trivially, and does not need to: a
48-minute batch job refreshed every 6 real hours has a comfortable margin.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
from pathlib import Path

from ..anchors import AnchorRegistry
from ..curve import build_curve
from .schema import SCHEMA, TABLE_VERSION


def generate(
    registry: AnchorRegistry,
    out_path: str | Path,
    start_jd: float,
    horizon_days: float,
    step_days: float = 0.25,
    samples: int = 48,
    pairs: list[tuple[str, str]] | None = None,
    progress: bool = False,
) -> Path:
    """Build a transfer table and atomically move it into place.

    Writes to a temporary file and renames on success, so a running service
    reading the previous table is never exposed to a half-written one.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    anchor_ids = registry.ids()
    if pairs is None:
        pairs = [(a, b) for a in anchor_ids for b in anchor_ids if a != b]

    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=out_path.parent, prefix=".transfers-", suffix=".sqlite"
    )
    Path(tmp_name).unlink()
    db = sqlite3.connect(tmp_name)
    db.executescript(SCHEMA)

    end_jd = start_jd + horizon_days
    n_steps = int(horizon_days / step_days)
    elements_epoch = next(
        (el.epoch_jd for el in registry.elements.values()), None
    )

    meta = {
        "table_version": str(TABLE_VERSION),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "ephemeris_backend": registry.backend.name,
        "elements_source": next(
            (el.source for el in registry.elements.values()), "none"
        ),
        "elements_epoch_jd": str(elements_epoch),
        "coverage_start_jd": str(start_jd),
        "coverage_end_jd": str(end_jd),
        "departure_step_days": str(step_days),
        "samples_per_curve": str(samples),
    }
    db.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", meta.items())

    # Same-well pairs are analytic and have no departure dependence at all.
    for origin, destination in pairs:
        if registry.same_well(origin, destination):
            dv, tof = registry.local_transfer(origin, destination)
            db.execute(
                "INSERT OR REPLACE INTO local_transfer "
                "(origin, destination, dv_total, tof_s) VALUES (?, ?, ?, ?)",
                (origin, destination, dv, tof),
            )

    interplanetary = [
        (a, b) for a, b in pairs if not registry.same_well(a, b)
    ]

    rows: list[tuple] = []
    for index, (origin, destination) in enumerate(interplanetary, start=1):
        if progress:
            print(f"[{index}/{len(interplanetary)}] {origin} -> {destination}",
                  flush=True)
        dv_fixed = registry.fixed_budget(origin, destination)
        origin_fn = lambda jd, a=origin: registry.state(a, jd)
        dest_fn = lambda jd, b=destination: registry.state(b, jd)

        for step in range(n_steps):
            departure_jd = start_jd + step * step_days
            try:
                curve = build_curve(
                    origin_fn, dest_fn, departure_jd,
                    dv_fixed=dv_fixed, samples=samples,
                )
            except RuntimeError:
                continue
            for point in curve.points:
                rows.append((
                    origin, destination, departure_jd, point.tof,
                    point.dv_depart, point.dv_arrive, point.dv_fixed,
                    point.dv_total, point.revolutions,
                ))
            if len(rows) >= 50_000:
                _flush(db, rows)
                rows.clear()

    _flush(db, rows)
    db.commit()
    db.execute("ANALYZE")
    db.commit()
    db.close()

    Path(tmp_name).replace(out_path)
    return out_path


def _flush(db: sqlite3.Connection, rows: list[tuple]) -> None:
    if rows:
        db.executemany(
            "INSERT INTO curve_point (origin, destination, departure_jd, "
            "tof_s, dv_depart, dv_arrive, dv_fixed, dv_total, revolutions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
