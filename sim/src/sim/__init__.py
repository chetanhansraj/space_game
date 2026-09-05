"""sim -- the world tick.

Agent decisions, production, consumption, depletion, price formation, shocks.
Deterministic: seeded RNG, logged seeds, reproducible from any tick.

This package decides *what happens*. It never moves money itself -- every
credit and every kilogram goes through `market`, so conservation stays
structural here too. If `sim` has a bug, the world becomes implausible; it
cannot become unbalanced.

No language model touches anything in here. Agents decide with cheap utility
arithmetic over the database, per invariant 2. `voice/` reads the events this
package emits and writes prose about them, and if `voice/` is down the world
keeps running with placeholder text.

One tick is one game hour, which at the 60x clock is one real minute. Every
rate in docs/seed-data.md is per game day, so per-tick amounts are day rates
divided by 24.
"""

__version__ = "0.1.0"

#: Game hours per tick. The world advances one hour at a time.
TICK_GAME_HOURS = 1

#: Ticks in a game day. Seed-data rates are per game day.
TICKS_PER_GAME_DAY = 24
