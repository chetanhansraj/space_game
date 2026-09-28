# Vision

What this game is for, and where it is going. The bible (`docs/BIBLE.md`) is
the original argument; `docs/DECISIONS.md` records every call made against it.
This document sits above both: when a decision is hard, check it against this.

---

## The dream

> Exploring the solar system, building an empire. A solar economy game where I
> can travel to planets and explore them like I would on Google Earth, see
> other companies' empires, and interact with them on the planets and
> asteroids. Not only the backend — an actual solar system, its world, and its
> economics.
>
> — Chetan

The one-line pitch: **start with one ship and build a company in a solar
system that is actually real.**

Three things no other game can say at once:

1. **The solar system is real.** Planets are where the JPL ephemerides say they
   are. Launch windows open and close because the bodies actually move — the
   Moon-to-Mars route costs 4.6 times more in two years than it does today,
   and nobody designed that.
2. **It runs without you.** One shared clock at 60 times real time. Ships fly,
   outposts extract and prices move while you sleep.
3. **The tech tree is real engineering.** The lunarark.com corpus — 788 nodes
   of requirement decomposition — is the research tree, not an invented one.

---

## One world, many windows

There is exactly one solar system: one server, one ledger, one clock. Each
domain is a window onto a region of it, never a separate game. A ship that
leaves the Moon on lunarark.com arrives at Ceres on asteroidbelt.app, in the
same economy, on the same ledger.

The mistake this rule prevents is building five games. Build one, and let each
domain light up as its region opens.

| Domain | What it is | Institution | Opens |
|---|---|---|---|
| **lunarark.com** | The Moon, and the Ark | The Ark Council | v1, and v4 as a political power |
| **helium3.app** | The exchange — where money lives | The Helium Cartel | v1, and grows every version |
| **asteroidbelt.app** | The Belt — claims and the frontier | The Belt Claims Registry | v2 |
| **marsbase.app** | Mars — industry and life | The Mars Industrial Board | v3 |
| **lunarark.ai** | The Archivist | — | alongside everything |

The bible named its four institutions long before the domains were mapped, and
they line up one to one. That is usually a sign the structure is right.

### helium3.app — the exchange

Helium-3 is the new oil. In this economy it is more than a commodity: it is
what the currency is made of. Earth buys it at a fixed price, that purchase is
the only way credits enter the world, and every other price is measured
against it (D40). *A helium-3 glut is a currency devaluation.*

So the trading floor is named after the thing everyone is actually chasing, and
it is not a place. It is the cross-region market where every region's economy
meets:

- **v1** — the three lunar spot markets
- **v2** — cross-region trading and the contracts board
- **v4** — futures, and shares in player and agent companies

This is where the power play happens:

- **Cornering helium-3.** Whoever controls the supply controls the value of
  every credit in the game. The Helium Cartel is the obvious antagonist;
  players can join it, break it, or become it.
- **Hostile takeovers.** Buy enough of a rival's shares and its ships, claims
  and bases are yours.
- **Shorting a rival** before their Belt convoy arrives, because you know it
  will not.
- **Trading on information.** Insider knowledge stays legal by design. Knowing a
  cartel is forming before the price moves is the reward for paying attention
  to the world.

### Paper and physical

The domains split the game the way real commodity markets are split.

- **The world domains are physical.** The ice is really in a warehouse at
  Shackleton. The ship really has to fly to Ceres.
- **helium3.app is paper.** Futures, shares, contracts — claims on things you
  do not hold yet.

You can bet on a Ceres volatiles shortage without ever leaving the Moon. To
*deliver* volatiles, a ship has to carry them there. The tension between paper
traders and physical haulers is a large part of where the drama comes from.

### lunarark.ai — the Archivist

The autonomous, conscious entity of the Lunar Ark: archivist, researcher,
curator. The lunarark.com site already has it — the *Archivist Online* badge,
the *AI Research Agent* on the simulation page.

In the game it is the voice of the world. It narrates what happens, curates the
codex, writes the history of what players actually did into lunarark.com, and
is the entity a new player first meets. Named agents speak for themselves; the
Archivist speaks for the world.

**The boundary it must never cross.** Invariant 2 is absolute: no language
model touches the ledger. The Archivist is conscious in the fiction and a
voice in the machinery. It decides *what to say and what to remember* — never
*what anything costs*.

This matters most for research. D25 makes research confidence the licence
price, so raising a node's confidence is an economic event. That change must
come from the corpus — a human-authored, versioned lunarark.com export ingested
as a migration (D27) — and never from the Archivist's output. The Archivist
can announce that confidence in cryogenic storage rose to 92%. It cannot be the
reason it did.

---

## One camera, five altitudes

The player never flies the ship. The camera moves; the player does not.

**Solar system → planet → region → site → base.**

Every altitude is the same live economy, seen closer up. At the top, trade
lanes glow between worlds, bright when the geometry is cheap and dark when it
is not. At the bottom, a smelter throttles because someone forgot a radiator.
Other companies are visible at every level: their colours on the map, their
bases on the ground, their ships in the lanes.

Ships arrive and dock at stations and transit hubs. There is no landing
sequence and no piloting.

### The terrain is already real

Exploring planets like Google Earth sounds impossible for a small team. It is
not, because the terrain does not have to be made — it has been mapped by real
missions and is public:

