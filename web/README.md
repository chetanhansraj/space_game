# web

The client. Rendering only — no game logic, per invariant 1.

Nothing here is the real client yet. What exists is one page, generated from a
live simulation run, to settle the visual language before anything is built on
it.

## The terminal

```bash
python web/build_terminal.py                 # 480 ticks, seed 20260904
python web/build_terminal.py --ticks 960 --seed 7
```

Runs `sim` and renders whatever comes out. **It is not a mockup** — every
figure on the page is simulation output, so the page cannot drift from what
the economy actually does. Change the simulation and the terminal changes with
it, which makes a screenshot of it evidence rather than illustration.

The current run: 5,798 trades between 54 firms, 43 kg of helium-3 delivered to
Earth, money supply at 1.03, and the headline — **water ice at 657 cr/t at
Shackleton Depot against 333 at Peary Ridge**, a 1.97× gap that nothing
designed. Shackleton has electrolysis plants eating ice; Peary does not.

## Visual language

Follows `docs/DESIGN-LANGUAGE.md`, which was extracted from lunarark.com so the
game and the codex read as one universe rather than two products.

| | |
|---|---|
| Ground | `#07070f` — near-black, biased violet rather than neutral grey |
| Lead | violet `#8b5cf6`, with cyan `#22d3ee` for micro-labels |
| Semantic | green live, amber warning, red critical — separate from the accent |
| Display | Chakra Petch, for the squarish technical face |
| Data | JetBrains Mono, tabular figures throughout |
| Prose | Barlow |

Committed dark, single theme, matching the site.

**The hex values are eyeballed from screenshots.** The real stylesheet has not
been readable from any session so far. Replacing them is a five-minute job that
changes nothing structural — swap the tokens in `DESIGN-LANGUAGE.md`, re-run
the generator.

## Still to build

The inbox, which the bible calls the permanent front door: *"A player does not
open a map, a market, or a tutorial. They open a message."* Then the node
graph, the base layout grid, and the standing-instruction editor.
