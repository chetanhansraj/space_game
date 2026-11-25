declare const process: any; declare const require: any;
// Headless check. Plays the game with no graphics and asserts the things a player needs to be true:
//  1. doing nothing loses,
//  2. a player who does what the crew asks survives the first night with all four crew,
//  3. the colony then grows by itself on zoned land: habitats, foundries, lodges and concourses appear, people arrive,
//     rovers run, money comes in, and nobody is lost,
//  4. and the same rules on Mars: doing nothing loses there too, and a player who follows the crew comes
//     through a dust storm, grows a settlement and makes propellant.
import { BUILDINGS, BuildingType, ZONES, ZONE_BUILDS, ZONE_COST } from '../src/sim/buildings';
import { MISSIONS, missions } from '../src/sim/missions';
import { steward } from '../src/steward';
import { WorldId } from '../src/sim/buildings';
import { State, Intent, createState, tick as localTick, apply as localApply, siteProblem, siteWarning, ringFrom, inBlast, padOf, blastOn, Ring, zoneProblem, habAt, aliveCount, population, support, tierOf, LUNAR_DAY, isNight } from '../src/sim/sim';
import { dusty } from '../src/sim/world';

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

const hour = steward(apply);


/** A player who does what the crew says, and between missions answers what the demand bars ask for. */
function play(name: string, hours: number, follow: boolean, on: WorldId = 'moon', seed = 1969) {
  const s = createState(seed, on);
  if (REMOTE) mirror(s, http('POST', '/api/town/found', {}));
  const log: string[] = [], said: string[] = [];
  let next = 0, lastMission = -1, heard = 0;
  while (s.phase === 'playing' && s.t < hours) {
    if (follow && s.t >= next) {
      next = s.t + 1;
      if (s.mission !== lastMission) { lastMission = s.mission; const m = missions(s)[s.mission]; log.push(`t=${s.t.toFixed(0)} [${m ? s.crew[m.who].name.split(' ')[0] : '-'}] ${m ? m.goal : 'all missions done'} (credits ${s.materials.toFixed(0)}, pop ${population(s)})`); }
      hour(s);
    }
    tick(s);
    for (const a of s.alerts) if (a.id > heard) { heard = a.id; said.push(a.msg); }
    if (follow && process.env.DEALS && hours > 1000) for (const a of s.alerts) if (a.id > (s as any)._seen || !(s as any)._seen) { if (/ontract|offer|Survey find|storm|scrubbed|came in hard|breach/.test(a.msg)) log.push(`      t=${s.t.toFixed(0)} ${a.msg}`); (s as any)._seen = a.id; }
    if (follow && process.env.DUMP && hours > 1000 && [200, 843, 1150, 1500].some(q => Math.abs(s.t - q) < 0.05)) require('fs').writeFileSync(`/tmp/state-${Math.round(s.t)}.json`, JSON.stringify(s));
    if (follow && Math.abs(s.t / 177 - Math.round(s.t / 177)) < 0.0004) log.push(`    t=${s.t.toFixed(0)} ${isNight(s.t) ? 'night' : 'day  '} pop ${population(s)} (${s.residents} res, ${s.tourists} vis) credits ${s.materials.toFixed(0)} ${s.flows.income >= 0 ? '+' : ''}${s.flows.income.toFixed(1)}/h jobs ${s.flows.jobs}/${s.flows.workers} charge ${s.charge.toFixed(0)}/${s.flows.battCap} o2 ${s.o2.toFixed(0)} food ${s.food.toFixed(0)} | want R${s.want.r.toFixed(1)} I${s.want.i.toFixed(1)} V${s.want.v.toFixed(1)} | block ${ZONES.map(z => s.block[z.key] ? z.key + ':' + s.block[z.key] : '').filter(Boolean).join(', ') || 'none'} | grown ${s.stats.grown} up ${s.stats.upgrades} deals ${s.stats.deals}/${s.stats.broken} finds ${s.stats.finds} events ${s.stats.events} lost ${s.stats.lost} evac ${s.stats.evacuated}`);
  }
  const c: any = {}; for (const b of s.buildings) if (b.type !== 'conduit') c[b.type] = (c[b.type] || 0) + 1;
  console.log(`\n== ${name}: ${s.phase} at t=${s.t.toFixed(0)}h · crew ${aliveCount(s)}/4 · pop ${population(s)} (${tierOf(population(s))}) · credits ${s.materials.toFixed(0)} · mission ${s.mission}/${missions(s).length} · flights ${s.stats.flights} · trips ${s.stats.trips} · grown ${s.stats.grown} · upgrades ${s.stats.upgrades} · hab homes ${s.flows.habHomes.toFixed(0)} lodges ${s.flows.habLodges.toFixed(0)}`);
  if (follow) console.log('   ' + JSON.stringify(c));
  if (log.length) console.log(log.join('\n'));
  return Object.assign(s, { said });
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
// A breach in a full lodge sends its guests home: that is the rules working, and which map it happens on is luck.
// Across six maps the blast zone changed evacuations from 52 to 18 (D96), so this asks for few, not none.
expect(day3.stats.lost === 0 && day3.stats.evacuated <= 3, 'without losing anyone, and with no more than three sent home');
expect(day3.materials > 0 && day3.stats.earned > 800, 'and it earns its living');
expect(day3.stats.deals >= 2 && day3.stats.broken <= 1, 'contracts with nations and companies are signed and kept');
expect(day3.buildings.some(b => b.type === 'market') && day3.buildings.some(b => b.type === 'lodge'), 'Commercial land grew both a lodge and a concourse');
expect(day3.stats.finds >= 2 && day3.buildings.some(b => b.type === 'printer' && day3.ore[b.y * day3.size + b.x] > 0), 'rovers found ore and a foundry stands on it');
expect(day3.stats.events >= 2, 'storms, breaches and delays came and the town came through them');
expect(day3.materials < 4000, 'and credits have not piled up out of reach of any cost');

// Mars. The same rules with another world's numbers: a sol of 24.66 hours, dust storms instead of a long night,
// nothing to eat or drink off the transports, eight berths every fourth sol.
const marsIdle = play('Mars: do nothing', 400, false, 'mars', 2199);
const mars = play('Mars: follow the crew for 600 hours', 600, true, 'mars', 2199);
const made = (type: BuildingType) => mars.buildings.some(b => b.type === type && b.progress >= 1);
console.log('');
expect(marsIdle.phase === 'lost', 'on Mars, doing nothing loses');
expect(mars.phase === 'playing' && aliveCount(mars) === 4, 'on Mars, following the crew keeps all four alive for 600 hours');
expect((mars.stats.hazes ?? 0) >= 1, 'through at least one dust storm');
expect(mars.stats.evacuated === 0 && mars.stats.lost === 0, 'and nobody was lost or sent home in it');
expect(made('drill') && made('greenhouse'), 'on water from an ice drill and food from a Bio-Dome, since transports bring neither');
expect(mars.stats.flights >= 3 && mars.residents >= 16, 'three or more transports have landed and sixteen or more settlers stayed');
expect(made('sabatier'), 'and a Sabatier plant is making propellant');
expect(mars.mission >= 17, 'seventeen or more of the Mars missions are complete');
// Every line the crew and the world say on Mars is in Mars's words (D95).
const moonish = mars.said.concat(marsIdle.said).filter(m => /shuttle|foundr|Tranquil|lodge|Oxygen Plant|Recycler|Greenhouse|Concourse|[Cc]linic|Micrometeorite|\b[Aa] [AEIO][a-z]/.test(m));
expect(moonish.length === 0, `nothing said on Mars uses the Moon's words${moonish.length ? ': ' + moonish[0] : ''}`);

// The storm forecast has to be true (D95). Orbit says whether life support will last. When it says it will,
// nobody may be left without a powered bed while that storm is overhead.
function forecasts(seed: number) {
  const s = createState(seed, 'mars'), act = steward(localApply);
  let next = 0, heard = 0, told = 0, promised = false, cold = 0;
  while (s.phase === 'playing' && s.t < 1200) {
    if (s.t >= next) { next = s.t + 1; act(s); }
    localTick(s);
    for (const a of s.alerts) if (a.id > heard) { heard = a.id; if (/Orbit reports a dust storm/.test(a.msg)) { told++; promised = /will come through/.test(a.msg); } }
    const e = s.event;
    // the storm, and the dust it leaves on the arrays after the sky clears
    if (promised && e && ((e.kind === 'haze' && s.t >= e.from) || e.kind === 'dust') && s.flows.exposed + s.flows.atRisk > 0) cold++;
  }
  return { told, cold, alive: aliveCount(s) };
}
const sky = [2199, 7, 42].map(forecasts);
console.log(`\nMars forecasts on three maps: ${sky.map(f => `${f.told} storms forecast, ${f.cold} ticks anyone was cold in a storm called safe`).join(' · ')}`);
expect(sky.every(f => f.told >= 2), 'on three maps, two or more dust storms were forecast a sol ahead');
expect(sky.every(f => f.cold === 0 && f.alive === 4), 'and when Orbit said life support would last, it did');
// ----- The landing pad's blast zone (D96) -----
// A rocket lands on exhaust. What stands too close is destroyed, a little further out it is knocked offline,
// and beyond that arrays are dusted. The player is warned and may build there anyway.
console.log('');
expect((day3.stats.blasted ?? 0) === 0 && (mars.stats.blasted ?? 0) === 0, 'a steward who stands the pad off loses nothing to it, on the Moon or on Mars');
for (const on of ['moon', 'mars'] as WorldId[]) {
  const s = createState(on === 'moon' ? 1969 : 2199, on), act = steward(localApply);
  let next = 0;
  const run = (until: () => boolean, most = 600) => { const end = s.t + most; while (s.phase === 'playing' && s.t < end && !until()) { if (s.t >= next) { next = s.t + 1; act(s); } localTick(s); } };
  run(() => s.stats.flights >= 1);
  const pad = padOf(s)!, clear = inBlast(s, pad.x, pad.y);
  expect(!!pad && clear.lost.length === 0 && clear.hurt.length === 0, `${on}: the steward's pad has nothing inside its red and amber rings`);
  // Now a player who does not listen: a home in the red ring, a battery in the amber, an array in the dust.
  s.materials = 2000;
  const spot = (type: BuildingType, ring: Ring) => { for (let y = 0; y < s.size; y++) for (let x = 0; x < s.size; x++) if (!siteProblem(s, type, x, y) && ringFrom(pad.x, pad.y, { type, x, y }) === ring) return [x, y] as const; return null; };
  const put = (type: BuildingType, ring: Ring) => { const p = spot(type, ring); if (!p) return null; const warned = siteWarning(s, type, p[0], p[1]); const ok = localApply(s, { k: 'place', type, x: p[0], y: p[1] }).ok; const b = s.buildings[s.buildings.length - 1]; b.progress = 1; return { uid: b.uid, warned, ok }; };
  const home = put('habitat', 'red'), store = put('battery', 'hurt'), array = put('solar', 'dust');
  expect(!!home?.ok && !!store?.ok && !!array?.ok && !!home.warned && !!store.warned && !!array.warned, `${on}: building inside each ring is warned about and still allowed`);
  const flights = s.stats.flights; s.nextShuttle = s.t; s.shuttle.phase = 'away';
  // no steward now: he would move the pad
  { const end = s.t + 200; while (s.t < end && s.stats.flights === flights) localTick(s); }
  const find = (uid?: number) => s.buildings.find(b => b.uid === uid);
  expect(s.stats.flights === flights + 1 && !find(home?.uid), `${on}: the next landing destroys the home in the red ring`);
  expect(!!find(store?.uid)?.damaged, `${on}: knocks the battery in the amber ring offline`);
  expect(!!find(array?.uid) && dusty(s, find(array?.uid)!), `${on}: and coats the array in the outer ring in dust`);
  expect(!!s.buildings.find(b => b.type === 'lander') && !!padOf(s) && s.buildings.filter(b => b.type === 'conduit').every(b => !b.damaged), `${on}: the pad, the conduit to it and the crew's ship are spared`);
  expect((s.stats.blasted ?? 0) === 1, `${on}: and the loss is counted`);
}
// The crew will not build a pad whose exhaust reaches their own ship, and nobody builds on zoned land in the rings.
{
  const s = createState(1969, 'moon'); s.materials = 500;
  const lander = s.buildings.find(b => b.type === 'lander')!;
  let near = 0, far = 0;
  for (let y = 0; y < s.size - 3; y++) for (let x = 0; x < s.size - 3; x++) {
    const r = ringFrom(x, y, lander), why = siteProblem(s, 'pad', x, y);
    if (r === 'red' || r === 'hurt') { if (!why) near++; } else if (!why) far++;
  }
  expect(near === 0 && far > 50, 'a pad is refused wherever its exhaust would reach the lander, and allowed elsewhere');
  // A town from before the rule: no notice hour on it, so a landing takes nothing until the server gives it one.
  const old = createState(1969, 'moon'); delete old.blast;
  expect(!blastOn(old) && blastOn(s), 'a town from before the rule is not under it until it has been given notice');
}
// A town built before the rule has its pad among its buildings. It is given notice. If nobody moves the pad by then,
// Earth moves it clear, free, once: nothing is destroyed by a rule the town was never built under.
for (const on of ['moon', 'mars'] as WorldId[]) {
  const s = createState(on === 'moon' ? 1969 : 2199, on), act = steward(localApply);
  let next = 0;
  while (s.phase === 'playing' && s.t < 420) { if (s.t >= next) { next = s.t + 1; act(s); } localTick(s); }
  // put the pad back where the old rules let it stand: against the buildings
  while (s.shuttle.phase !== 'away') localTick(s);
  const good = padOf(s)!; s.materials += 500;
  localApply(s, { k: 'demolish', uid: good.uid });
  let worst: [number, number] | null = null, most = 0;
  for (let y = 0; y < s.size; y++) for (let x = 0; x < s.size; x++) if (!siteProblem(s, 'pad', x, y)) { const h = inBlast(s, x, y), k = h.lost.length * 2 + h.hurt.length; if (k > most) { most = k; worst = [x, y]; } }
  localApply(s, { k: 'place', type: 'pad', x: worst![0], y: worst![1] });
  const pad = padOf(s)!; pad.progress = 1;
  delete s.blast; s.blast = s.t + 50;        // the notice the server gives
  const was = inBlast(s, pad.x, pad.y), count = s.buildings.length, credits = s.materials;
  let blastedBefore = s.stats.blasted ?? 0, flights = s.stats.flights;
  while (s.phase === 'playing' && s.t < 420 + 400) localTick(s);   // nobody at the controls
  const now = padOf(s), still = now ? inBlast(s, now.x, now.y) : null;
  expect(was.lost.length >= 2 && s.stats.flights > flights, `${on}: an old town's pad stood with ${was.lost.length} buildings in its red ring, and ships kept landing`);
  expect(!!now && (now.x !== pad.x || now.y !== pad.y) && still!.lost.length === 0 && still!.hurt.length === 0, `${on}: when its notice ended Earth moved the pad clear`);
  expect((s.stats.blasted ?? 0) === blastedBefore && aliveCount(s) === 4, `${on}: and not one building was lost to the rule`);
}

process.exit(fail ? 1 : 0);
