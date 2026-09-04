#!/usr/bin/env python3
"""Generate the precomputed transfer table.

Runs on a schedule, never in a request. See docs/DECISIONS.md D15 for where
the grid parameters come from.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from orbital.anchors import AnchorRegistry
from orbital.clock import to_jd
from orbital.ephemeris import get_backend
from orbital.table.build import generate

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "kernel", "legacy", "analytic"])
    parser.add_argument("--out", default=str(ROOT / "data" / "transfers.sqlite"))
    parser.add_argument("--start", default=None,
                        help="ISO sky date to start coverage (default: now)")
    parser.add_argument("--horizon-days", type=float, default=730.0,
                        help="sky days of coverage (default: 2 sky years)")
    parser.add_argument("--step-hours", type=float, default=6.0,
                        help="departure grid spacing in sky hours")
    parser.add_argument("--samples", type=int, default=48,
                        help="time-of-flight samples swept per departure")
    parser.add_argument("--anchors", nargs="*", default=None,
                        help="restrict to these anchor ids")
    args = parser.parse_args()

    backend = get_backend(args.backend)
    registry = AnchorRegistry.load(
        backend,
        ROOT / "data" / "anchors.toml",
        ROOT / "data" / "smallbody_elements.json",
    )

    if args.start:
        start = dt.datetime.fromisoformat(args.start).replace(
            tzinfo=dt.timezone.utc
        )
    else:
        start = dt.datetime.now(dt.timezone.utc)

    ids = args.anchors or registry.ids()
    pairs = [(a, b) for a in ids for b in ids if a != b]

    print(f"backend      {backend.name}")
    print(f"anchors      {len(ids)}  pairs {len(pairs)}")
    print(f"coverage     {start.date()} + {args.horizon_days:g} sky days")
    print(f"grid         every {args.step_hours:g} sky hours, "
          f"{args.samples} tof samples")

    path = generate(
        registry,
        args.out,
        start_jd=to_jd(start),
        horizon_days=args.horizon_days,
        step_days=args.step_hours / 24.0,
        samples=args.samples,
        pairs=pairs,
        progress=True,
    )
    size = Path(path).stat().st_size / 1e6
    print(f"\nwrote {path} ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
