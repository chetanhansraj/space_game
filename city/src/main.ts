// Glue: owns the game loop, turns input into intents, and hands state to the view and the interface.
// In the shared-world version this file becomes the client that sends intents to a server.

import { BUILDINGS, BuildingType } from './sim/buildings';
import { State, Intent, createState, tick, apply, refresh, placeProblem, siteProblem, zoneProblem, touchesBase, TICK, LUNAR_DAY } from './sim/sim';
import { View } from './view/view';
import { ORES } from './sim/world';
import { Hud, UiState, Tool, zoneOf, stateLine } from './ui/hud';

const HOURS_PER_SECOND = LUNAR_DAY / 900;   // one lunar day in 15 minutes at 1x
const SAVE_KEY = 'lunarark.tranquility.v5';

declare global { interface Window { claude?: { hot?: { snapshot(fn: () => unknown): void; ready?(fn: (data: any) => void): void; data?: any } }; __game?: any } }

const load = (): State | null => {
  try { const raw = localStorage.getItem(SAVE_KEY); const s = raw ? JSON.parse(raw) : null; return s && s.v === 5 ? s : null; } catch { return null; }
};
const save = (s: State) => { try { localStorage.setItem(SAVE_KEY, JSON.stringify(s)); } catch { /* storage is optional */ } };

