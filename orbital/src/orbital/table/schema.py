"""Transfer table schema.

SQLite, one file, read-only in production, replaced by atomic rename when
regenerated. Chosen over Parquet because the access pattern is point lookups
rather than scans, and over a real database because the orbital service is
forbidden one -- this is a build artifact, not shared state.

Every table carries its provenance in ``meta``: which ephemeris produced it,
which small-body elements and at what epoch, when it was generated and what
sky window it covers. A transfer table that cannot say where its numbers came
from is not usable for debugging a live economy at 2am.
"""

from __future__ import annotations

TABLE_VERSION = 1

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per Pareto-optimal transfer. A (origin, destination, departure)
-- triple owns a handful of rows: the cost curve for that departure.
CREATE TABLE curve_point (
    origin       TEXT NOT NULL,
    destination  TEXT NOT NULL,
    departure_jd REAL NOT NULL,
    tof_s        REAL NOT NULL,
    dv_depart    REAL NOT NULL,
    dv_arrive    REAL NOT NULL,
    dv_fixed     REAL NOT NULL,
    dv_total     REAL NOT NULL,
    revolutions  INTEGER NOT NULL
);

-- Transfers inside a single gravity well. Geometry-independent, so these
-- have no departure date: one row per ordered pair, forever.
CREATE TABLE local_transfer (
    origin      TEXT NOT NULL,
    destination TEXT NOT NULL,
    dv_total    REAL NOT NULL,
    tof_s       REAL NOT NULL,
    PRIMARY KEY (origin, destination)
);

CREATE INDEX idx_curve_lookup
    ON curve_point (origin, destination, departure_jd, dv_total);
"""

META_KEYS = (
    "table_version",
    "generated_at",
    "ephemeris_backend",
    "elements_source",
    "elements_epoch_jd",
    "coverage_start_jd",
    "coverage_end_jd",
    "departure_step_days",
    "samples_per_curve",
)
