# sim

The world tick. Agents, production, consumption, depletion, price formation,
shocks.

`sim` decides *what happens*. It never moves money itself — every credit and
kilogram goes through `market`, so conservation stays structural here too. A
bug in `sim` makes the world implausible; it cannot make the world unbalanced.

No language model touches anything here. Agents decide with arithmetic over
their own balance sheets, per invariant 2.

**One tick is one game hour**, which at the 60× clock is one real minute.

## Price formation

The mechanic the whole game rests on. The bible: *"as a warehouse fills, the
bid falls; as it empties, the ask climbs."*

```
pressure = (holding - target) / target      surplus positive, deficit negative
price    = reference × (1 - elasticity × pressure)
```

One formula, both sides, because the incentive is symmetric. A seller on
surplus lowers its ask; a seller running dry holds out. A buyer with full
tanks bids weakly; a buyer running dry bids up. Supply and demand fall out of
that and nothing has to impose them.

`reference` is the last trade **blended back toward the seed anchor**. Both
halves matter: quoting purely off the anchor is how the Ark Authority became
a one-way valve (finding F2), and quoting purely off the last print ratchets
without limit (finding F5 — ice reached 1,670 against a 400 anchor).

`elasticity` and reversion both come from seed-data's volatility column, which
says volatility is *"the mean-reversion strength and shock sensitivity"* —
two jobs, so two numbers, with reversion running inverse to volatility.

## The macro loop

Credits enter the world in exactly one place and leave in exactly one place:

```
Earth's standing order  →  helium-3 sellers  →  wages  →  households
                                    ↓                          ↓
                                 sinks  ←  upkeep, fees, power
```

The ratio between those two flows **is** the money supply — see D40. It is
invisible in every other metric: the first measured world had stable prices,
no insolvencies and perfect conservation while quietly draining itself at a
0.52 ratio (finding F4).

## The v1 world

50 bulk agents across the three lunar nodes from seed-data. Named agents are
`voice/`'s concern — they speak rather than trade.

| Node | Firms |
|---|---|
| **Peary Ridge** | 8 ice extractors, 2 households, 1 trader |
| **Shackleton Depot** | 10 ice extractors, 4 electrolysis plants, 5 households, 4 traders |
| **Tranquillitatis Flats** | 8 regolith extractors, 4 helium-3 separators, 2 households, 2 traders |

Ten ice miners at 12 t/day feed four plants at 30 t/day exactly — seed-data's
own ratio. Get it wrong and you get correct price formation over an incoherent
roster: six of each put ice at six times its anchor.

**Shackleton ice settles around 650, Peary ice around 333.** The same good at
two prices, because Shackleton has refineries eating it and Peary does not.
That gap is what seed-data means by *"enough for arbitrage, because arbitrage
needs exactly two prices"* — and it is the merchant profession waiting for v2
to give it ships.

## Reproducibility

Randomness comes from named streams: a draw is a pure function of
(seed, stream, tick, salt), hashed rather than sequential. Adding a new source
of randomness leaves every existing stream bit-identical, so a replay of
yesterday's bug does not diverge because the code changed in between. Any draw
is recomputable without replaying the ticks before it.

## Test

```bash
.venv/bin/python -m pytest sim/tests -q
```

31 tests. The world-level ones run a real world for real ticks, which is
slower and deliberate: every bug that mattered while building this was
emergent, and no unit test would have caught any of them.
