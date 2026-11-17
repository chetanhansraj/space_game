# Decisions

Every open question, contradiction and missing value found in `CLAUDE.md`,
`README.md`, `docs/BIBLE.md` (renamed from `solar-economy-world-bible.md`, which is what `CLAUDE.md` and `README.md` had always pointed at) and `docs/seed-data.md`,
with the call made on it and why.

These were decided under explicit authority to make them. **Each one is
reversible.** Where a decision changes a number the design documents already
stated, the change is called out in bold and the original is recorded, so
overruling any of it is a small edit rather than an archaeology exercise.

Decisions that only affect `orbital/` are implemented. Decisions that affect
`sim/` or `market/` are recorded here and written into `docs/seed-data.md`,
but no code depends on them yet.

---

## The load-bearing three

Everything else is bookkeeping. These three set the shape of the game.

### D1 — Lambert everywhere, and the service returns a curve, not classes

**The contradiction.** The bible commits to Izzo's Lambert solver, which
computes *impulsive ballistic* arcs. But it describes trajectories in
*continuous low-thrust* terms — "a ship sustaining a few hundredths of a gee",
"a propellant cost measured in hundreds of km/s of delta-v". Those are
different physics. A constant 0.01 g burn for 20 days gives Δv = a·t ≈ 169
km/s, which is where "hundreds of km/s" comes from, and it is not a Lambert
number.

**Decision: Lambert for everything.**

The deciding argument is economic, not technical. A brachistochrone's Δv
depends on distance and time and almost nothing else. Under a continuous-thrust
model the cost of reaching Mars would barely move across the synodic cycle —
and *the entire merchant profession rests on it moving*. "Windows are prices,
not gates", the fortnightly rhythm of cheap and expensive Mars freight, bulk
iron waiting for geometry while volatiles leave immediately at four times the
fuel cost: all of that is a Lambert property. Continuous thrust would quietly
delete the core mechanic while every individual number still looked plausible.

Measured, on the implemented service, Shackleton → Tharsis Yards:

| Departure | Min-energy Δv | Δv for a 120-day crossing |
|---|---|---|
| 2028-11-16 (favourable) | 8.7 km/s | 19.9 km/s |
| 2029-12-21 (unfavourable) | 46.3 km/s | 60.8 km/s |

A **5.3× price swing from geometry alone.** That is the game, and it is now a
computed fact rather than a design aspiration. It is asserted in
`tests/test_curve.py::test_geometry_sets_price`, which fails if the ratio ever
falls below 3×.

**Corollary — the service returns a cost curve.** Not three classes. For each
departure it returns the Pareto frontier of Δv against time of flight: every
arc where nothing else is both faster and cheaper. Naming a point on it
"standard torch" lives in `sim/`.

This resolves three flagged problems at once. It keeps game concepts out of
`orbital/` as the architecture demands. It lets trajectory classes be retuned
without regenerating a single table. And it serves cases three fixed classes
cannot: a ship with an odd mass ratio, a contract with an awkward deadline, a
player who will overpay for six hours all read different points off the same
curve.

### D2 — Fusion drive exhaust velocity is 400 km/s

**The gap.** No exhaust velocity or specific impulse appears anywhere in the
documents, so Δv could not be converted to propellant mass — which makes the
bible's "3–5× baseline fuel" and "8–15× baseline" uncomputable.

**Decision: v_e = 400 km/s (Isp ≈ 40,800 s).** One constant, in one place,
tunable.

This was not picked to sound impressive. It was solved for. It is the value
that makes the bible's own transit times work:

| Crossing | Δv (best window) | Propellant fraction | Bible's claim |
|---|---|---|---|
| 20 game days | 284 km/s | 51% | "~20 days", **"roughly 8 real hours"** |
| 30 game days | 182 km/s | 37% | — |
| 60 game days | 86 km/s | 19% | standard torch |
| 120 game days | 35 km/s | 8.5% | — |
| 290 game days | 8.8 km/s | 2.2% | minimum-energy |

The 20-day crossing comes out at **7.8 real hours** against the bible's
"roughly 8 real hours". The bible's pacing numbers were right all along; they
just needed an engine specified. 400 km/s is also physically ordinary for a
fusion drive — D-He³ products are ~10⁷ m/s, so this is a few percent of
exhaust energy retained, which is what a magnetic nozzle with dilution gives.

