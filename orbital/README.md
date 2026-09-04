# orbital

Given two anchors and a departure time, what does it cost to get from one to
the other?

Standalone service. No game concepts, no database, no LLM. Pure computation
over ephemerides plus a precomputed lookup table.

## What it returns

Not three trajectory classes — a **cost curve**. For any departure, the
Pareto frontier of delta-v against time of flight: every arc where nothing
else is both faster and cheaper.

```
 TOF game-d  real-hrs   dv km/s      Shackleton Depot -> Tharsis Yards
       11.8       4.7     689.3      departing 2028-01-15
       23.0       9.2     345.6
       45.1      18.0     168.1
       88.1      35.3      77.0
      172.4      68.9      37.7
```

Naming points on that curve — *minimum-energy*, *standard torch*, *hard
burn* — is a game decision and lives in `sim/`. This service stays physics.
The reasoning is in [`docs/DECISIONS.md`](../docs/DECISIONS.md) D1.

## Accuracy

Target from the bible is arcminutes, not milliarcseconds. Measured:

| Check | Result | Target |
|---|---|---|
| DE421 vs ERFA, Earth & Mars positions | ≤ 15 arcsec | 60 arcsec |
| Lambert vs Vallado Example 7-5 | < 1 m/s | 1 m/s |
| Launch C3 vs 4 real NASA Mars missions | 0.0–5.6% | 10% |
| Mars elements recovered vs JPL published | a, e, i, period all match | — |

The mission test is the one that matters. Reconstructing Perseverance's
launch energy to 0.0% and InSight's to 0.3%, from nothing but two dates and
an ephemeris, exercises the whole stack in a single number.

## Install

```bash
python -m venv .venv && .venv/bin/pip install -e 'orbital[offline,serve,dev]'
```

Ephemeris backends, in preference order:

| Backend | Data | Accuracy | Use |
|---|---|---|---|
| `kernel` | DE440, ~114 MB from NAIF | reference | production |
| `legacy` | DE421, pip-installable | < 1 arcsec of DE440 | CI, sealed builds |
| `analytic` | none, ERFA series | ~15 arcsec | fallback, cross-checks |

`scripts/fetch_kernels.py` gets DE440 where `naif.jpl.nasa.gov` is
reachable. Where it is not, `legacy` and `analytic` are both inside the
accuracy target — the service says which one produced any given table.

## Build a table

```bash
.venv/bin/python orbital/scripts/fetch_sbdb.py       # refresh asteroid elements
.venv/bin/python orbital/scripts/build_table.py      # sweep and reduce
```

Defaults: departures every 6 sky hours over a 2 sky year horizon, all anchor
pairs. 7.1M rows, ~850 MB, 48 minutes on one core. Written to a temp file and
renamed atomically, so a running service never sees a half-written table.

## Serve

```bash
ORBITAL_TABLE=orbital/data/transfers.sqlite \
  .venv/bin/uvicorn orbital.api.app:app
```

`GET /transfers?origin=&destination=&departure_jd=` returns the curve.
`GET /health` returns provenance and the coverage window.

A departure outside coverage returns 422 naming the window. It is never
solved on demand — there is no import path from the request handler to a
Lambert solver, and `tests/test_determinism.py` asserts it.

## Test

```bash
.venv/bin/python -m pytest orbital/tests -q
```

117 tests. Textbook Lambert cases, real mission energies, cross-backend
agreement, Kepler round-trips against a real ephemeris, Hypothesis property
tests over the Pareto frontier, and assertions on the architectural
invariants themselves.

## Layout

```
src/orbital/
  constants.py     SI constants. One source of truth.
  clock.py         The 60x clock. The rate appears here and nowhere else.
  frames.py        Barycentric/heliocentric, ecliptic/equatorial.
  costs.py         The Transfer type. No dependencies, so the read path
                   can use it without importing a solver.
  ephemeris/       Three interchangeable backends.
  smallbody.py     Keplerian propagation for asteroid anchors.
  lambert.py       Izzo 2015, thin wrapper.
  transfer.py      Arc -> delta-v.
  lunar.py         Analytic suborbital hops and well budgets.
  curve.py         The Pareto frontier.
  anchors.py       Places. Not nodes.
  table/           Generate, store, look up.
  api/             HTTP. Lookups only.
```
