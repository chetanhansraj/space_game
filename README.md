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
| `orbital/README.md` | The transfer service: accuracy, how to build a table, how to run it. |

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
.venv/bin/pip install -e 'orbital[offline,serve,dev]'
.venv/bin/python -m pytest orbital/tests -q          # 117 tests

.venv/bin/python orbital/scripts/fetch_sbdb.py       # refresh asteroid elements
.venv/bin/python orbital/scripts/build_table.py      # generate transfer table
ORBITAL_TABLE=orbital/data/transfers.sqlite .venv/bin/uvicorn orbital.api.app:app
```

Ephemeris kernels (JPL DE440) are fetched at build time into `orbital/kernels/` and are not committed — they are large and reproducible.

## Status

Pre-v1. The orbital service is built and returns validated numbers: it
reproduces the launch energies of four real NASA Mars missions to between
0.0% and 5.6%, and two independent ephemerides agree to 15 arcseconds against
an arcminute target.

Nothing else is built yet. `sim/`, `market/`, `api/`, `voice/` and `web/` are
empty.

Roadmap is in `docs/BIBLE.md` §10. Short version: one lunar node and one market, then ships, then the Belt, then Mars industry, then the political layer.
