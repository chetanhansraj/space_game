# market

Order books, escrow, settlement, and the ledger. The most correctness-critical
code in the repository.

## The one idea

**Conservation is structural, not tested.**

Every economic event is a set of postings that sum to zero per asset. There is
no code path that can create or destroy a credit, because a transaction that
does not balance is rejected before it is written. The property tests do not
establish conservation — they check that nothing has subverted it.

Value enters and leaves the world only through four named accounts, and
because they sit on the same ledger as everyone else, every credit ever
created and destroyed is a query:

| Account | What it is |
|---|---|
| `world:genesis` | The only source of credits. Its balance is the negative of every credit in existence. |
| `world:sink` | Where credits die: fuel, upkeep, docking fees, wages, licensing, tariffs. Invariant 7's audit. |
| `world:extraction` | Mass out of the ground. |
| `world:consumption` | Mass used up — life support, propellant burned, food eaten. |

```python
ledger.credits_in_existence()   # -balance(world:genesis)
ledger.credits_destroyed()      #  balance(world:sink)
ledger.assert_conserved()       #  every asset sums to zero, or raise
```

There is no balance column anywhere. Balances are summed from postings every
time, because a stored balance is a second source of truth that will
eventually disagree with the first and there will be no way to tell which is
right. `UPDATE` and `DELETE` on the ledger are blocked by database triggers,
not by convention.

## No rounding, anywhere

CLAUDE.md requires integer credits and kilogram masses. Those conflict:
regolith at 150 cr/tonne is 0.15 cr/kg, which is not an integer.

Resolved the way real commodity markets do — **priced per lot, sized in whole
lots**. A lot is a tonne for bulk goods and a kilogram for platinum group
metals and helium-3, matching the trade-unit column in `docs/seed-data.md`.
Quantities are still stored in kilograms, constrained to whole multiples of
the lot mass, so the cost of a fill is an integer multiplication and the kg
conversion is exact both ways. There is no float in the package.

## The book

Limit orders only. Price-time priority. The resting order sets the price, so
an aggressor that crossed the spread gets the difference refunded from escrow.
Everything resting is collateralised from the moment it is placed — a bid
holds its credits, an ask holds its goods — so nothing can be promised twice
and cancelling returns exactly what is left.

Self-trading is skipped rather than rejected. One account per person is an
invariant, so trading with yourself can only be wash trading.

## The Ark Authority

A standing bid at 60% of seed value and an ask at 175%, so a lone player has a
working market on day one with no other participants.

It is not special-cased in the engine — an ordinary institutional account
placing ordinary escrowed limit orders. Anyone quoting inside its spread gets
hit first by price priority, which is how the training wheels come off without
anyone flipping a switch. `share_of_volume()` is the number that should fall
toward zero.

**Its treasury is finite.** "Always buys at a floor" read literally is a
printing press wearing an institution's clothes. It is funded once from
genesis in a single auditable transaction and trades against real holdings
after that. Drain it and the floor thins and disappears — a genuine economic
event, and everyone who sold into it was paid with real money on the way down.

## Test

```bash
.venv/bin/python -m pytest market/tests -q
```

40 tests. The centre of gravity is `test_conservation.py`: a Hypothesis state
machine that places, cancels, sweeps, self-trades, overdraws, mines, consumes
and burns in whatever order it finds interesting, checking after **every
single step** that nothing was created or destroyed, no ordinary account is
overdrawn, every resting order is still fully collateralised, and every closed
order's escrow is empty.

## Not built yet

The contracts board (v2), futures and equity (v3+), and player-to-player
rendezvous trade — which the bible gates behind escrow and a public reputation
record. Escrow now exists; reputation does not.
