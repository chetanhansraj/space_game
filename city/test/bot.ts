declare const process: any; declare const require: any;
// Headless check. Plays the game with no graphics and asserts the things a player needs to be true:
//  1. doing nothing loses,
//  2. a player who does what the crew asks survives the first night with all four crew,
//  3. the colony then grows by itself on zoned land: habitats, foundries, lodges and concourses appear, people arrive,
//     rovers run, money comes in, and nobody is lost.
import { BUILDINGS, BuildingType, ZONES, ZONE_BUILDS, ZONE_COST } from '../src/sim/buildings';
import { MISSIONS } from '../src/sim/missions';
import { urgent } from '../src/ui/advisor';
import { State, Intent, createState, tick as localTick, apply as localApply, siteProblem, zoneProblem, habAt, aliveCount, population, support, tierOf, LUNAR_DAY, isNight } from '../src/sim/sim';

// The same player, against a town in the shared world.
//
//   TOWN_URL=http://127.0.0.1:8765 TOWN_KEY=<company key> node dist/bot.cjs
//
// Every request goes to the server and every hour is the server's: this page of the bot holds
// only a mirror, replaced by the server's state after each of its ticks. It needs a test server
// that will step its clock when asked (POST /test/step), which no live server does.
const REMOTE: string = process.env.TOWN_URL || '';
let refused = 0, sent = 0;
function http(method: string, path: string, body?: unknown): any {
  const args = ['-s', '-X', method, REMOTE + path, '-H', 'Authorization: Bearer ' + process.env.TOWN_KEY, '-H', 'Content-Type: application/json'];
  if (body !== undefined) args.push('-d', JSON.stringify(body));
  return JSON.parse(require('child_process').execFileSync('curl', args, { encoding: 'utf8', maxBuffer: 1 << 28 }));
}
const mirror = (s: State, from: any) => { for (const k of Object.keys(s)) delete (s as any)[k]; Object.assign(s, from.state); (s as any).materials = from.meta.wallet; };
function apply(s: State, it: Intent): { ok: boolean; reason?: string } {
  const r = localApply(s, it);
  if (!REMOTE || !r.ok) return r;
  sent++;
  const reply = http('POST', '/api/town/intent', it);
  if (reply.detail) { refused++; mirror(s, http('GET', '/api/town')); return { ok: false, reason: reply.detail }; }
  mirror(s, reply);
  return r;
}
function tick(s: State) {
  if (!REMOTE) { localTick(s); return; }
  http('POST', '/test/step');
  mirror(s, http('GET', '/api/town'));
}

const DUSTY: BuildingType[] = ['pad', 'garage', 'o2plant', 'reactor', 'solar', 'battery'];

