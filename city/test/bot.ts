declare const process: any; declare const require: any;
// Headless check. Plays the game with no graphics and asserts the things a player needs to be true:
//  1. doing nothing loses,
//  2. a player who does what the crew asks survives the first night with all four crew,
//  3. the colony then grows by itself on zoned land: habitats, foundries, lodges and concourses appear, people arrive,
//     rovers run, money comes in, and nobody is lost.
import { BUILDINGS, BuildingType, ZONES, ZONE_BUILDS, ZONE_COST } from '../src/sim/buildings';
import { MISSIONS } from '../src/sim/missions';
import { steward } from '../src/steward';
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

const hour = steward(apply);


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
      hour(s);
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