async function boot(hot: any) {
  const stage = document.getElementById('stage')!;
  const view = await View.create(stage);
  let s: State = createState();
  const ui: UiState = { tool: null, selected: null, speed: 0, hint: '', overlay: false };
  let hover: { x: number; y: number } | null = null;
  let heldSpeed = 1, helpOpen = false;
  let look: { x: number; y: number } | null = null;   // tile under the mouse, for naming buildings
  let running = false, ended = false, acc = 0, last = performance.now(), lastHud = 0, lastSave = 0, hintUntil = 0;

  const say = (msg: string, ms = 2600) => { ui.hint = msg; hintUntil = performance.now() + ms; };
  const send = (it: Intent) => {
    const first = s.t === 0;
    const r = apply(s, it);
    if (!r.ok && r.reason) say(r.reason); else refresh(s);
    if (r.ok && (it.k === 'place' || it.k === 'zone') && first && ui.speed === 0) ui.speed = 1;   // the clock starts with the first move
    return r.ok;
  };

  /** What the ground under the cursor is worth, while a zone tool is in hand. */
  const tileHint = (k: number, z: number) => {
    const ore = s.ore[k] ? ORES[s.ore[k] - 1] : null;
    const level = s.prep[k] >= 1 ? 'already level' : `${s.rough[k]} h to level`;
    return `Habitability ${s.hab[k]} · ${level}${ore ? ` · ${ore.name}: a foundry here earns ${Math.round(ore.bonus * 100)}% more${z !== 2 ? ', zone it for Industry' : ''}` : ''}`;
  };

  const hud = new Hud({
    pickTool: t => { ui.tool = ui.tool === t ? null : t; if (ui.tool) ui.selected = null; if (!ui.tool) hover = null; },
    setSpeed: n => { ui.speed = n; },
    toggle: uid => send({ k: 'toggle', uid }),
    repair: uid => send({ k: 'repair', uid }),
    demolish: uid => { if (send({ k: 'demolish', uid })) ui.selected = null; },
    start: resume => begin(resume ? load() : null),
    help: () => { if (!running || ended) return; heldSpeed = ui.speed; ui.speed = 0; helpOpen = true; hud.briefing(null, true); },
    resume: () => { helpOpen = false; ui.speed = heldSpeed; },
    price: level => { send({ k: 'price', level }); },
    overlay: () => { ui.overlay = !ui.overlay; },
    deselect: () => { ui.selected = null; },
    readOffer: () => { if (!running || ended || helpOpen || !s.offer) return; heldSpeed = ui.speed; ui.speed = 0; helpOpen = true; hud.offerDialog(s); },
    offer: accept => { send({ k: 'offer', accept }); },
    setOn: (types, on) => { for (const b of [...s.buildings]) if (types.includes(b.type) && b.progress >= 1 && b.on !== on) send({ k: 'toggle', uid: b.uid }); },
  });

  function begin(from: State | null) {
    s = from ?? createState();
    s.netDirty = true; refresh(s);
    ui.tool = null; ui.selected = null; ui.speed = from && from.t > 0 ? 1 : 0; hover = null; ended = false; running = true; acc = 0; helpOpen = false;
    view.scale = window.innerWidth < 820 ? 0.7 : 1;
    view.centreOn(s.size / 2, s.size / 2 + (window.innerWidth < 820 ? 0 : 1));
    hud.resetAlerts(s, !from); view.resetActors(s);
    window.__game = { get state() { return s; }, ui, view, send, skip: (h: number) => { for (let i = 0; i < h / TICK; i++) tick(s); } };
  }

  // ----- pointer input -----
  const cv = view.app.canvas;
  const pts = new Map<number, { x: number; y: number }>();
  let down: { x: number; y: number; moved: boolean; button: number } | null = null;
  let pinch = 0, painting = false;
  const local = (e: PointerEvent | WheelEvent) => { const r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const origin = (p: { x: number; y: number }, t: Tool) => {
    const tile = view.screenToTile(p.x, p.y);
    if (zoneOf(t) >= 0) return tile;
    const d = BUILDINGS[t as BuildingType];
    return { x: tile.x - Math.floor((d.w - 1) / 2), y: tile.y - Math.floor((d.h - 1) / 2) };
  };
  const place = (p: { x: number; y: number }, quiet = false) => {
    if (!ui.tool || !running) return;
    const o = origin(p, ui.tool), z = zoneOf(ui.tool);
    if (z >= 0) { if (quiet && zoneProblem(s, z, o.x, o.y)) return; send({ k: 'zone', z, x: o.x, y: o.y }); return; }
    if (quiet && siteProblem(s, ui.tool as BuildingType, o.x, o.y)) return;
    send({ k: 'place', type: ui.tool as BuildingType, x: o.x, y: o.y });
  };

  cv.addEventListener('pointerdown', e => {
    cv.setPointerCapture(e.pointerId);
    hud.fold();
    const p = local(e); pts.set(e.pointerId, p);
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = Math.hypot(a.x - b.x, a.y - b.y); down = null; painting = false; return; }
    down = { ...p, moved: false, button: e.button };
    painting = !!ui.tool && (ui.tool === 'conduit' || zoneOf(ui.tool) >= 0) && e.button === 0;
    if (painting) { hover = origin(p, ui.tool!); place(p, true); }
  });
  cv.addEventListener('pointermove', e => {
    const p = local(e), prev = pts.get(e.pointerId);
    if (ui.tool && (e.pointerType === 'mouse' || painting)) hover = origin(p, ui.tool);
    look = e.pointerType === 'mouse' ? view.screenToTile(p.x, p.y) : null;
    if (!prev) return;
    pts.set(e.pointerId, p);
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch > 0) view.zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, dist / pinch);
      pinch = dist; view.panBy((p.x - prev.x) / 2, (p.y - prev.y) / 2);
      return;
    }
    if (!down) return;
    if (painting) { place(p, true); return; }
    if (!down.moved && Math.hypot(p.x - down.x, p.y - down.y) > 6) down.moved = true;
    if (down.moved) view.panBy(p.x - prev.x, p.y - prev.y);
  });
  const up = (e: PointerEvent) => {
    const p = local(e); pts.delete(e.pointerId); pinch = 0;
    if (!down) return;
    const d = down; down = null;
    if (painting) { painting = false; return; }
    if (d.moved || d.button !== 0 || !running) return;
    if (ui.tool) { hover = origin(p, ui.tool); place(p); if (e.pointerType !== 'mouse') window.setTimeout(() => { hover = null; }, 700); return; }
    const t = view.screenToTile(p.x, p.y);
    const uid = t.x >= 0 && t.y >= 0 && t.x < s.size && t.y < s.size ? s.occ[t.y * s.size + t.x] : 0;
    ui.selected = uid || null;
  };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', e => { pts.delete(e.pointerId); down = null; painting = false; });
  cv.addEventListener('pointerleave', () => { if (!painting) hover = null; look = null; });
  cv.addEventListener('contextmenu', e => { e.preventDefault(); ui.tool = null; hover = null; });
  cv.addEventListener('wheel', e => { e.preventDefault(); const p = local(e); view.zoomAt(p.x, p.y, e.deltaY < 0 ? 1.12 : 1 / 1.12); }, { passive: false });

  window.addEventListener('keydown', e => {
    if (!running || helpOpen || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === '?') { e.preventDefault(); document.getElementById('btn-help')!.click(); return; }
    if (e.key === ' ') { e.preventDefault(); ui.speed = ui.speed ? 0 : 1; return; }
    if (e.key === 'Escape') { if (!ui.tool && ui.selected === null) hud.escape(); ui.tool = null; ui.selected = null; hover = null; return; }
    if (e.key === 'h' || e.key === 'H') { ui.overlay = !ui.overlay; return; }
    if (e.key === '[' || e.key === ']') { const sp = [0, 1, 2, 4, 8]; const i = sp.indexOf(ui.speed) + (e.key === ']' ? 1 : -1); ui.speed = sp[Math.max(0, Math.min(sp.length - 1, i))]; return; }
    const t = hud.keyTool(e.key);
    if (t) { ui.tool = ui.tool === t ? null : t; ui.selected = null; if (!ui.tool) hover = null; }
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden && running) save(s); last = performance.now(); });

  // ----- loop -----
  function frame(now: number) {
    const dt = Math.min(0.25, (now - last) / 1000); last = now;
    if (running && s.phase === 'playing' && ui.speed > 0) {
      acc += dt * ui.speed * HOURS_PER_SECOND;
      let steps = 0;
      while (acc >= TICK && steps < 120) { tick(s); acc -= TICK; steps++; }
      if (steps === 120) acc = 0;
    }
    if (running && s.phase !== 'playing' && !ended) { ended = true; ui.tool = null; hover = null; save(s); window.setTimeout(() => hud.ending(s), 900); }
    if (ui.hint && now > hintUntil) ui.hint = '';
    let ok: 'ok' | 'warn' | 'bad' = 'bad';
    const inMap = (q: { x: number; y: number }) => q.x >= 0 && q.y >= 0 && q.x < s.size && q.y < s.size;
    if (ui.tool && hover) {
      const z = zoneOf(ui.tool);
      if (z >= 0) {
        const why = zoneProblem(s, z, hover.x, hover.y);
        ok = why && why !== 'Already zoned' ? 'bad' : 'ok';
        if (now > hintUntil) ui.hint = why && why !== 'Already zoned' ? why : inMap(hover) ? tileHint(hover.y * s.size + hover.x, z) : '';
      } else {
        const why = placeProblem(s, ui.tool as BuildingType, hover.x, hover.y);
        const apart = !why && !touchesBase(s, ui.tool as BuildingType, hover.x, hover.y);
        ok = why ? 'bad' : apart ? 'warn' : 'ok';
        if (now > hintUntil) ui.hint = why ?? (apart ? 'Not touching your base. It will do nothing here unless you link it with conduit.' : '');
      }
    } else if (look && now > hintUntil && inMap(look)) {
      const b = s.buildings.find(q => q.uid === s.occ[look!.y * s.size + look!.x]);
      if (b) ui.hint = `${BUILDINGS[b.type].name}${b.level > 1 ? ' level ' + b.level : ''} · ${stateLine(b).text} · click for details`;
      else if (ui.overlay) ui.hint = `Habitability ${s.hab[look.y * s.size + look.x]}`;
    }
    view.frame(s, ui.selected, ui.tool, hover, ok, now, running && s.phase === 'playing' ? ui.speed : 0, ui.overlay);
    if (now - lastHud > 150) { lastHud = now; hud.update(s, ui); }
    if (running && s.phase === 'playing' && now - lastSave > 5000) { lastSave = now; save(s); }
    requestAnimationFrame(frame);
  }

  window.claude?.hot?.snapshot(() => (running ? { state: s, speed: ui.speed } : {}));
  refresh(s);
  view.centreOn(s.size / 2, s.size / 2);
  hud.update(s, ui);
  if (hot && hot.state && hot.state.v === 5) { begin(hot.state as State); ui.speed = hot.speed ?? 1; }
  else hud.briefing(load());
  window.__game = { get state() { return s; }, ui, view, send };
  requestAnimationFrame(frame);
}

const start = (data: any) => { boot(data).catch(err => { const m = document.getElementById('modal'); if (m) { m.classList.add('show'); m.innerHTML = `<div class="card"><h1>Could not start</h1><p class="lede">This browser did not give the game a graphics context. ${String(err && err.message || err)}</p></div>`; } }); };
if (window.claude?.hot?.ready) window.claude.hot.ready(start); else start(window.claude?.hot?.data ?? {});