The ratio of hard-burn to minimum-energy propellant lands at **~23×** against
the bible's stated 8–15×, and standard torch at ~8.8× against its stated 3–5×.
**I kept the transit times and let the multipliers move**, because the times
are a product decision about pacing ("dispatch in the morning, arrive by
evening") and the multipliers were a guess. `docs/seed-data.md` has been
updated.

### D3 — Sky time, and why the game is not actually set in 2190

**The gap.** The setting is "late 22nd century", but nothing said what
instant to evaluate ephemerides at. This is not cosmetic: the approximate
elements in `seed-data.md` are stamped *valid 1800–2050*, and asteroid
elements two-body-propagated 165 years accumulate errors far outside the
arcminute target.

**Decision: three separate clocks, and only one of them is fictional.**

| Clock | What it is |
|---|---|
| **real time** | wall clock |
| **sky time** | what ephemerides are evaluated at. Starts at the real launch instant, advances 60× |
| **game date** | sky time + 164 years. Displayed to players. **Never used in a computation** |

So the sky starts today and runs fast; the calendar just says 2190. Players
cannot tell, and it buys everything: kernels stay in their valid range,
asteroid elements stay near their epoch, and no accuracy is spent on fiction.

Coverage becomes a monitored expiry date rather than a surprise. DE440 (to
2650) gives ~10 real years from a 2026 launch; DE441 is effectively
unlimited. `/health` reports the window.

Implemented in `clock.py`. The 60× factor appears in that file and nowhere
else in the package, asserted by
`tests/test_determinism.py::test_the_sixty_times_factor_lives_in_exactly_one_module`.

---

## Orbital service

### D4 — Multipliers apply to propellant mass, not delta-v
"Fuel cost" in the trajectory table means propellant mass fraction. Δv and
propellant are related exponentially, so the distinction is worth a factor of
several. Baseline is the minimum-energy Lambert solution *for that pair on
that date*, not a fixed number.

### D5 — Asteroid elements come from SBDB at build time; the table is scaffolding
The seed-data asteroid table gives a, e, i, Ω, ω and period — **no mean
anomaly and no epoch.** That is five of the six elements needed; you cannot
place a body on its ellipse without the sixth. The table is unusable as
written, including for scaffolding.

`scripts/fetch_sbdb.py` pulls complete current elements and stamps the epoch
and fetch time into the transfer table's metadata.
`data/smallbody_elements.json` holds placeholder J2000 values so the code path
is exercisable offline, marked as placeholders in the file itself.

Measured two-body drift, propagating Mars from a known state (this is the
honest limit, not a hidden one): 0.4 arcsec at 30 days, 22 arcsec at 180 days,
**88 arcsec at 10 years** — outside the arcminute target. Hence refreshing.
Pinned by `tests/test_smallbody.py::test_two_body_drift_is_documented_not_denied`.

### D6 — DE440 governs; the Keplerian tables in seed-data are illustrative
`CLAUDE.md` says seed-data governs where the bible is vague, which read
literally would let a low-accuracy Keplerian table override the explicitly
committed DE440 kernel. That is not the intent. Kernel wins; seed-data's
tables are marked illustrative.

Three interchangeable backends exist, because this environment could not
reach `naif.jpl.nasa.gov` and a service that cannot be built offline is a
service that cannot be tested: `kernel` (DE440, production), `legacy`
(DE421 via pip, < 1 arcsec of DE440), `analytic` (ERFA, no data at all).
**Measured agreement between DE421 and ERFA: ≤ 15 arcsec** — four times
inside target. Two independent implementations agreeing is stronger evidence
than one implementation matching a fixture.

### D7 — Lunar surface-to-surface is a ballistic suborbital hop
The seed data had surface→LLO (1,870 m/s) and LLO→escape (700 m/s) but **no
surface-to-surface number, and all three v1 nodes are lunar surface sites** —
so the first question the service would ever be asked had no answer.

Derived, not guessed. Minimum-energy ballistic arc over central angle θ:

    v²/v_c² = 2·sin(θ/2) / (1 + sin(θ/2)),  Δv_total = 2v,  v_c = 1,680 m/s

| Route | Angle | Δv | Transit |
|---|---|---|---|
| Shackleton → Peary Ridge | 178.5° | 3,360 m/s | 54 game min (~54 real sec) |
| Shackleton → Tranquillitatis | 98.4° | 3,119 m/s | 44 game min |
| Peary Ridge → Tranquillitatis | 80.1° | 2,973 m/s | 38 game min |

Correctly cheaper than going via orbit (3,740 m/s) and converging to exactly
2·v_c at antipodal. Transit lands at "lunar hops take minutes" of real time,
matching the bible without being tuned to.

Surface → interplanetary is **2,570 m/s** (1,870 + 700).

### D8 — Accuracy tolerances, as testable numbers
"Arcminutes" is an angular target on a service returning Δv and seconds.
Made concrete: position ≤ 60 arcsec; velocity ≤ 20 m/s between backends;
Lambert ≤ 1 m/s against published cases; **launch C3 within 10% of published
mission values** (achieved: 0.0%, 0.3%, 1.7%, 5.6%).

### D15 — Precompute grid parameters
Nothing in the documents specified these. Set, and measured:

| Parameter | Value |
|---|---|
| Departure grid | every 6 sky hours (= 6 real minutes) |
| Horizon | 2 sky years (= 12.2 real days) |
| Time-of-flight sweep | 48 samples, geometric, 0.05×–1.6× Hohmann time |
| Revolutions | 0 and 1 |
| Refresh | rolling, every 6 real hours, atomic rename |

**Measured cost: 7.1M rows, ~850 MB, 48 min single-core (6 min on 8 cores).**
Queries snap to the nearest gridded departure rather than interpolating —
interpolating Δv across departures smears the sharp cost ridges that make
launch windows economically meaningful.

### D16 — Mars and asteroid gravity-well budgets *(invented — flagging loudly)*
Not in the seed data. Mars: **5,500 m/s** to escape (surface → low Mars orbit
→ escape), **1,000 m/s** to arrive (aerocapture plus powered descent). The
asymmetry is deliberate and physical: Mars has an atmosphere, so arriving is
cheap and leaving is not, which makes it a natural sink for manufactured
goods. Asteroids: escape velocity, 10–510 m/s.

These are the only numbers here I invented outright. They are in
`orbital/data/anchors.toml`, one line each.

### D17 — Anchors, not nodes
`orbital/` knows *anchors*: a body plus fixed well budgets. The game maps
"Shackleton Depot" → `luna_south` in its own config. The service has never
heard of a docking fee. This is what keeps the "no game concepts" rule true
rather than aspirational.

### D18 — SQLite, single read-only file
"No database access" means no *game* database. A generated read-only artifact
is the cache the architecture already calls for. SQLite over Parquet because
the access pattern is point lookups; over a server because there must not be
one. Written to a temp file and renamed atomically.

### D19 — Out-of-coverage returns 422, never a solve
There is no import path from the request handler to a Lambert solver.
Asserted by `tests/test_determinism.py::test_api_module_cannot_reach_a_solver`
— which caught a real violation during development, when the `Transfer` type
still lived next to the solver. It now lives in a dependency-free `costs.py`.

---

## Economy and content

Recorded here, written into `docs/seed-data.md`, not yet depended on by code.

### D9 — Ten commodities, not eight
The bible says "eight tradeable classes" and lists eight; seed-data lists ten.
**Ten.** Regolith feeds the He-3 chain and rare earths give Psyche and Pallas
a reason to exist. Bible amended. (Its commodity section had also lost its
`## 4.` heading entirely — restored.)

### D10 — The first outpost's budget, corrected
The worked example did not close, in three separate ways: the cost line
implied two radiators and a battery (2,840,000 cr, not the stated 2,700,000);
the power line's −149 kW only works with *one* radiator (two gives −153); and
the heat load of 137 kW matched neither one radiator nor two against the
stated 128.

**Corrected build:** ice miner + solar ×3 + battery + radiator ×1 + cargo
warehouse + comms relay = **2,565,000 cr**, power +150/−113, heat 95/120.

Closes exactly, comes in *cheaper* than the stated figure, and keeps the
lesson intact — the 25 kW of heat headroom means one more warm module forces
a second radiator, and that radiator's own draw is what eats the power margin.
"The constraint everyone forgets" survives.

### D11 — The first outpost sells ice, not propellant
The bible calls it "an ice extractor feeding propellant into the market", but
the seed-data build has no electrolysis plant, so it produces water ice.
Adding one (−280 kW, 1,800,000 cr) needs seven more solar arrays and roughly
doubles the cost.

**It sells ice.** This is better: raw extraction first, then buy electrolysis
and capture the 400 → 1,800 cr/t refining margin. That is exactly the
progression the bible asks for elsewhere — "refine your own ore instead of
selling it raw". The cryo tank farm is replaced by a cargo warehouse, since
there is no propellant to store yet.

### D12 — v2 is five lunar nodes
Bible says v2 adds "three lunar nodes", but v1 already ships three. Seed-data
marks Selene Station and Ark Terminus v2. **v2 = five.**

### D13 — Eros stays v3, opening first
Near-Earth, not Belt, but it is "the cheapest first claim in the game" and
makes the right tutorial for interplanetary transfer. First node to open in v3.

### D14 — All rates are game time
`400 cr/day` upkeep, `12 t/day` ice, `30 t/day` electrolysis: all **game**
days. At 60× the difference is a factor of sixty, and nothing said which.

Consequence worth surfacing: the *Kestrel* at 400 cr/game-day costs 24,000 cr
per **real** day, so 120,000 cr of starting cash is **five real days of runway
with no income.** That may be the intended pressure or may be brutal — it is a
tuning question for the first simulation run, flagged not changed.

### D20 — Prices are integer credits per trade unit
Order books quote per trade unit (tonne or kg as listed). Price formation
uses integer thousandths internally, settling in whole credits. Never floats,
per `CLAUDE.md`.

### D21 — Earth delivers to Selene Station
Earth is "a standing order on the exchange", but helium-3 is physical cargo
and had no destination. **Selene Station (low lunar orbit) is the delivery
point**, with Earth present as a standing market participant, not a node. The
700 m/s LLO→escape budget is priced into its bid.

### D22 — Docking fees are per docking event
### D23 — Helium-3 volatility stays "very high"
It is simultaneously the monetary base and the most volatile commodity, which
means the unit of account moves. Kept: the bible states the consequence
deliberately ("a helium-3 glut is a currency devaluation").

---

## Verified, not changed

Two numbers were checked and hold up.

**Helium-3 at 236,000 cr/kg.** D-He³ fusion yields ~5.87 × 10¹⁴ J/kg; at 1
credit = 1 GJ the price implies **~40% net conversion efficiency**, which is
a genuinely realistic figure. The energy-anchoring method behind the
commodity table is sound, not decorative.

**The 13-real-day Mars rhythm.** Earth–Mars synodic period is 780 days;
÷ 60 = 13 real days. Exactly as the bible claims.

---

## The Ark corpus

Added after seeing lunarark.com. These change `sim/`, not `orbital/`.

The bible said the Ark's technical corpus "functions as the tech tree" and
called it "the structural advantage no competitor has". Having now seen the
Simulation and Research pages, that is an understatement — the tree is not a
thing to be built, it already exists, with typed dependency edges and
engineering attributes on every node.

Observed: **788 nodes, 2,575 links, depth L4**, 8 functional clusters, 25 L1
subsystems under the `L0-ARK` root. Nodes carry an ID (`L1-CDH`), a type, a
status, a research-confidence percentage, prose, and real engineering
attributes — Command & Data Handling is *85 kg, 150 W, 2,000 MIPS, rated to
300 krad*. Edges are typed `DEPENDS ON` or `SHARED TECH` and carry a strength
percentage.

### D24 — The corpus graph is the tech tree, edges included

The two edge types already mean different things and should keep meaning them:

| Site edge | Game mechanic |
|---|---|
| `DEPENDS ON` | Hard prerequisite. The module cannot be built or licensed until its dependency is. This is the tech tree's spine. |
| `SHARED TECH` | Soft link. Licensing one discounts the other, because you have already paid the Ark for the underlying engineering. |

Edge **strength** (observed at 80%) sets how hard the gate is: the fraction of
a dependency's licence you must hold, and the size of the shared-tech
discount. This gives the Ark a lever it can actually pull — see D25.

That the corpus has 788 nodes at depth 4 and the game's seed data has 21
modules is not a conflict. `docs/seed-data.md` is a **coarsening**: each
buildable module maps to one L1 or L2 node, and the depth below it is what the
Ark charges for certifying. The mapping is explicit, not derived, and lives in
a table the game owns.

### D25 — Research confidence is the licence price

Every node carries a confidence percentage (Lunar Ark 85%, the CDH cluster
70%). This is the cleanest possible hook for the Ark's economic role, and it
costs nothing to implement because the number already exists:

- **High confidence** — mature engineering, cheap to license, widely held.
- **Low confidence** — speculative, expensive, and the licence is the moat.
- **`IN PROGRESS` status** — not yet licensable at any price. This is the
  frontier, and it moves when the corpus is updated.

So the Ark Council's policy lever is not an invented tariff dial. It is the
corpus itself. When a node's confidence rises, the price of everything
downstream of it falls, and every firm that had positioned on the old price
takes a hit. That is a genuine economic event generated by real work on a real
site, which is exactly the thing the bible says cannot be copied.

### D26 — Node IDs are the canonical module identifiers

`L0-ARK`, `L1-CDH`, `L1-COM`, `L1-CRY`, `L1-DST`. The game adopts these
verbatim as module IDs rather than inventing a parallel scheme. One namespace
across the codex and the economy, and a player reading a module's page on
lunarark.com is reading canon about a thing they own.

### D27 — The game reads an export, never scrapes the site

The bible says "the site is canon and the game reads from it". It should not
read it over HTTP at request time — that would put a third-party availability
dependency inside the economy, and it would let a site edit move prices with
no audit trail.

**Proposed contract.** lunarark.com publishes a versioned JSON export:

```json
{ "version": "2026-08-13",
  "nodes": [ { "id": "L1-CDH", "name": "Command & Data Handling",
               "parent": "L0-ARK", "level": 1, "cluster": "OPERATIONAL_SUPPORT",
               "status": "IN_PROGRESS", "confidence": 0.70,
               "mass_kg": 85, "power_w": 150 } ],
  "edges": [ { "from": "L1-CDH", "to": "L1-COM",
               "type": "DEPENDS_ON", "strength": 0.80 } ] }
```

The game ingests it as a **migration**, forward-only, like any other change to
a persistent world. Corpus version is recorded against every licence issued,
so a price move is always traceable to a specific corpus revision.

This is the one piece I cannot build without you: the export endpoint has to
come from the lunarark.com side. The shape above is a proposal, not a
constraint — if the underlying data is already in some other form, the
ingester bends to it.

### D28 — The Ark was founded in 2031, and that is consistent

The site gives the Ark a target date of 2031 and describes it as "designed for
1000 years of operation without human input". D3 puts the game's displayed
calendar at 2190. So the Ark is 159 years old when the player meets it, still
running, well inside its design life — and the bible's description of it as
"the institution that outlived its own founding purpose" is exact rather than
approximate. No adjustment needed anywhere. Worth writing down because it
looked like it might be a contradiction and is not.

### D29 — Shackleton Depot moves to the canonical coordinates

The site places the Ark at **89.54°S, 0.00°E** on the Shackleton Crater rim.
`orbital/data/anchors.toml` had 89.9°S from a rough reading of "lunar south
pole". Corrected to the canon value. It moves the hop delta-v by a few m/s
and matters not at all numerically, but the game's south-pole node and the
codex's Ark site should not be at different latitudes.

---

## Market and ledger

Implemented in `market/`. See `market/README.md`.

### D30 — Conservation is structural, not tested

Every economic event is a set of postings summing to zero per asset, and a
transaction that does not balance is rejected before it is written. Value
enters and leaves only through four named world accounts — `world:genesis`,
`world:sink`, `world:extraction`, `world:consumption` — which sit on the same
ledger as everyone else, so every credit ever created and destroyed is a
query rather than an estimate.

This matters more than it sounds. CLAUDE.md asks for property tests asserting
conservation; a test can only catch a leak after someone writes one. Making
the ledger reject unbalanced writes means the leak cannot be written in the
first place, by present or future code. The property tests then check that
nothing has subverted the structure, which is a much stronger position.

No balance is stored anywhere. Balances are summed from postings on every
read, because a cached balance is a second source of truth that eventually
disagrees with the first and gives you no way to tell which is right.
`UPDATE` and `DELETE` on the ledger are blocked by database triggers rather
than by convention.

### D31 — Orders are priced per lot and sized in whole lots

Two CLAUDE.md rules conflict: money is integer credits, and mass is stored in
kilograms. Regolith at 150 cr/tonne is 0.15 cr/kg, so one kilogram has no
integer price and a market that quietly rounds it invents or destroys value on
every fill.

Resolved the way real commodity markets do. A lot is a tonne for bulk goods
and a kilogram for platinum group metals and helium-3, matching the trade-unit
column already in `docs/seed-data.md`. Quantities are still *stored* in
kilograms as CLAUDE.md requires, constrained to whole multiples of the lot
mass, so cost is an integer multiplication and the kg conversion is exact in
both directions. **There is no float in the package and no rounding anywhere.**
A calculation that cannot be done exactly in integers is refused.

### D32 — Escrow is a ledger account per order

A resting bid holds its credits and a resting ask holds its goods, from the
moment the order is placed, in an account named for that order. Nothing can be
promised twice; cancelling returns exactly what is left; and because escrow is
ordinary accounts, it is covered by conservation like everything else. A
property test asserts every closed order's escrow ends at exactly zero.

### D33 — The Ark Authority quotes 60% / 175%, from a finite treasury
*(`seed-data.md` listed the spread as an open value)*

Bid at 60% of seed base value, ask at 175% — roughly a 3× spread, wide enough
that any serious quote beats it, tight enough that day-one prices mean
something.

**The treasury is finite, and that is a correction to the bible.** "It will
always buy at a floor and always sell at a ceiling" read literally means
unlimited credits, which is a printing press wearing an institution's clothes
and squarely against invariant 3. So the Authority is funded once from genesis
in a single auditable transaction and trades against real holdings from then
on. Drain it and the floor thins and then vanishes — a genuine economic event,
and everyone who sold into it was paid with real money the whole way down.

It gets no special case in the matching engine: it is an ordinary
institutional account placing ordinary escrowed limit orders, so anyone
quoting inside its spread is hit first by price priority. That is the
mechanism by which "the training wheels dissolve on their own" actually works.
`share_of_volume()` is the number to watch.

### D34 — The resting order sets the price

An aggressor that crosses the spread pays what is already on the book, not its
own limit. A buyer whose limit was generous escrowed at that limit and gets
the difference refunded on each fill. Standard exchange behaviour, and the
alternative rewards aggression with a worse price for no reason.

### D35 — Self-trading is skipped, not rejected

One account per person is an invariant, so an account matching its own resting
order can only be wash trading — manufacturing a price history to sell into.
Skipping rather than rejecting can briefly leave a crossed book if one account
holds both sides, which is harmless and clears the moment anyone else trades.
A test covers exactly that.

### D36 — SQLite, forward-only migrations

Real transactions, no server, and inspectable from a shell at 2am against a
live economy — which CLAUDE.md explicitly asks for. Every money movement
happens inside one `BEGIN IMMEDIATE` transaction, so a failure mid-settlement
leaves the world exactly as it was; a test raises an exception halfway through
a transfer and asserts nothing moved. The SQL is kept plain enough to move to
Postgres when concurrency demands it.

Migrations only go forward. There is no downgrade path, because the world is
persistent and cannot be reset once live. If a migration is wrong, the fix is
another migration.

---

## First simulation findings

`docs/seed-data.md` says its numbers "will be wrong after the first simulation
run, and that is expected. Tune by simulation, not by argument." This is that
run — 400 ticks of `scripts/demo_market.py`, seed 20260904. The agents are
deliberately stupid, so treat these as signals about the *design*, not as
balance conclusions.

### F1 — The Authority is genuinely two-sided, on a long timescale

The propellant book told a complete economic story with nobody steering it:

| Ticks | What happened |
|---|---|
| 1–50 | Propellant scarce, price climbs to 3,150 — the Authority's ceiling — and pins there. It sells into the spike; its inventory drains 400 t → 113 t. |
| 50–100 | Inventory exhausted. The ceiling stops being defended and the price comes off it: 3,150 → 2,707. |
| 100–300 | Both haulers go bankrupt. Demand collapses. Refineries keep producing into it. Price falls 2,707 → 1,225. |
| 300–400 | Price hits 1,080 — the Authority's *floor* — and stops dead. It starts buying. Inventory recovers 48 t → 396 t. |

So the Authority round-tripped: seller at the ceiling, buyer at the floor,
inventory 400 → 48 → 396. That is exactly what the bible asks of it, arriving
without any special-casing. It answers the v1 question — *"can you watch this
market for ten minutes and find it interesting?"* — more convincingly than any
argument could.

### F2 — Ice is a one-way valve, and this one needs a decision

Authority ice inventory over the same run: 2,000 → 2,587 → 4,157 → 5,600 →
7,682 t, climbing monotonically and showing no sign of stopping.

The cause is structural, not a tuning issue. Ice settles near 250 against a
240 floor and a 700 ceiling, so the market sits hard against the bid: the
Authority buys constantly and its ask never fills. **A fixed spread anchored
to a seed value only ever trades on whichever side the market has drifted
to.** Whenever the settled price is far from the seed value, the Authority
stops being a market maker and becomes a subsidy in one direction.

Partly a demo artifact — there is no depletion here, so three miners dig at a
constant rate forever, and the bible's "richness falls as it is worked" would
throttle the oversupply. But not entirely: the same asymmetry will appear for
any commodity whose real price settles far from its seed anchor.

Three ways out, not yet chosen:

1. **Leave it.** Accept that the Authority accumulates gluts. It has finite
   credits (D33), so it self-limits eventually — it just does so by going
   broke rather than by balancing.
2. **Anchor the spread to a slow moving average of traded price** rather than
   the seed value, so it straddles the actual market and recycles inventory.
   Departs from the bible's fixed floor and ceiling.
3. **Cap inventory per commodity.** It stops bidding once it holds more than
   N lots. Simplest, keeps the fixed spread, and makes the floor visibly
   thin under a sustained glut — which is itself good drama.

### F3 — Bankruptcy is terminal, and nothing in the design says what happens next

Both haulers went insolvent around tick 76 and stayed insolvent for the
remaining 320 ticks: unable to pay docking fees, unable to buy propellant,
present in the world but economically dead.

The ledger handled it correctly — it refuses to let any account go negative,
so the fee simply fails. But the bible has no answer for what happens to a
firm that runs out of money. Without one, the agent population only ever
shrinks, and a long-running world slowly empties.

This needs a design decision before `sim/` ships bulk agents: liquidation and
replacement, a credit line, a floor income, or something else. Flagging, not
choosing — this one is properly a game-design question rather than an
engineering one.

---

## Failure and re-entry

### D37 — A bankrupt firm is liquidated, and its owner becomes crew

*Answers F3. Decided by Chetan; this supersedes the "the Ark capitalises a
replacement" proposal, which was worse — it removed the person from the world
and made the institution a charity.*

Three separate mechanisms, because bankruptcy means different things to a
player, to an agent, and to the assets:

**1. The estate is auctioned.** A firm that cannot meet its obligations is
wound up. Its cargo, and later its ships and claims, are sold into the live
order book at whatever the market will pay — no special-case pricing, no
institutional bailout. Proceeds settle debts in order; anything left over is
written off. Banks, rival firms and players bid like anyone else, so a
bankruptcy is a *buying opportunity* for whoever has capital and nerve, which
is how it works in the real economy and is more interesting than a reset.

**2. The owner becomes crew, and earns their way back.** This is the part that
matters. Losing your ship does not end your run: you take a berth on someone
else's, draw a wage, and rebuild. The arc has a floor, not a cliff.

That single change makes the whole risk curve playable. A player can take a
genuinely dangerous position — a leveraged bet on volatiles, a Belt run with
too little margin — knowing that the downside is *demotion*, not deletion.
Games where ruin is terminal teach people not to gamble, and this economy is
uninteresting if nobody gambles.

It also creates a labour market, which the bible half-implies without ever
saying: crew wages already appear in the sinks list, and "hired crew" appears
in the Operator arc. This closes the loop by making wages someone's income.

**Accounting consequence, and it needs care.** The bible lists crew wages as a
*sink* — money leaving the world. That is only true for crew who are not
modelled. So: wages paid to unmodelled bulk crew are a sink and drain to
``world:sink``; wages paid to a player or a named agent are an ordinary
transfer between accounts. Both are real money from an employer who earned it
selling cargo, so invariant 3 holds either way, but they post differently and
conflating them would quietly break invariant 7.

**3. Agent population regenerates from success, not from charity.** In v1
there are no ships and no players, so the crew route does not yet exist. The
agent population still has to stay non-decreasing or a long-running world
empties itself.

Rather than minting capital for new entrants, **a prosperous firm spins off a
competitor out of its own balance sheet** once it exceeds a wealth threshold.
No credits are created, and it is self-balancing in a pleasing way:
concentration produces new entrants, new entrants produce competition,
competition erodes concentration. Wealth that would otherwise pool into a
single dominant agent gets recycled into the thing that constrains it.

**Sequencing.** Part 1 and part 3 ship with `sim/` in v1. Part 2 needs ships
and crew, so it lands with v3 — but the design is fixed now, because it
changes how risk should be tuned everywhere before then.

---

## Simulation

Implemented in `sim/`. All three were listed as open values in
`docs/seed-data.md`.

### D38 — Depletion is exponential in cumulative mass

`richness(x) = exp(-x / scale)`, with `scale` the mass that drops output to
1/e. Exponential rather than hyperbolic because the tail is the point: a
hyperbolic curve leaves a worked-out rock limping along at 10% forever, which
keeps marginal supply on the market and blunts exactly the pressure meant to
push players outward.

Scale is set so a rig at nameplate halves its yield after ~173 game days,
which is the bible's own "a rock that has been mined for six months yields
less per hour than it did on day one". Lunar ice deposits are 3,000 t;
regolith 100,000 t. Below 5% richness a site is abandoned.

### D39 — Two shocks in v1, at these frequencies

Solar flares halt surface work: ~1 per 30 game days (about two per real day),
lasting 6–18 game hours. Rig failures: ~1 per firm per 60 game days, 12–48
game hours, 25,000 cr to repair. Both are named explicitly in the bible;
convoy loss, claim expiry, policy changes and cartel formation all need
systems that do not exist yet.

Every roll is a pure function of (world seed, tick, stream name), so a shock
is replayable without simulating the ticks before it.

### D40 — The money supply is Earth's faucet against the sinks

Nothing in the design documents states this, and it is the most consequential
number in the game.

**Credits enter the world in exactly one place**: Earth's standing order,
buying helium-3 at its seed anchor. **They leave in exactly one place**: the
sinks. Genesis funding aside, those two flows *are* the money supply, and the
ratio between them decides whether the economy inflates, deflates, or holds.

Earth's bid also denominates everything else. Helium-3's seed value is what
Earth pays; every other commodity is priced against it through the energy
anchor. Earth is not one participant among many — it is the unit of account.

Because seed-data gives no upkeep figures for installations (its only anchor
is the Kestrel at 400 cr/game-day), the per-firm upkeep in `sim/seed_world.py`
is invented, and scaled by an explicit dial to hold the ratio near 1.0. That
dial is a tuning parameter, not a discovered constant, and it is the first
thing to revisit whenever the roster changes.

---

## Simulation findings, second run

### F4 — The first world was quietly deflationary

Measured over 360 ticks: Earth injected 566,000 cr per game day against
942,000 cr of sinks. **A ratio of 0.52** — the economy draining itself, with
the firms' 66 million in capital exhausted in roughly 145 game days, or about
two and a half real days.

Nothing would have looked wrong. Prices were stable and near their anchors,
no firm was insolvent, conservation held on every tick. The world was simply
running down, and it would have taken days of watching to notice.

Scaling upkeep to a 0.98 ratio fixes it for this roster. The general lesson is
D40: **this ratio needs a permanent readout**, because it is invisible in
every other metric and it decides whether the world has a future.

### F5 — Three bugs that only an integration test could find

Recorded because each was invisible to unit tests and each looked like an
economic fact until traced.

**Agents stacked orders instead of refreshing them.** A resting bid escrows
its credits, so a firm re-bidding its full shortfall every hour escrowed the
same purchase again and again. The helium-3 separators bled 201,066 cr an
hour against an expected 6,667, and were wound up with 5.8 million credits
still on their balance sheet — almost all of it locked behind orders they had
already placed. Agents now cancel before they quote.

**A reference price with no anchor ratchets without limit.** With the last
trade as the sole reference, a market where most firms are short walks upward
forever: each deficit buyer bids above the last print, that print becomes the
next reference. Ice reached 1,670 against a 400 anchor and was still climbing.
The fix was already specified and unused — seed-data says volatility *is* the
mean-reversion strength, so the reference is now the last trade blended back
toward the seed anchor, weighted inversely to volatility.

**Rounding production to trading lots silently deletes whole industries.** A
separator yields 0.6 kg of helium-3 from 400 tonnes of regolith, which is
0.025 kg an hour. Rounded to a 1 kg lot every tick, that is zero, forever —
so the world's only source of credits produced nothing and nothing else was
visibly wrong. Mass is stored in kilograms and only *orders* need whole lots,
so production no longer rounds, and the sub-kilogram remainder is carried
between ticks rather than discarded.

---

## Ships and freight

### D41 — Kestrel dry mass 30 t, tank 40 t
*`seed-data.md` gave the hold, crew and upkeep, and nothing else.*

Chosen so the tradeoff bites at the right place. A fully loaded Kestrel has
181 km/s of delta-v and an empty one 339, which means a favourable 30-day Mars
crossing at 182 km/s is *just* reachable and costs 40 t of propellant to carry
39.8 t of cargo — the ship is at its limit and knows it. The same run at 120
days costs 6.5 t and carries a full hold.

Nothing enforces the bible's "no strictly best ship, only ships suited to
particular routes". It is the rocket equation: a tonne of propellant is a
tonne that is not cargo, so range and payload are one quantity spent two ways.

### D42 — Fuel is a stock the ship carries, not a purchase at departure

This looked like an implementation detail and is a design decision. Peary
Ridge produces no propellant, so under a buy-at-departure model every hauler
based there was permanently stranded: it could never buy the fuel it needed
to reach the only place selling fuel. Ships now fill up where they can and
spend the tank where they must.

The same mistake in another form: propellant was excluded from haulable cargo,
on the reasoning that a ship hauling fuel to fund a trip to buy fuel is a loop
with no cargo in it. Wrong — freight to a place that cannot make its own fuel
is most of what freight is *for*. Propellant now flows Shackleton to Peary and
ice flows back, which is a two-way route nobody designed.

---

## Simulation findings, third run: freight

### F6 — Price formation has a stability condition, and I had it backwards

The most consequential thing found so far.

A short buyer bids `ref × (1 + e)`. That print becomes the next reference,
pulled back toward the seed anchor by `r`. Iterating:

    ref' = ref × (1 + e) × (1 - r) + anchor × r

which converges **only when `(1 + e)(1 - r) < 1`**, that is:

    r > e / (1 + e)

Below that threshold there is no equilibrium price at all. The market does not
oscillate or overshoot — it walks away and never comes back.

The original reversion values were chosen on the intuition that a volatile
commodity should be "free to roam", so reversion ran *inverse* to elasticity.
That is exactly wrong. Propellant, at elasticity 0.35, needed reversion above
0.259 and had 0.12. Helium-3 needed 0.333 and had 0.06. Both were divergent by
construction.

**How it presented**: propellant at Peary Ridge reached 18,018 credits against
an 1,800 anchor and then froze at precisely that number for three hundred
ticks. The frozen price was the last trade before the market died — nothing
could afford a bid, so nothing traded, so the price never moved again. Every
other indicator looked healthy: conservation held, no firm was insolvent, the
other books were fine.

Reversion now rises with elasticity, sits a clear 0.10 above the threshold for
every class, and `test_pricing.py` asserts the condition rather than the
values. Volatility still produces bigger per-trade swings — that is what
elasticity does — but a market that swings harder needs a shorter leash.

### F7 — Freight closes the gap it feeds on, and stops

The prediction was that arbitrage would narrow the ice spread toward the cost
of the run without collapsing it. Measured over 600 ticks:

| | Shackleton | Peary | gap |
|---|---|---|---|
| No ships | 657 | 333 | **1.97×** |
| Six Kestrels | ~430 | ~348 | **1.23×** |

Which is the merchant profession working exactly as the bible describes it,
and it settles rather than running to parity — freight is not free, so a gap
survives. `test_haulage.py` asserts both halves: the gap must narrow, and it
must stay above 1.02.

Propellant at Peary holds a standing premium of roughly 3× the anchor, because
it is a node that cannot make its own fuel. That is not a defect. It is what
pays for the freight.

---

## Direction

### D43 — The solar system is rendered, and the domains are windows onto one world

*Decided by Chetan. Recorded in full in `docs/VISION.md`.*

The bible said *"Not a rendered solar system. Orbits are solved, not drawn,"*
and treated a 3D view as an optional skin to come later. That line was written
defensively, as a guard against building a flight simulator before an economy.
The economy now exists, and the direction has changed: the solar system is
drawn, explorable down to real terrain, with the camera moving and the player
never piloting.

The physics does not change. `orbital/` still solves; the renderer only shows
where things are. Invariant 6 is untouched.

The domains are windows onto one shared world — one server, one ledger, one
clock — and map onto the bible's four institutions: lunarark.com and the Ark
Council, asteroidbelt.app and the Belt Claims Registry, marsbase.app and the
Mars Industrial Board, helium3.app and the Helium Cartel. helium3.app is the
exchange rather than a region. lunarark.ai is the Archivist, which is voice
only and never a cause of any economic change (invariant 2).

---

## The first playable loop

Everything below was decided under the delegated authority of D43 onward,
while building the first version a person can actually play. **Invented**
marks a number with no source in the design documents.

### D44 — New companies are staked by a finite Ark development fund

`seed-data.md` gives a new player 120,000 cr and a Kestrel, and says nothing
about where either comes from. Minting 120,000 cr per signup would make every
new account a credit faucet, which is invariant 3's failure in its purest form.

So the Ark has a **development office**, funded once at world creation from
genesis in a single auditable transaction — **30,000,000 cr and 10,000 t of
propellant** (*invented*: 250 companies' worth). A new company's 120,000 cr and
full 40 t tank are transfers out of it. When it runs out, the charter office
closes and signup says so. The Kestrel is *chartered* from the Ark rather than
owned, which is why no credit is spent creating it.

The matching sinks, per invariant 7: the Kestrel's **400 cr/day charter fee**
(the seed-data upkeep, taken at game midnight) and **docking fees, prepaid at
launch** so an arrival can never fail for want of money. A fee that cannot be
paid is recorded as owed and grounds the ship until settled; the ledger never
goes negative and the charge becomes a ledger entry only when paid.

### D45 — Player orders are immediate-or-cancel in v1

A player's buy or sell fills against the book now, up to their limit, and any
remainder is cancelled. Players are offline most of the time; a resting order
left while they sleep is escrow they forgot about, and a stale bid that fills
at 3am is a support ticket. Standing orders are the bible's design and come
back with the standing-instruction editor, where they can be shown and managed.

### D46 — Supply contracts: firms that are short say so, with the money down

The bible's first act is a named agent writing with "two or three things the
player could take on." Those are supply contracts:

- Posted by a consumer or refiner that is genuinely short of a tonne-lot good,
  checked every 6 ticks with a 50% chance per port, at most 3 open per port.
- Priced at the local going rate **+12%** for certainty of supply, sized 8–30 t,
  with a **72 game-hour** deadline (72 real minutes). *All invented.*
- The payment is **escrowed at posting** from the issuer's own account, and an
  issuer never commits more than a fifth of its cash. Expiry returns it.
- Only goods that can be bought at *another* port are asked for, and never for
  less than 5,000 cr — see F8.
- Goods must be **carried**: delivery happens on docking, or by hand for goods
  that came in aboard. Goods bought at the issuer's own door do not count,
  or the premium would be a free 12% on anything sold locally.

Players take contracts; agents do not, yet. An untaken contract expires and
the issuer stays short, which is what happens to a firm nobody will supply.

### D47 — The world is saved every tick, and a tick is all-or-nothing

The ledger always persisted itself. The rest — firms, deposits, ships, weather
— is now one JSON snapshot written in the **same transaction** as the tick that
produced it, so the two can never disagree about which hour it is. Transactions
nest as savepoints: an order refused inside a tick leaves no trace, while a
tick that fails rolls back completely, in the database and in memory. A server
killed mid-hour loses the hour cleanly and runs it again.

On start-up the world runs every hour the wall clock says it missed, however
many. There is no cap: offline is absent, not paused. A new world runs **one
game week** (168 ticks, *invented*) of real history before it opens, with its
clock started that far back, because at tick zero the only propellant for sale
is the Ark's ceiling (F8).

Balances read from a **checkpoint** plus the postings since it (market
migration 3). The checkpoint is derived, written only from postings, and
verifiable at any time; the property tests take checkpoints at random points
and require every balance to equal the raw sum.

### D48 — Access is a key and an invitation code, for now

A company signs in with a random key, shown once and stored only as a hash.
Founding a company needs `SOLAR_ACCESS_CODE` when it is set, and one address
may found three per hour.

**This does not satisfy invariant 8** (one account per person). It slows a
script down; it does not stop a person with two browsers. Real identity —
email verification at minimum, ideally a sign-in the person already has — is
required before the world is open to the public. Until then the access code is
the gate, and the development fund's finiteness bounds the damage.

### D49 — One server, one process, SQLite, at play.lunarark.com

The world runs as a single process holding one SQLite connection behind one
lock, with a ticker thread keeping it on the clock. At this scale a tick costs
about 30 ms, and a single writer makes the concurrency story one sentence long.
It must never run as two workers: that would be two worlds.

It is served at `play.lunarark.com` — the Moon's domain, since v1 is the Moon,
on a subdomain so the research codex keeps its own front page (VISION.md, open
questions). `docs/DEPLOY.md` has the steps.

**Known limit:** the append-only ledger grows about **150 MB per real day**,
almost all of it agents' cancel-and-replace quotes. Months of playtest fit on
a VPS; a public world does not. Before launch this needs a design — most
likely closing each game month into an archived ledger file with carried-
forward balances, which keeps every entry and the ability to reconstruct any
balance, while the live file stays small.

### D50 — voice/ ships templates first, and five characters front real firms

No language model yet. Letters and the feed are templates filled from
structured facts, chosen as a pure function of the message id so a letter
reads the same every time. That is the fallback CLAUDE.md requires; built
first, a model added later can only improve the words.

Five named characters front the v1 firms — Mira Vance (Vance Propellant,
Shackleton), Sol Adeyemi (Peary Ridge Ice Cooperative), Dr Ines Halloran
(Halloran Isotopes, Tranquillitatis), Tomas Okafor (Peary Ridge settlement) and
Yusuf Brandt (Ark Development Office) — plus the Archivist. *Invented.* A
character is the face; the balance sheet is the firm's.

### D51 — On a shared server the world is a guest: capped, local, and it stops before the disk fills

Found by checking the real VPS before anything was run on it: lunarark.com's
server already serves **two** production sites (lunarark.com and kundali.app)
through nginx and certbot, on one vCPU with no swap. The Docker plan would
have stopped at the port check, and the backup plan was wrong: fourteen daily
copies of a database growing 150 MB a day fill 46 GB in about six weeks.

So on a server that already runs nginx:

- **No Docker.** The game is a systemd service in a Python 3.11 virtualenv,
  bound to `127.0.0.1`, running as its own user who can write only
  `data/`. Measured: about 80 MB of RAM, and ~30 ms of CPU a minute after an
  8-second warm-up. Capped anyway at 60% of one CPU and 600 MB, at low
  priority, so the sites beside it always win.
- **nginx and certbot as they already are.** One new server block, reloaded
  only if `nginx -t` passes (otherwise removed again), and one more
  certificate on the existing renewal schedule. Ports 80/443 and the firewall
  are not touched.
- **Backups are bounded.** Three kept, and a backup that would leave less
  than 3 GB free is skipped and logged instead.
- **The world holds rather than fill the disk.** Below `SOLAR_MIN_FREE_GB`
  (3 GB) the ticker stops advancing, logs an error every ten minutes and
  reports `holding_for_disk` on `/api/health`. This is a deliberate exception
  to invariant 5: a world that keeps writing to a full disk takes other
  people's websites down with it. When space is freed it catches up on every
  held hour, so the only cost is lateness.

### D52 — The installer never takes over what it did not create; signup fails closed

A second review, of the scripts themselves on the real server, found that the
first installer would have overwritten the lunarark.com Codex's own service.
It used the name `lunarark` for the service, the user and the folder, and the
Codex already runs as `lunarark.service` from `/opt/lunarark` — the only place
its admin token is stored. It would also have reused the Codex's `.env`
(its API keys, and no access code), and with no access code set the game
accepted every signup.

The fix is a rule, not only a rename:

- Everything the game's installer creates is named `arkgame` and lives in
  `/opt/arkgame`, and every file it writes carries a marker line.
- Before changing anything it refuses if the folder is not a clone of this
  repository, if a service, user, `.env` or nginx block with its name exists
  without its marker, or if another service or site uses its folder. Each
  case is tested against a stub server.
- `CHECK_ONLY=1` runs every check and changes nothing.
- **Signup fails closed.** With no `SOLAR_ACCESS_CODE`, the charter office is
  shut; open signup needs `SOLAR_OPEN_SIGNUP=1`, asked for by name.

### F8 — What the first playtest found

Driven in a headless browser against a live server:

- **The board asked for the impossible.** Regolith contracts at Tranquillitatis,
  the only regolith source on the Moon, for 1,915 cr against a 400 cr docking
  fee. Fixed by D46's two filters.
- **The first pilot paid the ceiling.** At tick zero the only propellant ask at
  Shackleton was the Ark's 3,150 (175% of anchor); a week later it trades at
  about 1,750. Fixed by D47's warm-up.
- **The loop pays.** Propellant bought at Shackleton for ~1,760 and sold at
  Peary Ridge for ~3,180 after one real minute of flight. That spread is the
  one the agent haulers leave on the table, and it should narrow as players
  work it — F7's prediction, now with people in it.

---

## The base: one game, two altitudes

*Direction decided by Chetan, 16 November 2026. Everything else in this
section was decided under the authority he gave for it ("I leave it to you
what is best for the game"), and every number marked invented is his to
change.*

### D53 — The arc is reversed: a company starts on the ground

The bible's arc runs contractor, speculator, owner: a ship first, and an
outpost after "roughly two good months of trading". The city builder at
sim.lunarark.com showed that the base is the part Chetan wants to play first,
and his own statement of the arc is the opposite one: *build the base, make
industries, grow that piece of land or crater, then afford ships and trade the
industrial products.* That is now the design. A base gives a company
something to sell, which is the reason to want a ship at all.

It is being built in three steps, each a complete game:

1. **This one.** Any company may take a charter on a site and run a works
   there, in the same world as its ship. Signup is unchanged, so a new company
   still gets its Kestrel and its grant as before.
2. Industry zones whose tenants are real firms, and residents who are real
   households.
3. Signup changes to land first, and the Kestrel becomes something a company
   charters out of what its base earns.

**The starter kit is leased, not granted.** The smallest works that turns a
profit on seed-data's module prices is 9.6 million credits of plant. Against a
120,000 cr stake it cannot be bought, and granting it would empty the
development fund (D44) in three companies. So the Ark keeps ownership and
charges a daily fee, exactly as it does for the Kestrel. Nothing is minted and
nothing leaves the fund.

**One site in build 1: the Shackleton rim.** Seed-data says solar gives "zero
output through lunar night unless polar", so a polar site needs no night
model, and VISION's v1 already puts "your base on Shackleton". The flats
arrive with the helium-3 licence, where a long night is the price of the
richer product.

### D54 — The site: a 24 by 24 grid, five ice patches, richer further out

*Invented.* A site is 576 tiles with boulders on about 7% of them and a clear
middle. Five patches of ice lie on a ring around it, graded 70%, 85%, 100%,
125% and 150% of nameplate, the richer ones further from the middle. The best
ice is therefore the longest conduit run, and the engineer's default layout
(`base.suggest_layout`) deliberately takes the nearest patches so that finding
the better layout is left to the player.

The ground is derived from the company's id and never stored. Each patch is a
`Deposit` with D38's ice figure, 3,000 t to 1/e, so a patch depletes exactly
as an agent's claim does and the frontier logic is one piece of code.

### D55 — Budgets: life support first, the diggers last, heat throttles

The bible gives the budgets (power, heat, crew) and the rule that a smelter
without radiators throttles. It does not say what happens when power or crew
is short. *Decided:* modules switch on in a fixed order while power and hands
last: airlock, life support and habs, then command and comms, radiators,
storage, the plant, and the ice miners last. A base that cannot run everything
keeps people breathing before it keeps mining. Short of heat rejection, the
plant and the miners throttle in proportion.

Crew are a capacity in build 1, not people: berths from powered habs, capped
by life support at 8 per unit, and none at all without an airlock. Residents
who eat and breathe arrive with build 2. *(They have: D64.)*

A base with no staffed command post runs no plant. A flare stands the plant
and the miners down, as it does every agent rig.

### D56 — Storage: a yard, a run tank, and boil-off

Seed-data gives a warehouse 2,000 t and a tank farm 800 t, and says a
liquefaction plant is "required to store propellant" with "boil-off if
underpowered". *Invented* to complete it: a bare site holds 20 t of dry stock
in the yard; each electrolysis plant has a 5 t run tank of its own, enough to
make a trading lot; a tank farm holds nothing unless a liquefaction plant is
running; and propellant held beyond capacity boils off at 2% of the excess an
hour. So a new works must sell as it makes, and holding propellant for a
better price is something you build toward.

### D57 — Dust: a solar array within two tiles of a digger gives half power

*Invented.* It is the cheapest rule that makes where things stand matter, and
it is a real problem on the real Moon. With the linking rule and the ice
grades it gives a layout three things to trade off: conduit length, ice
quality and clean arrays.

### D58 — Conduit, assembly and moving

*Invented.* Conduit is 1,000 cr a tile, bought, with no upkeep. A module takes
1, 2 or 4 game hours to assemble by size and is down for the same time when
moved; moving is free. A leased module taken down goes back to the Ark; an
owned one is scrap, with no refund, so that no credit leaves the fund through
a demolition.

### D59 — The base's money, tuned by simulation

*All invented, all dials.* Module prices are seed-data's. Seed-data gives no
running costs for installations (D40 already notes this), so:

| | | |
|---|---|---|
| Lease | 0.10% of list price per game day | burned |
| Wear, on everything standing | 0.03% of list price per game day | burned |
| Payroll | 1,500 cr per working crew per game day | to the port's households |
| Lease cap | 12,000,000 cr of plant per company | |
| Modules bought, and conduit | list price | paid into the development fund |

Charges accrue by the hour and are billed at game midnight, so there is
nothing to gain by taking plant down before the bill. What cannot be paid is
recorded as owed, the works stand down, and it settles the hour the money is
there; unpaid payroll in that case is burned with the rest rather than paid
late, which is a simplification.

Measured with `scripts/demo_base.py` on a fresh world after a week's warm-up,
propellant near 1,665 cr/t:

| Layout | Net per game day |
|---|---|
| The engineer's default, buying about a third of its ice | +21,000 cr |
| Both miners moved to the two richest patches | +27,000 cr |

That is about 1.3 to 1.6 million credits per real day, which buys one major
module a day and several small ones. It is the first number to revisit after
real play. On the live world propellant was at its 3,150 ceiling when this was
written, so the first days will pay roughly double until a player's own
supply brings the price down.

**Invariant 7's pairing:** the base adds credit inflows to a company only by
sale to real bidders and by the bonuses in D60; it adds four sinks (lease,
wear, arrears, and purchases that leave the player economy for the fund).

### D60 — Development bonuses, and what they cost the fund

*Invented.* Five milestones pay a bonus once each, as transfers out of the
development fund: command post staffed 20,000; first propellant 30,000; first
sale 30,000; thirty tonnes of ice through the plant in a day 40,000; first
module bought outright 30,000. A bonus is skipped, not owed, while the fund
cannot afford it.

**This changes D44's arithmetic.** A company can now draw up to 270,000 cr
from the fund rather than 120,000, so the 30,000,000 cr fund stakes about 110
companies rather than 250. Against that, every module a company buys pays
into the same fund.

### D61 — Stock in its own account; standing orders that never rest

A base's ice and propellant are held in a ledger account of its own,
`base:<player>`, because the Kestrel's hold is defined as everything in the
company's account (D42). Credits never rest there: a bid is funded from the
company's wallet for the length of one order and every sale is swept back in
the same transaction.

D45 keeps player orders immediate-or-cancel so that nobody leaves escrow on
the book while they sleep. A base has to trade while its owner sleeps, so its
standing orders are the same immediate-or-cancel orders placed again each
hour, with the owner's price limits. They need a running comms relay, which
is what seed-data means by "required for remote operation".

A ship docked at the base's port can load from the base and unload to it.
Goods loaded that way count as loaded at that port, so they cannot be handed
straight back as a contract delivery there.

### D62 — A base runs inside the world's hour, and cannot stop it

Each base's hour is part of the tick's transaction, in a savepoint of its own.
A base that raises loses its own hour, has it counted in `base.faults`, and
the world goes on. Without this, one bug in one company's site would stop the
clock for everyone, which invariant 5 does not allow for.

### D63 — The base screen is part of the trade client, and the city builder is the Simulator

The live base is served at `play.lunarark.com/base/` from `web/`, by the same
server and under the same key as the Moon map. Scrolling out of it rises to
the Moon; a button on the Moon goes back down. VISION's five altitudes are
joined here for the first time, by a fade rather than a continuous camera.

`city/`, at sim.lunarark.com, stays as it is: a fast, pausable game in the
browser with its own money. It cannot share the ledger, because it can be
paused and runs about 47 times faster than the shared clock (invariant 5) and
because it runs on the client (invariant 1). It is where the base's ideas are
tried at speed, and its crew (Asha, Lena, Rafael) are the voices on the live
base.

### D64 — The town and the trade game are one and the same; one universal time

*Decided by Chetan, 17 November 2026, the night the first base went live.*

The first base was built as a new works beside the trade game. That was a
misreading, and he said so: the town he has been building in the city builder
*is* the game, the market is where that town may choose to trade, and each
goes on whether or not the other is used. *"It is like I live in a town but
it is my choice if I want to trade or not."*

It was then proposed that the town keep its fast, pausable clock and meet the
world only through ships that call on world time. He rejected that with one
example: if the town can run faster than the world, a promise to deliver ore
in five days means nothing, because the town can always be run forward to
meet it. Production time is part of the deal. **So there is one universal
time, for the town as for everything else, with no speed-up and no pause**,
and the town lives on the server so that closing the tab is not a pause
either. He offered to give up both controls for it. Invariant 5 already said
this; it now covers the town by his own decision.

The base from D53 is therefore not a second game but the ground the town is
being moved onto, system by system. `city/` at sim.lunarark.com stays as the
practice mode it was called in D63.

**People are the first system moved.** A site is founded by six: the city
builder's four (Asha, Kenji, Lena, Rafael), an agronomist and a plant
operator. They never leave, so a site can always be recovered. Everyone else
comes on a daily shuttle.

*Invented:*

| | |
|---|---|
| Water | 24 kg a person a day, taken from ice in stock. A recycler leaves 15% of that (seed-data's 85%) |
| Food | 2.4 kg a person a day. A hydroponics bay grows that for six (seed-data's "feeds 6") |
| Arrivals | up to 2 a day, at game midnight, only if nobody went without air, water or food all day and there is a berth with air and a bay to feed them |
| Departures | a need unmet for 12 hours of a day sends the newest resident home; nobody stays without a berth |

Seed-data says a hydroponics bay "needs volatiles". Nothing in the v1 world
makes volatiles, so a bay runs on power and hands alone for now; that
requirement returns with the Belt.

People are not on the ledger. They are who the town can keep alive, and they
are its workforce: a module that needs crew runs only if someone lives there
to run it, with life support, the desk and the farm staffed before the plant.
A bay takes two and a life-support unit one, so roughly four people in ten
are free for industry. Industry grows only as fast as the town does.

People drink before the plant is fed, and neither the plant nor a standing
sale touches the last day of the town's water. Food goes from the bays to the
table and only a surplus reaches the ledger; counted per kilogram, a town
that grew exactly enough went hungry by rounding and nobody ever arrived.

**D56 changes with it:** a plant's run tank is 40 t, one Kestrel hold, not 5,
so that a town can make up a shipload for a promise without first building a
tank farm.

### D65 — The Ark leases to towns, not to machinery

*Invented.* The lease limit of D59 becomes 12,000,000 cr for a founding crew
plus 1,000,000 for every resident after the six, to a ceiling of 40,000,000.
The kit is now 29 modules and 10,335,000 cr of plant (a hydroponics bay and a
fourteenth solar array). A sixth bonus, 50,000 cr, is paid for a town of ten,
which takes D60's most a company can draw from the fund to 320,000 cr.

Played by a bot for 22 game days on a fresh world: the kit alone nets about
18,000 cr a game day; a town of twelve running two plants about 35,000. On
day 16 the bids for propellant at the Depot ran out altogether for three
days, and the town lost 38,000 cr a day until they returned. Nobody designed
that. It is the market answering one town's supply, and it is the reason to
build tanks, take promises and own a ship.

### D66 — Promises: supply contracts kept from the base

Chetan's example was a promise to deliver ore in five days. The world already
has that instrument (D46): a firm that is short posts a contract with the
money in escrow and a 72-hour deadline. The base screen now lists the open
contracts at other ports for goods the base makes, with what is in stock,
what a day makes and how long the flight is. A promise that is taken is held
back from the base's standing sales, loaded into the company's ship and
settled when the ship docks. D46's rule stands: goods must be carried, so a
base cannot fill a contract at its own port.

### D67 — How this is tested, and why there is no cheat code on the live world

Chetan suggested a cheat code that speeds the world clock up for testing.
The tests do exactly that, but not on the live world: `scripts/demo_base.py`
and the test suite step a private world as fast as the machine allows, and
the browser checks run against a local server ticking every second or two.
The live world has no such switch. One that existed could be found, and a
clock that can be run forward is the thing D64 was decided to prevent.

### D68 — Towns run by agents

*Direction from Chetan, not yet built.* Agents will run towns of their own,
so that the Moon has an economy for people to join. Two rules are fixed now.
An agent's town is an ordinary company: same charter, same lease, same
ledger, no grants a player cannot get (invariant 3). And invariant 2 holds:
an agent that decides with a language model acts through the same API a
player does, from outside the tick; nothing inside `sim/` asks a model
anything.

### D69 — The town is the city builder itself, run on the server

Chetan's correction after the Shackleton works went live: the settlement
game he designed is the game, and the trading world is the market it may
use. So the town is not a second, smaller base written in Python. It is the
city builder's own rules (`city/src/sim/`), bundled to one file
(`sim/src/sim/town_engine.js`) and run inside the world tick by an embedded
JavaScript engine (`mini-racer`, a pip wheel, nothing to install on the
server by hand).

Porting the rules to Python was the alternative. It was refused because
there would then be two copies of about three thousand lines of tuned rules,
and the practice game at sim.lunarark.com would drift from the live one
within weeks. One source, two builds.

What keeps the invariants: the engine is handed a state and a wallet and
returns a state and a wallet, as text. It has no database, no network and no
clock. It runs with a four-second and 256 MB limit, its context is thrown
away on any failure, and each town's hour is in its own savepoint (D62), so
a town that breaks loses that hour and the world goes on. The rules are
deterministic from the town's seed (invariant 2 is untouched: no model is
involved anywhere). The requests a player may send are the seven the game
already had (place, zone, demolish, toggle, repair, price, offer) and
anything else is refused before the rules see it.

The site is the equatorial plot the city builder always had, on Mare
Tranquillitatis, so the town has a real lunar night: 354 game hours of it,
nearly six real hours on the world's clock.

### D70 — The town's money is the company's money

*Invented, and mine to defend.* One town credit is 1,000 cr. The city
builder's prices then sit where a new company's stake does: a solar array is
12,000 cr, a habitat 30,000 cr. The Ark's development fund pays 40,000 cr
when a town is founded, so a new company starts its town with the 160 town
credits the game was balanced for (120,000 cr stake plus the grant).

The town has no purse of its own. Before its rules run they are handed the
company's balance; afterwards the difference is posted:

- What the rules pay the town on a tick (mission payments, fares, rents,
  contracts with agencies and companies, what Earth pays for foundry
  output) is paid out of Earth's account, the one faucet (D40), and only
  while Earth can pay. Nothing is minted (invariant 3).
- What the rules charge the town on a tick (supplies, upkeep, penalties,
  evacuations) is burned. That is the sink for the line above
  (invariant 7).
- What is spent building goes to the Ark's development fund, and a
  demolition refund comes back out of it.
- A town may run into debt and the ledger may not go below zero, so what a
  town cannot pay is recorded as owed and taken first from whatever the
  company earns next. Fractions of a credit are carried, never rounded away.

What this does not do yet, said plainly: the town's income is still the city
builder's own, paid by Earth. Its foundries do not yet put real cargo into
the market's order books. That is the next build, and it is the one that
makes town and market one economy instead of one wallet. *Done since, for
the foundries: D76.*

### D71 — Trade opens when the town can support it

Chetan's rule: only when the town reaches a decent level can it trade. The
level is a working landing pad and eight people. *The number eight is
invented.* The town page keeps its Moon button locked until then and says
why.

This is a lock on the door, not on the building. A company's ship and the
exchange are still reachable from the Moon page by anyone who goes there
directly, because every company that existed before towns did must keep
working. Making the gate hard on the server, for companies founded from now
on, belongs with land-first signup.

### D72 — A town left alone can be lost, and can be founded again

Chetan: "people need to take care of their base no matter if they play or
not." The town runs every hour whether its owner is there or not (D64), and
the city builder's own rule stands: when the last of the crew is gone the
town has fallen silent. The owner gets a letter and the world record says
so. They may send a new crew to the same land. The new crew starts from the
lander with whatever the company has left; there is no second grant, so what
was built and lost is the price.

Measured on a private world: a new town with nothing built is lost in about
200 game hours (a little over three real hours), because the lander's air
lasts 160. A grown town of 81 people left with no orders for two lunar days
(about a real day) was still alive with 56 people and had earned money. So
the danger is the first sitting, not the absence.

### D73 — A caretaker for hire

*Direction from Chetan, not yet built.* A player may buy an agent from the
game to look after the town while they are away. Fixed now, so that it is
built the right way round: the caretaker is deterministic code acting
through the same seven requests a player has (invariants 1 and 2), its fee
is a real payment that leaves the world (invariant 7), and it keeps the town
alive, it does not grow it. A town that plays itself is not a game.
*Built since: D79.*

### F9 — The Moon's own firms did not last, and nobody was told

*Found on the live world on 17 November 2026, day 49, while looking for
someone to sell a town's goods to.*

Every producing firm on the live Moon is bankrupt: all the ice miners, the
propellant plants, the helium-3 separators, the six haulers and the traders.
Eighty insolvencies between tick 721 and tick 39,913. The last one failed
about three real weeks before it was noticed. What is left is 65 settlement
households holding 7.3 million credits between them with no wages coming in,
the households at two of the three ports with under 4,000 credits between
them, and one company
(the first, from September) with nothing and a million credits of arrears.
Earth still holds 1,765 million of its 2,000 million and has had nothing to
buy since the separators stopped.

A private world built from the same seed does the same, quickly. The polar
ice miners are gone by game day 100 with their deposits still about 80 per
cent rich, so that is not depletion. The Shackleton propellant plants follow
by day 200. On the Flats the regolith miners multiply to 37 by day 400 while
three of the four separators fail, then the claim they share falls to the
5 per cent at which it is abandoned by day 600, and by day 900 there is not
one producer left on the Moon. On the 60x clock that whole story takes
fifteen real days.

So "the trading world goes on with its bots whether you trade or not" has
not been true for most of the time the server has been up. Two causes, and
they need different answers: the firms' prices and costs do not balance
(the early deaths), and nothing ever opens a new claim (the late ones).

D37 already ruled out the Ark standing a replacement firm up each time one
fails, and that ruling stands. The direction Chetan has since given is that
towns, run by people and by agents, are what the Moon's economy is made of
(D68). That is the repair. Until it is built, what a town sells is bought by
Earth's order and by what the households have left (D74, D75).

### D74 — Households buy manufactured goods, out of savings only

seed-data lists goods among what all three lunar ports consume and names no
maker nearer than Mars, so until now no agent on the Moon had ever bid for
any. A town's foundries make them (D76), and goods need a buyer who has
money of their own.

Every propellant household also uses 100 kg of goods a game day and keeps
two tonnes on hand, reordering a tonne at a time. *Both numbers are
invented.* A household burns six to eight tonnes of propellant a day, so it
is a block of a settlement and not a family; a tenth of a tonne of parts and
fittings beside that is small.

It bids for goods after it has bid for propellant, and only with credits
above its opening capital. So this demand cannot crowd out the one a
household cannot live without, by construction, and it is funded by wages
saved. On a world where firms are paying wages that is a real and growing
market: on a private world goods settled at about 75,000 cr a tonne, well
over the 45,000 anchor, because households were short of them. On the live
world there are no wages (F9) and about 400,000 cr of savings above opening
capital, so it is a few tonnes and then nothing.

A world that already exists gains the demand when it is opened. Nothing is
minted and nothing is reset.

### D75 — Earth takes twelve tonnes of lunar parts a day, at the anchor

The city builder's foundries were always "paid by Earth". D70 kept that as a
payment inside the town's rules and called it a debt. It is now a standing
bid on the order book at Tranquillitatis, where Earth already takes delivery
of helium-3: three one-tonne lots at each refresh, four refreshes a game
day, at the seed anchor of 45,000 cr a tonne. Parts and fittings for work in
Earth orbit, which cost less to lift from the Moon than from the ground.

*The cap is invented*, and it is the number that matters. Twelve tonnes a
day is 540,000 cr a day at most. The helium-3 order, when all four
separators ran, paid 4 x 0.6 kg x 236,000 = 566,400 cr a day. So the faucet
D40 describes is about as wide as it was designed to be, through a different
good, and it is finite: Earth alone carries about 38 foundry levels across
the whole Moon, which is two thriving towns. Past that, towns compete for
the bid, and what is left over waits in the yard or has to find another
buyer.

Earth pays from the account funded at genesis and buys only what it can
afford (invariant 3). The matching sink is the one that already matches
town income: supplies, upkeep and penalties are burned (invariant 7, D70).

### D76 — A town's foundries make cargo, and the town sells it

Chetan: "once I build industries and have a thriving lunar base, I can sell
goods I mine there and more people will come to live there and the town
will grow and so will the pressure to maintain."

**Making.** On a live town a foundry level makes 13 kg of manufactured
goods an hour at full staff, half as much again on ilmenite or pyroclastic
glass, twice as much on helium-3 regolith, exactly as the survey finds
always worked. *13 is invented*: at the anchor it is worth 585 credits an
hour against the 600 the practice game pays, so the town was not made
richer or poorer by the change, only real. The goods are on the ledger, in
an account of the town's own at the port (`town:<player>`), and the practice
game is untouched.

**The yard** holds 20 tonnes. *Invented*: a little under two game days of
all that Earth will take. A full yard stops the foundries and their shifts
are sent home, which the town's own rules then feel: fewer jobs, lower
rents, nobody new moving in. No company builds another foundry beside a
yard more than half full.

**Selling.** Whole tonnes, into the port's order book, to whoever bids
most, immediate or cancel (D46's rule that nothing of a player's is left
resting). By hand, or by a standing instruction that is on by default and
never sells below the anchor. Or the goods are loaded into the company's
ship and flown to where they are wanted.

**The gate.** Nothing leaves the yard until the town has a working landing
pad and eight people (D71). What is made before then waits, and is there to
sell on the morning the town opens. D71's lock was on the page; this one is
on the server.

**Growth and pressure.** These were already in the city builder and needed
no new rule, only real goods under them: foundries that are working offer
jobs, jobs bring residents, residents want homes, gardens, a concourse and
a clinic, and each of them costs more in supplies than the last. What is
new is the other direction. If the goods stop selling, the yard fills, the
foundries stop, and the town that grew on them has to be carried without
them.

**What this still does not do.** Ilmenite and glass make more of the same
goods, not iron or volatiles, because nothing on the Moon buys those yet.
Helium-3 still waits for its licence (D53). The town's ground does not run
out. And a town's supplies are still bought from Earth by formula and
burned, not bought from another town.

### D77 — The steward

The headless test has always carried a player who does what the crew asks
and then answers what the town is short of. It is the proof that the game
can be played. It now lives in `city/src/steward.ts`, acts only through the
seven requests a player has, and the engine will answer "what would a
careful player do this hour" for any town.

Nothing in the live game uses it yet. The tests use it to grow a town to
the morning it can trade. It is the caretaker Chetan asked for (D73) and
the hands of a town run by the world (D68), written once.

### D78 — A company that has been away can come back

Found on the live world (F9). Its first company owed about a million
credits of charter fees, 400 a game day for seven weeks on a ship that was
grounded the whole time. Founding a town with it would have paid the grant
in and taken all of it at the next game midnight, and then everything the
town earned at every midnight after.

Arrears stop growing at thirty game days of the fee, 12,000 cr. *Thirty is
invented.* The ship stays grounded until they are paid, so the fee still
does what it was for. Arrears were never ledger entries, so capping them
destroys nothing.

A town is founded with at least the 160 town credits the game was balanced
for. A new company gets there with the ordinary 40,000 cr grant. A company
with less is brought up to it, once, from the Ark's fund, with its capped
arrears covered. That hands an old company nothing a new one could not have
from the same fund by signing up, and a company with money still gets only
the ordinary grant.

### D79 — The caretaker is built: urgent work only, for a wage

D73 was direction. This is the thing, because without it a town founded in
a lunch break is dead by the evening, and Chetan asked for exactly this
remedy.

A company may hire a caretaker for its town, and let one go, at any time.
While one is hired, each game hour:

1. The wage is paid: 200 cr, burned. *Invented.* It is 4,800 cr a game
   day, about what a town of ten pays for its supplies, so a small town
   feels it and a large one does not. Eight real hours away costs 96 town
   credits. By D37 a wage paid to nobody who is modelled is a sink, and
   this is the sink the feature needs (invariant 7).
2. The steward (D77) is asked what is urgent, and each answer is put to the
   town's rules through the same door as a player's request. Urgent is the
   crew's own list: something broken, something not linked, air, water,
   food, shelter, and enough stored power for tonight.

It does not follow the missions, zone land to grow on, answer offers or
set prices. On the first morning of a new town nothing is urgent yet, so a
caretaker hired at founding builds nothing: it will keep a town and it will
not found one. What it builds is paid for by the town like anything else.
If the wage cannot be paid it leaves, and a letter says so.

Invariant 2 is untouched: the caretaker is the steward, deterministic code
inside the tick. Nothing asks a model anything.

Measured on a private world with the same town each time. Left after one
real hour of play: alone, lost at hour 828 (in its first night); with a
caretaker, alive with all four crew at hour 1,500, having paid 288 town
credits in wages. Left after two and a half real hours, by which time the
night was already provided for, it lived either way and the caretaker was
270 credits spent for nothing. So it is insurance, and it is priced so that
the choice is a real one.

---

## Still open — needs you

Deliberately not decided, because these are yours.

1. **The corpus export endpoint** — see D27. Everything else about the Ark
   integration is decided; this is the one piece that has to come from the
   lunarark.com side.
2. **Real design tokens.** Resolved for the game: `web/index.html` uses
   lunarark.com's own stylesheet values from `lunarark_files/` (`#030014`,
   glass `rgba(15,23,42,.6)`, violet `#8b5cf6`, cyan `#06b6d4`, Orbitron /
   Rajdhani / Space Mono). `docs/DESIGN-LANGUAGE.md` and the prototype
   terminal still carry the older eyeballed values.
7. **Real identity before a public launch** — D48. How should a person prove
   they are one person: email, a Google or Apple sign-in, something else?
8. **Ledger archival before a public launch** — D49.
3. **"Heavy hulls only"** for hard burns — undefined threshold.
5. **Starting cash against first-outpost cost** — 120,000 cr against
   2,565,000 cr, and see D14 on runway. `seed-data.md` already flags this.
6. **Depletion curve shape, Ark Authority spread, agent counts, shock
   frequency** — already listed as open in `seed-data.md`. Unchanged.
9. **The base's money** — D59 and D60. Lease and wear rates, payroll, the
   lease cap and the bonuses were all invented and tuned on a fresh world.
   Play it on the live one and say what feels too slow or too easy.
11. **The clock rate itself** — D64. One game hour a real minute was set
    for a trading game. A town on it sees a shuttle every 24 real minutes
    and, on the flats, a night of nearly six real hours. If the town feels
    slow once it is lived in, the rate can change, but for the whole world
    at once.
12. **The first sitting** — D72. On the world's clock a new crew has two
    hours forty minutes of lander air, and the first night falls about six
    real hours after founding. That is tense, which may be right, or it may
    lose people who found a town and go to dinner. Say which.
13. **The caretaker's price and powers** — D79. Built with a wage of 200 cr
    a game hour and urgent work only. Say if it should cost more, or do
    more, or need the town to reach some size before one can be hired.
14. **Eight people to trade** — D71.
15. **The Moon's firms are all dead** — F9. This is the big one. Towns
    run by agents (D68) are the repair you have pointed at, and they are
    not built. Until they are, the market a town sells into is Earth's
    order and little else, and there is no propellant being made anywhere
    for anyone's ship. Say whether agent towns are the next build.
16. **Earth's purse is finite** — D40, D75. Earth has 1,765 million credits
    left on the live world and no income. At the full twelve tonnes a day
    of goods that is about eight real weeks. Then nothing enters the world
    at all. Should Earth be an outside economy that never runs dry and is
    limited only by its appetite, or is a world that ends by design what
    you want?
17. **Thirteen kilograms, twenty tonnes, twelve tonnes a day** — D75, D76.
    Play it and say what feels too slow or too easy.
18. **What a foundry on ilmenite should make** — D76. Iron and volatiles
    are in the commodity table and nobody on the Moon buys them.
10. **Helium-3 for players** — D53. A player separator adds to the only
    faucet in the economy (D40), so it needs a licence and a royalty before
    the flats open. The size of that royalty is the decision.
