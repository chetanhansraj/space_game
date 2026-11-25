// The steward: one hour's decisions of a player who does what the crew asks and then answers what
// the town is short of. Deterministic, no randomness of its own, and it can do nothing a player
// cannot: every move it makes goes through `apply`, one of the game's seven requests at a time.
//
// It has three users. The headless test plays whole lunar days with it. The server asks it what a
// careful player would do next (Town.steward in engine.ts), which is how a town can be looked
// after while its owner is away and how a town can be run by the world itself. And it is the
// reference for what "playable" means: if the steward cannot keep a town alive, the rules are wrong.
import { BUILDINGS, BuildingType, ZONES, ZONE_BUILDS, ZONE_COST } from './sim/buildings';
import { MISSIONS, missions } from './sim/missions';
import { urgent } from './ui/advisor';
import { State, Intent, PRICES, BLAST, ground, siteProblem, siteWarning, tileRing, inBlast, padOf, padSite, zoneProblem, habAt, aliveCount, population, support, isNight, world } from './sim/sim';

/** The last of the crew's missions that needs a working foundry. A temperament that shuts foundries waits until it is done. */
const lastFoundry = (list: typeof MISSIONS) => list.reduce((last, m, i) => (/foundry|Industry/.test(m.goal) ? i : last), -1);

export type Apply = (s: State, it: Intent) => { ok: boolean; reason?: string };

/**
 * A temperament: how a company likes to build once its crew is safe. It changes what the steward
 * chooses, never what it is allowed: every choice is still one of the game's seven requests.
 * What the crew asks for (missions) and what is urgent are done whatever the temperament.
 */
export interface Style {
  /** The most two-by-two lots of a zone it lays out of its own accord: r homes, i industry, v commercial. Missing means no limit. */
  lots?: { r?: number; i?: number; v?: number };
  /** The price level it charges: 0 low, 1 fair, 2 high. Missing leaves prices alone. */
  price?: number;
  /** Kinds of contract it turns down. */
  refuse?: string[];
  /**
   * The most foundries it keeps running once the crew's own foundry missions are done; the rest it
   * switches off. A resort that runs none makes no goods, and has to buy every part its buildings wear out.
   */
  foundries?: number;
}

