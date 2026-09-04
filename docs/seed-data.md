# Seed data

Three tables. Everything in the economy descends from these.

**These are first-pass values, not balanced values.** They are internally consistent and physically anchored, which is enough to build against. They will be wrong after the first simulation run, and that is expected. Tune by simulation, not by argument.

**Every rate on this page is per game day**, and every duration is game time. At the 60× clock a game day is 24 real minutes, so the distinction is worth a factor of sixty. One consequence worth seeing early: the *Kestrel*'s 400 cr/game-day upkeep is 24,000 cr per real day, which makes 120,000 cr of starting cash five real days of runway with no income. See `docs/DECISIONS.md` D14.

---

## 1. Locations

### Orbital elements

Heliocentric Keplerian elements at epoch J2000. Planetary elements are JPL's approximate-positions set with secular rates per Julian century, valid 1800–2050.

**These tables are illustrative. DE440 governs.** The orbital service reads planetary positions from the JPL kernel, not from here — the kernel is the committed source and is three orders of magnitude more accurate. The numbers below are for reading, not for computing against. See `docs/DECISIONS.md` D6.

| Body | a (AU) | e | i (°) | L (°) | ϖ (°) | Ω (°) |
|---|---|---|---|---|---|---|
| Earth–Moon barycentre | 1.00000261 | 0.01671123 | −0.00001531 | 100.46457166 | 102.93768193 | 0.0 |
| Mars | 1.52371034 | 0.09339410 | 1.84969142 | −4.55343205 | −23.94362959 | 49.55953891 |

Rates per Julian century:

| Body | da/dt | de/dt | di/dt | dL/dt | dϖ/dt | dΩ/dt |
|---|---|---|---|---|---|---|
| Earth–Moon barycentre | 0.00000562 | −0.00004392 | −0.01294668 | 35999.37244981 | 0.32327364 | 0.0 |
| Mars | 0.00001847 | 0.00007882 | −0.00813131 | 19140.30268499 | 0.44441088 | −0.29257343 |

Asteroid elements are osculating and epoch-dependent. **Pull these fresh from the JPL Small-Body Database at build time rather than hardcoding them** — `orbital/scripts/fetch_sbdb.py` does this and stamps the epoch into the generated transfer table.

Note that the table below is short of a **mean anomaly and an epoch**, which are the sixth and seventh numbers needed to place a body on its ellipse. Without them these elements cannot be propagated at all, so they are not usable even for scaffolding. Period is given instead, which is derivable from `a` and therefore carries no extra information. See `docs/DECISIONS.md` D5.

| Body | a (AU) | e | i (°) | Ω (°) | ω (°) | Period (yr) | Character |
|---|---|---|---|---|---|---|---|
| 1 Ceres | 2.766 | 0.079 | 10.59 | 80.31 | 73.60 | 4.60 | Water, volatiles. The Belt's capital. |
| 4 Vesta | 2.362 | 0.088 | 7.14 | 103.81 | 151.20 | 3.63 | Metals, closest major body. Early Belt target. |
| 16 Psyche | 2.923 | 0.134 | 3.10 | 150.02 | 229.55 | 5.00 | Metallic. Platinum group. The prize. |
| 2 Pallas | 2.773 | 0.230 | 34.83 | 172.9 | 310.9 | 4.62 | High inclination — brutally expensive to reach. |
| 433 Eros | 1.458 | 0.223 | 10.83 | 304.3 | 178.9 | 1.76 | Near-Earth. Cheapest first claim in the game. |

Pallas at nearly 35° inclination is deliberate content: it is rich and almost nobody can afford to go there. Plane changes are the most expensive thing in orbital mechanics and the game should teach that lesson through someone's bankruptcy.

### Nodes

The Earth–Moon system is treated as a single point for interplanetary purposes. Lunar surface-to-orbit is a fixed budget that never changes: surface → low lunar orbit is 1.87 km/s, LLO → Earth escape is roughly 0.7 km/s. Surface → interplanetary space is therefore **2.57 km/s**.

Surface-to-surface was missing, and all three v1 nodes are surface sites. It is a ballistic suborbital hop, derived in `docs/DECISIONS.md` D7 and implemented in `orbital/src/orbital/lunar.py`:

