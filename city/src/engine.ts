// The town's rules, for a server to run.
//
// The same simulation the browser plays, behind four functions that take and return JSON text.
// Nothing here knows about a ledger, a database or a clock: a state goes in, a state comes out.
// The server (sim/src/sim/town.py) calls these from inside the world's tick, so the live town is
// not a copy of this game's rules. It is these rules.
//
// `credits` is the one thing the server owns: the company's wallet, in town credits. It is put
// into the state before the rules run and read back after, and the server posts the difference to
// the ledger. The town never keeps money of its own.
//
// Built by `npm run build:engine` into sim/src/sim/town_engine.js, which is committed.

import { BUILDINGS } from './sim/buildings';
import { steward, Style } from './steward';
import { State, Intent, createState, apply, tick, refresh, TICK, PRICES, population, tierOf, working } from './sim/sim';

const summary = (s: State) => {
  const pop = population(s);
  return {
    t: s.t, phase: s.phase, population: pop, tier: tierOf(pop),
    pad: s.buildings.some(b => b.type === 'pad' && working(b)),
    mission: s.mission, buildings: s.buildings.length, residents: s.residents, tourists: s.tourists,
    crew: s.crew.filter(c => c.alive).length,
    make: s.flows.make, parts: s.flows.parts, yardFull: s.flows.yardFull,
    foundries: s.buildings.reduce((n, b) => n + (b.type === 'printer' && working(b) ? b.level : 0), 0),
  };
};
const reply = (s: State, extra: object = {}) =>
  JSON.stringify({ state: JSON.stringify(s), credits: s.materials, summary: summary(s), ...extra });

const whole = (v: unknown, lo: number, hi: number) => typeof v === 'number' && Number.isInteger(v) && v >= lo && v < hi;

/** Refuse anything that is not one of the game's own requests, before the rules see it. */
function malformed(s: State, it: any): string | null {
  if (!it || typeof it !== 'object') return 'That is not a request';
  const tile = () => whole(it.x, 0, s.size) && whole(it.y, 0, s.size);
  switch (it.k) {
    case 'place': return typeof it.type === 'string' && Object.prototype.hasOwnProperty.call(BUILDINGS, it.type)
      && (BUILDINGS as any)[it.type].buildable && tile() ? null : 'That cannot be built there';
    case 'zone': return whole(it.z, 0, 4) && tile() ? null : 'That cannot be zoned';
    case 'demolish': case 'toggle': case 'repair': return whole(it.uid, 1, 1e9) ? null : 'No such building';
    case 'price': return whole(it.level, 0, PRICES.length) ? null : 'No such price';
    case 'offer': return typeof it.accept === 'boolean' ? null : 'Answer yes or no';
    default: return 'That is not a request';
  }
}

(globalThis as any).Town = {
  /** A new town on untouched ground. */
  create(seed: number, credits: number): string {
    const s = createState(seed | 0);
    s.materials = credits;
    refresh(s);
    return reply(s);
  },

  /** One request from the player. The state comes back only if the rules allowed it. */
  apply(state: string, intent: string, credits: number): string {
    const s = JSON.parse(state) as State;
    s.materials = credits;
    const it = JSON.parse(intent);
    const why = malformed(s, it);
    if (why) return JSON.stringify({ ok: false, reason: why });
    const r = apply(s, it as Intent);
    if (!r.ok) return JSON.stringify({ ok: false, reason: r.reason || 'That cannot be done' });
    refresh(s);
    return reply(s, { ok: true });
  },

  /**
   * Advance the town by whole or part hours, in the simulation's own steps.
   *
   * `yard` is the other thing the server owns: `{cap, held}` in kilograms, the size of the town's
   * yard and what is in it. Given a yard, foundries make goods into it instead of being paid, and
   * the reply says how many whole kilograms were made. The part of a kilogram left over stays in
   * the state for the next hour, so nothing is rounded away.
   *
   * With `wear` set, the buildings also use goods from the yard as spare parts: the reply says how
   * many whole kilograms were `used`, counted the same way, and how many Earth `landed` because the
   * yard had none, which the town has already paid for at `importAt` credits a kilogram.
   */
  tick(state: string, hours: number, credits: number, yard?: string): string {
    const s = JSON.parse(state) as State;
    s.materials = credits;
    if (yard) {
      // What is really in the yard is what the ledger holds, plus the part of a kilogram made and
      // not yet handed over, less the part of one used and not yet taken.
      const y = JSON.parse(yard), part = s.cargo ? s.cargo.made : 0, worn = s.cargo ? s.cargo.used ?? 0 : 0;
      const stock = Math.max(0, y.held + part - worn);
      s.cargo = { cap: y.cap, room: Math.max(0, y.cap - stock), made: part, stock, wear: !!y.wear, importAt: y.importAt ?? 0, used: worn, landed: 0, full: !!s.cargo?.full };
    }
    const steps = Math.round(hours / TICK);
    for (let i = 0; i < steps && s.phase === 'playing'; i++) tick(s);
    let made = 0, used = 0, landed = 0;
    if (s.cargo) {
      made = Math.floor(s.cargo.made + 1e-9); s.cargo.made = Math.max(0, s.cargo.made - made);
      used = Math.floor((s.cargo.used ?? 0) + 1e-9); s.cargo.used = Math.max(0, (s.cargo.used ?? 0) - used);
      landed = s.cargo.landed ?? 0;
    }
    return reply(s, { made, used, landed });
  },

  /**
   * What a careful player would do this hour: the requests, in order, that the steward would send.
   * With `keep`, only what a caretaker would: what is urgent, and nothing that grows the town.
   * `style` is a temperament as JSON (see Style in steward.ts): how this company likes to build.
   * Nothing is changed here. The server sends each one through `apply` like any player's, so the
   * rules judge a steward's move exactly as they judge a person's.
   */
  steward(state: string, credits: number, keep?: boolean, style?: string): string {
    const s = JSON.parse(state) as State;
    s.materials = credits;
    const intents: Intent[] = [];
    const hour = steward((st, it) => {
      if (malformed(st, it)) return { ok: false };
      const r = apply(st, it);
      if (r.ok) intents.push(it);
      return r;
    }, style ? JSON.parse(style) as Style : {});
    if (s.phase === 'playing') hour(s, !!keep);
    return JSON.stringify({ intents });
  },

  /** What the rest of the world needs to know about a town, without reading its whole state. */
  summary(state: string): string {
    return JSON.stringify(summary(JSON.parse(state) as State));
  },
};
