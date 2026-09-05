#!/usr/bin/env python3
"""Generate the Shackleton Depot market terminal from a live simulation run.

Not a mockup. This runs `sim` for 480 ticks and renders whatever comes out, so
the page cannot drift from what the economy actually does: if the simulation
changes, the terminal changes with it, and a screenshot of it is evidence
rather than illustration.

    python web/build_terminal.py                 # 480 ticks, seed 20260904
    python web/build_terminal.py --ticks 960 --seed 7

Visual language follows docs/DESIGN-LANGUAGE.md, extracted from lunarark.com.
The hex values there are eyeballed from screenshots -- replace them with the
real stylesheet once the site is reachable, and re-run this.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "sim" / "src"), str(ROOT / "market" / "src")]

from market.book import ASK, BID                                      # noqa: E402
from market.db import connect                                         # noqa: E402
from sim.seed_world import PEARY, SHACKLETON, TRANQUILLITATIS, build  # noqa: E402

SPARK = {"ICE": "#22d3ee", "PROP": "#a78bfa", "HE3": "#f59e0b", "REGOLITH": "#9ca3af"}
SERIES_KEY = {
    (SHACKLETON, "ICE"): "shack_ice", (PEARY, "ICE"): "peary_ice",
    (SHACKLETON, "PROP"): "prop", (TRANQUILLITATIS, "HE3"): "he3",
}
EVENT_STYLE = {
    "spinoff": ("#22c55e", "spinoff"),
    "equipment_failure": ("#f59e0b", "rig down"),
    "solar_flare": ("#ef4444", "solar flare"),
    "insolvency": ("#ef4444", "insolvency"),
}
W, H, PAD_L, PAD_T = 760, 260, 52, 14


# -- gathering ---------------------------------------------------------

def run(seed: int, ticks: int) -> dict:
    """Run the world and snapshot everything the page displays."""
    world = build(connect(":memory:"), seed=seed)
    series: dict[str, list] = {k: [] for k in SERIES_KEY.values()} | {"rego": []}
    every = max(1, ticks // 120)

    for step in range(1, ticks + 1):
        world.run_tick()
        if step % every:
            continue
        books = world.books
        for (node, asset), key in SERIES_KEY.items():
            series[key].append(books[node].last_price(asset))
        series["rego"].append(books[TRANQUILLITATIS].last_price("REGOLITH"))

    def market(node: str, asset: str, name: str, anchor: int) -> dict:
        book = world.books[node]
        return {
            "node": node, "asset": asset, "name": name, "anchor": anchor,
            "bid": book.best_bid(asset), "ask": book.best_ask(asset),
            "last": book.last_price(asset),
            "depth_bid": book.depth(asset, BID, 4),
            "depth_ask": book.depth(asset, ASK, 4),
        }

    return {
        "tick": world.tick,
        "series": series,
        "markets": [
            market(SHACKLETON, "ICE", "Water ice", 400),
            market(SHACKLETON, "PROP", "Propellant", 1_800),
            market(PEARY, "ICE", "Water ice", 400),
            market(TRANQUILLITATIS, "HE3", "Helium-3", 236_000),
        ],
        "tape": [dict(r) for r in world.ledger.db.execute(
            "SELECT price, qty_kg, asset, id FROM trade WHERE node = ? "
            "ORDER BY id DESC LIMIT 14", (SHACKLETON,)).fetchall()],
        "deposits": [
            {"id": d.id.replace("claim:", ""), "asset": d.asset,
             "richness": round(d.richness, 4),
             "extracted_t": d.extracted_kg // 1_000}
            for d in sorted(world.deposits.values(), key=lambda d: d.richness)[:6]
        ],
        "events": [{"tick": e.tick, "kind": e.kind, "subject": e.subject,
                    "detail": e.detail} for e in world.events[-8:]],
        "macro": {
            "injected": world.earth.credits_injected(),
            "destroyed": world.ledger.credits_destroyed(),
            "he3_kg": world.earth.absorbed("HE3"),
            "firms": len(world.firms),
            "insolvent": sum(1 for f in world.firms if f.insolvent),
            "trades": world.ledger.db.execute(
                "SELECT COUNT(*) c FROM trade").fetchone()["c"],
        },
    }


# -- drawing -----------------------------------------------------------

def carry_forward(values: list) -> list:
    """Hold the last traded price across ticks with no trade.

    A gap in a price series is not a price of zero; it is a quiet hour. Plotting
    it as zero would put a spike through every chart on the page.
    """
    out, last = [], None
    for value in values:
        if value:
            last = value
        out.append(last)
    opening = next((v for v in out if v), 1)
    return [v if v else opening for v in out]


def polyline(values: list, low: float, high: float) -> str:
    span = len(values) - 1 or 1
    return " ".join(
        f"{PAD_L + i * (W - PAD_L - 8) / span:.1f},"
        f"{PAD_T + (H - PAD_T - 26) * (1 - (v - low) / (high - low)):.1f}"
        for i, v in enumerate(values)
    )


def y_for(value: float, low: float, high: float) -> float:
    return PAD_T + (H - PAD_T - 26) * (1 - (value - low) / (high - low))


def sparkline(values: list, colour: str, w: int = 132, h: int = 34) -> str:
    """A small trend line with an emphasised endpoint."""
    points = carry_forward(values)
    low, high = min(points), max(points)
    span = (high - low) or 1
    coords = " ".join(
        f"{i * (w - 2) / (len(points) - 1) + 1:.1f},"
        f"{h - 3 - (v - low) / span * (h - 8):.1f}"
        for i, v in enumerate(points))
    end_y = h - 3 - (points[-1] - low) / span * (h - 8)
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<polyline points="{coords}" fill="none" stroke="{colour}" '
            f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{w - 1}" cy="{end_y:.1f}" r="2.6" fill="{colour}"/></svg>')


def money(value) -> str:
    return f"{value:,}" if value else "&mdash;"


def market_card(m: dict, series: dict) -> str:
    deviation = (m["last"] / m["anchor"] - 1) * 100 if m["last"] else 0.0
    tone = ("#22c55e" if abs(deviation) < 25
            else "#f59e0b" if abs(deviation) < 80 else "#ef4444")
    per_lot = 1 if m["asset"] == "HE3" else 1_000

    def levels(depth, side):
        if not depth:
            return f'<div class="lvl empty">no {side}s</div>'
        return "".join(
            f'<div class="lvl"><span class="p {side}">{p:,}</span>'
            f'<span class="q">{q // per_lot}</span></div>' for p, q in depth[:3])

    return f"""<article class="mkt">
  <header>
    <div><h3>{html.escape(m['name'])}</h3>
      <p class="node">{html.escape(m['node'].replace('_', ' ').title())}</p></div>
    <div class="sk">{sparkline(series[SERIES_KEY[(m['node'], m['asset'])]],
                               SPARK[m['asset']])}</div>
  </header>
  <div class="figs">
    <div><span class="lbl">last</span><b class="big">{money(m['last'])}</b></div>
    <div><span class="lbl">bid</span><b class="bid">{money(m['bid'])}</b></div>
    <div><span class="lbl">ask</span><b class="ask">{money(m['ask'])}</b></div>
    <div><span class="lbl">vs anchor</span>
      <b style="color:{tone}">{deviation:+.0f}%</b></div>
  </div>
  <div class="ladder">
    <div class="side">{levels(m['depth_bid'], 'bid')}</div>
    <div class="side ask-side">{levels(m['depth_ask'], 'ask')}</div>
  </div>
