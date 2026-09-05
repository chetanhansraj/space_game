#!/usr/bin/env python3
"""Refresh small-body elements from the JPL Small-Body Database.

Asteroid elements are osculating: they describe the orbit at one instant and
drift from reality as unmodelled perturbations accumulate. Two-body
propagation of Ceres is good to roughly an arcminute per decade, and the sky
clock runs 60x, so a real year is 60 sky years. Refreshing re-anchors the
propagation.

Run this before every table generation. The fetch timestamp and element epoch
are written into the JSON and copied into the transfer table's metadata, so
any number the service returns can be traced back to the elements that
produced it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://ssd-api.jpl.nasa.gov/sbdb.api"

# The five candidate asteroid nodes from docs/seed-data.md.
BODIES = {
    "ceres": "1", "pallas": "2", "vesta": "4",
    "psyche": "16", "eros": "433",
}


def fetch(designation: str) -> dict:
    url = f"{API}?{urllib.parse.urlencode({'sstr': designation, 'full-prec': 'true'})}"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def extract(payload: dict) -> dict:
    elements = {e["name"]: e for e in payload["orbit"]["elements"]}
    return {
        "name": payload["object"]["fullname"].strip(),
        "a_au": float(elements["a"]["value"]),
        "e": float(elements["e"]["value"]),
        "i_deg": float(elements["i"]["value"]),
        "raan_deg": float(elements["om"]["value"]),
        "argp_deg": float(elements["w"]["value"]),
        "M0_deg": float(elements["ma"]["value"]),
        "epoch_jd": float(payload["orbit"]["epoch"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1]
                    / "data" / "smallbody_elements.json"),
    )
    args = parser.parse_args()

    bodies = {}
    for key, designation in BODIES.items():
        print(f"fetching {key} ({designation})")
        try:
            bodies[key] = extract(fetch(designation))
        except Exception as exc:
            print(f"failed on {key}: {exc}", file=sys.stderr)
            print(
                "\nElements were NOT refreshed. The existing file still has "
                "its previous epoch stamped in it, so nothing silently "
                "degrades -- but do not generate a production table until "
                "this succeeds.",
                file=sys.stderr,
            )
            return 1

    document = {
        "_comment": "Heliocentric osculating Keplerian elements, ecliptic J2000.",
        "_provenance": "Fetched from the JPL Small-Body Database.",
        "source": "jpl-sbdb",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bodies": bodies,
    }
    Path(args.out).write_text(json.dumps(document, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