| Route | Central angle | Δv | Transit (game time) |
|---|---|---|---|
| Shackleton → Peary Ridge | 178.5° | 3,360 m/s | 54 min |
| Shackleton → Tranquillitatis | 98.4° | 3,119 m/s | 44 min |
| Peary Ridge → Tranquillitatis | 80.1° | 2,973 m/s | 38 min |

All three are cheaper than going up to orbit and back down (3,740 m/s), and converge on exactly twice lunar circular speed for an antipodal trip.

| Node | Parent | Class | Produces | Consumes | Docking fee (cr) | Version |
|---|---|---|---|---|---|---|
| Shackleton Depot | Moon (S pole) | Settlement | Water ice, propellant | Food, volatiles, goods | 800 | v1 |
| Peary Ridge | Moon (N pole) | Extraction | Water ice | Propellant, goods | 300 | v1 |
| Tranquillitatis Flats | Moon (equatorial) | Extraction | Helium-3, regolith | Propellant, goods, food | 400 | v1 |
| Selene Station | Low lunar orbit | Depot | — | Propellant | 1,200 | v2 |
| Ark Terminus | Moon (S pole) | Settlement | Licences, blueprints | Everything | 2,000 | v2 |
| Eros Claim Field | 433 Eros | Extraction | Metals | Everything | 200 | v3 |
| Vesta Station | 4 Vesta | Settlement | Metals, PGM | Everything | 1,500 | v3 |
| Ceres Exchange | 1 Ceres | Settlement | Water, volatiles | Goods, food, He-3 | 2,500 | v3 |
| Psyche Works | 16 Psyche | Extraction | PGM, rare earths | Everything | 900 | v3 |
| Pallas Reach | 2 Pallas | Extraction | Metals, rare earths | Everything | 600 | v4 |
| Tharsis Yards | Mars | Settlement | Goods, food, alloys | Ore, He-3, propellant | 3,000 | v4 |
| Hellas Agricultural | Mars | Settlement | Food | Volatiles, power | 1,800 | v4 |

**v1 ships with the first three nodes only.** That is enough for arbitrage, because arbitrage needs exactly two prices.

---

## 2. Commodities

Base values are anchored in energy. One credit is one gigajoule of delivered energy, so a commodity's base value approximates the energy embodied in producing and delivering it. Helium-3 is priced from its actual fusion yield at realistic conversion efficiency, which is why it is six orders of magnitude above bulk cargo — that spread is correct and creates genuinely different ship classes.

| Commodity | Trade unit | Base value | Volatility | Produced at | Consumed by |
|---|---|---|---|---|---|
| Regolith / silicates | tonne | 150 cr | Low | Lunar equatorial | Construction, solar panel fab |
| Water ice | tonne | 400 cr | Medium | Lunar poles, C-types | Life support, propellant refining |
| Propellant (LOX/LH₂) | tonne | 1,800 cr | High | Moon, Mars, C-types | Every ship, everywhere |
| Iron / nickel | tonne | 2,500 cr | Low | M-type asteroids | Mars industry, all construction |
| Volatiles (C, N, NH₃) | tonne | 6,000 cr | Very high | C-type asteroids | Agriculture, all life support |
| Food | tonne | 12,000 cr | Medium | Mars only | Every crewed installation |
| Rare earths | tonne | 90,000 cr | Medium | Psyche, Pallas | Electronics, reactor components |
| Manufactured goods | tonne | 45,000 cr | Low | Mars only | Outposts, upgrades, modules |
| Platinum group | kg | 1,200 cr | High | M-type asteroids | Catalysts, electronics, Earth |
| Helium-3 | kg | 236,000 cr | Very high | Moon only | Fusion plants, Earth standing order |

Volatility is the mean-reversion strength and shock sensitivity, not a price band. Volatiles are the most dangerous commodity in the game: quiet for weeks, then a lost convoy turns a farming station into a bidding war.

**Propellant is effectively a second currency.** It is the most traded good, it is consumed by the act of trading, and its price sets the cost of every route.

**Fusion drive exhaust velocity is 400 km/s** (Isp ≈ 40,800 s). This is the constant that converts a route's delta-v into tonnes of propellant burned, so it sets the operating cost of everything that moves. It was solved for rather than picked: it is the value at which the bible's stated transit times produce sane propellant fractions — 51% of ship mass for a 20-day Mars hard burn, 19% for a 60-day standard crossing, 2.2% for a minimum-energy arc. See `docs/DECISIONS.md` D2.