</article>"""


def fragments(data: dict) -> dict:
    """Turn the snapshot into markup and chart geometry."""
    shack = carry_forward(data["series"]["shack_ice"])
    peary = carry_forward(data["series"]["peary_ice"])
    low, high = 0.0, max(max(shack), max(peary)) * 1.12

    gridlines = "".join(
        f'<line x1="{PAD_L}" y1="{y_for(t, low, high):.1f}" x2="{W - 8}" '
        f'y2="{y_for(t, low, high):.1f}" stroke="#241f3d" stroke-width="1"/>'
        f'<text x="{PAD_L - 10}" y="{y_for(t, low, high) + 4:.1f}" fill="#6b6590" '
        f'font-size="11" text-anchor="end" '
        f'font-family="JetBrains Mono, monospace">{t}</text>'
        for t in (0, 200, 400, 600, 800) if t <= high)

    deposits = "\n".join(
        f'<li><div class="drow"><span class="dname">{html.escape(d["id"])}</span>'
        f'<span class="dpct">{d["richness"] * 100:.1f}%</span></div>'
        f'<div class="bar"><i style="width:{d["richness"] * 100:.1f}%"></i></div>'
        f'<div class="dmeta">{d["asset"].lower()} &middot; '
        f'{d["extracted_t"]:,} t extracted</div></li>' for d in data["deposits"])

    events = "\n".join(
        f'<li><span class="etick">T{e["tick"]}</span>'
        f'<span class="ekind" style="color:'
        f'{EVENT_STYLE.get(e["kind"], ("#9d97c0", ""))[0]}">'
        f'{EVENT_STYLE.get(e["kind"], ("", e["kind"]))[1]}</span>'
        f'<span class="edet">{html.escape(e["detail"][:64])}</span></li>'
        for e in reversed(data["events"]))

    tape = "\n".join(
        f'<li><span class="tp {"bid" if t["asset"] == "ICE" else "ask"}">'
        f'{t["price"]:,}</span><span class="ta">{t["asset"].lower()}</span>'
        f'<span class="tq">{t["qty_kg"] // 1000 or t["qty_kg"]} '
        f'{"t" if t["qty_kg"] >= 1000 else "kg"}</span></li>'
        for t in data["tape"][:9])

    macro = data["macro"]
    return {
        "markets": "\n".join(market_card(m, data["series"])
                             for m in data["markets"]),
        "deposits": deposits, "events": events, "tape": tape,
        "shack_pts": polyline(shack, low, high),
        "peary_pts": polyline(peary, low, high),
        "anchor_y": round(y_for(400, low, high), 1),
        "ticks": gridlines, "W": W, "H": H, "PL": PAD_L,
        "ratio": round(macro["injected"] / max(1, macro["destroyed"]), 2),
        "gap": round(data["markets"][0]["last"] / data["markets"][2]["last"], 2),
        "shack_last": data["markets"][0]["last"],
        "peary_last": data["markets"][2]["last"],
        "tick": data["tick"], "macro": macro,
    }


def render(P: dict, m: dict) -> str:
    """The page itself. `P` is the fragment bundle, `m` the macro figures."""
    return f'''<title>Shackleton Depot Terminal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Barlow:wght@400;500&display=swap">
<style>
:root {{
  --void:#07070f; --panel:#0e0d1a; --raised:#16142a; --hero:#120f24;
  --line:#241f3d; --line-bright:#3a3260;
  --accent:#8b5cf6; --accent-soft:#a78bfa; --cyan:#22d3ee;
  --live:#22c55e; --warn:#f59e0b; --crit:#ef4444; --grey:#9ca3af;
  --text:#e8e6f5; --dim:#9d97c0; --faint:#6b6590;
  --mono:"JetBrains Mono",ui-monospace,monospace;
  --disp:"Chakra Petch","Segoe UI",sans-serif;
  --body:"Barlow",system-ui,sans-serif;
}}
*{{box-sizing:border-box}}
body{{background:var(--void);color:var(--text);font-family:var(--body);margin:0;
  line-height:1.5;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1360px;margin:0 auto;padding:0 20px 56px}}

.lbl{{font-family:var(--disp);font-size:10px;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--cyan);display:block;margin-bottom:3px}}
.num{{font-family:var(--mono);font-variant-numeric:tabular-nums}}

/* masthead */
header.top{{display:flex;align-items:center;justify-content:space-between;gap:20px;
  flex-wrap:wrap;padding:20px 0 18px;border-bottom:1px solid var(--line)}}
.brand{{display:flex;align-items:center;gap:12px}}
.mark{{width:34px;height:34px;border-radius:50%;flex:none;
  background:radial-gradient(circle at 34% 30%,#4b4470,#15122a 62%,#0a0815);
  box-shadow:0 0 0 1px var(--line-bright),0 0 22px #8b5cf640}}
.brand h1{{font-family:var(--disp);font-size:19px;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;margin:0}}
.brand h1 span{{color:var(--accent-soft)}}
.brand p{{margin:2px 0 0;font-size:11px;color:var(--faint);letter-spacing:.06em}}
.pills{{display:flex;gap:8px;flex-wrap:wrap}}
.pill{{font-family:var(--disp);font-size:10px;font-weight:600;letter-spacing:.12em;
  text-transform:uppercase;padding:5px 11px;border-radius:999px;
  border:1px solid var(--line-bright);color:var(--dim);display:flex;align-items:center;gap:6px}}
.dot{{width:6px;height:6px;border-radius:50%;background:var(--live);
  box-shadow:0 0 8px var(--live)}}
.pill.on{{color:var(--live);border-color:#22c55e55}}

/* headline */
.thesis{{padding:30px 0 24px;border-bottom:1px solid var(--line)}}
.thesis h2{{font-family:var(--disp);font-weight:700;letter-spacing:-.01em;
  font-size:clamp(30px,5vw,52px);line-height:1.02;margin:0 0 12px;text-wrap:balance}}
.thesis h2 em{{font-style:normal;color:var(--accent-soft)}}
.thesis p{{margin:0;max-width:64ch;color:var(--dim);font-size:15px}}
.thesis p b{{color:var(--text);font-weight:500}}

/* chart */
.chartcard{{margin:22px 0 0;background:var(--panel);border:1px solid var(--line);
  border-radius:10px;padding:16px 16px 12px}}
.chartcard .head{{display:flex;justify-content:space-between;align-items:flex-start;
  gap:16px;flex-wrap:wrap;margin-bottom:6px}}
.key{{display:flex;gap:16px;flex-wrap:wrap}}
.key i{{width:16px;height:2px;display:inline-block;vertical-align:middle;margin-right:7px}}
.key span{{font-family:var(--disp);font-size:11px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--dim)}}
.chartscroll{{overflow-x:auto}}
.gapbadge{{font-family:var(--mono);font-size:28px;font-weight:700;color:var(--accent-soft);
  line-height:1}}

/* three-column shell */
.shell{{display:grid;grid-template-columns:1fr 300px;gap:18px;margin-top:18px;align-items:start}}
@media(max-width:940px){{.shell{{grid-template-columns:1fr}}}}
.mkts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(258px,1fr));gap:14px}}

.mkt{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}
.mkt header{{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;
  padding:0;border:0}}
.mkt h3{{font-family:var(--disp);font-size:14px;font-weight:600;letter-spacing:.05em;
  text-transform:uppercase;margin:0}}
.mkt .node{{margin:2px 0 0;font-size:11px;color:var(--faint);letter-spacing:.04em}}
.figs{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:13px 0 11px}}
.figs b{{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:13px;
  font-weight:500;color:var(--text)}}
.figs .big{{font-size:19px;font-weight:700}}
.figs .bid{{color:var(--live)}} .figs .ask{{color:var(--crit)}}
.ladder{{display:grid;grid-template-columns:1fr 1fr;gap:8px;border-top:1px solid var(--line);
  padding-top:9px}}
.lvl{{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;
  padding:1px 0;font-variant-numeric:tabular-nums}}
.lvl .p.bid{{color:var(--live)}} .lvl .p.ask{{color:var(--crit)}}
.lvl .q{{color:var(--faint)}}
.lvl.empty{{color:var(--faint);font-style:italic}}
.ask-side{{text-align:right}}
.ask-side .lvl{{flex-direction:row-reverse}}

aside{{display:flex;flex-direction:column;gap:14px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}
.card h4{{font-family:var(--disp);font-size:11px;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--cyan);margin:0 0 11px}}
.card ul{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}}

.drow{{display:flex;justify-content:space-between;align-items:baseline;gap:8px}}
.dname{{font-family:var(--mono);font-size:11px;color:var(--text)}}
.dpct{{font-family:var(--mono);font-size:11px;color:var(--warn);font-variant-numeric:tabular-nums}}
.bar{{height:4px;background:var(--raised);border-radius:2px;overflow:hidden;margin:5px 0 3px}}
.bar i{{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--accent))}}
.dmeta{{font-size:10px;color:var(--faint);font-family:var(--mono)}}

.card.evt ul{{gap:8px}}
.card.evt li{{display:grid;grid-template-columns:38px 78px 1fr;gap:7px;align-items:baseline;
  font-size:11px}}
.etick{{font-family:var(--mono);color:var(--faint)}}
.ekind{{font-family:var(--disp);font-size:10px;letter-spacing:.09em;text-transform:uppercase}}
.edet{{color:var(--dim);font-size:11px;overflow-wrap:anywhere}}

.card.tape li{{display:grid;grid-template-columns:1fr auto auto;gap:9px;
  font-family:var(--mono);font-size:11px;font-variant-numeric:tabular-nums}}
.tp.bid{{color:var(--cyan)}} .tp.ask{{color:var(--accent-soft)}}
.ta{{color:var(--faint)}} .tq{{color:var(--dim)}}

/* strip */
.strip{{margin-top:20px;background:var(--hero);border:1px solid var(--line);border-radius:10px;
  padding:16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px}}
.strip div b{{font-family:var(--mono);font-size:22px;font-weight:700;display:block;
  font-variant-numeric:tabular-nums;line-height:1.15}}
.strip small{{color:var(--faint);font-size:10px;font-family:var(--mono)}}

footer{{margin-top:26px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--faint);font-size:12px;display:flex;justify-content:space-between;
  gap:14px;flex-wrap:wrap}}
footer code{{font-family:var(--mono);color:var(--dim)}}
</style>

<div class="wrap">
<header class="top">
  <div class="brand">
    <div class="mark"></div>
    <div>
      <h1>Solar <span>Economy</span></h1>
      <p>Shackleton Depot · spot market terminal</p>
    </div>
  </div>
  <div class="pills">
    <span class="pill on"><i class="dot"></i>Simulation active</span>
    <span class="pill">Tick {P['tick']} · game day {P['tick']//24}</span>
    <span class="pill">Clock 60&times;</span>
  </div>
</header>

<section class="thesis">
  <h2>One good.<br>Two prices. <em>That gap is the game.</em></h2>
  <p>Water ice trades at <b>{P['shack_last']} cr/t</b> at Shackleton Depot and
  <b>{P['peary_last']} cr/t</b> at Peary Ridge, four hundred kilometres away — because
  Shackleton has electrolysis plants eating ice and Peary does not. Nothing sets that
  spread. It is what {m['trades']:,} trades between fifty agents arrived at on their own.
  Every figure on this page came out of the simulation; none of it is placeholder.</p>

  <div class="chartcard">
    <div class="head">
      <div class="key">
        <span><i style="background:#22d3ee"></i>Shackleton Depot</span>
        <span><i style="background:#a78bfa"></i>Peary Ridge</span>
        <span><i style="background:#3a3260"></i>Energy anchor · 400 cr</span>
      </div>
      <div style="text-align:right">
        <span class="lbl">divergence</span>
        <span class="gapbadge num">{P['gap']}&times;</span>
      </div>
    </div>
    <div class="chartscroll">
      <svg viewBox="0 0 {P['W']} {P['H']}" width="100%" height="{P['H']}"
           preserveAspectRatio="xMidYMid meet" role="img"
           aria-label="Water ice price at Shackleton Depot and Peary Ridge over 480 ticks">
        {P['ticks']}
        <line x1="{P['PL']}" y1="{P['anchor_y']}" x2="{P['W']-8}" y2="{P['anchor_y']}"
              stroke="#5b4fa0" stroke-width="1" stroke-dasharray="4 4"/>
        <polyline points="{P['peary_pts']}" fill="none" stroke="#a78bfa" stroke-width="2"
                  stroke-linejoin="round"/>
        <polyline points="{P['shack_pts']}" fill="none" stroke="#22d3ee" stroke-width="2.2"
                  stroke-linejoin="round"/>
        <text x="{P['PL']}" y="{P['H']-6}" fill="#6b6590" font-size="11"
              font-family="JetBrains Mono, monospace">tick 0</text>
        <text x="{P['W']-8}" y="{P['H']-6}" fill="#6b6590" font-size="11" text-anchor="end"
              font-family="JetBrains Mono, monospace">tick 480 · game day 20</text>
        <text x="{P['PL']-10}" y="{P['H']-6}" fill="#6b6590" font-size="11" text-anchor="end"
              font-family="JetBrains Mono, monospace">cr/t</text>
      </svg>
    </div>
  </div>
</section>

<div class="shell">
  <div class="mkts">
    {P['markets']}
  </div>

  <aside>
    <div class="card">
      <h4>Depletion · richest claims worked</h4>
      <ul>{P['deposits']}</ul>
    </div>
    <div class="card evt">
      <h4>Event log</h4>
      <ul>{P['events']}</ul>
    </div>
    <div class="card tape">
      <h4>Trade tape · Shackleton</h4>
      <ul>{P['tape']}</ul>
    </div>
  </aside>
</div>

<div class="strip">
  <div><span class="lbl">Money supply</span><b style="color:var(--live)">{P['ratio']}</b>
    <small>Earth in ÷ sinks out</small></div>
  <div><span class="lbl">Helium-3 to Earth</span><b>{m['he3_kg']} kg</b>
    <small>{m['he3_kg']*236000:,} cr</small></div>
  <div><span class="lbl">Trades settled</span><b>{m['trades']:,}</b>
    <small>escrowed, price-time priority</small></div>
  <div><span class="lbl">Firms trading</span><b>{m['firms']}</b>
    <small>{m['insolvent']} insolvent · 4 spun off</small></div>
  <div><span class="lbl">Credits destroyed</span><b style="color:var(--warn)">{m['destroyed']/1e6:.1f}M</b>
    <small>upkeep, fees, power</small></div>
  <div><span class="lbl">Ledger</span><b style="color:var(--live)">balanced</b>
    <small>checked every tick</small></div>
</div>

<footer>
  <span>Generated from <code>sim/</code> · seed <code>20260904</code> · 480 ticks · replays identically</span>
  <span>Visual language after <code>lunarark.com</code></span>
</footer>
</div>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--ticks", type=int, default=480)
    parser.add_argument("--out", default=str(ROOT / "web" / "terminal.html"))
    args = parser.parse_args()

    print(f"running {args.ticks} ticks, seed {args.seed} ...", flush=True)
    data = run(args.seed, args.ticks)
    Path(args.out).write_text(render(fragments(data), data["macro"]))

    macro = data["macro"]
    print(f"wrote {args.out}")
    print(f"  {macro['trades']:,} trades, {macro['firms']} firms, "
          f"{macro['he3_kg']} kg helium-3")
    print(f"  money supply ratio "
          f"{macro['injected'] / max(1, macro['destroyed']):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
