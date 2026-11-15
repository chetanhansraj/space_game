// The world acting on the base: graders that level zoned ground, what the rovers find, and things that go wrong.

import { BUILDINGS } from './buildings';
import { State, Building, GROUND, LUNAR_DAY, bedsOf, hoursToSunrise, hoursToSunset, isNight, pushAlert, rnd, working } from './sim';

export interface Grader { x: number; y: number; k: number; phase: 'idle' | 'go' | 'work' | 'home'; }
export interface Find { id: number; x: number; y: number; kind: number; near: string; }
export type EventKind = 'storm' | 'scrub' | 'dust' | 'breach';
export interface GameEvent { kind: EventKind; from: number; to: number; hit: boolean; }

export const GRADER_SPEED = 1.5;      // tiles an hour
export const DUST_RADIUS = 5, DUST_HOURS = 60, STORM_HOURS = 16, STORM_WARNING = 10, SCRUB_HOURS = 45;
/** What the rovers can find. A foundry standing on a deposit earns that much more. */
export const ORES = [
  { name: 'Ilmenite', what: 'titanium and iron ore', bonus: 0.5, color: 0xb59cf0 },
  { name: 'Pyroclastic glass', what: 'volcanic glass beads, rich in volatiles', bonus: 0.5, color: 0xf0a04e },
  { name: 'Helium-3 regolith', what: 'old soil soaked by the solar wind', bonus: 1, color: 0x6fe3d2 },
];
const FIND_AT = [3, 18, 40, 70, 110];   // rover trips before each find
const FIND_KIND = [0, 1, 0, 2, 1];
const LENA = 2, RAFAEL = 3, ASHA = 0, KENJI = 1;

// ---------- ground ----------
/** Hours a grader needs on each tile: 2 on smooth ground, up to 6 where it is rough. Rough ground comes in patches. */
export function initWorld(s: State) {
  const n = s.size, G = 7, grid: number[] = [];
  for (let i = 0; i < (G + 1) * (G + 1); i++) grid.push(rnd(s));
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const fx = (x / n) * G, fy = (y / n) * G, ix = Math.floor(fx), iy = Math.floor(fy), ax = fx - ix, ay = fy - iy;
    const at = (i: number, j: number) => grid[j * (G + 1) + i];
    const v = at(ix, iy) * (1 - ax) * (1 - ay) + at(ix + 1, iy) * ax * (1 - ay) + at(ix, iy + 1) * (1 - ax) * ay + at(ix + 1, iy + 1) * ax * ay;
    s.rough[y * n + x] = Math.max(2, Math.min(6, Math.round(1 + v * 6)));
  }
}

/** Is this two-by-two lot level and ready to build on? */
export const lotLevel = (s: State, x: number, y: number) => {
  const k = y * s.size + x, n = s.size;
  return s.prep[k] >= 1 && s.prep[k + 1] >= 1 && s.prep[k + n] >= 1 && s.prep[k + n + 1] >= 1;
};
/** Zoned tiles still waiting for a grader. */
export const rawTiles = (s: State) => { let c = 0; for (let k = 0; k < s.zone.length; k++) if (s.zone[k] && !s.occ[k] && s.prep[k] < 1) c++; return c; };

const needsGrading = (s: State, k: number) => s.zone[k] > 0 && !s.occ[k] && s.prep[k] < 1;

/** Two graders live at the lander, and every Rover Bay adds one. They level zoned ground, nearest first. */
export function tickGraders(s: State, dt: number) {
  const n = s.size, hx = n / 2, hy = n / 2;
  const want = 2 + s.buildings.filter(b => b.type === 'garage' && working(b)).length;
  while (s.graders.length < want) s.graders.push({ x: hx, y: hy, k: -1, phase: 'idle' });
  if (stormActive(s)) return;
  const look = Math.round(s.t * 10) % 5 === 0;
  for (const g of s.graders) {
    if (g.phase === 'idle' || g.phase === 'home') {
      if (look) {
        let best = -1, bd = Infinity;
        for (let k = 0; k < s.zone.length; k++) {
          if (!needsGrading(s, k) || s.graders.some(o => o !== g && o.k === k && (o.phase === 'go' || o.phase === 'work'))) continue;
          const d = Math.hypot((k % n) + 0.5 - g.x, Math.floor(k / n) + 0.5 - g.y);
          if (d < bd) { bd = d; best = k; }
        }
        if (best >= 0) { g.k = best; g.phase = 'go'; }
      }
      if (g.phase === 'idle' && Math.hypot(g.x - hx, g.y - hy) > 0.1) g.phase = 'home';
    }
    if (g.phase === 'go' || g.phase === 'work') {
      if (!needsGrading(s, g.k)) { g.phase = 'idle'; g.k = -1; continue; }
    }
    if (g.phase === 'work') {
      s.prep[g.k] += dt / s.rough[g.k];
      if (s.prep[g.k] >= 1) { s.prep[g.k] = 1; s.rev++; g.phase = 'idle'; g.k = -1; }
      continue;
    }
    if (g.phase === 'go' || g.phase === 'home') {
      const tx = g.phase === 'go' ? (g.k % n) + 0.5 : hx, ty = g.phase === 'go' ? Math.floor(g.k / n) + 0.5 : hy;
      const dx = tx - g.x, dy = ty - g.y, dist = Math.hypot(dx, dy), step = GRADER_SPEED * dt;
      if (dist > step) { g.x += (dx / dist) * step; g.y += (dy / dist) * step; }
      else { g.x = tx; g.y = ty; g.phase = g.phase === 'go' ? 'work' : 'idle'; }
    }
  }
}

