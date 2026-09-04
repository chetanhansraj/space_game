# The Solar Economy — World & Systems Bible

*Working draft v0.1. Everything here is a decision, not a suggestion. Where something is genuinely undecided it is marked OPEN.*

---

## 1. Premise

It is the late 22nd century. Fusion works, and it runs on helium-3, which Earth does not have and the Moon does. That single fact built everything else.

Earth is not in this game. It is the demand at the end of the pipe: an enormous, wealthy, resource-exhausted customer that buys helium-3 and platinum-group metals at a price that makes the entire off-world economy viable. Players never go there. Earth exists as a standing order on the exchange and as the reason anyone bothers.

Between the Moon and the Belt, something unplanned happened. What began as extraction turned into settlement, and settlement turned into an economy with its own internal logic. Fuel is refined where the ice is. Steel is smelted where the ore is. Food grows where there is gravity and nitrogen. Nobody is self-sufficient, everything is far apart, and moving mass between two points costs a known and unforgiving amount of energy.

That is the game. Not conquest, not war. Freight, prices, and the slow accumulation of capital.

**The player is a firm, not a hero.** You start with a ship and a small balance. What you become is decided by the market.

---

## 2. The four regions

Each of the four domains is a region with a monopoly on something the others cannot make. This is the engine of the whole economy: dependency is designed in, not emergent.

### The Moon — `helium3.app`
Energy. Regolith is strip-harvested for helium-3, and the polar craters are mined for water ice, which becomes propellant. Close to everything, cheap to reach, shallow gravity well. The Moon is the fuel station of the solar system and the cheapest place to launch from.

**Exports:** helium-3, propellant (LOX/LH2), oxygen, silicates and solar panels.
**Imports:** metals, volatiles (carbon, nitrogen), food, spare parts.
**Character:** industrial, crowded, established. Low margins, low risk, high volume. This is where new players are born.

### The Belt — `asteroidbelt.app`
Raw matter. Metallic asteroids for iron, nickel and platinum-group metals. Carbonaceous rocks for water and volatiles. The Belt holds most of the accessible mass in the solar system and almost none of the infrastructure.

**Exports:** iron/nickel, platinum-group metals, rare earths, volatiles, water ice.
**Imports:** everything. Fuel, food, air, parts, crew.
**Character:** far, slow, dangerous, rich. Claims are cheap and life is not. This is where fortunes are made and ships are lost.

### Mars — `marsbase.app`
Industry and life. The only place with meaningful gravity, an atmosphere to work with, and agriculture. Raw ore arrives, finished goods leave. Mars turns matter into things.

**Exports:** manufactured modules, ship components, life-support units, food, ceramics, refined alloys.
**Imports:** ore, helium-3, propellant, rare earths.
**Character:** settled, bureaucratic, expensive. Mars makes what everyone needs and charges accordingly.

### The Ark — `lunarark.com`
Knowledge. The first permanent lunar settlement, and the institution that outlived its own founding purpose. The Ark does not mine or manufacture at scale. It maintains the engineering corpus that everything else is built to: the standards, the certified designs, the technical decomposition of every system a human settlement needs.

**Exports:** blueprints, design licences, certification, arbitration, policy.
**Imports:** a cut of everyone else's revenue.
**Character:** archival, slow, quietly powerful. You cannot build a certified pressure module without an Ark licence, and the Ark decides what certification costs.

> **Production note.** The Ark's technical corpus is the existing lunarark.com decomposition. In-game it functions as the tech tree: modules unlock as their dependency chains are licensed. The site is canon and the game reads from it. This is the structural advantage no competitor has — a research tree grounded in real requirement decomposition rather than invented tiers.

---

## 3. Physical law

The world is a **graph**, not a rendered solar system. Roughly twenty nodes at maturity, six at launch.

**A node has:** a name, a parent body, a class (settlement / extraction site / depot), the commodities it produces and consumes, docking fees, and local market inventory.

**An edge is not fixed.** Delta-v and transit time between any two nodes are computed from real two-body patched-conic mechanics against the current date. Bodies move. Routes open and close.

This is committed as foundation, not a later feature, because the cost of rigour here is close to zero: solving a transfer is a pure function returning two numbers, and it runs server-side in microseconds. What is expensive is *rendering* orbits, not solving them. The game never renders them.

### Trajectory classes

Every shipment is a decision between fuel and time. Three classes, priced by physics:

| Class | Propellant cost | Mars | Ceres | Availability |
|---|---|---|---|---|
| **Minimum-energy** | Baseline | Slowest | Slowest | Favourable geometry only |
| **Standard torch** | ~9× baseline | ~20 days | ~27 days | Any time |
| **Hard burn** | ~23× baseline | ~10 days | ~14 days | Any time; heavy hulls only |

