#!/usr/bin/env python3
"""Fetch the JPL DE ephemeris kernel. Build time only, never at runtime.

The kernel is large and exactly reproducible from this script, so it is not
committed. ``orbital/kernels/`` is gitignored.

Kernel choice, and what it costs you:

  de440s.bsp   32 MB, 1849-2150. Fine for tests and development.
  de440.bsp    114 MB, 1550-2650. The production default. At the 60x clock a
               world launched in 2026 has about ten real years of sky before
               it runs out.
  de441.bsp    3.1 GB in two parts, -13200 to +17191. Effectively unlimited.

The service reports its kernel's coverage window on /health, so running out
is a monitored expiry date years in advance rather than a surprise.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BASE = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/"
KERNELS = {"de440s": "de440s.bsp", "de440": "de440.bsp", "de441": "de441.bsp"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", choices=sorted(KERNELS), default="de440")
    parser.add_argument(
        "--dest",
        default=str(Path(__file__).resolve().parents[1] / "kernels"),
    )
    args = parser.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    name = KERNELS[args.kernel]
    target = dest / name

    if target.exists():
        print(f"{target} already present ({target.stat().st_size / 1e6:.0f} MB)")
        return 0

    url = BASE + name
    print(f"fetching {url}")
    tmp = target.with_suffix(".partial")
    try:
        urllib.request.urlretrieve(url, tmp)
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        print(
            "\nIf this environment cannot reach naif.jpl.nasa.gov, the service\n"
            "still runs: install the 'offline' extra for DE421 coefficients,\n"
            "or fall back to the analytic ERFA backend. Both are inside the\n"
            "arcminute accuracy target. See docs/DECISIONS.md, D6.",
            file=sys.stderr,
        )
        return 1

    tmp.replace(target)
    print(f"wrote {target} ({target.stat().st_size / 1e6:.0f} MB)")
    print(f"\nexport ORBITAL_KERNEL={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