/** A free spot touching the base. Dusty things go east of the lander, pleasant things west, as a sensible player would. */
function findSpot(s: State, type: BuildingType): [number, number] | null {
  const d = BUILDINGS[type], c = s.size / 2, n = s.size;
  const tx = DUSTY.includes(type) ? c + 6 : c - 5;
  let best: [number, number] | null = null, bestScore = Infinity;
  const at = (x: number, y: number) => x >= 0 && y >= 0 && x < n && y < n && (s.occ[y * n + x] > 0 || s.zone[y * n + x] > 0);
  for (let y = 0; y < n - d.h; y++) for (let x = 0; x < n - d.w; x++) {
    if (siteProblem(s, type, x, y)) continue;
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
    if (siteProblem(s, 'reactor', x, y)) continue;
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

/** Zone the best two-by-two block of a survey find for Industry, with a conduit out to it if it stands alone. */
function zoneOre(s: State): boolean {
  const n = s.size, c = n / 2;
  let best: [number, number] | null = null, bs = -Infinity;
  for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) {
    const ks = [y * n + x, y * n + x + 1, (y + 1) * n + x, (y + 1) * n + x + 1];
    if (ks.some(k => s.zone[k] || s.occ[k] || s.ground[k] !== 0)) continue;
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

/** Zone one two-by-two lot touching linked ground. People zones take the most habitable spot, the others the least. */
function zoneLot(s: State, z: number): boolean {
  if (s.materials < 4 * ZONE_COST) return false;
  const n = s.size, c = n / 2, people = z === 1 || z === 3;
  let best: [number, number] | null = null, bestScore = -Infinity;
  const linked = (x: number, y: number) => x >= 0 && y >= 0 && x < n && y < n && s.linked[y * n + x] > 0;
  for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) {
    let ok = true, touch = false;
    for (let j = 0; j < 2; j++) for (let i = 0; i < 2; i++) { if (zoneProblem(s, z, x + i, y + j)) ok = false; if (s.zone[(y + j) * n + x + i]) ok = false; }
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

/** A player who does what the crew says, and between missions answers what the demand bars ask for. */
function play(name: string, hours: number, follow: boolean) {
  const s = createState(1969);
  if (REMOTE) mirror(s, http('POST', '/api/town/found', {}));
  const log: string[] = [];
  let next = 0, lastMission = -1;
  while (s.phase === 'playing' && s.t < hours) {
    if (follow && s.t >= next) {
      next = s.t + 1;
      if (s.mission !== lastMission) { lastMission = s.mission; const m = MISSIONS[s.mission]; log.push(`t=${s.t.toFixed(0)} [${m ? s.crew[m.who].name.split(' ')[0] : '-'}] ${m ? m.goal : 'all missions done'} (credits ${s.materials.toFixed(0)}, pop ${population(s)})`); }
      const u = urgent(s), m = MISSIONS[s.mission];
      const count = (t: BuildingType) => s.buildings.filter(b => b.type === t).length;
      const answer = (why: string, z: number): boolean => {
        if (why === 'no zoned land') return zoneLot(s, z);
        if (why === 'night power') return s.mission > 9 && count('reactor') < 6 && s.materials >= 200 ? put(s, 'reactor') || put(s, 'battery') : s.mission > 9 && count('battery') >= 8 + 4 * count('reactor') ? false : put(s, 'battery');
        if (why === 'daytime power') return put(s, 'solar');
        if (why === 'oxygen tanks') return put(s, 'o2tank');
        if (why === 'oxygen plants') return put(s, 'o2plant');
        if (why === 'greenhouses') return put(s, 'greenhouse');
        if (why === 'people want a garden') return put(s, 'garden');
        if (why === 'people want a clinic') return put(s, 'clinic');
        if (why.includes('Commercial')) return freeLot(s, 3) ? false : zoneLot(s, 3);
        if (why.includes('habitability')) return count('garden') < 1 + Math.floor(count('habitat') / 3) ? put(s, 'garden') : zoneLot(s, z);
        return false;
      };
      if (u) {
        if (u.title.startsWith('Repair')) { for (const b of s.buildings) if (b.damaged && b.repair === 0) apply(s, { k: 'repair', uid: b.uid }); }
        else if (u.zone) { if (!freeLot(s, u.zone)) zoneLot(s, u.zone); }
        else if (u.tool && u.tool !== 'conduit') put(s, u.tool);
      } else if (!isNight(s.t)) {
        let acted = false;
        if (m && m.goal.includes('survey find')) acted = !oreZoned(s) && zoneOre(s);
        else if (m && m.tool) acted = put(s, m.tool);
        else if (m && m.zone && !freeLot(s, m.zone) && !s.buildings.some(b => b.type === ZONE_BUILDS[m.zone!] && b.progress < 1) && s.want[ZONES[m.zone - 1].key] > 0.15) acted = zoneLot(s, m.zone);
        // sign what is offered, then work to keep it
        if (s.offer) apply(s, { k: 'offer', accept: true });
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
          if (cap.limit - population(s) < 4) acted = answer(cap.why, 1);
          if (!acted && count('garage') < 2 && s.tourists >= 6) acted = put(s, 'garage');
        }
      }
    }
    tick(s);
    if (follow && process.env.DEALS && hours > 1000) for (const a of s.alerts) if (a.id > (s as any)._seen || !(s as any)._seen) { if (/ontract|offer|Survey find|storm|scrubbed|came in hard|breach/.test(a.msg)) log.push(`      t=${s.t.toFixed(0)} ${a.msg}`); (s as any)._seen = a.id; }
    if (follow && process.env.DUMP && hours > 1000 && [200, 843, 1150, 1500].some(q => Math.abs(s.t - q) < 0.05)) require('fs').writeFileSync(`/tmp/state-${Math.round(s.t)}.json`, JSON.stringify(s));
    if (follow && Math.abs(s.t / 177 - Math.round(s.t / 177)) < 0.0004) log.push(`    t=${s.t.toFixed(0)} ${isNight(s.t) ? 'night' : 'day  '} pop ${population(s)} (${s.residents} res, ${s.tourists} vis) credits ${s.materials.toFixed(0)} ${s.flows.income >= 0 ? '+' : ''}${s.flows.income.toFixed(1)}/h jobs ${s.flows.jobs}/${s.flows.workers} charge ${s.charge.toFixed(0)}/${s.flows.battCap} o2 ${s.o2.toFixed(0)} food ${s.food.toFixed(0)} | want R${s.want.r.toFixed(1)} I${s.want.i.toFixed(1)} V${s.want.v.toFixed(1)} | block ${ZONES.map(z => s.block[z.key] ? z.key + ':' + s.block[z.key] : '').filter(Boolean).join(', ') || 'none'} | grown ${s.stats.grown} up ${s.stats.upgrades} deals ${s.stats.deals}/${s.stats.broken} finds ${s.stats.finds} events ${s.stats.events} lost ${s.stats.lost} evac ${s.stats.evacuated}`);
  }
  const c: any = {}; for (const b of s.buildings) if (b.type !== 'conduit') c[b.type] = (c[b.type] || 0) + 1;
  console.log(`\n== ${name}: ${s.phase} at t=${s.t.toFixed(0)}h · crew ${aliveCount(s)}/4 · pop ${population(s)} (${tierOf(population(s))}) · credits ${s.materials.toFixed(0)} · mission ${s.mission}/${MISSIONS.length} · flights ${s.stats.flights} · trips ${s.stats.trips} · grown ${s.stats.grown} · upgrades ${s.stats.upgrades} · hab homes ${s.flows.habHomes.toFixed(0)} lodges ${s.flows.habLodges.toFixed(0)}`);
  if (follow) console.log('   ' + JSON.stringify(c));
  if (log.length) console.log(log.join('\n'));
  return s;
}

if (REMOTE) {
  const town = play('The same player, through the server, for three lunar days', LUNAR_DAY * 3, true);
  const meta = http('GET', '/api/town').meta;
  console.log(`\nrequests sent ${sent}, refused by the server ${refused} · wallet ${meta.credits} cr · owed ${meta.owed} · faults ${meta.faults} · trade open ${meta.trade.open}`);
  let bad = 0;
  const want = (ok: boolean, msg: string) => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`); if (!ok) bad++; };
  want(town.phase === 'playing' && aliveCount(town) === 4, 'on the server, after three lunar days the crew is still alive');
  want(population(town) >= 20, 'the town has grown to a Colony of 20 or more');
  want(town.stats.grown >= 8, 'at least eight buildings grew by themselves');
  want(town.stats.deals >= 2, 'contracts with nations and companies were signed and kept');
  want(meta.faults === 0 && meta.owed === 0, 'the town never failed an hour and owes nothing');
  want(meta.trade.open, 'and the market is open to it');
  want(refused <= sent / 20, 'the server agreed with the player about almost every move');
  process.exit(bad ? 1 : 0);
}
const idle = play('Do nothing', LUNAR_DAY, false);
const night1 = play('Follow the crew through the first night', LUNAR_DAY + 1, true);
const day3 = play('Follow the crew for three lunar days', LUNAR_DAY * 3, true);

let fail = 0;
const expect = (ok: boolean, msg: string) => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`); if (!ok) fail++; };
console.log('');
expect(idle.phase === 'lost', 'doing nothing loses');
expect(night1.phase === 'playing' && aliveCount(night1) === 4, 'following the crew brings all four through the first night');
expect(night1.crew.every(c => c.health > 80), 'and in good health');
expect(night1.stats.grown >= 1, 'a company built a foundry on zoned Industry land');
expect(night1.stats.flights >= 1 && night1.stats.trips >= 1, 'a shuttle has landed and rovers have been out before the first sunrise');
expect(night1.mission >= 12, 'the first twelve missions are complete at the first sunrise');
expect(day3.phase === 'playing' && aliveCount(day3) === 4, 'after three lunar days the crew is still alive');
expect(population(day3) >= 20, 'the base has grown to a Colony of 20 or more');
expect(day3.stats.grown >= 8, 'at least eight buildings grew by themselves');
expect(day3.stats.upgrades >= 1, 'and at least one expanded because its surroundings were good');
expect(day3.stats.lost === 0 && day3.stats.evacuated === 0, 'without losing or evacuating a single resident or visitor');
expect(day3.materials > 0 && day3.stats.earned > 800, 'and it earns its living');
expect(day3.stats.deals >= 2 && day3.stats.broken <= 1, 'contracts with nations and companies are signed and kept');
expect(day3.buildings.some(b => b.type === 'market') && day3.buildings.some(b => b.type === 'lodge'), 'Commercial land grew both a lodge and a concourse');
expect(day3.stats.finds >= 2 && day3.buildings.some(b => b.type === 'printer' && day3.ore[b.y * day3.size + b.x] > 0), 'rovers found ore and a foundry stands on it');
expect(day3.stats.events >= 3, 'storms, breaches and delays came and the town came through them');
expect(day3.materials < 4000, 'and credits have not piled up out of reach of any cost');
process.exit(fail ? 1 : 0);
