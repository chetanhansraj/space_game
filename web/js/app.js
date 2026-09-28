/* The client. It renders and submits intent, nothing more (invariant 1).
 *
 * Every number shown here came from the server. The two things computed
 * locally are both display: the clock's minute hand between server ticks, and
 * the "best cargo" hint on the routes tab, which is arithmetic over public
 * prices the server already published. Neither can change anything; every
 * action is a request the server validates and may refuse.
 */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const KEY = "lunarark.key";
  const S = {
    token: null, world: null, me: null, sky: null, contracts: [], markets: {},
    node: null, tab: "market", open: null, offset: 0, feedSeen: new Set(),
    letters: [], reading: null, spectating: false,
  };
  try { S.token = localStorage.getItem(KEY); } catch (e) { /* private mode */ }

  // -- helpers ------------------------------------------------------------------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const cr = (n) => n == null ? "—" : `${Math.round(n).toLocaleString()} cr`;
  const num = (n) => n == null ? "—" : Math.round(n).toLocaleString();
  const t = (kg) => { const v = kg / 1000; return `${v % 1 ? v.toFixed(1) : v.toLocaleString()} t`; };
  const NAMES = { REGOLITH: "Regolith", ICE: "Water ice", PROP: "Propellant", IRON: "Iron",
    VOLATILE: "Volatiles", FOOD: "Food", GOODS: "Goods", HE3: "Helium-3", PGM: "Platinum", RAREEARTH: "Rare earths" };
  const UNIT = (a) => (a === "HE3" || a === "PGM") ? "kg" : "t";
  const nodeName = (id) => (S.world && S.world.nodes.find((n) => n.id === id) || {}).name || id;
  const nodeOf = (id) => S.world && S.world.nodes.find((n) => n.id === id);

  function toast(msg, kind) {
    const el = document.createElement("div");
    el.className = "toast " + (kind || ""); el.textContent = msg;
    $("#toast").appendChild(el);
    setTimeout(() => el.remove(), kind === "bad" ? 5200 : 3800);
  }

  async function api(path, body) {
    const opts = { headers: {} };
    if (S.token) opts.headers.Authorization = "Bearer " + S.token;
    if (body !== undefined) {
      opts.method = "POST"; opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch("/api" + path, opts);
    let data = null; try { data = await r.json(); } catch (e) { /* empty */ }
    if (r.status === 401 && S.token) { signOut(); throw new Error("Signed out."); }
    if (!r.ok) {
      const d = data && data.detail;
      throw new Error(typeof d === "string" ? d : Array.isArray(d) ? "Check the numbers." : `Error ${r.status}`);
    }
    return data;
  }

  // -- the clock ----------------------------------------------------------------
  function frac() {
    const w = S.world; if (!w) return 0;
    const ms = Date.now() + S.offset - Date.parse(w.tick_started_at);
    return Math.max(0, Math.min(0.999, ms / (w.tick_seconds * 1000)));
  }
  const tickNow = () => (S.world ? S.world.tick + frac() : 0);
  const realSeconds = (ticks) => ticks * (S.world ? S.world.tick_seconds : 60);
  function dur(sec) {
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return `${sec}s`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, "0")}s`;
    return `${Math.floor(sec / 3600)}h ${String(Math.floor(sec / 60) % 60).padStart(2, "0")}m`;
  }

  function drawClock() {
    const w = S.world; if (!w) return;
    const f = frac(), minute = String(Math.floor(f * 60)).padStart(2, "0");
    $("#date").textContent = w.date.slice(0, 14) + minute;
    $("#tickline").textContent = `Hour ${num(w.tick)} · next in ${dur(w.tick_seconds * (1 - f))}`;
    $("#hour").style.width = (f * 100).toFixed(1) + "%";
    const flight = document.querySelector("[data-flight]");
    if (flight && S.me) {
      const s = S.me.ship, span = Math.max(1, s.arrive_tick - s.depart_tick);
      const p = Math.max(0, Math.min(1, (tickNow() - s.depart_tick) / span));
      flight.querySelector("i").style.width = (p * 100).toFixed(1) + "%";
      const eta = document.querySelector("[data-eta]");
      if (eta) eta.textContent = p >= 1 ? "docking…" : dur(realSeconds(s.arrive_tick - tickNow()));
    }
    document.querySelectorAll("[data-due]").forEach((el) => {
      el.textContent = "due in " + dur(realSeconds(+el.dataset.due - tickNow()));
    });
  }

  // -- the world ----------------------------------------------------------------
  async function loadWorld() {
    const w = await api("/world");
    S.offset = Date.parse(w.server_time) - Date.now();
    const first = !S.world;
    S.world = w;
    Scene.setWorld(w);
    $("#flare").classList.toggle("hidden", !w.flare_until);
    if (first) {
      const home = S.me ? S.me.ship.location : "shackleton_depot";
      S.node = home;
    }
    drawFeed();
    if (first) drawPort();
    return w;
  }

  function drawFeed() {
    const list = S.world.feed.slice(0, 5);
    $("#feedList").innerHTML = list.map((e) => {
      const fresh = S.feedSeen.size && !S.feedSeen.has(e.id);
      return `<li class="${fresh ? "new" : ""}"><b>H${num(e.tick)}</b>${esc(e.text)}</li>`;
    }).join("") || '<li>The record is quiet.</li>';
    S.world.feed.forEach((e) => S.feedSeen.add(e.id));
  }

  async function loadSky() {
    try { S.sky = await api("/sky"); Scene.setSky(S.sky); } catch (e) { /* display only */ }
  }

  async function loadContracts() {
    try { S.contracts = await api("/contracts"); } catch (e) { S.contracts = []; }
    const here = S.contracts.filter((c) => c.node === S.node).length;
    $("#jobsN").textContent = S.contracts.length ? ` ${S.contracts.length}` : "";
    if (S.tab === "jobs") drawPort();
    return here;
  }

  async function loadMarket(node) {
    try { S.markets[node] = await api("/market/" + node); } catch (e) { /* keep last */ }
    if (S.tab === "market" && S.node === node && !typing()) drawPort();
  }
  const typing = () => document.activeElement && document.activeElement.closest && document.activeElement.closest(".trade");

  // -- the player ---------------------------------------------------------------
  async function loadMe() {
    if (!S.token) return;
    const me = await api("/me");
    const moved = S.me && (S.me.ship.state !== me.ship.state || S.me.ship.location !== me.ship.location);
    const earned = S.me ? me.credits - S.me.credits : 0;
    S.me = me;
    Scene.setMe(me.ship.id);
    $("#cash").textContent = num(me.credits);
    $("#cashChip").classList.remove("hidden");
    $("#inboxBtn").classList.remove("hidden");
    $("#unread").textContent = me.unread;
    $("#unread").classList.toggle("hidden", !me.unread);
    $("#left").classList.remove("hidden");
    drawCompany();
    if (moved) {
      if (me.ship.state === "docked") {
        toast(`Docked at ${nodeName(me.ship.location)}${earned > 0 ? ` · +${cr(earned)}` : ""}`, "good");
        S.node = me.ship.location; loadMarket(S.node); drawPort();
      }
    }
    if (S.tab === "routes") drawPort();
  }

  function drawCompany() {
    const me = S.me; if (!me) return;
    const s = me.ship, fly = s.state === "in_transit";
    const hold = s.hold_used_kg / s.hold_kg, tank = s.fuel_kg / s.tank_kg;
    const cargo = Object.entries(s.cargo).map(([a, q]) => `<span>${t(q)} ${esc(NAMES[a] || a)}</span>`);
    if (s.cargo_prop_kg) cargo.push(`<span>${t(s.cargo_prop_kg)} Propellant (cargo)</span>`);
    const jobs = me.contracts.map((c) => jobCard(c, true)).join("");
    $("#company").innerHTML = `
      <div class="lbl">Your company</div>
      <h2>${esc(me.name)}</h2>
      <div class="big">${cr(me.credits)}</div>
      ${me.upkeep_owed ? `<div class="note" style="color:var(--amber)">Grounded — ${cr(me.upkeep_owed)} charter fee owed.</div>` : ""}
      <div class="shipcard">
        <div class="row"><div class="status ${fly ? "fly" : ""}"><i></i>${fly ? "In flight" : "Docked"}</div>
          <button class="btn ghost" id="findShip">Find</button></div>
        <div style="font-size:17px;font-weight:600;margin:4px 0 2px">
          ${fly ? `${esc(nodeName(s.location))} → ${esc(nodeName(s.destination))}` : esc(nodeName(s.location))}</div>
        <div class="sub">${esc(s.class)} · ${num(s.voyages)} voyages</div>
        ${fly ? `<div class="row"><span>Arrives in</span><b data-eta>—</b></div>
          <div class="meter flight" data-flight><i></i></div>
          <div class="note">${s.sell_on_arrival ? "Cargo sells at the best bid on docking." : "Cargo stays aboard on docking."}</div>` : ""}
        <div class="row" style="margin-top:8px"><span>Hold</span><b>${t(s.hold_used_kg)} / ${t(s.hold_kg)}</b></div>
        <div class="meter hold"><i style="width:${(hold * 100).toFixed(1)}%"></i></div>
        <div class="row"><span>Tank</span><b>${t(s.fuel_kg)} / ${t(s.tank_kg)}</b></div>
        <div class="meter tank"><i style="width:${(tank * 100).toFixed(1)}%"></i></div>
        <div class="cargo">${cargo.join("") || '<span style="color:var(--faint)">Hold empty</span>'}</div>
      </div>
      <h3>Contracts held</h3>
      ${jobs || '<div class="note">None. The JOBS tab has work with the money already in escrow.</div>'}
      <h3>Charter</h3>
      <div class="row"><span>Fee</span><b>${cr(me.upkeep_per_day)} / game day</b></div>
      <div class="note">Paid at game midnight — every 24 real minutes. Docking fees are paid at launch.</div>`;
    $("#findShip").onclick = () => { if (Scene.view() !== "moon") setView("moon"); Scene.focusShip(); };
    bindJobs($("#company"));
    drawClock();
  }

  // -- the port panel -----------------------------------------------------------
  function drawPort() {
    const n = nodeOf(S.node); if (!n) return;
    const docked = S.me && S.me.ship.state === "docked" && S.me.ship.location === n.id;
    const here = S.world.ships.filter((s) => s.state === "docked" && s.location === n.id).length;
    $("#portKind").textContent = `Port · docking fee ${cr(n.fee)}`;
    $("#portName").textContent = n.name;
    $("#portSub").textContent = docked ? "Your Kestrel is docked here." :
      `${here} ship${here === 1 ? "" : "s"} docked · ${Math.abs(n.lat).toFixed(2)}°${n.lat < 0 ? "S" : "N"} ${Math.abs(n.lon).toFixed(1)}°${n.lon < 0 ? "W" : "E"}`;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === S.tab));
    const el = $("#port");
    if (S.tab === "market") el.innerHTML = marketHtml(n, docked);
    else if (S.tab === "routes") el.innerHTML = routesHtml(n, docked);
    else el.innerHTML = jobsHtml(n);
    bindPort(el, n, docked);
    drawClock();
  }

  function spark(hist) {
    if (!hist || hist.length < 2) return "";
    const w = 64, h = 18, lo = Math.min(...hist), hi = Math.max(...hist), span = hi - lo || 1;
    const pts = hist.map((p, i) => `${(i / (hist.length - 1) * w).toFixed(1)},${(h - (p - lo) / span * h).toFixed(1)}`).join(" ");
    const up = hist[hist.length - 1] >= hist[0];
    return `<svg class="spark" width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="${up ? "#34d399" : "#f87171"}" stroke-width="1.4"/></svg>`;
  }

  function marketHtml(n, docked) {
    const m = S.markets[n.id];
    if (!m) { loadMarket(n.id); return '<div class="empty">Reading the book…</div>'; }
    const rows = Object.entries(m.assets).map(([a, d]) => {
      const bid = d.bids[0] && d.bids[0][0], ask = d.asks[0] && d.asks[0][0];
      const open = S.open === a;
      return `<tr class="asset ${open ? "open" : ""}" data-asset="${a}">
        <td>${esc(NAMES[a] || a)}<small>per ${UNIT(a)}</small></td>
        <td class="bid">${num(bid)}</td><td class="ask">${num(ask)}</td><td>${num(d.last)}</td>
        <td>${spark(d.history)}</td></tr>` + (open ? `<tr><td colspan="5" class="trade">${tradeHtml(a, d, bid, ask, docked)}</td></tr>` : "");
    }).join("");
    return `<table class="mkt"><thead><tr><th>Commodity</th><th>Bid</th><th>Ask</th><th>Last</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p class="note" style="margin-top:12px">Bid: the best anyone here will pay. Ask: the cheapest anyone here will sell.
      Every order is against real firms' real stock.</p>`;
  }

  function tradeHtml(a, d, bid, ask, docked) {
    if (!S.me) return `<div class="note">Take a charter to trade.</div>`;
    if (a === "HE3" || a === "PGM") return `<div class="note">Traded by the kilogram at the refineries. Not a Kestrel's cargo yet.</div>`;
    if (!docked) return `<div class="note">Dock at this port to trade here. Your Kestrel is at ${esc(nodeName(S.me.ship.location))}.</div>`;
    const s = S.me.ship, held = a === "PROP" ? (s.cargo_prop_kg + s.fuel_kg) : (s.cargo[a] || 0);
    const space = (s.hold_kg - s.hold_used_kg) + (a === "PROP" ? s.tank_kg - s.fuel_kg : 0);
    const buyPrice = ask || d.last || bid || 1, sellPrice = bid || d.last || 1;
    const maxBuy = Math.max(0, Math.min(Math.floor(space / 1000), Math.floor(S.me.credits / buyPrice)));
    // Propellant in the tank is fuel; only what is carried as cargo is offered
    // by default. Selling the tank is allowed, but never the suggestion.
    const heldT = Math.floor((a === "PROP" ? s.cargo_prop_kg : held) / 1000);
    return `<div class="grid">
        <div class="field"><span class="lbl">Buy tonnes</span><input type="number" min="1" step="1" id="bq" value="${Math.max(1, Math.min(10, maxBuy))}"></div>
        <div class="field"><span class="lbl">Pay at most</span><input type="number" min="1" step="1" id="bp" value="${buyPrice}"></div>
      </div>
      <div class="est" data-est="b"></div>
      ${ask && d.last && ask > d.last * 1.25 ? `<div class="note" style="color:var(--amber)">The ask is ${Math.round((ask / d.last - 1) * 100)}% above the last trade — likely the Ark's ceiling. A lower limit may fill later from firms, or not at all.</div>` : ""}
      <div class="acts"><button class="btn go" data-act="buy" data-asset="${a}" ${maxBuy < 1 ? "disabled" : ""}>Buy</button></div>
      <div class="grid" style="margin-top:14px">
        <div class="field"><span class="lbl">Sell tonnes</span><input type="number" min="1" step="1" id="sq" value="${Math.max(1, heldT)}"></div>
        <div class="field"><span class="lbl">Accept at least</span><input type="number" min="1" step="1" id="sp" value="${sellPrice}"></div>
      </div>
      <div class="est" data-est="s"></div>
      <div class="acts"><button class="btn bad" data-act="sell" data-asset="${a}" ${held < 1000 ? "disabled" : ""}>Sell</button></div>
      <div class="note" style="margin-top:8px">Room for ${num(maxBuy)} t at the ask · you hold ${t(held)}.
      Orders fill against the book now, up to your limit; anything unfilled is cancelled.</div>`;
  }

  function bestCargo(from, to) {
    const a = from.prices || {}, b = to.prices || {}, out = [];
    for (const k of Object.keys(a)) {
      if (k === "HE3" || k === "PGM") continue;
      const buy = a[k] && a[k].ask, sell = b[k] && (b[k].bid || null);
      if (buy && sell && sell > buy) out.push({ asset: k, buy, sell, gain: sell - buy });
    }
    return out.sort((x, y) => y.gain - x.gain).slice(0, 3);
  }

  function routesHtml(n, docked) {
    if (!S.me) return `<div class="empty">Take a charter to fly.</div>` + routesPreview(n);
    if (S.me.ship.state !== "docked") return `<div class="empty">Your Kestrel is in flight. Routes open when it docks.</div>`;
    if (!docked) return `<div class="note">Routes are planned from where your ship is — ${esc(nodeName(S.me.ship.location))}.</div>
      <p><button class="btn cyan" data-goto="${S.me.ship.location}">Go to ${esc(nodeName(S.me.ship.location))}</button></p>` + routesPreview(n);
    const here = nodeOf(S.me.ship.location);
    return S.me.routes.map((r) => {
      const to = nodeOf(r.destination), opps = bestCargo(here, to);
      const fuelOk = S.me.ship.fuel_kg + S.me.ship.cargo_prop_kg >= r.fuel_kg;
      return `<div class="route">
        <h4>→ ${esc(to.name)}</h4>
        <div class="facts"><span>${r.ticks} game h · ${dur(realSeconds(r.ticks))}</span><span>Δv ${num(r.dv)} m/s</span>
          <span>burns ${num(r.fuel_kg)} kg</span><span>fee ${cr(r.fee)}</span></div>
        <div class="opps">${opps.length ? opps.map((o) => `<div class="opp"><span>${esc(NAMES[o.asset])}: ${num(o.buy)} here → ${num(o.sell)} there</span><b class="plus">+${num(o.gain)}/t</b></div>`).join("")
          : '<div class="note">No commodity is cheaper here than it bids there right now.</div>'}</div>
        <label class="check"><input type="checkbox" data-sell="${r.destination}" checked> Sell cargo at the best bid on arrival</label>
        <button class="btn cyan wide" data-launch="${r.destination}" ${fuelOk ? "" : "disabled"}>Launch for ${esc(to.name)}</button>
      </div>`;
    }).join("");
  }

  function routesPreview(n) {
    const others = S.world.nodes.filter((o) => o.id !== n.id);
    return `<h3 style="margin-top:6px">From ${esc(n.name)}</h3>` + others.map((o) => {
      const opps = bestCargo(n, o);
      return `<div class="route"><h4>→ ${esc(o.name)}</h4><div class="opps">${opps.map((x) =>
        `<div class="opp"><span>${esc(NAMES[x.asset])}: ${num(x.buy)} → ${num(x.sell)}</span><b class="plus">+${num(x.gain)}/t</b></div>`).join("") ||
        '<div class="note">No spread worth flying right now.</div>'}</div></div>`;
    }).join("");
  }

  function jobCard(c, mine) {
    const ch = c.issuer_character || {};
    const docked = S.me && S.me.ship.state === "docked" && S.me.ship.location === c.node;
    let act = "";
    if (S.me && mine) act = `${docked ? `<button class="btn go" data-deliver="${c.id}">Deliver</button>` : ""}
      <button class="btn ghost" data-abandon="${c.id}">Drop</button>`;
    else if (S.me) act = `<button class="btn cyan" data-accept="${c.id}">Accept</button>`;
    return `<div class="job ${mine ? "mine" : ""}">
      <div class="who"><div class="av" style="background:${esc(ch.colour || "#a78bfa")}">${esc(ch.sigil || "")}</div>
        <div><b>${esc(ch.name || c.issuer)}</b><small>${esc(ch.org || "")}</small></div></div>
      <div class="what">Bring <b>${t(c.qty_kg)}</b> ${esc((NAMES[c.asset] || c.asset).toLowerCase())} to <b>${esc(nodeName(c.node))}</b></div>
      <div class="terms"><div><div class="pay">${cr(c.payment)}</div><div class="due" data-due="${c.deadline_tick}"></div></div>
        <div style="display:flex;gap:6px">${act}</div></div></div>`;
  }

  function jobsHtml(n) {
    const mine = S.me ? S.me.contracts : [];
    const minedIds = new Set(mine.map((c) => c.id));
    const open = S.contracts.filter((c) => !minedIds.has(c.id));
    const local = open.filter((c) => c.node === n.id), rest = open.filter((c) => c.node !== n.id);
    return (mine.length ? `<h3 style="margin-top:0">Yours</h3>` + mine.map((c) => jobCard(c, true)).join("") : "") +
      `<h3 ${mine.length ? "" : 'style="margin-top:0"'}>Wanted at ${esc(n.name)}</h3>` +
      (local.map((c) => jobCard(c, false)).join("") || '<div class="note">Nobody here is short of anything right now.</div>') +
      (rest.length ? `<h3>Elsewhere</h3>` + rest.map((c) => jobCard(c, false)).join("") : "") +
      `<p class="note" style="margin-top:14px">The payment is already held in escrow. Carry the goods in from another port —
      the job settles the moment your ship docks. Goods bought at the buyer's own door don't count.</p>`;
  }

  function bindJobs(el) {
    el.querySelectorAll("[data-accept]").forEach((b) => b.onclick = () => act(`/contracts/${b.dataset.accept}/accept`, {}, "Contract accepted."));
    el.querySelectorAll("[data-abandon]").forEach((b) => b.onclick = () => act(`/contracts/${b.dataset.abandon}/abandon`, {}, "Contract dropped."));
    el.querySelectorAll("[data-deliver]").forEach((b) => b.onclick = () => act(`/contracts/${b.dataset.deliver}/deliver`, {}, (r) => `Delivered. Paid ${cr(r.payment)}.`));
  }

  function bindPort(el, n, docked) {
    el.querySelectorAll("tr.asset").forEach((tr) => tr.onclick = () => {
      S.open = S.open === tr.dataset.asset ? null : tr.dataset.asset; drawPort();
    });
    const val = (id) => { const i = el.querySelector(id); return i ? parseInt(i.value, 10) : 0; };
    const est = () => {
      const eb = el.querySelector('[data-est="b"]'), es = el.querySelector('[data-est="s"]');
      if (eb) eb.textContent = `At most ${cr(val("#bq") * val("#bp"))}`;
      if (es) es.textContent = `At least ${cr(val("#sq") * val("#sp"))}`;
    };
    el.querySelectorAll(".trade input").forEach((i) => i.oninput = est); est();
    el.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => {
      const side = b.dataset.act, asset = b.dataset.asset, k = side === "buy" ? "b" : "s";
      act("/" + side, { asset, tonnes: val(`#${k}q`), price: val(`#${k}p`) },
        (r) => r.kg ? `${side === "buy" ? "Bought" : "Sold"} ${t(r.kg)} ${NAMES[asset]} for ${cr(r.value)}` : "Nothing filled at that price.",
        () => loadMarket(n.id));
    });
    el.querySelectorAll("[data-launch]").forEach((b) => b.onclick = () => {
      const dest = b.dataset.launch, sell = el.querySelector(`[data-sell="${dest}"]`).checked;
      const from = S.me.ship.location;
      act("/dispatch", { destination: dest, sell_on_arrival: sell }, `Launched for ${nodeName(dest)}.`, () => {
        if (Scene.view() === "moon") Scene.frameRoute(from, dest);
      });
    });
    el.querySelectorAll("[data-goto]").forEach((b) => b.onclick = () => selectNode(b.dataset.goto, true));
    bindJobs(el);
  }

  async function act(path, body, ok, after) {
    try {
      const r = await api(path, body);
      toast(typeof ok === "function" ? ok(r) : ok, "good");
      await Promise.all([loadMe(), loadContracts(), loadWorld()]);
      if (after) after(r);
      drawPort();
    } catch (e) { toast(e.message, "bad"); }
  }

  function selectNode(id, fly) {
    S.node = id; S.open = null;
    if (fly) Scene.select(id, true);
    loadMarket(id); drawPort();
  }

  // -- the inbox ----------------------------------------------------------------
  async function openInbox() {
    $("#inbox").classList.remove("hidden");
    S.letters = await api("/inbox");
    drawLetters(S.letters[0]);
    setTimeout(async () => {
      if (!S.letters.length) return;
      await api("/inbox/read", { upto: S.letters[0].id }).catch(() => {});
      loadMe();
    }, 1200);
  }

  function drawLetters(sel) {
    S.reading = sel;
    $("#letters").innerHTML = S.letters.map((l) => `<div class="letter ${l.read ? "" : "unread"} ${sel && sel.id === l.id ? "on" : ""}" data-id="${l.id}">
      <div class="av" style="background:${esc(l.from.colour)}">${esc(l.from.sigil)}</div>
      <div class="t"><b>${esc(l.subject)}</b><small>${esc(l.from.name)} · hour ${num(l.tick)}</small></div></div>`).join("")
      || '<div class="empty" style="padding:16px">No letters yet.</div>';
    $("#letters").querySelectorAll(".letter").forEach((el) => el.onclick = () =>
      drawLetters(S.letters.find((l) => l.id === +el.dataset.id)));
    $("#reader").innerHTML = sel ? `<button class="close" data-close>✕</button>
      <div class="from"><div class="av" style="background:${esc(sel.from.colour)}">${esc(sel.from.sigil)}</div>
        <div><b>${esc(sel.from.name)}</b><small>${esc(sel.from.title)} · ${esc(sel.from.org)}</small></div></div>
      <h3>${esc(sel.subject)}</h3>${sel.body.map((p) => `<p>${esc(p)}</p>`).join("")}` :
      '<button class="close" data-close>✕</button>';
    bindClose();
  }

  function bindClose() {
    document.querySelectorAll("[data-close]").forEach((b) => b.onclick = () => b.closest(".overlay").classList.add("hidden"));
  }

  // -- arriving -----------------------------------------------------------------
  const INTRO = [
    "I am <em>the Archivist</em>. I keep the record of this world.",
    "Three ports on the real Moon trade with each other — ice from the poles, propellant from Shackleton, helium-3 from the Sea of Tranquility. They never agree on what anything is worth.",
    "The world does not stop. Ships fly, rigs work and prices move whether you are watching or not.",
    "Take a charter, and I will write your company into the record.",
  ];
  function intro() {
    $("#intro").classList.remove("hidden");
    Scene.intro(true);
    let i = 0;
    const v = $("#introVoice");
    const next = () => {
      if ($("#intro").classList.contains("hidden")) return;
      v.style.opacity = 0;
      setTimeout(() => { v.innerHTML = INTRO[i % INTRO.length]; v.style.opacity = 1; i++; }, 300);
      if (i < INTRO.length) setTimeout(next, 5200);
    };
    v.style.transition = "opacity .3s"; next();
  }

  async function signup(ev) {
    ev.preventDefault();
    $("#joinErr").textContent = "";
    try {
      const r = await api("/signup", { name: $("#joinName").value, access_code: $("#joinCode").value });
      S.token = r.token;
      try { localStorage.setItem(KEY, r.token); } catch (e) { /* private mode */ }
      $("#intro").classList.add("hidden"); Scene.intro(false);
      $("#keyText").textContent = r.token;
      $("#keyShow").classList.remove("hidden");
      await enter(false);
    } catch (e) { $("#joinErr").textContent = e.message; }
  }

  async function signInWithKey(ev) {
    ev.preventDefault();
    S.token = $("#keyInput").value.trim();
    try {
      await api("/me");
      try { localStorage.setItem(KEY, S.token); } catch (e) { /* private mode */ }
      $("#intro").classList.add("hidden"); Scene.intro(false);
      await enter(true);
    } catch (e) { S.token = null; $("#keyErr").textContent = "That key does not open any company."; }
  }

  function signOut() {
    S.token = null; S.me = null;
    try { localStorage.removeItem(KEY); } catch (e) { /* private mode */ }
    $("#left").classList.add("hidden"); $("#cashChip").classList.add("hidden"); $("#inboxBtn").classList.add("hidden");
    intro();
  }

  async function enter(returning) {
    await loadMe();
    S.node = S.me.ship.location;
    Scene.select(S.node, true);
    selectNode(S.node, false);
    const away = await api("/session", {});
    if (returning && (away.hours >= 1 || away.unread)) showAway(away);
    else if (!returning) setTimeout(() => { if ($("#keyShow").classList.contains("hidden")) openInbox(); }, 400);
  }

  function showAway(a) {
    const days = a.hours / 24;
    $("#awayTitle").textContent = days >= 1 ? `${days.toFixed(1)} game days passed` : `${a.hours} game hours passed`;
    $("#awayText").textContent = `That was ${dur(realSeconds(a.hours))} of your time. The world kept going.`;
    const w = a.world || {};
    const stat = (n, l) => `<div><b>${num(n || 0)}</b><small>${l}</small></div>`;
    $("#awayStats").innerHTML = stat(a.unread, "letters waiting") + stat(w.contract_posted, "jobs posted") +
      stat((w.solar_flare || 0) + (w.insolvency || 0), "flares & failures");
    $("#away").classList.remove("hidden");
    bindClose();
  }

  function setView(v) {
    document.querySelectorAll("#views button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
    Scene.setView(v);
  }

  // -- boot ---------------------------------------------------------------------
  async function boot() {
    Scene.init($("#stage"), $("#labels"), {
      onSelect: (id) => { if (id !== S.node) selectNode(id, false); },
      onView: (v) => {
        document.querySelectorAll("#views button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
        $("#hint").textContent = v === "moon" ? "Drag to turn the Moon · scroll to zoom · click a port"
          : "The solar system, where the ephemerides put it now · click Earth to return";
      },
    });
    Scene.setClock(tickNow);
    document.querySelectorAll("#views button").forEach((b) => b.onclick = () => setView(b.dataset.view));
    document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => { S.tab = b.dataset.tab; drawPort(); });
    $("#inboxBtn").onclick = openInbox;
    $("#joinForm").onsubmit = signup;
    $("#keyForm").onsubmit = signInWithKey;
    $("#haveKey").onclick = () => $("#keyForm").classList.toggle("hidden");
    $("#justLook").onclick = () => { $("#intro").classList.add("hidden"); Scene.intro(false); S.spectating = true; };
    $("#keyCopy").onclick = () => { navigator.clipboard && navigator.clipboard.writeText($("#keyText").textContent); toast("Key copied."); };
    $("#keyDone").onclick = () => { $("#keyShow").classList.add("hidden"); openInbox(); };
    $("#awayRead").onclick = () => { $("#away").classList.add("hidden"); openInbox(); };
    document.querySelectorAll(".overlay").forEach((o) => o.addEventListener("click", (e) => {
      if (e.target === o && o.id !== "intro" && o.id !== "keyShow") o.classList.add("hidden");
    }));
    bindClose();

    try { await loadWorld(); } catch (e) {
      $("#tickline").textContent = "The world is unreachable."; toast("Cannot reach the server.", "bad"); return;
    }
    loadSky(); loadContracts(); loadMarket(S.node);
    if (S.token) {
      try { await enter(true); } catch (e) { if (!S.token) { /* signed out in api() */ } }
    } else intro();

    setInterval(drawClock, 250);
    setInterval(() => loadWorld().catch(() => {}), 3000);
    setInterval(() => { if (S.token) loadMe().catch(() => {}); }, 3000);
    setInterval(() => loadContracts(), 6000);
    setInterval(() => { if (S.tab === "market" && S.node) loadMarket(S.node); }, 5000);
    setInterval(loadSky, 30000);
  }
  boot();
})();