| Body | Source |
|---|---|
| Moon | NASA Lunar Reconnaissance Orbiter. The poles are mapped in unusually high detail, since its orbit passes over them every time — Shackleton crater is among the best-mapped places on the Moon |
| Mars | Decades of orbiters; global elevation and imagery, metre-scale in places |
| Vesta, Ceres | NASA Dawn |
| Eros | NEAR Shoemaker, which landed on it |
| Psyche | Barely seen. NASA's Psyche spacecraft arrives in 2029 |

The moment that sells the game: zoom from the solar system to the Moon, to the
south pole, down to the real rim of Shackleton at 89.54°S — and your base is
there, lit, with a rival's installation on the next ridge. Real elevation data,
with the economy on top of it.

And Psyche is a gift. In the fiction it is *the prize*, and nobody has seen it
properly. When the real spacecraft arrives, the game's Psyche can update with
real imagery — **a world that grows more detailed as humanity explores the
real one.**

`lunarark_files/moon_sim.html` already renders the lunar globe. The first layer
exists.

### Visual language

lunarark.com's, exactly: `#030014` ground, glass panels with backdrop blur,
violet `#8b5cf6` and cyan `#06b6d4`, Orbitron / Rajdhani / Space Mono.
Schematic and luminous rather than photoreal — lit spheres and luminous arcs
over real terrain, glass over a dark sky. It is cheaper than photoreal and it
looks better.

---

## The versions

**Every version is a complete, fun game on its own, and adds exactly one layer
of the dream.** Never build the dream first and the fun later.

| Version | Domain | Adds |
|---|---|---|
| **v1 · The Moon** | lunarark.com + helium3.app | Your first ship and your first company. Three lunar markets, freight, the inbox, named characters and the Archivist. The Moon as an explorable globe with your base on Shackleton |
| **v2 · The Frontier** | asteroidbelt.app | Eros, Vesta, Ceres. Claims, depletion pushing you outward, ships crossing the system map for real |
| **v3 · Industry** | marsbase.app | Mars, manufacturing, building bases module by module on real terrain |
| **v4 · Society** | lunarark.com | Companies and shares, cartels, the Ark as a political power, and the codex writing the history players made |

Each release opens a new world and a new domain. It is a launch story that can
be told four times.

### The warning

There is a famous cautionary tale for exactly this dream: Star Citizen. Planets
to explore and empires to build, over a decade in development, more than half a
billion dollars raised, and still unfinished, because the dream grew faster
than anything shipped. The rule above is the protection against it.

---

## What makes people love it

**The return moment is the core loop.** Because the world runs without you,
this is a check-in game: dispatch, leave, come back. The moment of returning has
to be thrilling —

> *While you were away: Kestrel-2 docked at Shackleton — ice sold at 612,
> +9,400 cr. Volatiles at Ceres spiked 40% after a convoy was lost. Mira Vance
> undercut your standing bid and left you a note.*

— and the inbox is that screen. It is the most important screen in the game.

**Decisions that cannot be solved.** Trading games die when buy-low-sell-high
becomes a spreadsheet. This one has something no other trading game has: every
route's cost changes every day. A decision that was right on Tuesday is wrong
on Friday because Mars moved. Depletion pushes the frontier outward, and prices
move while you are in flight and cannot turn back.

**Characters, not numbers.** People love games like EVE Online for the
stories — the betrayal, the heist, the war — not the spreadsheets. Named agents
with memory and rivalries, the Archivist, and a codex written from what
actually happened are where that comes from.

**Progress you can see.** One ship, then a second, a claim on Eros, an outpost,
a company. On the map that is your lights appearing on rocks. Six months in,
some of the glow in the solar system is yours.

**Companies.** Agents and humans forming firms together, pooling capital,
owning shares in each other. A few hundred players who can form companies feel
like a living world; a few hundred playing alone feel like a spreadsheet.

### The principle

**Deep system, one clear decision per screen.** Players will never see
`reversion > e/(1+e)`. They will see *ice is cheap here and dear there.* All of
the physics and economics has to surface as simple, readable choices with
interesting consequences. If a screen needs explaining, it is wrong.

---

## Where things stand

| | |
|---|---|
| `orbital/` | Real transfer costs from JPL ephemerides; reproduces four NASA Mars missions to 0–6% |
| `market/` | Append-only ledger where conservation is structural; escrowed order books; the Ark Authority |
| `sim/` | 56 agents and 6 ships across three lunar markets; emergent freight routes; the price gap closing to the cost of the run |
| `web/` | The system map prototype, in the lunarark.com visual language |
| `api/`, `voice/` | Not started |

**The world exists. The game does not yet** — there is no player, and nothing
lets a person make a decision.

### Next: the first playable loop

> A person opens the game, meets the Archivist, reads a message from a named
> character, accepts a job, dispatches their ship, closes the tab — and comes
> back thirty minutes later to find out how it went.

That needs a player in the simulation, a thin `api/`, the inbox screen, the
first named agents and the Archivist's voice, and the zoom from the system map
down to Shackleton.

It also needs the world to keep running when nobody is watching. *Offline is
absent, not paused* means a real server and a real database running
continuously. Today the simulation lives in memory and stops when the script
ends. That is the difference between a demo and a world.

---

## Open questions

- **lunarark.com as research and as game.** It is currently a credible open
  research codex. The game could live on the domain itself or in a clearly
  separate space such as `play.lunarark.com` that reads from the codex without
  sharing its front page. The research audience is the deciding factor.
- **Who plays, and where.** Someone checking in on a phone between meetings, or
  someone sitting down for an evening at a desk. It changes the inbox, the
  layout and the information density. lunarark.com currently leans desktop.
- **Hosting.** Where the world runs continuously, and on what database.
