#!/usr/bin/env python3
"""What does it cost to go somewhere, and when should you leave?

Solves live rather than reading the precomputed table, because this is a
inspection tool run by a person, not a request handler. In the game these
numbers are lookups -- see invariant 4 and orbital/README.md.

    python scripts/demo_routes.py
    python scripts/demo_routes.py --from luna_south --to ceres --days 900
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orbital" / "src"))

from orbital.anchors import AnchorRegistry
from orbital.clock import TIME_RATE, from_jd, to_jd
from orbital.curve import build_curve
from orbital.ephemeris import get_backend

V, C, G, A, R, D, W, X, B = (
    "\033[38;5;141m", "\033[38;5;80m", "\033[38;5;77m", "\033[38;5;214m",
    "\033[38;5;203m", "\033[38;5;245m", "\033[38;5;255m", "\033[0m", "\033[1m",
)

#: Fusion torch exhaust velocity, m/s. docs/DECISIONS.md D2.
EXHAUST_VELOCITY = 400_000.0


def propellant_fraction(dv: float) -> float:
    """Rocket equation. What share of the ship has to be tank."""
    return 1.0 - math.exp(-dv / EXHAUST_VELOCITY)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="origin", default="luna_south")
    parser.add_argument("--to", dest="destination", default="mars")
    parser.add_argument("--depart", default="2028-11-16")
    parser.add_argument("--days", type=int, default=780,
                        help="sky days to scan for launch windows")
    args = parser.parse_args()

    registry = AnchorRegistry.load(
        get_backend("auto"),
        ROOT / "orbital" / "data" / "anchors.toml",
        ROOT / "orbital" / "data" / "smallbody_elements.json",
    )
    origin, destination = registry[args.origin], registry[args.destination]
    depart = dt.datetime.fromisoformat(args.depart).replace(tzinfo=dt.timezone.utc)
    jd = to_jd(depart)

    print(f"\n{V}{B}{'─' * 78}{X}")
    print(f"{V}{B} {args.origin.upper()} → {args.destination.upper()}{X}"
          f"   {D}ephemeris{X} {W}{registry.backend.name}{X}"
          f"   {D}clock{X} {W}{TIME_RATE}×{X}")
    print(f"{V}{'─' * 78}{X}")

    if registry.same_well(args.origin, args.destination):
        dv, tof = registry.local_transfer(args.origin, args.destination)
        print(f"\n {C}SAME GRAVITY WELL{X} {D}· ballistic hop, no launch window{X}")
        print(f"   {C}DELTA-V{X} {W}{dv:>10,.0f} m/s{X}"
              f"     {C}TRANSIT{X} {W}{tof / 60:>7.0f} game min"
              f"  ({tof / TIME_RATE / 60:.1f} real min){X}\n")
        return 0

    fixed = registry.fixed_budget(args.origin, args.destination)
    curve = build_curve(lambda t: registry.state(args.origin, t),
                        lambda t: registry.state(args.destination, t),
                        jd, dv_fixed=fixed, samples=48)

    print(f"\n {C}COST CURVE{X} {D}· departing {depart.date()} "
          f"· well budgets {fixed:,.0f} m/s included{X}\n")
    print(f"   {D}{'transit':>10}  {'real time':>11}  {'delta-v':>11}"
          f"  {'propellant':>11}  {'cargo lost':>11}{X}")
    step = max(1, len(curve) // 9)
    for point in list(curve.points)[::step]:
        days = point.tof / 86400
        frac = propellant_fraction(point.dv_total)
        tint = R if frac > 0.45 else (A if frac > 0.22 else G)
        print(f"   {W}{days:>8.0f} d{X}  {W}{days * 24 / TIME_RATE:>9.1f} h{X}"
              f"  {W}{point.dv_total / 1000:>8.1f} km/s{X}"
              f"  {tint}{frac:>10.0%}{X}  {tint}{frac * 40:>9.1f} t{X}")
    print(f"\n   {D}cargo lost = tonnes of a 40 t Kestrel hold given over to tank{X}")

    print(f"\n {C}LAUNCH WINDOWS{X} {D}· minimum-energy cost across "
          f"{args.days} sky days ({args.days / TIME_RATE:.0f} real days){X}\n")
    samples = []
    for offset in range(0, args.days, max(1, args.days // 14)):
        try:
            window = build_curve(lambda t: registry.state(args.origin, t),
                                 lambda t: registry.state(args.destination, t),
                                 jd + offset, dv_fixed=fixed, samples=28)
        except RuntimeError:
            continue
        samples.append((jd + offset, window.cheapest.dv_total))

    if samples:
        low = min(s[1] for s in samples)
        high = max(s[1] for s in samples)
        for when, dv in samples:
            width = int(46 * (dv - low) / (high - low + 1e-9))
            tint = G if dv < low * 1.4 else (A if dv < low * 2.5 else R)
            print(f"   {D}{from_jd(when).date()}{X} {tint}{'█' * (width + 1)}{X}"
                  f" {W}{dv / 1000:.1f}{X}")
        print(f"\n   {D}cheapest{X} {G}{low / 1000:.1f} km/s{X}"
              f"   {D}dearest{X} {R}{high / 1000:.1f} km/s{X}"
              f"   {D}ratio{X} {W}{high / low:.1f}×{X}"
              f"   {D}← geometry setting price{X}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
