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

## Still open — needs you

Deliberately not decided, because these are yours.

1. **`lunarark.com` integration.** The network egress proxy in this
   environment blocks `lunarark.com`, `helium3.app`, `marsbase.app`,
   `asteroidbelt.app` and `lunarark.ai` outright. I could not see the styling,
   the research pages, or `moon_sim.html` — which the bible says is canon and
   the source of the module tech tree. Nothing here depends on them; the
   `sim/` module system and the entire `web/` layer will.
2. **Ship stats beyond the drive.** *Kestrel* has cargo capacity and upkeep;
   it needs dry mass, tank capacity and hull rating before D2's propellant
   fractions become playable numbers.
3. **"Heavy hulls only"** for hard burns — undefined threshold.
4. **Starting cash against first-outpost cost** — 120,000 cr against
   2,565,000 cr, and see D14 on runway. `seed-data.md` already flags this.
5. **Depletion curve shape, Ark Authority spread, agent counts, shock
   frequency** — already listed as open in `seed-data.md`. Unchanged.
