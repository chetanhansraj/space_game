/* The base: one company's site on the Moon, seen from just above it.
 *
 * This page renders and submits intent, nothing more (invariant 1). Every
 * module, every status, every tonne and every credit on it came from
 * /api/base. Three things are worked out here and all three are display: the
 * minute hand between server ticks, which of the server's status codes is
 * worth a sentence from the crew, and the ghost under the cursor. A click is
 * a request the server validates and may refuse.
 *
 * Scroll out far enough and the view rises to the Moon, which is the trade
 * game: same world, same company, same clock, one altitude up.
 */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const KEY = "lunarark.key";
  const S = {
    token: null, v: null, tool: null, sel: null, drawer: null, cat: null,
    cam: { x: 0, y: 0, s: 0.3 }, target: 0.95, hover: null, ptr: new Map(), drag: null,
    paint: null, rise: 0, sure: null, welcomed: false, leaving: false,
  };
  try { S.token = localStorage.getItem(KEY); } catch (e) { /* private mode */ }

  // -- helpers ------------------------------------------------------------------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const n0 = (n) => Math.round(n || 0).toLocaleString("en-US");
  const cr = (n) => `${n0(n)} cr`;
  const t1 = (kg) => { const v = (kg || 0) / 1000; return v >= 100 ? n0(v) : v.toFixed(1); };
  const NAMES = { ICE: "Water ice", PROP: "Propellant", FOOD: "Food" };
  const B = () => S.v && S.v.base;
  const spec = (type) => S.v.catalog.find((c) => c.id === type);

  function toast(msg, bad) {
    const el = $("#toast");
    el.textContent = msg; el.className = "show" + (bad ? " bad" : "");
    clearTimeout(toast.t); toast.t = setTimeout(() => { el.className = ""; }, bad ? 4200 : 2400);
  }

  async function api(path, body) {
    const opts = { headers: {} };
    if (S.token) opts.headers.Authorization = "Bearer " + S.token;
    if (body !== undefined) {
      opts.method = "POST"; opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch("/api" + path, opts);
    if (r.status === 401) { gate("nokey"); throw new Error("Sign in on the Moon map first."); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "The server refused that.");
    return j;
  }

  async function act(path, body, ok) {
    try {
      const j = await api(path, body);
      if (j && "base" in j) { S.v = j; draw(); } else await refresh();
      if (ok) toast(typeof ok === "function" ? ok(j) : ok);
      return j;
    } catch (e) { toast(e.message, true); return null; }
  }

  async function refresh() {
    if (S.leaving) return;
    const inDrawer = $("#drawer").contains(document.activeElement) && document.activeElement.tagName === "INPUT";
    S.v = await api("/base");
    draw(inDrawer);
  }

  // -- what the statuses mean ------------------------------------------------------
  const STATE = {
    on: ["g", "Running."],
    dusty: ["a", "Running at half power. It is standing in a digger's dust."],
    hot: ["a", "Throttled. The radiators cannot reject all the heat."],
    assembling: ["a", "Being assembled."],
    new: ["a", "Just placed. It joins the base on the next hour."],
    unlinked: ["r", "Not linked. Nothing leads from it back to the command post."],
    no_command: ["r", "Waiting for a staffed command post."],
    no_power: ["r", "Switched off. There is not enough power for it."],
    no_crew: ["r", "Nobody is free to run it."],
    flare: ["a", "Stood down for the solar flare."],
    suspended: ["r", "Stood down. The Ark is owed money."],
    no_ice: ["r", "Standing on bare ground. A miner only digs on ice."],
    worked_out: ["r", "The ice under it is worked out."],
    full: ["a", "Stopped. There is nowhere to put what it makes."],
    no_feed: ["r", "Idle. There is no ice to feed it."],
  };
  const DOT = { g: "#34d399", a: "#fbbf24", r: "#f87171" };
  const LOOK = {
    solar: ["#234a8c", 4, 0.05, "#cfe0ff", "SO"], battery: ["#3f8f63", 12, 0.18, "#06200f", "BA"],
    radiator: ["#c9d3ea", 18, 0.3, "#1b2238", "RA"], hab: ["#e2ded5", 18, 0.08, "#2b2a33", "HB"],
    airlock: ["#b9b3a6", 11, 0.22, "#2b2a33", "AL"], eclss: ["#69b4e3", 20, 0.14, "#06202f", "LS"],
    warehouse: ["#8a7f6a", 14, 0.06, "#1c170d", "WH"], tankfarm: ["#b5def4", 17, 0.2, "#0b2836", "TK"],
    cryo: ["#4a78dc", 21, 0.14, "#e6eeff", "CR"], ice_miner: ["#d2a84c", 14, 0.1, "#2a1e05", "IM"],
    electrolysis: ["#c084fc", 25, 0.1, "#1e0b38", "EL"], command: ["#e9e4d6", 24, 0.12, "#0a1c38", "CP"],
    comms: ["#94a3b8", 30, 0.32, "#0f172a", "CM"],
    hydroponics: ["#58b874", 13, 0.07, "#06220f", "HY"], recycler: ["#3a9bb0", 14, 0.2, "#031d22", "WR"],
  };
  const CATS = [["kit", "KIT"], ["power", "POWER"], ["thermal", "COOLING"], ["crew", "LIFE"],
    ["storage", "STORAGE"], ["industry", "INDUSTRY"], ["control", "CONTROL"], ["conduit", "CONDUIT"]];

  // -- the crew: which fact is worth saying ------------------------------------------
  function advice() {
    const b = B(), mods = b.modules, has = (s) => mods.some((m) => m.status === s);
    const r = b.report || {}, pw = r.power || [0, 0], ht = r.heat || [0, 0];
    const kit = () => act("/base/kit", {}, "Lena is standing the kit. Modules come up over the next few hours.");
    if (b.money.owed > 0) return ["RA", "Rafael", "The works have stood down",
      `We could not make the day's lease, wear and payroll, so the plant and the diggers are stopped. We owe ${cr(b.money.owed)}. It settles itself the hour the money is there.`];
    const P = b.people, here = P.residents.length, need = (b.report || {}).needs || {};
    const settled = !b.crates.length && b.milestones.some((m) => m.id === "desk" && m.done);
    if (settled && need.water === false) return ["KE", "Kenji", "We are out of water",
      "There is no ice in stock, and ice is our water and our air. Get a miner digging, or buy ice in the Market drawer. A day without it and people start going home."];
    if (settled && need.food === false) return ["KE", "Kenji", "We are short of food",
      `The bays grow food for ${P.fed} and there are ${here} of us. Each Hydroponics bay feeds six and needs two people and 60 kW. Nobody new comes while anyone is hungry.`];
    if (settled && need.air === false) return ["KE", "Kenji", "More people than air",
      `There are ${here} of us and berths with air for ${P.housed}. A hab adds six berths; a life support unit keeps eight. The newest will leave on the shuttle.`];
    if (b.crates.includes("command") && !mods.some((m) => m.type === "command")) return ["AS", "Asha", "Stand the command post",
      "Everything on site has to link back to it. Take it from the Kit tray below and click open ground, or let Lena stand the whole kit and rearrange it afterwards.",
      ["Stand it all for me", kit]];
    if (b.crates.length) return ["LE", "Lena", `${b.crates.length} crates still packed`,
      "A crate costs nothing until it is standing. Life support first, then the plant. Put the miners on the blue ice and keep solar arrays two tiles clear of them.",
      ["Stand the rest for me", kit]];
    if (has("unlinked")) return ["LE", "Lena", "Something is not linked",
      "A module with a red dot touches nothing that leads to the command post, so it does nothing. Move it up against the others, or lay Conduit out to it."];
    if (has("no_ice")) return ["RA", "Rafael", "A miner is on bare ground",
      "An ice miner only digs on the blue patches. The percentage on each patch is how rich its ice is. Select the miner and press Move."];
    if (has("no_crew")) return ["AS", "Asha", "We are short of hands",
      `The modules standing need ${(r.crew || [0, 0, 0])[2]} people and ${here} live here. Life support, the desk and the farm are staffed first. Make room and food for more, and the shuttle brings two a day.`];
    if (has("no_power")) return ["LE", "Lena", "We are short of power",
      `We can generate ${pw[1]} kW and everything standing wants more, so I switched the diggers off first. Add solar arrays, or move the ones marked amber out of the dust.`];
    if (S.v.flaring) return ["AS", "Asha", "Solar flare",
      "The plant and the diggers are stood down and everyone is under cover. Air and power stay on. It passes on its own."];
    if (has("hot")) return ["LE", "Lena", "The works are running hot",
      `We make ${ht[0]} kW of heat and reject ${ht[1]}, so the plant and the diggers are throttled back. One more Radiator panel fixes it.`];
    if (has("no_feed")) return ["RA", "Rafael", "The plant is out of ice",
      "It wants 30 t a day and is getting less. Move a miner onto richer ice, lease another miner, or raise the price we pay for ice in the Market drawer."];
    if (has("full")) {
      const bid = ((S.v.prices.PROP || {}).bid), floor = b.policy.PROP.min_price;
      return ["RA", "Rafael", "Nowhere to put it",
        !b.policy.PROP.sell ? "Storage is full and automatic selling is off. Sell some in the Market drawer, or build a tank farm and liquefaction to hold more."
          : `Storage is full. The best bid for propellant is ${bid ? cr(bid) : "nobody's"} and we hold out for ${cr(floor)}. Lower the floor, or build tanks and wait.`];
    }
    if (has("worked_out")) return ["RA", "Rafael", "A patch is worked out",
      "One miner is bringing up almost nothing. Move it to a patch that still shows a high percentage left."];
    const building = mods.filter((m) => m.status === "assembling" || m.status === "new");
    if (building.length) {
      const h = Math.max(1, ...building.map((m) => m.ready - S.v.tick));
      return ["LE", "Lena", `Assembling ${building.length} module${building.length > 1 ? "s" : ""}`,
        `Everything is up within ${h} game hour${h > 1 ? "s" : ""}. The bar under the date is the hour passing.`];
    }
    const patches = b.layout.patches;
    const on = (m) => patches.find((p) => p.tiles.some((t) => t[0] === m.x && t[1] === m.y));
    const used = new Set(mods.filter((m) => m.type === "ice_miner").map((m) => (on(m) || {}).id));
    const best = patches.filter((p) => !used.has(p.id)).sort((a, c) => c.grade * c.richness - a.grade * a.richness)[0];
    const worst = mods.filter((m) => m.type === "ice_miner").map(on).filter(Boolean)
      .sort((a, c) => a.grade * a.richness - c.grade * c.richness)[0];
    if (best && worst && best.grade * best.richness > worst.grade * worst.richness * 1.25) return ["RA", "Rafael", "There is richer ice",
      `One miner is on ${worst.grade}% ice. The ${best.grade}% patch further out would give more for the same power. Select the miner, press Move, then run Conduit to it.`];
    if (has("dusty")) return ["LE", "Lena", "Dust on the arrays",
      "The solar arrays marked amber stand within two tiles of a digger and give half their power. We have the margin for now. Move them when we need it."];
    const limit = Math.min(P.housed, P.fed);
    if (settled && here >= limit) {
      const short = P.fed <= P.housed ? "food: one more Hydroponics bay feeds six more"
        : "berths with air: a hab adds six berths, a life support unit keeps eight people";
      return ["AS", "Asha", `The town is full at ${here}`,
        `More people means more hands for industry, and the Ark leases a bigger town more plant. What holds us at ${here} is ${short}.`];
    }
    if (settled && here < limit) return ["AS", "Asha", "Room for more people",
      `We can house and feed ${limit} and there are ${here} of us. The shuttle brings up to ${P.arrivals_per_day} a day, at game midnight, if nobody went without air, water or food.`];
    const next = b.milestones.find((m) => !m.done);
    if (next) return ["AS", "Asha", `Next: ${next.title.toLowerCase()}`,
      `The Ark pays a ${cr(next.bonus)} development bonus for it. The Goals drawer has the full list.`];
    const y = b.books.yesterday || {};
    const net = (y.sales || 0) - (y.feed || 0) - (y.lease || 0) - (y.upkeep || 0) - (y.wages || 0);
    return ["AS", "Asha", "The works are running",
      `Yesterday we cleared ${cr(net)}. To grow: lease a third miner so we stop buying ice, or add liquefaction and a tank farm and sell when the price is high.`];
  }

  // -- drawing the HUD -------------------------------------------------------------
  function chip(id, html, cls) { const c = $(id); c.className = "chip " + (c.classList.contains("opt") ? "opt " : "") + (cls || ""); c.querySelector("b").innerHTML = html; }

  function draw(keepDrawer) {
    const v = S.v;
    if (!v) return;
    if (!v.base) { gate("charter"); return; }
    const b = v.base, r = b.report || {};
    ["#top", "#left", "#build"].forEach((s) => { $(s).hidden = false; });
    if ($("#gate").dataset.kind === "charter") $("#gate").hidden = true;
    $("#where").textContent = `${v.company} · ${b.site_name}`;
    $("#date").textContent = v.date;
    $("#flare").hidden = !v.flaring;
    const st = (s) => b.modules.some((m) => m.status === s);
    const pw = r.power || [0, 0], ht = r.heat || [0, 0], cw = r.crew || [0, 0, 0];
    chip("#cCash", n0(v.credits), b.money.owed ? "bad" : "");
    chip("#cPower", `${pw[0]} <small>/ ${pw[1]}</small>`, st("no_power") ? "bad" : "");
    chip("#cHeat", `${ht[0]} <small>/ ${ht[1]}</small>`, ht[0] > ht[1] ? "warn" : "");
    const nd = r.needs || {}, unhappy = nd.air === false || nd.water === false || nd.food === false;
    chip("#cCrew", `${b.people.residents.length} <small>/ ${cw[1]}</small>`, unhappy ? "bad" : st("no_crew") ? "warn" : "");
    chip("#cIce", t1(b.stock.ICE));
    chip("#cProp", `${t1(b.stock.PROP)} <small>/ ${t1(b.capacity.PROP)}</small>`, st("full") ? "warn" : "");

    const a = advice();
    $("#advice").innerHTML = `<div class="face">${a[0]}</div><div><div class="who">${a[1]}</div><h3>${esc(a[2])}</h3><p>${esc(a[3])}</p>${
      a[4] ? `<div class="act"><button class="btn cyan" id="advAct">${esc(a[4][0])}</button></div>` : ""}</div>`;
    if (a[4]) $("#advAct").onclick = a[4][1];

    document.querySelectorAll("#rail button").forEach((x) => x.classList.toggle("on", x.dataset.d === S.drawer));
    if (!keepDrawer) drawDrawer();
    drawBuild();
    drawInspect();
    if (!S.welcomed) { S.welcomed = true; welcomeBack(); }
  }

  function books(k) { const b = B().books; return [(b.today || {})[k] || 0, (b.yesterday || {})[k] || 0]; }

  function drawDrawer() {
    const el = $("#drawer"), b = B(), v = S.v;
    el.hidden = !S.drawer;
    if (!S.drawer) return;
    let h = "";
    if (S.drawer === "market") {
      h = `<h2>Market · ${esc(b.node_name)}</h2>`;
      for (const a of ["PROP", "ICE"]) {
        const p = v.prices[a] || {}, pol = b.policy[a], held = b.stock[a], cap = b.capacity[a];
        const whole = Math.floor(held / 1000);
        h += `<h3>${NAMES[a]}</h3>
          <div class="row"><span>In stock</span><b>${t1(held)} / ${t1(cap)} t</b></div>
          <div class="meter"><i style="width:${Math.min(100, cap ? held / cap * 100 : 0)}%"></i></div>
          <div class="row"><span>Bid / ask</span><b>${p.bid ? n0(p.bid) : "none"} / ${p.ask ? n0(p.ask) : "none"} cr</b></div>
          <div class="line"><button class="btn cyan" data-act="sell" data-a="${a}" ${whole && p.bid ? "" : "disabled"}>Sell ${whole} t now</button>
            ${a === "ICE" ? `<button class="btn" data-act="buy" data-a="ICE" ${p.ask ? "" : "disabled"}>Buy 10 t now</button>` : ""}</div>
          <div class="line"><input type="checkbox" data-pol="${a}.sell" ${pol.sell ? "checked" : ""}> Sell every hour, never below
            <input type="number" min="1" data-pol="${a}.min_price" value="${pol.min_price}"> cr</div>
          <div class="line">and always keep <input type="number" min="0" data-pol="${a}.keep_t" value="${pol.keep_t}"> t</div>`;
        if (a === "ICE") h += `<div class="line"><input type="checkbox" data-pol="ICE.buy" ${pol.buy ? "checked" : ""}> Buy every hour, paying up to
            <input type="number" min="1" data-pol="ICE.max_price" value="${pol.max_price}"> cr</div>
          <div class="line">until we hold <input type="number" min="0" data-pol="ICE.target_t" value="${pol.target_t}"> t</div>`;
      }
      h += `<div class="row" style="margin-top:10px"><span>${(b.report || {}).comms ? "Standing orders run each hour through the comms relay." : "No working comms relay: standing orders are not running."}</span></div>`;
    } else if (S.drawer === "money") {
      const line = (label, k, sign) => { const [t, y] = books(k); return `<div class="row"><span>${label}</span><b class="${sign > 0 ? "pos" : "neg"}">${t ? n0(t) : "0"} · ${y ? n0(y) : "0"}</b></div>`; };
      const net = (i) => books("sales")[i] + books("bonus")[i] - books("feed")[i] - books("wages")[i] - books("lease")[i] - books("upkeep")[i] - books("purchases")[i] - books("arrears_paid")[i];
      const m = b.money;
      h = `<h2>Money</h2><div class="row"><span></span><b>today · yesterday</b></div>
        ${line("Propellant and ice sold", "sales", 1)}${line("Ark bonuses", "bonus", 1)}${line("Ice bought", "feed", -1)}
        ${line("Payroll", "wages", -1)}${line("Lease", "lease", -1)}${line("Wear", "upkeep", -1)}${line("Bought from the Ark", "purchases", -1)}
        <div class="row total"><span>Net</span><b>${n0(net(0))} · ${n0(net(1))}</b></div>
        <h3>Every game day</h3>
        <div class="row"><span>Lease</span><b>${cr(m.lease_per_day)}</b></div>
        <div class="row"><span>Wear on everything standing</span><b>${cr(m.upkeep_per_day)}</b></div>
        <div class="row"><span>Payroll</span><b>${cr(m.wages_per_day)}</b></div>
        ${m.owed ? `<div class="row"><span>Owed to the Ark</span><b class="neg">${cr(m.owed)}</b></div>` : ""}
        <h3>The Ark's plant</h3>
        <div class="row"><span>On lease</span><b>${cr(m.leased_value)}</b></div>
        <div class="meter"><i style="width:${Math.min(100, m.leased_value / m.lease_cap * 100)}%"></i></div>
        <div class="row"><span>The most the Ark will lease a town this size</span><b>${cr(m.lease_cap)}</b></div>
        <div class="row"><span>It rises ${n0(m.lease_cap_per_resident)} with every resident after the founders.</span></div>
        <div class="row"><span>Plant you own</span><b>${cr(m.owned_value)}</b></div>
        <div class="row" style="margin-top:8px"><span>A game day is ${Math.round(24 * v.tick_seconds / 60)} real minutes. Charges are taken at game midnight.</span></div>`;
    } else if (S.drawer === "ship") {
      const s = b.ship;
      h = `<h2>Your Kestrel</h2>`;
      if (!s.docked_here) h += `<div class="row"><span>${s.state === "docked" ? "Docked at another port." : "In flight."} It loads and unloads here only while docked at ${esc(b.node_name)}.</span></div>`;
      else {
        h += `<div class="row"><span>Docked at ${esc(b.node_name)}</span><b>${t1(s.hold_room_kg)} t of hold free</b></div>`;
        for (const a of ["PROP", "ICE"]) h += `<h3>${NAMES[a]}</h3>
          <div class="row"><span>At the base</span><b>${t1(b.stock[a])} t</b></div>
          <div class="row"><span>Aboard${a === "PROP" ? ", fuel included" : ""}</span><b>${t1(s.aboard[a])} t</b></div>
          <div class="line"><input type="number" min="1" value="5" id="stow${a}"> t
            <button class="btn cyan" data-act="load" data-a="${a}">Load</button>
            <button class="btn" data-act="unload" data-a="${a}">Unload</button></div>`;
      }
      h += `<div class="line" style="margin-top:12px"><button class="btn ghost" data-act="moon">Fly it from the Moon map</button></div>
        <div class="row"><span>Propellant sells for more at ports that cannot make it. Load here, fly there.</span></div>`;
    } else if (S.drawer === "people") {
      const P = b.people, nd = (b.report || {}).needs || {}, cw = (b.report || {}).crew || [0, 0, 0];
      const toShuttle = Math.max(0, P.next_shuttle_tick - v.tick);
      const ok = (k, label) => `<div class="row"><span>${label}</span><b class="${nd[k] === false ? "neg" : "pos"}">${nd[k] === false ? "short" : "fine"}${P.unmet[k] ? ` · ${P.unmet[k]} h short today` : ""}</b></div>`;
      h = `<h2>People · ${P.residents.length}</h2>
        ${ok("air", "Air and a berth")}${ok("water", "Water")}${ok("food", "Food")}
        <h3>Room</h3>
        <div class="row"><span>Berths with air</span><b>${P.housed}</b></div>
        <div class="row"><span>The bays feed</span><b>${P.fed}</b></div>
        <div class="row"><span>At work / wanted</span><b>${cw[0]} / ${cw[2]}</b></div>
        <h3>The shuttle</h3>
        <div class="row"><span>Next one in</span><b>${toShuttle} game hours</b></div>
        ${P.shuttle ? `<div class="row"><span>Last one</span><b>${P.shuttle.came.length ? "brought " + esc(P.shuttle.came.join(", ")) : P.shuttle.left.length ? "took " + esc(P.shuttle.left.map((x) => x.name).join(", ")) + " home" : "brought no one"}</b></div>` : ""}
        <div class="row"><span>It brings up to ${P.arrivals_per_day} a day to a town with room and food for them, if nobody went without anything that day. ${P.unmet_hours_to_leave} hours short of something sends the newest home.</span></div>
        <h3>Who lives here</h3>` + P.residents.map((x) =>
          `<div class="row"><span>${esc(x.name)}${x.founder ? " ★" : ""}</span><b>${esc(x.trade)}</b></div>`).join("") +
        `<div class="row"><span>★ founded the site and will not leave.</span></div>`;
    } else if (S.drawer === "jobs") {
      const y = b.books.yesterday || {}, mine = b.jobs.filter((j) => j.mine).length;
      h = `<h2>Jobs · promises to other ports</h2>`;
      if (!b.jobs.length) h += `<div class="row"><span>Nobody at another port is asking for what we make right now. Jobs are posted when a firm runs short.</span></div>`;
      for (const j of b.jobs) {
        const left = j.deadline_tick - v.tick, have = b.stock[j.asset] || 0, rate = y["made_kg_" + j.asset] || 0;
        const short = Math.max(0, j.qty_kg - have);
        const ready = !short ? 0 : rate ? Math.ceil(short / rate * 24) : null;
        const fits = j.qty_kg <= (b.capacity[j.asset] || 0);
        const can = fits && ready != null && ready + (j.flight_ticks || 1) + 1 <= left;
        h += `<h3>${t1(j.qty_kg)} t ${NAMES[j.asset] || j.asset} to ${esc(j.node_name)}</h3>
          <div class="row"><span>Pays on delivery</span><b class="pos">${cr(j.payment)}</b></div>
          <div class="row"><span>Due in</span><b>${left} game hours</b></div>
          <div class="row"><span>We hold ${t1(have)} t${rate ? `, made ${t1(rate)} t yesterday` : ""}</span><b class="${can ? "pos" : "neg"}">${!fits ? "more than we can store" : !short ? "ready now" : ready == null ? "not making any" : `ready in ${ready} h`}</b></div>
          <div class="row"><span>Flight</span><b>${j.flight_ticks || "?"} game hour${j.flight_ticks > 1 ? "s" : ""}</b></div>
          <div class="line">${j.mine ? `<button class="btn red" data-act="abandon" data-id="${j.id}">Give it up</button><span>Promised, and held back from the market. Load it in the Ship drawer and fly it.</span>`
            : `<button class="btn cyan" data-act="accept" data-id="${j.id}" ${mine >= 3 ? "disabled" : ""}>Promise it</button>`}</div>`;
      }
      h += `<div class="row" style="margin-top:10px"><span>A promise is kept when your ship docks there with the goods before the hour runs out. You can hold three at once.</span></div>`;
    } else if (S.drawer === "goals") {
      h = `<h2>Ark development bonuses</h2>` + b.milestones.map((m) =>
        `<div class="goal ${m.done ? "done" : ""}"><i>${m.done ? "✓" : ""}</i><span>${esc(m.title)}</span><b>${n0(m.bonus)}</b></div>`).join("") +
        `<div class="row" style="margin-top:10px"><span>Each is paid once, out of the Ark's development fund.</span></div>`;
    }
    el.innerHTML = h;
  }

  function drawBuild() {
    const b = B(), cats = $("#cats"), tray = $("#tray");
    const counts = {}; b.crates.forEach((c) => { counts[c] = (counts[c] || 0) + 1; });
    if (S.cat === "kit" && !b.crates.length) S.cat = null;
    cats.innerHTML = CATS.filter(([id]) => id !== "kit" || b.crates.length).map(([id, name]) =>
      `<button data-c="${id}" class="${S.cat === id ? "on" : ""}">${name}${id === "kit" ? `<span class="n">${b.crates.length}</span>` : ""}</button>`).join("");
    tray.hidden = !S.cat;
    const hint = $("#hint");
    const t = S.tool;
    hint.hidden = !t;
    if (t) hint.textContent = t.kind === "conduit" ? "Drag across open ground to lay conduit · Esc to stop"
      : t.kind === "move" ? "Click open ground to stand it there · Esc to cancel"
        : `Click open ground to stand a ${spec(t.type).name} · Esc to stop`;
    $("#stage").classList.toggle("tool", !!t);
    if (!S.cat) return;
    const stat = (c) => `<b>${c.power_kw > 0 ? "+" : ""}${c.power_kw}</b> kW · <b>${c.heat_kw}</b> heat${c.crew ? ` · <b>${c.crew}</b> crew` : ""}`;
    let h = "";
    if (S.cat === "kit") {
      h = Object.keys(counts).map((id) => { const c = spec(id); return `<div class="card ${t && t.type === id && t.how === "crate" ? "on" : ""}">
        <h4>${esc(c.name)} × ${counts[id]}</h4><p>${esc(c.note)}</p><div class="st">${stat(c)}</div>
        <div class="two"><button class="btn cyan" data-tool="${id}" data-how="crate">Place<small>${n0(c.lease_per_day + c.upkeep_per_day)} a day</small></button></div></div>`; }).join("");
    } else if (S.cat === "conduit") {
      h = `<div class="card ${t && t.kind === "conduit" ? "on" : ""}"><h4>Conduit</h4><p>Links a module to the base across open ground. Carries power, air and data.</p>
        <div class="st"><b>${n0(b.money.conduit_cost)}</b> cr a tile</div>
        <div class="two"><button class="btn cyan" data-tool="conduit">Lay<small>drag on the ground</small></button></div></div>`;
    } else {
      h = S.v.catalog.filter((c) => c.group === S.cat).map((c) => `<div class="card ${t && t.type === c.id && t.how !== "crate" ? "on" : ""}">
        <h4>${esc(c.name)}</h4><p>${esc(c.note)}</p><div class="st">${stat(c)}</div>
        <div class="two"><button class="btn" data-tool="${c.id}" data-how="lease">Lease<small>${n0(c.lease_per_day + c.upkeep_per_day)} a day</small></button>
        <button class="btn cyan" data-tool="${c.id}" data-how="buy">Buy<small>${n0(c.cost)}</small></button></div></div>`).join("");
    }
    tray.innerHTML = h;
  }

  function drawInspect() {
    const el = $("#inspect"), b = B();
    const m = S.sel && S.sel.id ? b.modules.find((x) => x.id === S.sel.id) : null;
    const conduit = S.sel && S.sel.conduit && b.conduits.some((c) => c[0] === S.sel.conduit[0] && c[1] === S.sel.conduit[1]);
    el.hidden = !(m || conduit);
    if (conduit) {
      el.innerHTML = `<button class="x" data-act="close">✕</button><h2>Conduit</h2>
        <div class="state"><i style="background:${DOT.g}"></i><span>Links what it touches to the base.</span></div>
        <div class="acts"><button class="btn red" data-act="lift">Lift it</button></div>`;
      return;
    }
    if (!m) { S.sel = null; return; }
    const c = spec(m.type), [tone, text] = STATE[m.status] || ["a", m.status];
    let extra = "";
    if (m.status === "assembling") extra = ` Ready in ${Math.max(1, m.ready - S.v.tick)} game hour${m.ready - S.v.tick > 1 ? "s" : ""}.`;
    let rows = `<div class="row"><span>Power</span><b>${c.power_kw > 0 ? "+" : ""}${c.power_kw} kW</b></div>
      <div class="row"><span>Heat</span><b>${c.heat_kw} kW</b></div>${c.crew ? `<div class="row"><span>Crew</span><b>${c.crew}</b></div>` : ""}`;
    if (m.type === "ice_miner") {
      const p = b.layout.patches.find((q) => q.tiles.some((t) => t[0] === m.x && t[1] === m.y));
      rows += p ? `<div class="row"><span>Ice here</span><b>${p.grade}% grade · ${Math.round(p.richness * 100)}% left</b></div>
        <div class="row"><span>Brings up</span><b>${(12 * p.grade / 100 * p.richness).toFixed(1)} t a day</b></div>` : "";
    }
    rows += m.leased ? `<div class="row"><span>On lease from the Ark</span><b>${cr(c.lease_per_day + c.upkeep_per_day)} a day</b></div>`
      : `<div class="row"><span>Yours. Wear</span><b>${cr(c.upkeep_per_day)} a day</b></div>`;
    const sure = S.sure === m.id;
    el.innerHTML = `<button class="x" data-act="close">✕</button><h2>${esc(c.name)}</h2>
      <div class="state"><i style="background:${DOT[tone]}"></i><span>${esc(text + extra)}</span></div>${rows}
      <div class="acts"><button class="btn cyan" data-act="move">Move</button>
      ${m.leased ? `<button class="btn" data-act="buyout">Buy out · ${n0(c.cost)}</button>` : ""}
      <button class="btn red" data-act="remove">${sure ? (m.leased ? "Sure? It goes back" : "Sure? It is gone for good") : m.leased ? "Return to the Ark" : "Scrap"}</button></div>`;
  }

  // -- gates: no key, no base, back after a while ------------------------------------
  function gate(kind) {
    const g = $("#gate"), body = $("#gateBody"), v = S.v;
    if (g.dataset.kind === kind && !g.hidden) return;      // already showing
    g.dataset.kind = kind; g.hidden = false;
    if (kind === "nokey") {
      body.innerHTML = `<div class="lbl">Lunar Ark</div><h1>Found a company first</h1>
        <p>A base belongs to a company, and a company is founded on the Moon map. Take a charter there, then come back down.</p>
        <div class="acts"><a class="btn cyan" href="/" style="text-decoration:none">Go to the Moon</a></div>`;
      return;
    }
    if (kind === "charter") {
      const s = v.sites[0], p = s.prices || {}, kit = {};
      v.kit.forEach((k) => { kit[k] = (kit[k] || 0) + 1; });
      const cat = (id) => v.catalog.find((c) => c.id === id);
      const value = v.kit.reduce((a, k) => a + cat(k).cost, 0);
      const daily = v.kit.reduce((a, k) => a + cat(k).lease_per_day + cat(k).upkeep_per_day, 0);
      body.innerHTML = `<div class="lbl">Ark Development Office · site charter</div><h1>${esc(s.name)}</h1>
        <p>${esc(s.blurb)}</p>
        <p><b>${esc(v.company)}</b> can take this ground today. ${v.founders || 6} people found it with you. The Ark stands a kit beside it in crates: a small propellant works and what keeps its people alive, ${v.kit.length} modules, ${cr(value)} of plant, on lease.</p>
        <div class="stats"><div><span class="lbl">Kit, all standing</span><b>${n0(daily)} a day</b></div>
          <div><span class="lbl">Propellant bid</span><b>${p.PROP && p.PROP.bid ? n0(p.PROP.bid) : "none"} cr/t</b></div>
          <div><span class="lbl">Ice ask</span><b>${p.ICE && p.ICE.ask ? n0(p.ICE.ask) : "none"} cr/t</b></div>
          <div><span class="lbl">Your credits</span><b>${n0(v.credits)}</b></div></div>
        <ul><li>The town runs on the world's clock, the same for everyone, and it keeps living while you are away.</li>
          <li>Give people air, water and food and more come on the daily shuttle. More people run more industry.</li>
          <li>It makes propellant from ice and sells it at ${esc(s.node_name)}. Your ship can carry it to ports that pay more.</li>
          <li>Leased plant costs a daily fee. Plant you buy is yours.</li></ul>
        <div class="acts"><button class="btn cyan" id="takeCharter">Take the charter</button>
          <a class="btn ghost" href="/" style="text-decoration:none">Back to the Moon</a></div>`;
      $("#takeCharter").onclick = async () => {
        const j = await act("/base/charter", { site: s.id }, "The ground is yours. The kit is in crates beside it.");
        if (j) { g.hidden = true; S.cat = "kit"; S.welcomed = true; draw(); }
      };
    }
  }

  async function welcomeBack() {
    let a;
    try { a = await api("/base/seen", {}); } catch (e) { return; }
    if (!a || a.hours < 30 || !(a.made_kg_PROP || a.sales)) return;   // half a real hour
    const g = $("#gate"), paid = (a.lease || 0) + (a.upkeep || 0) + (a.wages || 0) + (a.feed || 0);
    // Game hours to real time by the server's own tick length, never a constant here.
    const mins = a.hours * S.v.tick_seconds / 60;
    const real = mins >= 120 ? `${(mins / 60).toFixed(1)} hours` : `${Math.round(mins)} minutes`;
    g.dataset.kind = "away"; g.hidden = false;
    $("#gateBody").innerHTML = `<div class="lbl">While you were away</div><h1>${n0(a.hours)} game hours</h1>
      <p>You were gone ${real}. The base kept working.</p>
      <div class="stats"><div><span class="lbl">Propellant made</span><b>${t1(a.made_kg_PROP)} t</b></div>
        <div><span class="lbl">Sold</span><b>${t1((a.sold_kg_PROP || 0) + (a.sold_kg_ICE || 0))} t</b></div>
        <div><span class="lbl">Taken in</span><b class="pos">${n0((a.sales || 0) + (a.bonus || 0))}</b></div>
        <div><span class="lbl">Paid out</span><b class="neg">${n0(paid)}</b></div>
        <div><span class="lbl">People</span><b>${a.arrived ? "+" + a.arrived : ""}${a.left ? " −" + a.left : ""}${!a.arrived && !a.left ? "no change" : ""}</b></div>
        <div><span class="lbl">Net</span><b>${n0((a.sales || 0) + (a.bonus || 0) - paid)}</b></div></div>
      <div class="acts"><button class="btn cyan" id="backToWork">Back to work</button></div>`;
    $("#backToWork").onclick = () => { g.hidden = true; };
  }

  // -- the ground ------------------------------------------------------------------
  const cv = $("#stage"), ctx = cv.getContext("2d");
  const TW = 64, TH = 32;
  let W = 0, H = 0, dpr = 1;
  function size() {
    dpr = Math.min(2, window.devicePixelRatio || 1); W = window.innerWidth; H = window.innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
  }
  const mid = () => (B() ? B().layout.size / 2 : 12);
  const iso = (x, y, z) => [(x - y - 0) * TW / 2, (x + y - 2 * mid()) * TH / 2 - (z || 0)];
  function shade(hex, k) {
    const n = parseInt(hex.slice(1), 16);
    const c = (s) => Math.max(0, Math.min(255, ((n >> s) & 255) * k)) | 0;
    return `rgb(${c(16)},${c(8)},${c(0)})`;
  }
  function quad(p, fill, stroke, lw) {
    ctx.beginPath(); ctx.moveTo(p[0][0], p[0][1]);
    for (let i = 1; i < p.length; i++) ctx.lineTo(p[i][0], p[i][1]);
    ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lw || 1; ctx.stroke(); }
  }
  const diamond = (x, y, i) => { i = i || 0; return [iso(x + i, y + i), iso(x + 1 - i, y + i), iso(x + 1 - i, y + 1 - i), iso(x + i, y + 1 - i)]; };
  function prism(x, y, hgt, inset, top, alpha) {
    const a = iso(x + inset, y + inset, hgt), b = iso(x + 1 - inset, y + inset, hgt);
    const c = iso(x + 1 - inset, y + 1 - inset, hgt), d = iso(x + inset, y + 1 - inset, hgt);
    ctx.globalAlpha = alpha == null ? 1 : alpha;
    if (hgt > 0) {
      quad([d, c, [c[0], c[1] + hgt], [d[0], d[1] + hgt]], shade(top, 0.62));
      quad([c, b, [b[0], b[1] + hgt], [c[0], c[1] + hgt]], shade(top, 0.42));
    }
    quad([a, b, c, d], top);
    ctx.globalAlpha = 1;
  }
  function tileAt(sx, sy) {
    const wx = (sx - W / 2 - S.cam.x) / S.cam.s, wy = (sy - H / 2 - S.cam.y) / S.cam.s;
    const m = mid();
    return [Math.floor(wy / TH + wx / TW + m), Math.floor(wy / TH - wx / TW + m)];
  }
  const noise = (x, y) => { let h = (x * 374761393 + y * 668265263) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; };

  function paint() {
    requestAnimationFrame(paint);
    // Ease toward the wanted zoom: the descent from the Moon, and the rise back.
    if (Math.abs(S.cam.s - S.target) > 0.002) S.cam.s += (S.target - S.cam.s) * 0.12;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#030014"; ctx.fillRect(0, 0, cv.width, cv.height);
    const b = B();
    if (!b) return;
    const s = S.cam.s * dpr;
    ctx.setTransform(s, 0, 0, s, (W / 2 + S.cam.x) * dpr, (H / 2 + S.cam.y) * dpr);
    const L = b.layout, N = L.size, t = S.tool;
    const rock = new Set(L.rocks.map((r) => r[0] + "," + r[1]));
    const at = new Map(b.modules.map((m) => [m.x + "," + m.y, m]));
    const cond = new Set(b.conduits.map((c) => c[0] + "," + c[1]));
    const patchOf = new Map();
    L.patches.forEach((p) => p.tiles.forEach((q) => patchOf.set(q[0] + "," + q[1], p)));
    const miners = b.modules.filter((m) => m.type === "ice_miner");
    const picked = S.sel && S.sel.id ? (b.modules.find((m) => m.id === S.sel.id) || {}).type : null;
    const showDust = (t && (t.type === "solar" || t.type === "ice_miner" || t.kind === "move"))
      || picked === "ice_miner" || picked === "solar";

    for (let x = 0; x < N; x++) for (let y = 0; y < N; y++) {
      const k = x + "," + y, g = 0.82 + noise(x, y) * 0.3;
      quad(diamond(x, y), shade("#17152e", g), "rgba(139,92,246,.09)", 0.6);
      const p = patchOf.get(k);
      if (p) quad(diamond(x, y, 0.04), `rgba(103,232,249,${0.08 + 0.3 * p.richness * p.grade / 150})`, "rgba(103,232,249,.45)", 0.8);
      if (showDust && miners.some((m) => Math.max(Math.abs(m.x - x), Math.abs(m.y - y)) <= 2))
        quad(diamond(x, y, 0.08), "rgba(251,191,36,.10)");
      if (cond.has(k)) {
        quad(diamond(x, y, 0.3), "#8f8ba6");
        for (const [dx, dy] of [[1, 0], [0, 1]]) {
          const n = (x + dx) + "," + (y + dy);
          if (cond.has(n) || at.has(n)) { const a = iso(x + 0.5, y + 0.5), c = iso(x + 0.5 + dx, y + 0.5 + dy);
            ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(c[0], c[1]); ctx.strokeStyle = "#8f8ba6"; ctx.lineWidth = 5; ctx.stroke(); }
        }
        for (const [dx, dy] of [[-1, 0], [0, -1]]) {
          if (at.has((x + dx) + "," + (y + dy))) { const a = iso(x + 0.5, y + 0.5), c = iso(x + 0.5 + dx, y + 0.5 + dy);
            ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(c[0], c[1]); ctx.strokeStyle = "#8f8ba6"; ctx.lineWidth = 5; ctx.stroke(); }
        }
      }
    }
    if (S.paint) S.paint.forEach((q) => quad(diamond(q[0], q[1], 0.3), "rgba(103,232,249,.7)"));

    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (let d = 0; d < 2 * N - 1; d++) for (let x = Math.max(0, d - N + 1); x <= Math.min(d, N - 1); x++) {
      const y = d - x, k = x + "," + y;
      if (rock.has(k)) { prism(x, y, 5 + noise(y, x) * 9, 0.18 + noise(x, y) * 0.12, "#3a3852"); continue; }
      const m = at.get(k);
      if (!m) continue;
      const lk = LOOK[m.type] || ["#888888", 10, 0.1, "#000", "??"];
      const tone = (STATE[m.status] || ["a"])[0];
      const lifted = t && t.kind === "move" && t.id === m.id;
      quad(diamond(x, y, 0.02), null, m.leased ? "rgba(167,139,250,.55)" : "rgba(103,232,249,.9)", 1.2);
      prism(x, y, lk[1], lk[2], lk[0], lifted ? 0.3 : m.status === "assembling" || m.status === "new" ? 0.5 : 1);
      const c = iso(x + 0.5, y + 0.5, lk[1]);
      ctx.fillStyle = lk[3]; ctx.font = "700 9px 'Space Mono', monospace"; ctx.fillText(lk[4], c[0], c[1]);
      if (tone !== "g") { ctx.beginPath(); ctx.arc(c[0], c[1] - 13, 4, 0, 7); ctx.fillStyle = DOT[tone]; ctx.fill();
        ctx.strokeStyle = "#030014"; ctx.lineWidth = 1.2; ctx.stroke(); }
      if (S.sel && S.sel.id === m.id) quad(diamond(x, y, -0.03), null, "#ffffff", 1.6);
    }

    ctx.font = "700 10px 'Orbitron', sans-serif";
    L.patches.forEach((p) => {
      // Under the patch's nearest corner, so it never sits on a miner.
      const low = p.tiles.reduce((a, q) => (q[0] + q[1] > a[0] + a[1] ? q : a));
      const c = iso(low[0] + 1, low[1] + 1), txt = `ICE ${p.grade}% · ${Math.round(p.richness * 100)}% LEFT`;
      const w = ctx.measureText(txt).width + 12;
      ctx.fillStyle = "rgba(3,0,20,.72)"; ctx.fillRect(c[0] - w / 2, c[1] + 3, w, 15);
      ctx.fillStyle = "#67e8f9"; ctx.fillText(txt, c[0], c[1] + 11);
    });

    const hv = S.hover;
    if (hv && hv[0] >= 0 && hv[1] >= 0 && hv[0] < N && hv[1] < N) {
      const k = hv[0] + "," + hv[1];
      if (t && (t.kind === "build" || t.kind === "move")) {
        const type = t.kind === "move" ? (b.modules.find((m) => m.id === t.id) || {}).type : t.type;
        const lk = LOOK[type] || ["#888888", 10, 0.1];
        const blocked = rock.has(k) || (at.has(k) && !(t.kind === "move" && at.get(k).id === t.id));
        const dusty = type === "solar" && miners.some((m) => Math.max(Math.abs(m.x - hv[0]), Math.abs(m.y - hv[1])) <= 2 && !(t.kind === "move" && m.id === t.id));
        const bare = type === "ice_miner" && !patchOf.has(k);
        prism(hv[0], hv[1], lk[1], lk[2], blocked ? "#f87171" : dusty || bare ? "#fbbf24" : lk[0], 0.6);
        S.ghostNote = blocked ? "" : dusty ? "In a digger's dust: half power here" : bare ? "No ice here: a miner digs nothing" : "";
      } else { S.ghostNote = ""; quad(diamond(hv[0], hv[1]), null, "rgba(255,255,255,.5)", 1); }
    }
  }

  // -- pointer and wheel -------------------------------------------------------------
  function goMoon() {
    if (S.leaving) return;
    S.leaving = true; S.target = 0.12; $("#rise").classList.add("on"); $("#fade").classList.add("on");
    setTimeout(() => { location.href = "/"; }, 650);
  }
  cv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const out = e.deltaY > 0, k = out ? 0.88 : 1 / 0.88;
    const next = Math.max(0.42, Math.min(2.2, S.target * k));
    if (out && S.target <= 0.43) { S.rise += 1; $("#rise").classList.add("on"); if (S.rise > 4) goMoon(); return; }
    S.rise = 0; $("#rise").classList.remove("on");
    const r = next / S.target;
    S.cam.x = e.clientX - W / 2 - (e.clientX - W / 2 - S.cam.x) * r;
    S.cam.y = e.clientY - H / 2 - (e.clientY - H / 2 - S.cam.y) * r;
    S.cam.s *= r; S.target = next;
  }, { passive: false });

  cv.addEventListener("pointerdown", (e) => {
    cv.setPointerCapture(e.pointerId);
    S.ptr.set(e.pointerId, [e.clientX, e.clientY]);
    if (S.ptr.size === 2) { const p = [...S.ptr.values()]; S.pinch = Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]); S.drag = null; S.paint = null; return; }
    S.drag = { x: e.clientX, y: e.clientY, cx: S.cam.x, cy: S.cam.y, moved: false };
    if (S.tool && S.tool.kind === "conduit" && e.button === 0) { S.paint = [tileAt(e.clientX, e.clientY)]; S.drag.painting = true; }
  });
  cv.addEventListener("pointermove", (e) => {
    S.hover = tileAt(e.clientX, e.clientY);
    if (S.ptr.has(e.pointerId)) S.ptr.set(e.pointerId, [e.clientX, e.clientY]);
    if (S.ptr.size === 2 && S.pinch) {
      const p = [...S.ptr.values()], d = Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]);
      S.target = Math.max(0.42, Math.min(2.2, S.target * d / S.pinch)); S.cam.s = S.target; S.pinch = d; return;
    }
    const g = S.drag;
    if (!g) return;
    if (Math.hypot(e.clientX - g.x, e.clientY - g.y) > 5) g.moved = true;
    if (g.painting) {
      const q = S.hover;
      if (!S.paint.some((p) => p[0] === q[0] && p[1] === q[1]) && S.paint.length < 64) S.paint.push(q);
    } else if (g.moved) { S.cam.x = g.cx + e.clientX - g.x; S.cam.y = g.cy + e.clientY - g.y; }
  });
  const up = (e) => {
    S.ptr.delete(e.pointerId); S.pinch = 0;
    const g = S.drag; S.drag = null;
    if (!g || !B()) return;
    if (g.painting) {
      const tiles = S.paint; S.paint = null;
      act("/base/conduit", { tiles }, (j) => "Conduit laid.");
      return;
    }
    if (g.moved) return;
    click(tileAt(e.clientX, e.clientY));
  };
  cv.addEventListener("pointerup", up);
  cv.addEventListener("pointercancel", (e) => { S.ptr.delete(e.pointerId); S.drag = null; S.paint = null; });
  cv.addEventListener("pointerleave", () => { S.hover = null; });
  cv.addEventListener("contextmenu", (e) => { e.preventDefault(); stopTool(); });

  function stopTool() { S.tool = null; S.sure = null; if (B()) { drawBuild(); } }

  async function click(q) {
    const b = B(), [x, y] = q, N = b.layout.size, t = S.tool;
    if (x < 0 || y < 0 || x >= N || y >= N) { S.sel = null; drawInspect(); return; }
    if (t && t.kind === "build") {
      const j = await act("/base/build", { type: t.type, x, y, how: t.how });
      if (j && t.how === "crate" && !j.base.crates.includes(t.type)) {
        const left = j.base.crates;
        S.tool = left.length ? { kind: "build", type: left[0], how: "crate" } : null;
        if (!left.length) toast("Every crate is standing.");
        drawBuild();
      }
      return;
    }
    if (t && t.kind === "move") {
      const j = await act("/base/move", { id: t.id, x, y }, "Moved. It is back up in a few hours.");
      if (j) { S.tool = null; drawBuild(); }
      return;
    }
    const m = b.modules.find((z) => z.x === x && z.y === y);
    S.sure = null;
    S.sel = m ? { id: m.id } : b.conduits.some((c) => c[0] === x && c[1] === y) ? { conduit: [x, y] } : null;
    if (m) { S.cat = null; drawBuild(); }
    drawInspect();
  }

  // -- buttons ---------------------------------------------------------------------
  $("#cats").addEventListener("click", (e) => {
    const c = e.target.closest("button"); if (!c) return;
    S.cat = S.cat === c.dataset.c ? null : c.dataset.c; S.sel = null; drawBuild(); drawInspect();
  });
  $("#tray").addEventListener("click", (e) => {
    const c = e.target.closest("[data-tool]"); if (!c) return;
    S.tool = c.dataset.tool === "conduit" ? { kind: "conduit" } : { kind: "build", type: c.dataset.tool, how: c.dataset.how };
    S.sel = null; drawBuild(); drawInspect();
  });
  $("#rail").addEventListener("click", (e) => {
    const c = e.target.closest("button"); if (!c) return;
    S.drawer = S.drawer === c.dataset.d ? null : c.dataset.d;
    document.querySelectorAll("#rail button").forEach((x) => x.classList.toggle("on", x.dataset.d === S.drawer));
    drawDrawer();
  });
  $("#inspect").addEventListener("click", async (e) => {
    const c = e.target.closest("[data-act]"); if (!c) return;
    const a = c.dataset.act, sel = S.sel;
    if (a === "close") { S.sel = null; S.sure = null; drawInspect(); }
    else if (a === "lift") { await act("/base/conduit/lift", { x: sel.conduit[0], y: sel.conduit[1] }); S.sel = null; drawInspect(); }
    else if (a === "move") { S.tool = { kind: "move", id: sel.id }; S.cat = null; drawBuild(); }
    else if (a === "buyout") await act("/base/buyout", { id: sel.id }, "Bought. It is yours now.");
    else if (a === "remove") {
      if (S.sure !== sel.id) { S.sure = sel.id; drawInspect(); return; }
      S.sure = null; await act("/base/remove", { id: sel.id }, "Taken down."); S.sel = null; drawInspect();
    }
  });
  $("#drawer").addEventListener("click", async (e) => {
    const c = e.target.closest("[data-act]"); if (!c) return;
    const a = c.dataset.act, asset = c.dataset.a, b = B(), p = (S.v.prices[asset] || {});
    const fill = (j) => j.kg ? `${j.verb === "sold" ? "Sold" : "Bought"} ${t1(j.kg)} t for ${cr(j.value)}.` : "Nothing filled at that price.";
    if (a === "sell") await act("/base/sell", { asset, tonnes: Math.floor(b.stock[asset] / 1000), price: p.bid }, fill);
    else if (a === "buy") await act("/base/buy", { asset, tonnes: 10, price: p.ask }, fill);
    else if (a === "load" || a === "unload") {
      const tonnes = Math.max(1, parseInt($("#stow" + asset).value, 10) || 1);
      await act("/base/" + a, { asset, tonnes }, a === "load" ? "Loaded." : "Unloaded.");
    } else if (a === "accept") await act(`/contracts/${c.dataset.id}/accept`, {}, "Promised. The clock is running.");
    else if (a === "abandon") await act(`/contracts/${c.dataset.id}/abandon`, {}, "Given up. It is back on the board.");
    else if (a === "moon") goMoon();
  });
  $("#drawer").addEventListener("change", (e) => {
    const k = e.target.dataset.pol; if (!k) return;
    const [asset, field] = k.split(".");
    const value = e.target.type === "checkbox" ? e.target.checked : Math.max(field.endsWith("price") ? 1 : 0, parseInt(e.target.value, 10) || 0);
    e.target.blur();
    act("/base/policy", { asset, [field]: value }, "Standing order changed.");
  });
  $("#toMoon").onclick = goMoon;
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (S.tool) stopTool();
    else if (S.sel) { S.sel = null; drawInspect(); }
    else if (S.cat) { S.cat = null; drawBuild(); }
    else if (S.drawer) { S.drawer = null; draw(); }
  });
  window.addEventListener("resize", size);

  // -- clock and start-up --------------------------------------------------------------
  function clock() {
    const v = S.v; if (!v || !v.tick_started_at) return;
    const f = (Date.now() - Date.parse(v.tick_started_at)) / (v.tick_seconds * 1000);
    $("#hour").style.width = Math.max(0, Math.min(1, f)) * 100 + "%";
    const h = $("#hint");
    if (S.tool && S.ghostNote !== S.shownNote) { S.shownNote = S.ghostNote; drawBuild(); if (S.ghostNote) h.textContent = S.ghostNote; }
  }

  async function boot() {
    size(); paint();
    if (!S.token) { gate("nokey"); return; }
    try { await refresh(); } catch (e) { if ($("#gate").hidden) toast("Cannot reach the server.", true); return; }
    setInterval(clock, 250);
    setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 4000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh().catch(() => {}); });
  }
  boot();
})();