The transit times here are the design intent and are preserved exactly. The multipliers were recomputed from the implemented solver once a drive was specified, and they are larger than first guessed -- see `docs/DECISIONS.md` D2. "Cost" means propellant *mass*, not delta-v; the two differ exponentially.

Fusion changes the numbers, not the principle. A twenty-day crossing to Mars costs a few hundred km/s of delta-v against roughly nine for a minimum-energy arc, which is affordable only because a fusion torch exhausts at 400 km/s. Nobody waits 259 days for anything. Chemical-era Hohmann figures do not apply to this setting.

These are ballistic arcs, not continuous burns, and that choice is load-bearing: a constant-acceleration transfer barely notices where the planets are, and geometry setting price is the mechanic the entire merchant profession rests on. `docs/DECISIONS.md` D1.

**Windows are prices, not gates.** With a torch you can always leave. What changes with geometry is what it costs: departing against an unfavourable alignment can multiply your propellant bill several times over, and propellant is your largest operating expense.

This is why the merchant profession exists. Bulk iron on a two percent margin waits for the geometry, because fuel eats the entire profit. Volatiles into a famine leave immediately at four times the fuel cost, because the buyer is desperate and pays for it. The market moves while you are in flight and you cannot change course.

Everything that matters physically reduces to three numbers:

1. **Delta-v** determines how much of your ship's mass must be propellant rather than cargo. Long routes are expensive not because of distance but because of the fuel fraction.
2. **Transit time** determines how long your capital is locked up and unavailable. A 40-hour Belt run is 40 hours you cannot react to a price move.
3. **Mass** is the universal constraint. Cargo holds are measured in tonnes and every module has a mass, so getting anything to the Belt is the real cost of the Belt.

**Time scale: one real minute equals one game hour (60×).** There is exactly one simulation clock and everyone shares it — players, agents, markets, outposts. No player experiences a different rate from any other. If two people ran on different clocks, the faster one would buy from the slower one's past, and the economy would be dead on arrival.

At 60×, a Mars run is roughly 8 real hours and Ceres roughly 11. Dispatch in the morning, arrive by evening. Lunar hops take minutes. The Mars geometry cycle turns over every 13 real days, giving the market a fortnightly rhythm of cheap and expensive Mars freight.

**Offline is absent, not paused.** Your ships keep burning, your outposts keep extracting, and prices keep moving while you sleep. The design therefore requires standing instructions: limit orders that execute at a price, standing haulage contracts, outpost production quotas, and eventually a hired broker who acts inside rules you set. You return to an inbox describing what happened, not a frozen world that waited for you.

**Depletion is real.** Every extraction site has a finite ore body with a richness value that falls as it is worked. A rock that has been mined for six months yields less per hour than it did on day one. This is the primary reason the frontier keeps moving outward and the primary defence against price collapse.

### The orbital service

A standalone service, separate from the game backend, answering one question: what does it cost to get from A to B departing at time t?

**Stack, committed:**

- **Skyfield with JPL DE440 kernels** for planetary state vectors. MIT licensed, pure Python, returns position *and* velocity, which is what a Lambert solver needs.
- **JPL Small-Body Database elements** for asteroid nodes. Six numbers per rock. Ceres, Vesta, Psyche, and whatever else becomes a node.
- **Izzo's Lambert solver** for transfer arcs. Fast, robust, standard.
- **Patched conics, never n-body.** Two-body arcs stitched at sphere-of-influence boundaries, which is how real missions are planned. N-body integration costs determinism and buys nothing a player can perceive, and the server must be authoritative.

*Not Swiss Ephemeris.* Excellent library, wrong problem. It produces geocentric apparent positions for astrology rather than heliocentric state vectors, it does not cover arbitrary small bodies well, and it is AGPL-3.0 unless licensed. Under AGPL §13 a network service owes its users the source, and publishing the pricing and depletion code of a shared economy guarantees it gets farmed.

**Precompute, never solve on request.** Generate a table of transfer costs between every node pair across a grid of departure dates, refreshed on schedule. A route query becomes a lookup. With hundreds of players checking routes, this is the difference between a responsive game and a melted server.

**The Moon is a special case, and can be dodged.** Lunar motion is genuinely difficult, but for interplanetary purposes the Moon sits at Earth's position, and lunar surface-to-orbit is a fixed delta-v budget that never changes. Treat the Earth–Moon system as one point with a known escape cost.

