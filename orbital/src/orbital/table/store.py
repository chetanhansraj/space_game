"""Read-only access to a generated transfer table.

The only thing a request handler is allowed to touch. There is no solver
import reachable from here, and a test asserts that.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..costs import Transfer


class OutsideCoverage(LookupError):
    """The requested departure is not in the table's window.

    Raised rather than silently solved. Invariant 4 is enforced structurally:
    there is no code path from a request to a Lambert solve, so the only
    possible answer to an out-of-range departure is an honest error naming
    the window that is available.
    """

    def __init__(self, requested: float, start: float, end: float) -> None:
        super().__init__(
            f"departure jd={requested:.3f} outside table coverage "
            f"[{start:.3f}, {end:.3f}]"
        )
        self.requested = requested
        self.start = start
        self.end = end


@dataclass(frozen=True)
class LocalTransfer:
    dv_total: float
    tof: float


class TransferTable:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True,
                                   check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self.meta = {
            row["key"]: row["value"]
            for row in self._db.execute("SELECT key, value FROM meta")
        }

    @property
    def coverage(self) -> tuple[float, float]:
        return (float(self.meta["coverage_start_jd"]),
                float(self.meta["coverage_end_jd"]))

    def _nearest_departure(self, origin: str, destination: str,
                           departure_jd: float) -> float:
        """Snap to the nearest gridded departure.

        Departures are gridded every few game hours. Snapping rather than
        interpolating between two curves is deliberate: interpolating
        delta-v across a departure grid smears the sharp cost ridges that
        make launch windows economically meaningful, and the grid is fine
        enough that the snap is worth under a percent.
        """
        row = self._db.execute(
            """
            SELECT departure_jd FROM curve_point
            WHERE origin = ? AND destination = ?
            ORDER BY ABS(departure_jd - ?) LIMIT 1
            """,
            (origin, destination, departure_jd),
        ).fetchone()
        if row is None:
            raise LookupError(f"no transfers stored for {origin} -> {destination}")
        return float(row["departure_jd"])

    def curve(self, origin: str, destination: str,
              departure_jd: float) -> list[Transfer]:
        """The full cost curve for a departure. Fastest first."""
        start, end = self.coverage
        if not (start <= departure_jd <= end):
            raise OutsideCoverage(departure_jd, start, end)

        snapped = self._nearest_departure(origin, destination, departure_jd)
        rows = self._db.execute(
            """
            SELECT tof_s, dv_depart, dv_arrive, dv_fixed, revolutions
            FROM curve_point
            WHERE origin = ? AND destination = ? AND departure_jd = ?
            ORDER BY tof_s ASC
            """,
            (origin, destination, snapped),
        ).fetchall()
        return [
            Transfer(
                tof=r["tof_s"],
                dv_depart=r["dv_depart"],
                dv_arrive=r["dv_arrive"],
                dv_fixed=r["dv_fixed"],
                revolutions=r["revolutions"],
            )
            for r in rows
        ]

    def local(self, origin: str, destination: str) -> LocalTransfer | None:
        row = self._db.execute(
            "SELECT dv_total, tof_s FROM local_transfer "
            "WHERE origin = ? AND destination = ?",
            (origin, destination),
        ).fetchone()
        if row is None:
            return None
        return LocalTransfer(dv_total=row["dv_total"], tof=row["tof_s"])

    def pairs(self) -> list[tuple[str, str]]:
        rows = self._db.execute(
            "SELECT DISTINCT origin, destination FROM curve_point "
            "ORDER BY origin, destination"
        ).fetchall()
        return [(r["origin"], r["destination"]) for r in rows]

    def close(self) -> None:
        self._db.close()