---

## 3. Lunar base modules

Power positive means generation, negative means draw. Heat is thermal load requiring radiator capacity. A base fails when any budget goes negative: power, heat, crew, or pressurised volume.

| Module | Mass (t) | Power (kW) | Heat (kW) | Crew | Cost (cr) | Output / notes |
|---|---|---|---|---|---|---|
| **Power** |
| Solar array, 50 kW | 4 | +50 | 2 | 0 | 180,000 | Zero output through lunar night unless polar |
| Fission reactor, 400 kW | 32 | +400 | 180 | 1 | 2,400,000 | Constant output. Ark licence required |
| Battery bank | 8 | — | 6 | 0 | 140,000 | 200 kWh buffer. Essential with solar |
| **Thermal** |
| Radiator panel | 3 | −4 | −120 | 0 | 95,000 | The constraint everyone forgets |
| **Structure** |
| Pressurised hab, 6-berth | 18 | −25 | 30 | 0 | 620,000 | +6 crew capacity |
| Airlock | 5 | −8 | 6 | 0 | 210,000 | One required per pressurised cluster |
| Cargo warehouse | 12 | −4 | 3 | 0 | 160,000 | 2,000 t storage |
| Cryo tank farm | 14 | −40 | 45 | 0 | 340,000 | 800 t propellant, boil-off if underpowered |
| Landing pad | 22 | −6 | 2 | 0 | 280,000 | One ship berth |
| **Life support** |
| ECLSS unit | 9 | −45 | 55 | 1 | 480,000 | Supports 8 crew |
| Water recycler | 6 | −30 | 35 | 0 | 260,000 | Cuts water import by 85% |
| Hydroponics bay | 15 | −60 | 40 | 2 | 550,000 | Feeds 6 crew. Needs volatiles |
| **Extraction** |
| Ice miner, automated | 20 | −90 | 70 | 0 | 1,500,000 | 12 t/day at richness 1.0. First outpost |
| Regolith harvester | 26 | −120 | 95 | 1 | 1,900,000 | 400 t/day raw feedstock |
| Helium-3 separator | 34 | −350 | 310 | 2 | 4,200,000 | 0.6 kg/day per 400 t regolith |
| **Processing** |
| Electrolysis plant | 24 | −280 | 240 | 1 | 1,800,000 | 30 t/day water → LOX/LH₂ |
| Cryo liquefaction | 18 | −200 | 220 | 0 | 1,100,000 | Required to store propellant |
| Ore smelter | 40 | −450 | 520 | 3 | 3,600,000 | 60 t/day ore → alloy. Ark licence |
| **Control** |
| Command post | 7 | −20 | 18 | 2 | 390,000 | Required. One per site |
| Comms relay | 4 | −15 | 10 | 0 | 130,000 | Required for remote operation |

### The first outpost

An automated ice extractor, uncrewed, feeding water ice into the market while the owner sleeps:

Ice miner + solar array ×3 + battery bank + radiator ×1 + cargo warehouse + comms relay
= **2,565,000 cr**, no crew, no life support, no failure modes involving people.

Check the budgets:

| Budget | Capacity | Load | Margin |
|---|---|---|---|
| Power | +150 kW | −113 kW | +37 kW |
| Heat | 120 kW | 95 kW | +25 kW |

It closes, but the heat margin is the tight one: 25 kW of headroom means the next warm module you add forces a second radiator, and that radiator's own 4 kW draw is what starts eating the power budget. Radiators really are the constraint everyone forgets.

It sells **ice, not propellant** — there is no electrolysis plant in this build, and adding one (−280 kW, 1,800,000 cr) needs seven more solar arrays. Refining is the next rung: buy electrolysis, stop selling at 400 cr/t and start selling at 1,800.

*The figures above are corrected. The original example did not close — its cost line implied two radiators and a battery (2,840,000 cr, not 2,700,000), its power line only worked with one radiator, and its heat load matched neither. See `docs/DECISIONS.md` D10.*

---

## Open values

Numbers deliberately not set here, because they need simulation to determine:

- Depletion curve shape, and richness decay rate per tonne extracted
- Ark Authority floor and ceiling spread width
- Agent population counts per node at each version
- Shock frequency and magnitude
- Starting cash relative to first-outpost cost — currently 120,000 cr against 2,700,000, which implies a long climb that may be too long