**Accuracy target: arcminutes, not milliarcseconds.** What sells the physics is that geometry matters, that hard burns cost a fortune, and that the numbers are internally consistent. Nobody can perceive the difference between DE440 and a milliarcsecond solution, and chasing it costs weeks.

*Built.* See `orbital/README.md`. The service returns a Pareto cost curve rather than three fixed classes, so trajectory-class definitions live in `sim/` and can be retuned without regenerating a table. It reproduces the launch energies of four real NASA Mars missions to between 0.0% and 5.6%.

---

## 4. The commodities

Ten tradeable classes at launch. Each has a mass per unit, a base value, and a volatility profile. The table below covers the eight that trade in volume; `docs/seed-data.md` governs and adds two more -- regolith/silicates, which feeds the helium-3 chain, and rare earths, which is why Psyche and Pallas are worth reaching. See `docs/DECISIONS.md` D9.

| Commodity | Produced at | Consumed by | Notes |
|---|---|---|---|
| **Propellant** | Moon, Mars, C-type rocks | Every ship, everywhere | The most-traded good in the game. Effectively the second currency. |
| **Helium-3** | Moon only | Earth standing order, fusion plants | Highest value density. The monetary base. |
| **Water / ice** | Lunar poles, C-types | Life support, propellant refining | Cheap in bulk, critical in shortage. |
| **Volatiles** (C, N, NH₃) | C-type asteroids | Mars agriculture, all life support | Quiet until a convoy is lost, then vicious. |
| **Iron / nickel** | Belt (M-types) | Mars industry, all construction | High mass, low value. Margin comes from volume. |
| **Platinum group** | Belt (M-types) | Electronics, catalysts, Earth | Low mass, very high value. Piracy bait. |
| **Manufactured goods** | Mars only | Outposts, ship upgrades, modules | The bottleneck good. Mars sets the price of expansion. |
| **Food** | Mars only | Every crewed installation | Perishable. Non-negotiable. |

Blueprints and licences trade separately through the Ark and are not physical cargo.

---

## 5. The market

Three layers, and they are the actual product.

### Local spot markets
Every node has an order book. Prices form from local inventory against local demand: as a warehouse fills, the bid falls; as it empties, the ask climbs. Nothing is globally priced. Water on the Moon and water at Ceres are different goods with different prices, and the gap between them minus fuel and time is the entire merchant profession.

### The contracts board
Haulage jobs posted by agents and institutions. Move X tonnes from A to B by deadline D for a fixed fee. No capital at risk, thin margins, and the safest income in the game. This is where new players live and it never becomes worthless.

### The Solar Exchange
The cross-node market. Futures on the eight commodities, claim auctions, licence trading, and **equity in agent-run corporations**. This is where the money is and where the money is lost. A player who reads a coming volatiles shortage and takes a position three weeks early makes more than a hundred haulage runs would pay.

**Equity works like any real exchange.** Named agents and institutions operate corporations with genuine balance sheets: assets, ships, claims, revenue, costs. Shares trade on an order book and the price moves with order flow, including yours. Buying size moves the price against you. A firm that loses three ships in the Belt reports a bad quarter and its stock falls, because the ships actually sank.

The hard requirement: corporate profit must be simulated, never granted. If dividends are issued from a number that isn't earned, the exchange becomes a money printer and the currency dies. Every credit paid out must have been earned by an agent selling real cargo to a real buyer.

**Insider knowledge stays legal.** Knowing that a cartel is forming before the price moves is the reward for participating in the world rather than watching a chart. Reputation, relationships and access to named agents are worth money, and that is the intended design.

### Player-to-player trade

Players post direct offers and wants to the market: a standing bid, an ask, or a shortfall. *"Short 40 t of iron, inbound to Vesta, arriving in 30 hours."*

**Rendezvous trades are the mechanic that makes orbital position economically valuable.** A want is matched against every ship whose trajectory can reach the requester for an affordable delta-v, computed from actual positions and burns. Being in the right part of the solar system at the right time is a tradeable asset. A ship already on a passing trajectory can fill an order that a closer but badly-aligned ship cannot.

Requires escrow at the exchange and a public reputation record before it ships. Both are non-negotiable.

### Price stability: the Ark Authority
The Ark maintains a standing bid and ask on every commodity with a deliberately wide spread. It will always buy at a floor and always sell at a ceiling.

Two things this achieves. On day one, a lone player has a functioning market with no other participants. Over time, as real players and agents quote inside that spread, the Authority's volume falls toward zero without anyone flipping a switch. The training wheels dissolve on their own.

