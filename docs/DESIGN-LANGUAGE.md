# Design language

Extracted from lunarark.com — Registry, Intel, Simulation (both views) and
Research. This is the visual system `web/` gets built against, so that the
game and the codex read as one universe rather than two products.

**Colour values here are eyeballed from screenshots, not pulled from the
stylesheet.** They are close, not exact. When lunarark.com is reachable,
replace this file's tokens with the real ones — the structure will hold, only
the hex values move.

---

## What the site already is

The bible calls for "instrument-panel density with editorial craft: oversized
kinetic typography, hard grid layouts, live numbers that move, the feel of
mission control crossed with a trading terminal."

lunarark.com is already that. The game does not need a new visual language.
It needs to not break this one.

---

## Tokens

```css
:root {
  /* Ground. Near-black, tinted blue-violet rather than neutral grey. */
  --bg-void:        #07070f;   /* page ground */
  --bg-panel:       #0e0d1a;   /* side panels, cards */
  --bg-raised:      #16142a;   /* stat tiles, hovered rows */
  --bg-hero:        #120f24;   /* hero bands, under imagery */

  /* Hairlines. Visible but never assertive. */
  --line:           #241f3d;
  --line-bright:    #3a3260;

  /* Accents. Violet leads, cyan supports. */
  --accent:         #8b5cf6;   /* primary: active nav, selected node, fills */
  --accent-soft:    #a78bfa;   /* hover, secondary emphasis */
  --accent-glow:    #8b5cf655; /* node glow, focus rings */
  --cyan:           #22d3ee;   /* micro-labels, secondary metrics, links */
  --cyan-soft:      #67e8f9;

  /* Status. Semantic, never decorative. */
  --live:           #22c55e;   /* ARCHIVIST ONLINE, SIMULATION: ACTIVE */
  --progress:       #f59e0b;   /* IN PROGRESS, schematic leaf borders */
  --critical:       #ef4444;   /* CRITICAL, DEPENDS ON */
  --pink:           #ec4899;   /* third metric in a stat cluster */

  /* Text. */
  --text:           #e8e6f5;
  --text-dim:       #9d97c0;
  --text-faint:     #6b6590;

  /* Type. Monospace does the technical work; the sans carries prose. */
  --font-mono: "JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace;
  --font-sans: "Space Grotesk", "Inter", system-ui, sans-serif;

  --radius:      10px;
  --radius-pill: 999px;
}
```

## Category colours

From the Simulation legend. These are load-bearing: the same ten colours must
mean the same ten things in the game.

| Cluster | Colour |
|---|---|
| Energy Systems | `#eab308` |
| Life Support Systems | `#22c55e` |
| Habitat & Infrastructure | `#9ca3af` |
| Communication & Navigation | `#3b82f6` |
| Transportation & Mobility | `#f97316` |
| Resource Utilization | `#a855f7` |
| Scientific Research & Exploration | `#06b6d4` |
| Crew Health & Safety | `#ef4444` |
| Robotics & Automation | `#84cc16` |
| Mission Control & Operations | `#ec4899` |

---

## Patterns worth copying exactly

**Micro-label.** Uppercase monospace, ~10px, letter-spacing ~0.12em, in
`--cyan` or `--text-faint`. Sits above every value in the site. It is what
makes a number read as an instrument reading rather than as text.

**Stat tile.** Micro-label above, oversized numeral below (28–48px, mono,
tight). Grouped in twos and threes. `NODES 788 · DEPTH L4 · LINKS 2575`.
Each metric in a cluster takes a different accent so the group scans as a
row of distinct gauges.

**Status pill.** `--radius-pill`, 1px border, dot then uppercase mono label.
`● LIVE`, `● ARCHIVIST ONLINE`, `● IN PROGRESS`.

**Filter chip row.** Pills, unselected transparent with a hairline border,
selected filled `--accent`. `ALL / APOLLO / SOVIET / MODERN / UPCOMING`.

**Three-column shell.** Left index panel, centre canvas, right detail panel.
Used on both Registry and Simulation. This is the right shell for the game's
market screen too: node list, order book, position detail.

**Oversized two-tone heading.** `ARK INTEL` — first word in `--text`, second
in `--accent`, 64px+, tight tracking. The bible's "oversized kinetic
typography", already solved.

**Confidence bar.** Thin gradient rail, cyan → violet, with the percentage
in `--cyan` at the right. Reused for any 0–100 quantity.

**Detail card.** Image, title, tag row, prose, then a 2-column grid of
labelled metric tiles. The Registry's `> MISSION INTEL` panel. This is
directly the shape of the game's node inspector.

**Typed edge chip.** `⚡ DEPENDS ON` in `--critical`, `⊞ SHARED TECH` in
`--cyan`, with a strength percentage right-aligned. See D24.