// ---------- survey finds ----------
/** How much richer than plain regolith the ground under this building is: 0, or up to 1 for helium-3. */
export function richOf(s: State, b: { type: Building['type']; x: number; y: number }): number {
  const d = BUILDINGS[b.type]; let sum = 0;
  for (let j = 0; j < d.h; j++) for (let i = 0; i < d.w; i++) { const o = s.ore[(b.y + j) * s.size + b.x + i]; if (o) sum += ORES[o - 1].bonus; }
  return sum / (d.w * d.h);
}
/** An empty Industry lot on a deposit, level and linked. Companies come for these whether or not there are hands to hire. */
export function oreLot(s: State): boolean {
  const n = s.size;
  for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) {
    const ks = [y * n + x, y * n + x + 1, (y + 1) * n + x, (y + 1) * n + x + 1];
    if (ks.every(k => s.zone[k] === 2 && !s.occ[k] && s.linked[k] && s.prep[k] >= 1) && ks.some(k => s.ore[k])) return true;
  }
  return false;
}

/** Called when a rover comes home. Every so many trips Rafael's instruments turn something up. */
export function maybeFind(s: State) {
  const i = s.finds.length;
  if (i >= FIND_AT.length || s.stats.trips < FIND_AT[i]) return;
  const kind = FIND_KIND[i], n = s.size, c = n / 2, ore = ORES[kind];
  for (let tries = 0; tries < 80; tries++) {
    const ang = rnd(s) * Math.PI * 2, dist = 6 + rnd(s) * (i < 2 ? 4 : 8), r = 1.6 + rnd(s) * 0.7;
    const cx = c + Math.cos(ang) * dist, cy = c + Math.sin(ang) * dist;
    const tiles: number[] = [];
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const k = y * n + x;
      if (Math.hypot(x + 0.5 - cx, y + 0.5 - cy) < r && s.ground[k] === GROUND.flat && !s.occ[k] && !s.ore[k]) tiles.push(k);
    }
    if (tiles.length < 7) continue;
    for (const k of tiles) s.ore[k] = kind + 1;
    let near = '', nd = 7;
    for (const p of s.pois) { const d = Math.hypot(p.x - cx, p.y - cy); if (d < nd) { nd = d; near = p.name; } }
    s.finds.push({ id: i + 1, x: cx, y: cy, kind, near });
    s.stats.finds++; s.rev++;
    pushAlert(s, 'good', `Survey find: ${ore.name.toLowerCase()}, ${ore.what}${near ? `, near ${near}` : ''}. It is marked on the map. A foundry standing on it earns ${Math.round(ore.bonus * 100)}% more. Zone it for Industry before something else goes there.`, RAFAEL);
    return;
  }
}

// ---------- things that go wrong ----------
export const stormActive = (s: State) => !!s.event && s.event.kind === 'storm' && s.t >= s.event.from && s.t < s.event.to;
export const dustActive = (s: State) => !!s.event && s.event.kind === 'dust' && s.t < s.event.to;
/** Is this solar array under the dust a hard landing threw up? */
export function dusty(s: State, b: Building): boolean {
  if (!dustActive(s) || !BUILDINGS[b.type].solar) return false;
  const pad = s.buildings.find(q => q.type === 'pad');
  return !!pad && Math.hypot(b.x + BUILDINGS[b.type].w / 2 - (pad.x + 1.5), b.y + BUILDINGS[b.type].h / 2 - (pad.y + 1.5)) < DUST_RADIUS;
}
/** One line for the top of the screen while something is happening. */
export function eventLine(s: State): { text: string; tone: string } | null {
  const e = s.event;
  if (!e) return null;
  const h = (t: number) => Math.max(1, Math.ceil(t - s.t));
  if (e.kind === 'storm') return s.t < e.from ? { text: `Solar storm in ${h(e.from)} h`, tone: 'warn' } : { text: `Solar storm · ${h(e.to)} h left`, tone: 'bad' };
  if (e.kind === 'scrub') return { text: `Shuttle delayed · ${h(e.to)} h`, tone: 'warn' };
  if (e.kind === 'dust') return { text: `Dust around the pad · ${h(e.to)} h`, tone: 'warn' };
  return null;
}
export const repairCost = (b: Building) => Math.max(8, Math.round(BUILDINGS[b.type].cost * 0.15)) * b.level;