### Currency
**COMMITTED: the credit is energy-backed.** One credit is one gigajoule of delivered energy. This is the universal unit — on the Moon, on Mars, in the Belt, and in Earth's standing orders. It works everywhere because a joule is a joule everywhere, which is precisely why an interplanetary economy would settle on it.

Consequences, accepted deliberately:

- Helium-3 is the monetary base. Whoever controls lunar fusion supply influences the value of everything.
- Monetary inflation and energy inflation are the same event. A helium-3 glut is a currency devaluation.
- Every price in the game is secretly a statement about energy. Shipping mass to the Belt costs what it costs because moving mass *is* spending energy, and the currency measures it directly.

---

## 6. The inhabitants

The world is populated before any human arrives. This is what removes the cold-start problem entirely: there is never an empty server.

**Critical architectural rule: no language model ever touches the ledger.** The economy is deterministic code. Supply curves, depletion, price formation, transit, settlement — all plain functions over the database. Agents decide using cheap utility math. The language model supplies the *voice*, not the decisions. Get this backwards and you get an economy that hallucinates itself into collapse and a bill you cannot pay.

Three tiers:

**Bulk agents (~90% of population).** Pure code. Numbers on an order book. They produce, consume, haul and quote. They give the market depth and they never speak. Cost: zero.

**Named agents (30–50).** Persistent characters with holdings, routes, rivals, memory and a home region. They speak on *events*, not on ticks: when they trade with a player, when they lose a ship, when they are undercut, when they form or break an alliance. A named trader who messages you once a week because you outbid her is worth more than fifty agents narrating their day.

**Institutions (4).** One per region. The Ark Council, the Belt Claims Registry, the Mars Industrial Board, the Helium Cartel. They set tariffs, issue policy, publish statements, and auction claims. Slower model, richer context, a handful of calls per day.

**The simulation writes the encyclopedia.** Every claim war, cartel, famine and lost convoy becomes a lunarark.com entry. The engineering corpus is the world's physical law; the codex becomes its history, generated by things that actually happened. This is the piece of the design that cannot be copied, because it requires a decomposed technical substrate underneath it.

---

## 7. The player

### The first hour

**The interface is an inbox.** A player does not open a map, a market, or a tutorial. They open a message.

A named agent writes to them: who they are, where the player stands, what needs moving and why. Attached are two or three things the player could take on. Choosing one is the first act of the game, and the fiction carries every explanation. You learn what cargo is by being asked to move some. You learn what delta-v means because one option costs more fuel and arrives sooner.

This is the onboarding and it never stops being the interface. At hour one it is three choices from one agent. At month six it is a dozen offers a day from rivals, institutions, and other players, and the skill is knowing which to ignore.

**Starting position (v1 numbers, to be tuned):**

- **Cash:** 120,000 cr
- **Ship:** *Kestrel*-class light hauler — 40 t cargo, crew of one (you), 400 cr/day upkeep
- **Location:** Shackleton Depot, lunar south pole
- **Reachable nodes at start:** three. Two lunar sites and one orbital depot.
- **In the inbox at minute one:** two haulage contracts and one speculative buy that is visibly underpriced if you read the local inventory.

The first hour must contain a real decision with a real consequence, resolvable inside a day. Not a tutorial. A trade you can get wrong.

### The arc

**Contractor.** Move other people's cargo for a fixed fee. No capital at risk, thin margins, and you learn the map by flying it.

**Speculator.** Buy with your own money and carry the price risk yourself. This is where skill starts to matter and where players first lose everything.

**Owner.** Buy a claim and stop being a middleman. The first outpost is small, automated and specific — an ice extractor on a rock you own, no crew, feeding water ice into the market while you sleep. Refining it into propellant means buying an electrolysis plant, and that is the next rung rather than this one: the 400-to-1,800 cr/t refining margin is what you climb toward. See `docs/DECISIONS.md` D11. Target cost is roughly two good months of trading, not billions. If the gap between merchant and owner is too wide, most players never cross it and half the game goes unseen.

**Operator.** Larger ships, hired crew, multiple outposts, a shipping line. Vertical integration: refine your own ore instead of selling it raw, then manufacture instead of refining.

**Firm.** Multiple regions, standing contracts with agents, positions on the exchange, and enough market share that the institutions start to care what you do.

### Ships

A ship is defined by cargo capacity, delta-v, fuel mass, crew requirement, hull integrity and upkeep. Upgrades improve one at the cost of another: bigger tanks mean less cargo, better engines cost more to maintain. There is no strictly best ship, only ships suited to particular routes.

Crewed ships unlock long-haul and Belt operations but introduce life support, food, and the possibility of losing people.

### Bases

