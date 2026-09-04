# Solar Economy

A persistent, asynchronous, multiplayer space economy. Players operate a firm — hauling cargo, speculating on commodities, and eventually owning extraction outposts across the Moon, Mars and the asteroid belt. The world is populated by autonomous agents who trade whether or not any human is online.

Real orbital mechanics, deterministic economy, one shared clock at 60× real time.

## Documentation

| File | What it's for |
|---|---|
| `CLAUDE.md` | Engineering invariants and working rules. Read before writing code. |
| `docs/BIBLE.md` | Design reasoning — the world, markets, agents, player arc. Why things are the way they are. |
| `docs/seed-data.md` | Locations, commodities, modules. The numbers everything descends from. |
| `docs/DECISIONS.md` | Every call made on what the above left ambiguous, contradictory or unset. |
| `docs/DESIGN-LANGUAGE.md` | The lunarark.com visual system, as tokens. What `web/` gets built against. |
| `orbital/README.md` | The transfer service: accuracy, how to build a table, how to run it. |
| `market/README.md` | The ledger and order books: why conservation is structural. |

## Layout

```
orbital/   Transfer solver. Standalone, no game concepts, no database.
sim/       World tick — agents, production, depletion, price formation.
market/    Order books, settlement, escrow, exchange. Correctness-critical.
api/       Thin request layer. No business logic.
voice/     The only place LLM calls exist. Text generation only.
web/       Client. Rendering only.
```

## Running locally

```bash
python -m venv .venv
.venv/bin/pip install -e './orbital[offline,serve,dev]' -e './market[dev]'
.venv/bin/python -m pytest -q                        # 157 tests

.venv/bin/python orbital/scripts/fetch_sbdb.py       # refresh asteroid elements
.venv/bin/python orbital/scripts/build_table.py      # generate transfer table
ORBITAL_TABLE=orbital/data/transfers.sqlite .venv/bin/uvicorn orbital.api.app:app
```

Ephemeris kernels (JPL DE440) are fetched at build time into `orbital/kernels/` and are not committed — they are large and reproducible.

## See it working

Nothing is playable yet — `sim/` and `web/` are empty. Two demo scripts show
the finished pieces actually running:

```bash
.venv/bin/python scripts/demo_market.py --ticks 40   # a live spot market
.venv/bin/python scripts/demo_routes.py              # transfer costs and windows
```

`demo_market.py` runs miners, refineries and haulers against the real ledger
and order books at Shackleton Depot, printing the book, the tape and a
conservation check every few ticks. `demo_routes.py` prints the delta-v
against transit-time curve for a route, and a bar chart of how the
minimum-energy cost moves across a synodic cycle.

Both are demo harnesses, not `sim/`. The agents are deliberately stupid.

## Status

Pre-v1. The orbital service is built and returns validated numbers: it
reproduces the launch energies of four real NASA Mars missions to between
0.0% and 5.6%, and two independent ephemerides agree to 15 arcseconds against
an arcminute target.

`market/` is built: an append-only double-entry ledger where conservation is
structural rather than tested, escrowed limit order books with price-time
priority, and the Ark Authority quoting a floor and ceiling from a finite
treasury. A Hypothesis state machine checks after every step of every
generated trade sequence that nothing was created or destroyed.

`sim/`, `api/`, `voice/` and `web/` are empty.

Roadmap is in `docs/BIBLE.md` §10. Short version: one lunar node and one market, then ships, then the Belt, then Mars industry, then the political layer.