export function tickEvents(s: State) {
  const e = s.event;
  if (e) {
    if (e.kind === 'storm' && !e.hit && s.t >= e.from) { e.hit = true; pushAlert(s, 'bad', 'The solar storm is here. Everyone is under cover. Foundries, rovers and graders have stopped.', LENA); }
    if (s.t >= e.to) {
      if (e.kind === 'storm') pushAlert(s, 'good', 'The storm has passed. Work outdoors can start again.', LENA);
      if (e.kind === 'dust') pushAlert(s, 'info', 'The dust around the pad has been swept off. Solar arrays there are back to full power.', LENA);
      s.event = null; s.nextEvent = s.t + 130 + rnd(s) * 110;
    }
    return;
  }
  // Nothing goes wrong before the first sunrise. After that, something does every week or so of daylight.
  if (s.nextEvent === 0) { if (s.t >= LUNAR_DAY) s.nextEvent = s.t + 40 + rnd(s) * 70; return; }
  if (s.t < s.nextEvent) return;
  if (isNight(s.t) || hoursToSunset(s.t) < 70) { s.nextEvent = s.t + hoursToSunrise(s.t) + 30 + rnd(s) * 60; return; }
  const pad = s.buildings.find(b => b.type === 'pad' && working(b));
  const homes = s.buildings.filter(b => (b.type === 'habitat' || b.type === 'lodge' || b.type === 'market') && working(b));
  const kinds: EventKind[] = ['storm'];
  if (pad && s.shuttle.phase === 'away' && s.nextShuttle > 0) kinds.push('scrub');
  if (pad) kinds.push('dust');
  if (homes.length > 1) kinds.push('breach');
  const pool = kinds.filter(k => k !== s.lastEvent);
  const kind = (pool.length ? pool : kinds)[Math.floor(rnd(s) * (pool.length ? pool.length : kinds.length))];
  s.lastEvent = kind; s.stats.events++;
  const left = (what: string, stock: number, rate: number) => (rate < -1e-6 && stock / -rate < 900 ? `${what} for ${Math.round(stock / -rate)} hours` : `${what} to spare`);
  if (kind === 'storm') {
    s.event = { kind, from: s.t + STORM_WARNING, to: s.t + STORM_WARNING + STORM_HOURS, hit: false };
    const clinic = s.buildings.some(b => b.type === 'clinic' && working(b));
    pushAlert(s, 'warn', `Solar storm in ${STORM_WARNING} hours. For ${STORM_HOURS} hours nobody works outdoors: foundries, rovers and graders stop, and the shuttle holds in orbit.${clinic ? '' : ' We have no clinic, so people will take it badly.'}`, LENA);
  } else if (kind === 'scrub') {
    s.nextShuttle = Math.max(s.nextShuttle, s.t) + SCRUB_HOURS;
    s.event = { kind, from: s.t, to: s.nextShuttle, hit: true };
    pushAlert(s, 'warn', `Earth has scrubbed a launch. The next shuttle is ${SCRUB_HOURS} hours late. We have ${left('food', s.food, s.flows.foodRate)} and ${left('water', s.water, s.flows.waterRate)}.`, ASHA);
  } else if (kind === 'dust') {
    s.event = { kind, from: s.t, to: s.t + DUST_HOURS, hit: true };
    const hit = s.buildings.filter(b => dusty(s, b)).length;
    pushAlert(s, hit ? 'warn' : 'info', `A cargo lander came in hard and threw dust over everything within ${DUST_RADIUS} tiles of the pad. ${hit ? `${hit} solar array${hit > 1 ? 's' : ''} there will give half power for ${DUST_HOURS} hours.` : 'No solar arrays were close enough to suffer.'}`, LENA);
  } else {
    const b = homes[Math.floor(rnd(s) * homes.length)], d = BUILDINGS[b.type];
    b.damaged = true; b.repair = 0; s.rev++;
    const beds = bedsOf(b);
    pushAlert(s, 'bad', `Pressure breach in a ${d.name}. ${beds ? `Its ${beds} beds are` : 'It is'} out of use until it is repaired. Repair costs ${repairCost(b)} credits.`, KENJI);
    s.nextEvent = s.t + 130 + rnd(s) * 110;
  }
}