Bases are placed module by module on a site grid, bound by budgets rather than aesthetics: power generated against power drawn, heat produced against radiator area, crew available against crew required, plus mass, pressurised volume and landing capacity. Place a smelter without radiators and it throttles.

This constraint puzzle is where the engineering corpus earns its keep, and a well-designed base out-earns a sloppy one built at the same cost. **This is a 2D layout screen. Flat HTML and CSS. No engine, no meshes, no rendered surface.**

---

## 8. Keeping it alive

### Sinks
An economy without drains inflates until currency is meaningless. Money leaves the world through fuel burn, ship maintenance, docking fees, crew wages and food, Ark licensing, regional tariffs, insurance premiums, module wear and replacement, and claim renewal. These are not punishments. They are the reason a credit is worth anything.

### Shocks
Left alone, agent economies calcify or concentrate. Scheduled and random disruption is a launch feature, not a later addition:

- **Solar flares** halt transit and damage unshielded hulls
- **Depletion** quietly ends the profitability of established sites
- **Claim expiry** returns worked ground to auction, keeping the frontier open to new players
- **Convoy loss** in the Belt removes supply from the market instantly
- **Policy changes** from the institutions: tariffs, licence fee changes, embargoes
- **Cartel formation** among named agents, which players can join, break or exploit

### Integrity
Server-authoritative without exception. Every state change happens on the backend, the client is purely a view. A shared economy with a manipulable client is a dead economy inside a month. One account per person, enforced at signup, or players will farm themselves.

---

## 9. What this is not

Stated explicitly, because the temptation will be constant:

- **Not a rendered solar system.** Orbits are solved, not drawn. Locations are database rows and the map is a node graph over real ephemerides. A 3D viewer is an optional skin over working data and comes after the economy is proven.
- **Emphatically not visually boring.** Flat and 2D is a scope decision, not an aesthetic one, and the two get confused constantly. The target is instrument-panel density with editorial craft: oversized kinetic typography, hard grid layouts, live numbers that move, the feel of mission control crossed with a trading terminal. This costs almost nothing next to a 3D pipeline and matters far more to whether people stay.
- **Not real-time multiplayer.** Asynchronous logistics means a few hundred scattered players behave like a busy market, where real-time would need thousands to feel alive.
- **Not a combat game.** Ships are lost to physics, cost and bad decisions. Piracy exists as a risk model, not a shooter.
- **Not five systems at once.** Base building, extraction, ship logistics, market trading and agent society are each a game on their own.

---

## 10. Build order

**v1 — one node, one loop.** `helium3.app` only. One lunar site, propellant and ice, a spot market, the Ark Authority, fifty bulk agents and five named ones. No ships, no travel, no other regions. **The test: can you watch this market for ten minutes, with zero other players, and find it interesting?** If not, nothing built on top of it will save it.

**v2 — movement.** Ships, five lunar nodes (the three from v1 plus Selene Station and Ark Terminus), transit time, the contracts board. The moment there are two places with different prices, the game becomes trade, and that is the real product.

**v3 — the frontier.** The Belt opens. Claims, depletion, distance, loss. Outposts become purchasable.

**v4 — industry.** Mars, manufacturing, crewed bases, the module system, the full engineering tree.

**v5 — society.** The Ark as a political layer. Tariffs, voting, arbitration, generated history written back into the codex.

---

## Resolved

1. **Currency is energy-backed.** One credit, one gigajoule, everywhere. Settled.
2. **Orbital mechanics is foundational.** Real state vectors, real geometry, real trajectory classes. Skyfield with DE440, Izzo Lambert, patched conics, precomputed transfer tables. Not Swiss Ephemeris, for licensing and problem-shape reasons.
3. **Fusion propulsion is standard.** Weeks between worlds, not months. Geometry sets price, not possibility.
4. **One clock at 60×**, shared by everyone. Offline is absent, not paused, so standing instructions are a launch feature.
5. **Equity trades on the exchange** with order-book price impact, backed by corporations with real balance sheets.
6. **Player-to-player trade ships**, including rendezvous matching against live trajectories. Escrow and reputation are prerequisites.
7. **The inbox is the interface.** Narrative delivery of choices is the onboarding, the tutorial, and the permanent front door.
8. **Visual ambition is not scope creep.** 2D, flat, and beautiful.

## Still open

- **Standing-instruction depth.** How much can a player automate before they stop playing? Limit orders are clearly right. An autonomous broker that trades unattended might hollow the game out.
- **Reputation mechanics.** Required before player-to-player trade ships, and undesigned.
- **Piracy.** Accepted as a risk model rather than combat, but the loss mechanic itself is unspecified.
