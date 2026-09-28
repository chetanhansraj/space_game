# Solar Economy

A persistent, asynchronous, multiplayer space economy. Players operate a firm — hauling cargo, speculating on commodities, and eventually owning extraction outposts across the Moon, Mars and the asteroid belt. The world is populated by autonomous agents who trade whether or not any human is online.

Real orbital mechanics, deterministic economy, one shared clock at 60× real time.

## Documentation

| File | What it's for |
|---|---|
| `docs/VISION.md` | What the game is for and where it is going. Check hard decisions against it. |
| `CLAUDE.md` | Engineering invariants and working rules. Read before writing code. |
| `docs/BIBLE.md` | Design reasoning — the world, markets, agents, player arc. Why things are the way they are. |
| `docs/seed-data.md` | Locations, commodities, modules. The numbers everything descends from. |
| `docs/DECISIONS.md` | Every call made on what the above left ambiguous, contradictory or unset. |
| `docs/DESIGN-LANGUAGE.md` | The lunarark.com visual system, as tokens. What `web/` gets built against. |
| `orbital/README.md` | The transfer service: accuracy, how to build a table, how to run it. |
| `market/README.md` | The ledger and order books: why conservation is structural. |
| `sim/README.md` | The world tick: price formation, the macro loop, the v1 roster. |
| `docs/DEPLOY.md` | Putting the world on a server, step by step. |

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

Python 3.11 or 3.12. **Not 3.13+ yet** — `lamberthub` needs `numba`, which
lags new Python releases. The `market/` package has no such constraint.

macOS and Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './orbital[offline,serve,dev]' -e './market[dev]' \
    -e './sim[dev]' -e './voice[dev]' -e './api[dev]'
.venv/bin/python -m pytest -q
```

Windows, **Git Bash** — forward slashes, but the Windows `Scripts` folder.
Backslashes are escape characters in bash and will silently mangle the path:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e "./orbital[offline,serve,dev]" -e "./market[dev]" -e "./sim[dev]" -e "./voice[dev]" -e "./api[dev]"
.venv/Scripts/python -m pytest -q
```

Windows, **PowerShell**:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".\orbital[offline,serve,dev]" -e ".\market[dev]" -e ".\sim[dev]" -e ".\voice[dev]" -e ".\api[dev]"
.venv\Scripts\python -m pytest -q
```

## Play it

```bash
SOLAR_DB=data/world.db .venv/bin/python -m api
```

Open http://127.0.0.1:8000. The first start runs a game week of history
(about ten seconds) so the markets have prices; after that the world keeps
time with the wall clock, one game hour per real minute, and catches up on any
hours it missed while stopped. Set `SOLAR_ACCESS_CODE` to require an
invitation code to found a company. To put it on a server, see
`docs/DEPLOY.md`.

Then, to generate and serve a transfer table (paths below are the Unix form):

```bash
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

`market/` is built: an append-only double-entry ledger where conservation is
structural rather than tested, escrowed limit order books with price-time
priority, and the Ark Authority quoting a floor and ceiling from a finite
treasury. A Hypothesis state machine checks after every step of every
generated trade sequence that nothing was created or destroyed.

`sim/` is built: the world tick, 56 agents and 6 ships across three lunar
nodes, exponential depletion, solar flares and rig failures, price formation
from inventory pressure, and freight closing the gap between ports. It
persists every tick atomically and survives restarts.

**The first playable loop exists.** Found a company, take the Ark's charter on
a Kestrel, buy where it is cheap, fly a real suborbital hop, sell where it is
dear, take supply contracts from five named characters, and come back to find
out what happened while you were away — on the real Moon, lit where the Sun
really is. `api/` serves it; `voice/` writes its letters; `web/` draws it.

Roadmap is in `docs/BIBLE.md` §10. Short version: one lunar node and one market, then ships, then the Belt, then Mars industry, then the political layer.
