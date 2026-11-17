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
import { State, Intent, createState, apply, tick, refresh, TICK, PRICES, population, tierOf, working } from './sim/sim';

const summary = (s: State) => {
  const pop = population(s);
  return {
    t: s.t, phase: s.phase, population: pop, tier: tierOf(pop),
    pad: s.buildings.some(b => b.type === 'pad' && working(b)),
    mission: s.mission, buildings: s.buildings.length, residents: s.residents, tourists: s.tourists,
    crew: s.crew.filter(c => c.alive).length,
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

  /** Advance the town by whole or part hours, in the simulation's own steps. */
  tick(state: string, hours: number, credits: number): string {
    const s = JSON.parse(state) as State;
    s.materials = credits;
    const steps = Math.round(hours / TICK);
    for (let i = 0; i < steps && s.phase === 'playing'; i++) tick(s);
    return reply(s);
  },

  /** What the rest of the world needs to know about a town, without reading its whole state. */
  summary(state: string): string {
    return JSON.stringify(summary(JSON.parse(state) as State));
  },
};
