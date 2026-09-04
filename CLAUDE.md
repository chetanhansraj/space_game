# CLAUDE.md

Project instructions for this repository. Read `docs/BIBLE.md` for the design reasoning. This file holds the rules that must not be broken while implementing it.

---

## What this is

A persistent, asynchronous, multiplayer space economy. Players operate a firm: hauling cargo, speculating on commodities, and eventually owning extraction outposts across the Moon, Mars and the asteroid belt. The world is populated by autonomous agents who trade whether or not any human is online.

The product is the economy. Everything else serves it.

---

## Invariants

These are not preferences. Violating any of them breaks the game, usually silently and usually months later.

**1. The server is authoritative. Always.**
Every state change happens on the backend. The client renders and submits intent, nothing more. No game logic in the client, no trusted client input, no computed balances client-side. A shared economy with a manipulable client is dead within a month.

**2. No language model ever touches the ledger.**
Prices, inventory, transfers, settlement, depletion, agent decisions — all deterministic code over the database. LLMs generate *voice only*: agent messages, institutional statements, generated encyclopedia entries. If an LLM output can change a number in the economy, the design is wrong.

**3. Agent profit is simulated, never granted.**
Every credit paid out by an agent corporation must have been earned by that corporation selling real cargo to a real buyer at a real price. No dividends from a formula. The moment money is created from nothing, the currency dies.

**4. Transfers are read from precomputed tables, never solved on request.**
The orbital service generates transfer costs across a grid of node pairs and departure dates on a schedule. Route queries are lookups. Never call a Lambert solver in a request handler.

**5. One clock, 60×, shared by everyone.**
One real minute is one game hour. There is no per-player time rate, no pausing, no offline freeze. Ships burn, outposts produce and prices move while players are away.

**6. Patched conics, never n-body.**
Two-body arcs stitched at sphere-of-influence boundaries. Deterministic and reproducible. N-body integration buys nothing perceivable and costs determinism.

**7. Money must leave the world.**
Fuel burn, maintenance, docking fees, wages, licensing, tariffs, insurance, wear, claim renewal. When adding any feature that creates credits, identify the matching sink in the same commit.

**8. One account per person.**
Enforced at signup. Alt accounts farming themselves is the classic killer of player economies.

---

## Architecture

**`orbital/`** — standalone service. Given two bodies and a departure time, returns delta-v and transit time. No game concepts inside it. No database access. Pure computation plus a cache.

- Skyfield + JPL DE440 kernels for planetary state vectors
- JPL Small-Body Database elements for asteroid nodes
- Izzo's Lambert solver for transfer arcs
- Accuracy target is arcminutes, not milliarcseconds. Do not chase precision no player can perceive.
- **Do not use Swiss Ephemeris.** It solves geocentric apparent positions for astrology, not heliocentric state vectors, and it is AGPL-3.0 unless licensed — which under §13 would oblige us to publish the economy source to our own users.

**`sim/`** — the world tick. Agent decisions, production, consumption, depletion, price formation, shocks. Deterministic. Seeded RNG, logged seeds, reproducible from any tick.

**`market/`** — order books, settlement, escrow, the exchange, futures, equity. The most correctness-critical code in the repo. Money movements are transactional or they are bugs.

**`api/`** — thin. Validation, authorisation, and calls into `sim` and `market`. No business logic.

**`voice/`** — the only place LLM calls exist. Takes structured event data, returns text. If this service is down, the game must keep running perfectly with placeholder text.

**`web/`** — client. Rendering only.

---

## Conventions

- **Money is integer credits.** Never floats. One credit is one gigajoule of delivered energy. Trade is commonly quoted in kcr and Mcr; store base units.
- **Mass is kilograms** in the database, displayed in tonnes.
- **All times are game time**, stored as UTC instants with the conversion in one place. Never scatter the 60× factor.
- **Every economic mutation is an append-only ledger entry.** Balances are derived, never edited. If you cannot reconstruct a player's balance from the ledger, the ledger is wrong.
- **Migrations are forward-only.** The world is persistent and cannot be reset once live.

---

## Testing

- The market and ledger need property tests, not just examples. Conservation of credits across any sequence of trades is the core invariant to assert.
- The orbital service is tested against known JPL values. Pick a handful of real transfer solutions and assert against them.
- Simulation runs must be reproducible from a seed. A bug report should be replayable.

---

## Working style

- **Ask before inventing economic values.** If a number is missing from `docs/seed-data.md`, it is a design decision and not yours to guess. Flag it.
- **The bible is an argument, not a spec.** Where it is vague, the tables in `docs/seed-data.md` govern. Where both are silent, ask.
- **Prefer boring, inspectable code** in `sim/` and `market/`. Cleverness here costs more than it saves — these are the systems that will need debugging at 2am against a live economy.
- Small commits. One decision per commit, with the reasoning in the message.