/** A steward who acts through `apply`. Call the result once a game hour. */
export function steward(apply: Apply, style: Style = {}): (s: State, keep?: boolean) => void {
  const DUSTY: BuildingType[] = ['pad', 'garage', 'o2plant', 'reactor', 'solar', 'battery', 'drill', 'sabatier', 'wind'];

  /** A free spot touching the base. Dusty things go east of the lander, pleasant things west, as a sensible player would. */
  function findSpot(s: State, type: BuildingType): [number, number] | null {
    const d = BUILDINGS[type], c = s.size / 2, n = s.size;
    const tx = DUSTY.includes(type) ? c + 6 : c - 5;
    let best: [number, number] | null = null, bestScore = Infinity;
    const at = (x: number, y: number) => x >= 0 && y >= 0 && x < n && y < n && (s.occ[y * n + x] > 0 || s.zone[y * n + x] > 0);
    for (let y = 0; y < n - d.h; y++) for (let x = 0; x < n - d.w; x++) {
      if (siteProblem(s, type, x, y) || siteWarning(s, type, x, y)) continue;   // not where a landing would take it (D96)
      let touch = false;
      for (let i = 0; i < d.w && !touch; i++) touch = at(x + i, y - 1) || at(x + i, y + d.h);
      for (let j = 0; j < d.h && !touch; j++) touch = at(x - 1, y + j) || at(x + d.w, y + j);
      if (!touch) continue;
      const dist = Math.hypot(x + d.w / 2 - tx, y + d.h / 2 - c);
      if (dist < bestScore) { bestScore = dist; best = [x, y]; }
    }
    return best;
  }

  // Lay a conduit line from the network to the nearest legal reactor site, well east of the homes.
  function placeReactor(s: State): boolean {
    const d = BUILDINGS.reactor, n = s.size, c = n / 2;
    let site: [number, number] | null = null, bd = Infinity;
    for (let y = 1; y < n - d.h - 1; y++) for (let x = 1; x < n - d.w - 1; x++) {
      if (siteProblem(s, 'reactor', x, y) || siteWarning(s, 'reactor', x, y)) continue;
      let zoned = false; for (let j = -1; j <= d.h; j++) for (let i = -1; i <= d.w; i++) if (s.zone[(y + j) * n + x + i]) zoned = true;
      if (zoned) continue;
      const dist = Math.hypot(x - (c + 12), y - c);
      if (dist < bd) { bd = dist; site = [x, y]; }
    }
    if (!site) return false;
    if (!linkSite(s, site[0], site[1], d.w, d.h, BUILDINGS.reactor.cost)) return false;
    return apply(s, { k: 'place', type: 'reactor', x: site[0], y: site[1] }).ok;
  }

  /** Lay the shortest conduit line from linked ground to the edge of a site. False if there is no way or not enough money. */
  function linkSite(s: State, sx: number, sy: number, w: number, h: number, extra: number): boolean {
    const n = s.size;
    const inSite = (x: number, y: number) => x >= sx && x < sx + w && y >= sy && y < sy + h;
    const prev = new Map<number, number>(), q: number[] = [];
    const free = (x: number, y: number) => x >= 0 && y >= 0 && x < n && y < n && !s.occ[y * n + x] && !s.zone[y * n + x] && s.ground[y * n + x] === 0 && !inSite(x, y);
    const linked = (x: number, y: number) => x >= 0 && y >= 0 && x < n && y < n && s.linked[y * n + x] > 0;
    for (let i = -1; i <= w; i++) for (let j = -1; j <= h; j++) {
      if ((i === -1 || i === w) === (j === -1 || j === h)) continue;   // edges only, no corners, no inside
      if (linked(sx + i, sy + j)) return true;                          // already touching the network
      if (free(sx + i, sy + j)) { prev.set((sy + j) * n + sx + i, -1); q.push((sy + j) * n + sx + i); }
    }
    let end = -1;
    while (q.length && end < 0) {
      const k = q.shift()!, x = k % n, y = (k - x) / n;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const X = x + dx, Y = y + dy;
        if (X < 0 || Y < 0 || X >= n || Y >= n) continue;
        if (s.linked[Y * n + X]) { end = k; break; }
        if (free(X, Y) && !prev.has(Y * n + X)) { prev.set(Y * n + X, k); q.push(Y * n + X); }
      }
    }
    if (end < 0) return false;
    let cost = extra; for (let k = end; k >= 0; k = prev.get(k)!) cost++;
    if (s.materials < cost) return false;
    for (let k = end; k >= 0; k = prev.get(k)!) apply(s, { k: 'place', type: 'conduit', x: k % n, y: Math.floor(k / n) });
    return true;
  }

  /** The pad stands off on its own, on the dusty side, with a conduit out to it: the rules know where (padSite). (D96) */
  function placePad(s: State): boolean {
    const d = BUILDINGS.pad, site = padSite(s);
    if (!site) return false;
    if (!linkSite(s, site[0], site[1], d.w, d.h, d.cost)) return false;
    return apply(s, { k: 'place', type: 'pad', x: site[0], y: site[1] }).ok;
  }

  /** Zone the best two-by-two block of a survey find for Industry, with a conduit out to it if it stands alone. */
  function zoneOre(s: State): boolean {
    const n = s.size, c = n / 2;
    let best: [number, number] | null = null, bs = -Infinity;
    for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) {
      const ks = [y * n + x, y * n + x + 1, (y + 1) * n + x, (y + 1) * n + x + 1];
      if (ks.some(k => s.zone[k] || s.occ[k] || s.ground[k] !== 0)) continue;
      if (ks.some(k => { const r = tileRing(s, k % n, Math.floor(k / n)); return r === 'red' || r === 'hurt'; })) continue;
      const ore = ks.filter(k => s.ore[k]).length;
      if (ore < 3) continue;
      const score = ore * 10 - Math.hypot(x + 1 - c, y + 1 - c);
      if (score > bs) { bs = score; best = [x, y]; }
    }
    if (!best || !linkSite(s, best[0], best[1], 2, 2, 4 * ZONE_COST)) return false;
    for (let j = 0; j < 2; j++) for (let i = 0; i < 2; i++) apply(s, { k: 'zone', z: 2, x: best[0] + i, y: best[1] + j });
    return true;
  }
  const oreZoned = (s: State) => s.zone.some((z, k) => z === 2 && s.ore[k] > 0);

  const put = (s: State, t: BuildingType) => {
    if (s.materials < BUILDINGS[t].cost) return false;
    if (t !== 'battery' && t !== 'solar' && s.buildings.some(b => b.type === t && b.progress < 1)) return false;   // one at a time
    if (t === 'reactor') return placeReactor(s);
    if (t === 'pad') return placePad(s);
    const p = findSpot(s, t);
    return !!p && apply(s, { k: 'place', type: t, x: p[0], y: p[1] }).ok;
  };

  /** Is there an empty, linked two-by-two lot of this zone waiting for a builder? */
  function freeLot(s: State, z: number): boolean {
    const n = s.size;
    for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) {
      const ks = [y * n + x, y * n + x + 1, (y + 1) * n + x, (y + 1) * n + x + 1];
      if (ks.every(k => s.zone[k] === z && !s.occ[k] && s.linked[k])) return true;
    }
    return false;
  }

  /**
   * Zone one two-by-two lot touching linked ground. People zones take the most habitable spot, the others the least.
   * Unless it `must` (the crew asked, or it is urgent), a company stops at as many lots of a kind as its temperament wants.
   */
  function zoneLot(s: State, z: number, must = false): boolean {
    const most = style.lots?.[ZONES[z - 1].key];
    if (!must && most !== undefined && s.zone.reduce((n, k) => n + (k === z ? 1 : 0), 0) >= most * 4) return false;
    if (s.materials < 4 * ZONE_COST) return false;
    const n = s.size, c = n / 2, people = z === 1 || z === 3;
    let best: [number, number] | null = null, bestScore = -Infinity;
    const linked = (x: number, y: number) => x >= 0 && y >= 0 && x < n && y < n && s.linked[y * n + x] > 0;
    for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) {
      let ok = true, touch = false;
      for (let j = 0; j < 2; j++) for (let i = 0; i < 2; i++) { if (zoneProblem(s, z, x + i, y + j)) ok = false; if (s.zone[(y + j) * n + x + i]) ok = false; const r = tileRing(s, x + i, y + j); if (r === 'red' || r === 'hurt') ok = false; }
      if (!ok) continue;
      for (let i = 0; i < 2; i++) touch = touch || linked(x + i, y - 1) || linked(x + i, y + 2) || linked(x - 1, y + i) || linked(x + 2, y + i);
      if (!touch) continue;
      const hab = habAt(s, x, y), side = people ? c - 5 : c + 5;
      const score = (people ? hab : -hab * 0.3) - Math.hypot(x + 1 - side, y + 1 - c) * 1.5;
      if (score > bestScore) { bestScore = score; best = [x, y]; }
    }
    if (!best) return false;
    for (let j = 0; j < 2; j++) for (let i = 0; i < 2; i++) apply(s, { k: 'zone', z, x: best[0] + i, y: best[1] + j });
    return true;
  }

  /**
   * `keep` is a caretaker's brief: deal with what is urgent (a breach to repair, air, water, food,
   * power for tonight) and nothing else. No missions, no zoning for growth, no contracts signed.
   */
  return (s: State, keep = false) => {
    ground(s);
    const u = urgent(s, false), m = missions(s)[s.mission];
    const count = (t: BuildingType) => s.buildings.filter(b => b.type === t).length;
    // A pad that stands among the buildings: move it, once there is the money to. A town that has had a ship and
    // has no pad builds one. This is what a house company does with the notice the old towns were given. (D96)
    if (s.blast !== undefined) {
      const pad = padOf(s);
      if (pad && pad.progress >= 1 && s.shuttle.phase === 'away' && s.materials >= BUILDINGS.pad.cost + 25) {
        const hit = inBlast(s, pad.x, pad.y);
        if ((hit.lost.length || hit.hurt.length) && padSite(s, true)) { apply(s, { k: 'demolish', uid: pad.uid }); if (put(s, 'pad')) return; }
      }
      if (!padOf(s) && (s.stats.flights > 0 || s.nextShuttle > 0) && put(s, 'pad')) return;
    }
    const answer = (why: string, z: number): boolean => {
      if (why === 'no zoned land') return zoneLot(s, z);
      if (why === 'night power') return s.mission > 9 && count('reactor') < 6 && s.materials >= 200 ? put(s, 'reactor') || put(s, 'battery') : s.mission > 9 && count('battery') >= 8 + 4 * count('reactor') ? false : put(s, 'battery');
      // On Mars the arrays give so little that past a dozen a reactor is the better buy.
      if (why === 'daytime power') return world().id === 'mars' && count('solar') >= 8 && s.materials >= BUILDINGS.reactor.cost + 20 ? put(s, 'reactor') || put(s, 'solar') : put(s, 'solar');
      if (why === 'oxygen tanks') return put(s, 'o2tank');
      if (why === 'oxygen plants') return put(s, 'o2plant');
      if (why === 'greenhouses') return put(s, 'greenhouse');
      if (why === 'ice drills') return put(s, 'drill');
      if (why === 'water recycling') return put(s, 'recycler');
      if (why === 'people want a garden') return put(s, 'garden');
      if (why === 'people want a clinic') return put(s, 'clinic');
      if (why.includes('Commercial')) return freeLot(s, 3) ? false : zoneLot(s, 3);
      if (why.includes('habitability')) return count('garden') < 1 + Math.floor(count('habitat') / 3) ? put(s, 'garden') : zoneLot(s, z);
      return false;
    };
    if (u) {
      if (u.title.startsWith('Repair')) { for (const b of s.buildings) if (b.damaged && b.repair === 0) apply(s, { k: 'repair', uid: b.uid }); }
      else if (u.zone) { if (!freeLot(s, u.zone)) zoneLot(s, u.zone, true); }
      else if (u.tool && u.tool !== 'conduit') put(s, u.tool);
    } else if (!keep && !isNight(s.t)) {
      let acted = false;
      if (m && m.goal.includes('survey find')) acted = !oreZoned(s) && zoneOre(s);
      else if (m && m.tool) acted = put(s, m.tool);
      else if (m && m.zone && !freeLot(s, m.zone) && !s.buildings.some(b => b.type === ZONE_BUILDS[m.zone!] && b.progress < 1) && s.want[ZONES[m.zone - 1].key] > 0.15) acted = zoneLot(s, m.zone, true);
      // sign what is offered, then work to keep it
      if (s.offer) apply(s, { k: 'offer', accept: !style.refuse?.includes(s.offer.kind) });
      if (style.price !== undefined && s.price !== PRICES[style.price]) apply(s, { k: 'price', level: style.price });
      if (style.foundries !== undefined && s.mission > lastFoundry(missions(s))) {
        const running = s.buildings.filter(b => b.type === 'printer' && b.on && b.progress >= 1).sort((a, b) => b.level - a.level || a.uid - b.uid);
        for (const b of running.slice(style.foundries)) apply(s, { k: 'toggle', uid: b.uid });
      }
      if (!acted) for (const d of s.deals) {
        if (d.kind === 'team') { const cap = support(s); acted = cap.limit - population(s) < 4 ? answer(cap.why, 1) : s.flows.housing - aliveCount(s) - s.residents < 4 ? put(s, 'habitat') : false; }
        else if (d.kind === 'oxygen') acted = s.flows.o2Cap < (d.amount ?? 150) + 0.035 * population(s) * 400 + 40 ? put(s, 'o2tank') : s.flows.o2Rate < 1 ? put(s, 'o2plant') : false;
        else if (d.kind === 'works') acted = !freeLot(s, 2) && zoneLot(s, 2);
        else acted = count('garage') < 1 ? put(s, 'garage') : s.flows.lodging < (d.amount ?? 6) && !freeLot(s, 3) ? zoneLot(s, 3) : false;
        if (acted) break;
      }
      // answer whatever is wanted and blocked
      if (!acted) for (const z of [...ZONES].sort((a, b) => (b.z === m?.zone ? 1 : 0) - (a.z === m?.zone ? 1 : 0))) if (s.want[z.key] > 0.15 && s.block[z.key] && answer(s.block[z.key], z.z)) { acted = true; break; }
      if (!acted && s.mission > 9) {
        const cap = support(s);
        if (cap.limit - population(s) < world().berths) acted = answer(cap.why, 1);
        if (!acted && count('garage') < 2 && s.tourists >= 6) acted = put(s, 'garage');
      }
    }
  };
}
