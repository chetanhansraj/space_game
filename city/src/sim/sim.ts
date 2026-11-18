// The simulation core. No DOM, no graphics, no timers: it takes a state and
// intents, and advances in fixed ticks. The same file runs in the browser
// today and can run on a server later without change.
//
// The player lays infrastructure by hand and zones land. Habitats, foundries, lodges and concourses
// then build themselves where demand, habitability and life support allow.

import { BUILDINGS, BuildingType, ZONE, ZONE_BUILDS, ZONE_COST, ZONES } from './buildings';
import { MISSIONS } from './missions';
import { Offer, Deal, tickContracts, answerOffer } from './contracts';
import { Grader, Find, GameEvent, EventKind, initWorld, lotLevel, tickGraders, richOf, oreLot, maybeFind, stormActive, dusty, tickEvents, repairCost } from './world';

export const LUNAR_DAY = 708;       // hours, sunrise to sunrise
export const HALF = 354;            // hours of light, then hours of dark
export const DARK = 400;            // hours the batteries must carry: the night plus the weak sun either side of it
export const TICK = 0.1;            // hours per simulation step
export const SIZE = 36;             // tiles per side
export const REACTOR_GAP = 6;       // tiles between a reactor and living quarters
export const SHUTTLE_EVERY = 60;    // hours between shuttle landings
export const GROW_EVERY = 5;        // hours between growth decisions
export const REPAIR_HOURS = 8;
/** Priority at or below this is life support and runs through the night. Everything above it sleeps after dark. */
export const ESSENTIAL = 2;

// Per person, per hour.
const O2_USE = 0.035, WATER_USE = 0.15, FOOD_USE = 0.026, RECYCLE = 0.85;
export const RENT = 0.08, VISITOR_RATE = 0.12, LANDING_FEE = 3, FARE = 5, SURVEY_GRANT = 2, ROVER_SPEED = 1.6;
/** Credits per person per hour for what Earth still has to send. People in a town expect more than people in an outpost. */
export const suppliesRate = (pop: number) => Math.min(0.09, 0.02 + 0.0009 * pop);
export const EVAC_COST = 15, POWER_MARGIN = 1.2;
export const O2_PLANT = 1, GREENHOUSE_FOOD = 0.6, SHUTTLE_FOOD = 20, SHUTTLE_WATER = 40, FOUNDRY = 0.6;
/**
 * Kilograms of goods a foundry level makes in an hour when the town's output is real cargo.
 * At the market's anchor for manufactured goods (45 credits a kilogram in this game's money, see
 * the root docs/DECISIONS.md D75) thirteen kilograms is worth what FOUNDRY pays in the practice game.
 */
export const FOUNDRY_KG = 13;
/**
 * Kilograms of spare parts a town's buildings wear out in an hour, for each credit an hour of
 * their upkeep. Parts are the same manufactured goods the foundries make, so a town's own industry
 * is what keeps it standing, and a town without enough of it buys from one that has. A town of
 * ninety buildings needs about thirteen kilograms an hour: two thirds of what its foundries make
 * over a lunar day and night. Invented; root docs/DECISIONS.md D82.
 */
export const PARTS_KG = 5;
/**
 * A full yard sends the foundry shift home. Once buildings take parts out of it a full yard is
 * never quite full, so the shift is called back only when there is real room again: this share of
 * the yard, which is less than the smallest sale.
 */
export const YARD_RESTART = 0.02;
export const PRICES = [0.75, 1, 1.3];   // low, fair, high

export const GROUND = { flat: 0, rim: 1, floor: 2, boulder: 3, heritage: 4 } as const;

export interface Building {
  uid: number; type: BuildingType; x: number; y: number;
  progress: number;      // 0..1, built when 1
  level: number;         // 1..3, zoned buildings expand
  on: boolean; powered: boolean; connected: boolean; asleep: boolean;
  damaged: boolean; repair: number;   // hours of repair left, 0 when idle
}
export interface Crew { name: string; role: string; health: number; alive: boolean; grit: number; }
export type AlertLevel = 'info' | 'good' | 'warn' | 'bad';
export interface Alert { id: number; t: number; level: AlertLevel; msg: string; who?: number; }
export interface Poi { x: number; y: number; name: string; bonus: number; }
export interface Rover {
  bay: number; x: number; y: number; hx: number; hy: number; tx: number; ty: number;
  phase: 'idle' | 'out' | 'visit' | 'back'; pax: number; poi: number; timer: number;
}
export interface Shuttle { phase: 'away' | 'landing' | 'landed' | 'launching'; timer: number; flight: number; }
export interface Pop { id: number; x: number; y: number; text: string; }
export type DemandKey = 'r' | 'i' | 'v';

/**
 * The yard, when what the foundries make is real cargo rather than a payment. Kilograms.
 * The server owns the yard: it says how much room is left before each hour and takes away what was made.
 * A practice game has no yard and its foundries are paid by Earth as before.
 */
export interface Cargo {
  cap: number; room: number; made: number;
  /** Kilograms in the yard now, as the rules count them through the hour. */
  stock?: number;
  /** The town is past its founding spares: its buildings wear and need parts. The server says when. */
  wear?: boolean;
  /** Credits a kilogram for parts landed from Earth when the yard has none. The server's price. */
  importAt?: number;
  /** Kilograms taken from the yard as parts and not yet reported, and kilograms Earth landed this hour. */
  used?: number; landed?: number;
  /** The yard filled and the shift went home; it stays home until there is room worth coming back for. */
  full?: boolean;
}

/**
 * The ground a town stands on. Six readings from 0 to 1. A half is the ground this game was first
 * tuned on (for ice, none), and a town with no plot at all plays exactly as the game always has.
 * Every plot's readings add up to the same total: no ground is better, each is better at something.
 *   sun    how much of the time the arrays are lit
 *   ice    water ice within reach, so less has to come from Earth for each person
 *   metal  iron and titanium in the soil: what a foundry makes
 *   glass  aluminium and silicon: frames and panes made on the spot, so buildings need fewer parts
 *   he3    how rich a survey find is when a foundry stands on it
 *   view   Earth in the sky, or the far side's silence: what a visitor will pay to be there
 * The server assigns it from where the plot is on the Moon (root docs/DECISIONS.md D84).
 */
export interface Plot { sun: number; ice: number; metal: number; glass: number; he3: number; view: number; lat?: number; lon?: number; name?: string; /** Hours of dark in a lunar day here. */ dark?: number; }
export type PlotKey = 'sun' | 'ice' | 'metal' | 'glass' | 'he3' | 'view';
/**
 * How much a reading counts. At 1 the ground gives this many times the usual, at 0 the same
 * fraction of it. Small differences get flattened by the rest of the rules and every town comes
 * out the same, so this is large on purpose. Invented; D84.
 */
export const PLOT_SWING = 2.5;
/**
 * What a reading multiplies: 1 on the reference ground, PLOT_SWING on the best, 1 / PLOT_SWING on the worst.
 * Ice is the exception. Almost none of the Moon has any, and the game was tuned on ground without it, so
 * having no ice costs nothing and having it is all gain: at most about 1.6 times less to bring from Earth.
 */
export const gain = (s: State, k: PlotKey) => {
  if (!s.plot) return 1;
  if (k === 'ice') return Math.pow(PLOT_SWING, Math.max(0, s.plot.ice - 0.05) / 1.8);
  // What visitors pay swings half as far: at the full swing a point of outlook was worth three points of anything else.
  return Math.pow(PLOT_SWING, (k === 'view' ? 1 : 2) * (s.plot[k] - 0.5));
};

export interface Flows {
  make: number;           // kilograms of goods per hour, when there is a yard
  parts: number;          // kilograms of spare parts the buildings need per hour, once they wear
  yardFull: boolean;      // foundries are standing idle because the yard has no room
  gen: number; load: number; demand: number; battCap: number;
  o2Cap: number; waterCap: number; housing: number; lodging: number;
  o2Rate: number; waterRate: number; foodRate: number;
  jobs: number; workers: number; staff: number;      // staff: 0..1, how fully jobs are filled
  earn: { foundry: number; rent: number; visitors: number; shops: number; grant: number }; upkeep: number;
  income: number;         // credits per hour, net
  nightDeficit: number;   // kW the batteries must cover at night
  essentialDeficit: number;
  exposed: number;        // crew with no safe shelter
  atRisk: number;         // residents and visitors with no safe shelter
  lackO2: boolean; lackWater: boolean; lackFood: boolean;
  offline: number;        // buildings that wanted power and did not get it
  saving: boolean;        // optional machines are resting to protect the batteries
  habHomes: number; habLodges: number;   // average habitability where people live and stay
}

export interface State {
  v: 5; seed: number; rng: number; size: number;
  ground: number[]; occ: number[]; zone: number[]; linked: number[]; view: number[]; hab: number[]; habRev: number;
  prep: number[];         // 0 raw ground, 1 levelled and ready to build on
  rough: number[];        // hours a grader needs on each tile
  ore: number[];          // 0, or 1 + index into ORES once a rover has found it
  cargo?: Cargo;
  plot?: Plot;
  pois: Poi[]; finds: Find[]; graders: Grader[];
  event: GameEvent | null; nextEvent: number; lastEvent: EventKind | '';
  buildings: Building[]; nextUid: number; rev: number; netDirty: boolean;
  t: number;
  o2: number; water: number; food: number; materials: number; charge: number;   // `materials` holds credits
  canisters: number;      // hours of CO2 scrubbing left in the lander
  crew: Crew[]; residents: number; tourists: number; mood: number; risk: number;
  rovers: Rover[]; shuttle: Shuttle; nextShuttle: number;
  mission: number; price: number; nextGrow: number;
  shopping: boolean;      // true when Commercial land should next get a Concourse, false for a lodge
  offer: Offer | null; deals: Deal[]; nextOffer: number; nextDeal: number;
  want: Record<DemandKey, number>;      // demand, -1..1
  block: Record<DemandKey, string>;     // why a wanted district is not growing, '' when nothing is in the way
  flows: Flows;
  alerts: Alert[]; nextAlert: number; cooldown: Record<string, number>;
  pops: Pop[]; nextPop: number;
  strikes: number[];
  phase: 'playing' | 'lost';
  stats: { built: number; grown: number; upgrades: number; flights: number; strikes: number; peakCharge: number; trips: number; earned: number; lost: number; evacuated: number; peakPop: number; deals: number; broken: number; finds: number; events: number };
}

export type Intent =
  | { k: 'place'; type: BuildingType; x: number; y: number }
  | { k: 'zone'; z: number; x: number; y: number }
  | { k: 'demolish'; uid: number }
  | { k: 'toggle'; uid: number }
  | { k: 'repair'; uid: number }
  | { k: 'price'; level: number }
  | { k: 'offer'; accept: boolean };

// ---------- deterministic random ----------
export function rnd(s: { rng: number }): number {
  let a = (s.rng += 0x6d2b79f5) | 0;
  a = Math.imul(a ^ (a >>> 15), a | 1);
  a ^= a + Math.imul(a ^ (a >>> 7), a | 61);
  return ((a ^ (a >>> 14)) >>> 0) / 4294967296;
}
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// ---------- clock ----------
export const phaseOf = (t: number) => t % LUNAR_DAY;
/**
 * How long the Sun is up where this town stands. Across nearly all the Moon it is half the lunar
 * day. On a polar rim the Sun circles the horizon and the dark is short. The plot says how many
 * hours of dark there are (root docs/DECISIONS.md D85); without a plot it is the half.
 *
 * These two are set from the state by `ground` at the top of every way into the rules, so the
 * clock helpers below can go on taking only a time. One town is worked on at a time.
 */
let LIGHT = HALF, CARRY = DARK;
export function ground(s: State): void {
  const dark = Math.max(24, Math.min(HALF, s.plot?.dark ?? HALF));
  LIGHT = LUNAR_DAY - dark;
  CARRY = dark + (DARK - HALF);
}
/** Hours of light and of dark in a lunar day here, and the hours the batteries must carry. */
export const lightHours = () => LIGHT, darkHours = () => LUNAR_DAY - LIGHT, carryHours = () => CARRY;
export const isNight = (t: number) => phaseOf(t) >= LIGHT;
export const sunFactor = (t: number) => (isNight(t) ? 0 : Math.sin((Math.PI * phaseOf(t)) / LIGHT));
export const hoursToSunset = (t: number) => LIGHT - phaseOf(t);
export const hoursToSunrise = (t: number) => LUNAR_DAY - phaseOf(t);
export const dayNumber = (t: number) => Math.floor(t / LUNAR_DAY) + 1;

// ---------- people and buildings ----------
export const aliveCount = (s: State) => s.crew.reduce((n, c) => n + (c.alive ? 1 : 0), 0);
export const population = (s: State) => aliveCount(s) + s.residents + s.tourists;
export const TIERS: [number, string][] = [[0, 'Outpost'], [8, 'Base'], [20, 'Colony'], [40, 'Town']];
export const tierOf = (pop: number) => { let name = TIERS[0][1]; for (const [n, t] of TIERS) if (pop >= n) name = t; return name; };
export const working = (b: Building) => b.progress >= 1 && b.connected && !b.damaged;
const grows = (t: BuildingType) => t === 'habitat' || t === 'lodge' || t === 'printer' || t === 'market';
/** Bigger buildings are more efficient: each extra level adds half the draw of the first. */
const scale = (b: Building) => (grows(b.type) ? 0.5 + 0.5 * b.level : 1);
export const bedsOf = (b: Building) => (b.type === 'habitat' ? 4 : b.type === 'lodge' ? 6 : 0) * b.level;
export const jobsOf = (b: Building) => BUILDINGS[b.type].jobs * (grows(b.type) ? b.level : 1);
export const drawOf = (b: Building, night: boolean) => (night ? BUILDINGS[b.type].drawNight : BUILDINGS[b.type].drawDay) * scale(b);
const centre = (b: { type: BuildingType; x: number; y: number }) => {
  const d = BUILDINGS[b.type];
  return [b.x + d.w / 2, b.y + d.h / 2];
};
const isQuarters = (t: BuildingType) => t === 'habitat' || t === 'lander' || t === 'lodge';

// ---------- setup ----------
function emptyFlows(): Flows {
  return { make: 0, parts: 0, yardFull: false, gen: 0, load: 0, demand: 0, battCap: 0, o2Cap: 0, waterCap: 0, housing: 0, lodging: 0, o2Rate: 0, waterRate: 0, foodRate: 0,
    jobs: 0, workers: 0, staff: 1, earn: { foundry: 0, rent: 0, visitors: 0, shops: 0, grant: 0 }, upkeep: 0, income: 0,
    nightDeficit: 0, essentialDeficit: 0, exposed: 0, atRisk: 0, lackO2: false, lackWater: false, lackFood: false, offline: 0,
    saving: false, habHomes: 50, habLodges: 50 };
}

// Real names from around the Apollo 11 landing site.
const CRATERS = ['West crater', 'Little West', 'Double crater', 'Armstrong', 'Aldrin', 'Collins'];

export function createState(seed = 1969): State {
  const N = SIZE * SIZE;
  const s: State = {
    v: 5, seed, rng: seed | 0, size: SIZE,
    ground: new Array(N).fill(GROUND.flat), occ: new Array(N).fill(0), zone: new Array(N).fill(0), linked: new Array(N).fill(0),
    view: new Array(N).fill(0), hab: new Array(N).fill(50), habRev: -1, pois: [],
    prep: new Array(N).fill(0), rough: new Array(N).fill(3), ore: new Array(N).fill(0), finds: [], graders: [], event: null, nextEvent: 0, lastEvent: '',
    buildings: [], nextUid: 1, rev: 1, netDirty: true,
    t: 0, o2: 45, water: 220, food: 60, materials: 160, charge: 40, canisters: 160,
    crew: [
      { name: 'Asha Rao', role: 'Commander', health: 100, alive: true, grit: 1.1 },
      { name: 'Kenji Mori', role: 'Flight surgeon', health: 100, alive: true, grit: 1.0 },
      { name: 'Lena Okafor', role: 'Systems engineer', health: 100, alive: true, grit: 0.95 },
      { name: 'Rafael Costa', role: 'Geologist', health: 100, alive: true, grit: 0.9 },
    ],
    residents: 0, tourists: 0, mood: 100, risk: 0,
    rovers: [], shuttle: { phase: 'away', timer: 0, flight: 0 }, nextShuttle: 0,
    mission: 0, price: 1, nextGrow: 2, shopping: false, offer: null, deals: [], nextOffer: 0, nextDeal: 1,
    want: { r: 0, i: 0, v: 0 }, block: { r: '', i: '', v: '' },
    flows: emptyFlows(), alerts: [], nextAlert: 1, cooldown: {}, pops: [], nextPop: 1,
    strikes: [], phase: 'playing',
    stats: { built: 0, grown: 0, upgrades: 0, flights: 0, strikes: 0, peakCharge: 40, trips: 0, earned: 0, lost: 0, evacuated: 0, peakPop: 4, deals: 0, broken: 0, finds: 0, events: 0 },
  };
  const c = SIZE / 2;
  // Craters: a raised rim around a sunken floor. Neither can be built on yet. Each is a place rovers can visit.
  for (let i = 0; i < 6; i++) {
    const r = 1.6 + rnd(s) * 2.4;
    let cx = 0, cy = 0, tries = 0;
    do { cx = 3 + rnd(s) * (SIZE - 6); cy = 3 + rnd(s) * (SIZE - 6); tries++; }
    while ((Math.hypot(cx - c, cy - c) < r + 7 || Math.hypot(cx - 5, cy - 30) < r + 4) && tries < 60);
    for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) {
      const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy);
      if (d < r - 0.55) s.ground[y * SIZE + x] = GROUND.floor;
      else if (d < r + 0.55 && s.ground[y * SIZE + x] === GROUND.flat) s.ground[y * SIZE + x] = GROUND.rim;
      // a view over the rim is worth something to anyone living or staying nearby
      if (d < r + 3.2) s.view[y * SIZE + x] = Math.max(s.view[y * SIZE + x], 14 * (1 - Math.max(0, d - r) / 3.2));
    }
    s.pois.push({ x: Math.max(1, Math.min(SIZE - 1, cx)), y: Math.max(1, cy - r - 1.2), name: CRATERS[i], bonus: 1 });
  }
  // The heritage site: where Eagle landed in 1969. Visitors pay double to see it.
  s.pois.push({ x: 5.5, y: 30.5, name: 'Tranquility Base', bonus: 2 });
  for (let i = 0; i < 34; i++) {
    const x = Math.floor(rnd(s) * SIZE), y = Math.floor(rnd(s) * SIZE);
    if (Math.hypot(x - c, y - c) > 5 && Math.hypot(x - 5, y - 30) > 3 && s.ground[y * SIZE + x] === GROUND.flat) s.ground[y * SIZE + x] = GROUND.boulder;
  }
  for (let y = 29; y <= 31; y++) for (let x = 4; x <= 6; x++) s.ground[y * SIZE + x] = GROUND.heritage;   // protected ground
  initWorld(s);
  s.strikes = [190 + rnd(s) * 110, 420 + rnd(s) * 180];
  addBuilding(s, 'lander', c - 1, c - 1, 1);
  recomputeNetwork(s);
  computeHab(s);
  computeFlows(s);
  pushAlert(s, 'info', 'Touchdown in Mare Tranquillitatis. Sunset in 354 hours.');
  return s;
}

export function addBuilding(s: State, type: BuildingType, x: number, y: number, progress: number): Building {
  const d = BUILDINGS[type];
  const b: Building = { uid: s.nextUid++, type, x, y, progress, level: 1, on: true, powered: false, connected: false, asleep: false, damaged: false, repair: 0 };
  s.buildings.push(b);
  for (let j = 0; j < d.h; j++) for (let i = 0; i < d.w; i++) { s.occ[(y + j) * s.size + x + i] = b.uid; s.prep[(y + j) * s.size + x + i] = 1; }
  s.netDirty = true; s.rev++;
  return b;
}

// ---------- alerts and money ----------
export function pushAlert(s: State, level: AlertLevel, msg: string, who?: number) {
  s.alerts.push({ id: s.nextAlert++, t: s.t, level, msg, who });
  if (s.alerts.length > 40) s.alerts.splice(0, s.alerts.length - 40);
}
function alertOnce(s: State, key: string, level: AlertLevel, msg: string, every = 80) {
  const last = s.cooldown[key];
  if (last !== undefined && s.t - last < every) return;
  s.cooldown[key] = s.t;
  pushAlert(s, level, msg);
}
/** Pay credits and, when a place is given, float the amount over the map there. */
export function earn(s: State, amount: number, x?: number, y?: number) {
  s.materials += amount; s.stats.earned += amount;
  if (x !== undefined && y !== undefined) {
    s.pops.push({ id: s.nextPop++, x, y, text: `+${Math.round(amount)}` });
    if (s.pops.length > 12) s.pops.splice(0, s.pops.length - 12);
  }
}

// ---------- placement rules ----------
/** Why this spot will not work, ignoring cost. Null means the site is fine. `auto` is the simulation building on a zone. */
export function siteProblem(s: State, type: BuildingType, x: number, y: number, auto = false): string | null {
  const d = BUILDINGS[type];
  if (!d.buildable && !auto) return 'Zone land for this and it will be built for you';
  if (x < 0 || y < 0 || x + d.w > s.size || y + d.h > s.size) return 'Outside the claim';
  for (let j = 0; j < d.h; j++) for (let i = 0; i < d.w; i++) {
    const k = (y + j) * s.size + x + i;
    if (s.occ[k]) return 'Something is already here';
    if (s.ground[k] === GROUND.heritage) return 'Tranquility Base is protected ground';
    if (s.ground[k] !== GROUND.flat) return 'Ground is too rough to build on';
    if (!auto && s.zone[k]) return 'This land is zoned. Unzone it first';
  }
  if (type === 'pad' && s.buildings.some(b => b.type === 'pad')) return 'One landing pad is enough for now';
  if (type === 'reactor' || isQuarters(type)) {
    const [cx, cy] = centre({ type, x, y });
    for (const b of s.buildings) {
      const clash = type === 'reactor' ? isQuarters(b.type) : b.type === 'reactor';
      if (!clash) continue;
      const [bx, by] = centre(b);
      if (Math.hypot(cx - bx, cy - by) < REACTOR_GAP)
        return `Reactors and living quarters must be ${REACTOR_GAP} tiles apart`;
    }
  }
  return null;
}

/** Does this footprint share an edge with anything already placed or zoned? If not, it will need a conduit. */
export function touchesBase(s: State, type: BuildingType, x: number, y: number): boolean {
  const d = BUILDINGS[type], n = s.size;
  const at = (X: number, Y: number) => X >= 0 && Y >= 0 && X < n && Y < n && (s.occ[Y * n + X] > 0 || s.zone[Y * n + X] > 0);
  for (let i = 0; i < d.w; i++) if (at(x + i, y - 1) || at(x + i, y + d.h)) return true;
  for (let j = 0; j < d.h; j++) if (at(x - 1, y + j) || at(x + d.w, y + j)) return true;
  return false;
}

export function placeProblem(s: State, type: BuildingType, x: number, y: number): string | null {
  const site = siteProblem(s, type, x, y);
  if (site) return site;
  const cost = BUILDINGS[type].cost;
  if (s.materials < cost) return `Needs ${cost} credits, you have ${Math.floor(s.materials)}`;
  return null;
}

/** Why this tile cannot be zoned. Null means it can. Zone 0 clears a tile. */
export function zoneProblem(s: State, z: number, x: number, y: number): string | null {
  if (x < 0 || y < 0 || x >= s.size || y >= s.size) return 'Outside the claim';
  const k = y * s.size + x;
  if (s.zone[k] === z) return z ? 'Already zoned' : 'Nothing to clear';
  if (s.ground[k] === GROUND.heritage) return 'Tranquility Base is protected ground';
  if (s.ground[k] !== GROUND.flat) return 'Ground is too rough to zone';
  if (s.occ[k]) return s.zone[k] ? 'Demolish the building first' : 'Something is already here';
  if (z && s.materials < ZONE_COST) return `Zoning costs ${ZONE_COST} credits a tile`;
  return null;
}

export function apply(s: State, it: Intent): { ok: boolean; reason?: string } {
  ground(s);
  if (s.phase !== 'playing') return { ok: false, reason: 'The mission is over' };
  if (it.k === 'place') {
    const why = placeProblem(s, it.type, it.x, it.y);
    if (why) return { ok: false, reason: why };
    s.materials -= BUILDINGS[it.type].cost;
    addBuilding(s, it.type, it.x, it.y, 0);
    return { ok: true };
  }
  if (it.k === 'zone') {
    const why = zoneProblem(s, it.z, it.x, it.y);
    if (why) return { ok: false, reason: why };
    if (it.z) s.materials -= ZONE_COST;
    s.zone[it.y * s.size + it.x] = it.z;
    s.netDirty = true; s.rev++;
    return { ok: true };
  }
  if (it.k === 'offer') return answerOffer(s, it.accept);
  if (it.k === 'price') {
    if (it.level < 0 || it.level >= PRICES.length) return { ok: false };
    s.price = PRICES[it.level];
    return { ok: true };
  }
  const b = s.buildings.find(q => q.uid === it.uid);
  if (!b) return { ok: false, reason: 'No such building' };
  const d = BUILDINGS[b.type];
  if (it.k === 'demolish') {
    if (b.type === 'lander') return { ok: false, reason: 'The lander stays' };
    s.materials += b.progress < 1 ? d.cost : Math.floor(d.cost / 2);
    for (let j = 0; j < d.h; j++) for (let i = 0; i < d.w; i++) s.occ[(b.y + j) * s.size + b.x + i] = 0;
    s.buildings.splice(s.buildings.indexOf(b), 1);
    s.rovers = s.rovers.filter(r => r.bay !== b.uid);
    s.netDirty = true; s.rev++;
    return { ok: true };
  }
  if (it.k === 'toggle') {
    if (!d.toggle) return { ok: false, reason: 'This cannot be switched off' };
    b.on = !b.on; s.rev++;
    return { ok: true };
  }
  if (it.k === 'repair') {
    if (!b.damaged) return { ok: false, reason: 'Nothing to repair' };
    if (b.repair > 0) return { ok: false, reason: 'Repair already under way' };
    if (s.materials < repairCost(b)) return { ok: false, reason: `Repair needs ${repairCost(b)} credits` };
    s.materials -= repairCost(b); b.repair = REPAIR_HOURS; s.rev++;
    return { ok: true };
  }
  return { ok: false };
}

// ---------- network ----------
/**
 * Utilities run through finished buildings, conduits and zoned land. A tile is linked when a chain of
 * those leads back to the lander. A building works only if it stands on or beside linked ground.
 */
export function recomputeNetwork(s: State) {
  const n = s.size, byUid = new Map<number, Building>();
  for (const b of s.buildings) { b.connected = false; byUid.set(b.uid, b); }
  s.linked.fill(0);
  s.netDirty = false;
  const lander = s.buildings.find(b => b.type === 'lander');
  if (!lander) return;
  const carries = (k: number) => { const o = byUid.get(s.occ[k]); return s.zone[k] > 0 || (!!o && o.progress >= 1); };
  const queue: number[] = [];
  for (let j = 0; j < 2; j++) for (let i = 0; i < 2; i++) { const k = (lander.y + j) * n + lander.x + i; s.linked[k] = 1; queue.push(k); }
  while (queue.length) {
    const k = queue.pop()!, x = k % n, y = (k - x) / n;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const X = x + dx, Y = y + dy;
      if (X < 0 || Y < 0 || X >= n || Y >= n) continue;
      const q = Y * n + X;
      if (!s.linked[q] && carries(q)) { s.linked[q] = 1; queue.push(q); }
    }
  }
  for (const b of s.buildings) {
    const d = BUILDINGS[b.type];
    for (let j = 0; j < d.h && !b.connected; j++) for (let i = 0; i < d.w; i++) if (s.linked[(b.y + j) * n + b.x + i]) { b.connected = true; break; }
  }
}

// ---------- habitability ----------
/** How good each tile is to live on, 0 to 100. Dust, noise and reactors lower it. Gardens, clinics and crater views raise it. */
export function computeHab(s: State) {
  const n = s.size, h = s.hab;
  for (let k = 0; k < n * n; k++) h[k] = 50 + s.view[k];
  const spread = (cx: number, cy: number, r: number, amount: number) => {
    for (let y = Math.max(0, Math.floor(cy - r)); y <= Math.min(n - 1, Math.ceil(cy + r)); y++)
      for (let x = Math.max(0, Math.floor(cx - r)); x <= Math.min(n - 1, Math.ceil(cx + r)); x++) {
        const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy);
        if (d < r) h[y * n + x] += amount * (1 - d / r);
      }
  };
  for (const b of s.buildings) {
    const [cx, cy] = centre(b);
    if (b.type === 'pad') spread(cx, cy, 8, -40);
    else if (b.type === 'printer') spread(cx, cy, 5, -18 - 6 * b.level);
    else if (b.type === 'garage') spread(cx, cy, 4, -12);
    else if (b.type === 'o2plant') spread(cx, cy, 3.5, -12);
    else if (b.type === 'reactor') spread(cx, cy, 10, -32);
    else if (b.type === 'garden' && b.progress >= 1) spread(cx, cy, 6.5, 30);
    else if (b.type === 'clinic' && b.progress >= 1) spread(cx, cy, 7.5, 16);
    else if (b.type === 'market' && b.progress >= 1) spread(cx, cy, 5, 8 + 4 * b.level);
  }
  const tb = s.pois.find(p => p.bonus > 1);
  if (tb) spread(tb.x, tb.y, 6, 12);
  for (let k = 0; k < n * n; k++) h[k] = clamp(Math.round(h[k]), 0, 100);
  s.habRev = s.rev;
}
export const habAt = (s: State, x: number, y: number, w = 2, hgt = 2) => {
  let sum = 0;
  for (let j = 0; j < hgt; j++) for (let i = 0; i < w; i++) sum += s.hab[(y + j) * s.size + x + i];
  return sum / (w * hgt);
};

// ---------- capacity ----------
/** kWh of storage needed to carry life support through a whole night. */
export const nightNeed = (s: State) => Math.max(0, s.flows.essentialDeficit) * CARRY;

/** Hours of night the batteries cover. Infinity when no deficit. */
export function nightCover(s: State): number {
  const f = s.flows;
  if (f.nightDeficit <= 0.001) return Infinity;
  return (isNight(s.t) ? s.charge : f.battCap) / f.nightDeficit;
}

/**
 * How many people the base can keep alive through a full lunar day and night, and what holds that number down.
 * Earth sends new people only up to this limit, so it is the colony's growth gauge.
 */
export function support(s: State): { limit: number; why: string; air: number; food: number; power: boolean } {
  const f = s.flows;
  const n = (t: BuildingType) => s.buildings.filter(b => b.type === t && working(b)).length;
  const tank = Math.floor(f.o2Cap / (O2_USE * (LUNAR_DAY - LIGHT + 90)));          // a night of breathing has to fit in the tanks
  const plants = Math.floor((n('o2plant') * O2_PLANT) / (O2_USE * 2.1)); // plants only run by day, so they must make double
  const air = Math.min(tank, plants);
  const food = Math.floor((0.8 * (n('greenhouse') * GREENHOUSE_FOOD * 0.5 + SHUTTLE_FOOD / SHUTTLE_EVERY)) / FOOD_USE);
  const need = nightNeed(s);
  const power = f.battCap >= need * POWER_MARGIN - 1 && (isNight(s.t) || sunsetCharge(s) >= need * 1.05);
  let limit = Math.min(air, food), why = air <= food ? (tank <= plants ? 'oxygen tanks' : 'oxygen plants') : 'greenhouses';
  if (!power) { limit = Math.min(limit, population(s)); why = 'night power'; }
  return { limit, why, air, food, power };
}

/**
 * The charge the batteries can still reach by sunset if only life support keeps running, with a margin for
 * dust and low sun. This is what decides whether there is daylight left to take on more for tonight.
 */
export function sunsetCharge(s: State, extraDay = 0): number {
  let peak = 0, steady = 0, essDay = 0, cap = 0;
  for (const b of s.buildings) {
    const d = BUILDINGS[b.type];
    if (d.priority <= ESSENTIAL) essDay += drawOf(b, false);
    if (!working(b)) continue;
    cap += d.battery;
    if (b.on) { if (d.solar) peak += d.gen * gain(s, 'sun'); else steady += d.gen; }
  }
  if (isNight(s.t)) return s.charge;
  const ph = phaseOf(s.t), sunset = LIGHT - ph;
  const sunE = peak * (LIGHT / Math.PI) * (1 + Math.cos((Math.PI * ph) / LIGHT));
  return Math.min(cap, s.charge + 0.85 * Math.max(0, sunE + (steady - essDay - extraDay) * sunset));
}

/** Could the grid carry this much more? Developers will not build what cannot be kept warm at night or run by day. */
function powerFor(s: State, extraNight: number, extraDay: number): string {
  let essential = 0, steady = 0, peak = 0, day = 0, cap = 0;
  for (const b of s.buildings) {
    const d = BUILDINGS[b.type];
    if (d.priority <= ESSENTIAL) essential += drawOf(b, true);
    day += drawOf(b, false);
    if (!working(b)) continue;
    cap += d.battery;
    if (d.solar) peak += d.gen * gain(s, 'sun'); else steady += d.gen;
  }
  const nightKwh = Math.max(0, essential + extraNight - steady) * CARRY;
  if (extraNight > 0 && cap < nightKwh * POWER_MARGIN) return 'night power';
  // There has to be enough daylight left today to fill the batteries for it.
  if (extraNight > 0 && !isNight(s.t) && sunsetCharge(s, extraDay) < nightKwh * 1.08) return 'night power';
  // After dark, only what the remaining charge can carry to sunrise.
  if (extraNight > 0 && isNight(s.t) && s.charge < Math.max(0, essential + extraNight - steady) * (hoursToSunrise(s.t) + 40) * 1.1) return 'night power';
  // Over a whole day the arrays must run the base and still fill the batteries for the night.
  const dayGain = (peak * 0.6366 + steady - day - extraDay) * LIGHT;
  if (dayGain < nightKwh * 1.1) return 'daytime power';
  return '';
}

// ---------- one tick ----------
function computeFlows(s: State, dt = 0) {
  const f = emptyFlows();
  const night = isNight(s.t), sun = sunFactor(s.t), pop = population(s);
  const sunset = hoursToSunset(s.t), toDawn = hoursToSunrise(s.t);

  // First pass: capacity and what life support needs.
  if (s.cargo) { if (s.cargo.room <= 0) s.cargo.full = true; else if (s.cargo.room >= s.cargo.cap * YARD_RESTART) s.cargo.full = false; }
  const full = !!s.cargo?.full;
  let nightDraw = 0, steady = 0, essential = 0, planned = 0;
  for (const b of s.buildings) {
    const d = BUILDINGS[b.type];
    b.asleep = false;
    if (d.priority <= ESSENTIAL) planned += drawOf(b, true);   // includes what is still going up
    if (!working(b)) continue;
    f.battCap += d.battery; f.o2Cap += d.o2Store; f.waterCap += d.waterStore;
    if (d.priority <= ESSENTIAL) essential += drawOf(b, true);
    if (!d.solar && b.on) steady += d.gen;
    if (b.type === 'printer' && full) { if (b.on) f.yardFull = true; continue; }   // nowhere to put the goods: the shift is sent home
    f.jobs += b.on ? jobsOf(b) : 0;
  }
  f.essentialDeficit = essential - steady;
  s.charge = Math.min(s.charge, f.battCap);
  f.workers = aliveCount(s) + s.residents;
  f.staff = f.jobs > 0 ? Math.min(1, f.workers / f.jobs) : 1;

  // Optional machines rest at night, and late in the day while the batteries still need filling.
  // Oxygen plants keep going until the tanks hold enough to reach the next morning.
  const need = Math.max(0, planned - steady) * CARRY;
  // By day they also rest whenever running them would leave the batteries short at sunset.
  f.saving = night || sunsetCharge(s) < Math.min(need * (s.flows.saving ? 1.12 : 1.06), f.battCap * 0.995);
  const o2Short = night ? s.o2 < O2_USE * pop * toDawn + 6 : s.o2 < Math.min(f.o2Cap * 0.97, O2_USE * pop * (sunset + LUNAR_DAY - LIGHT + 30));

  const storm = stormActive(s);
  const loads: { b: Building; draw: number; pr: number }[] = [];
  for (const b of s.buildings) {
    const d = BUILDINGS[b.type];
    if (!working(b) || !b.on) { b.powered = false; continue; }
    f.gen += d.gen * (d.solar ? sun * gain(s, 'sun') * (dusty(s, b) ? 0.5 : 1) : 1);
    const optional = d.priority > ESSENTIAL && d.drawNight > 0;
    if (optional && f.saving && !(b.type === 'o2plant' && o2Short)) { b.asleep = true; b.powered = false; continue; }
    if (storm && (b.type === 'printer' || b.type === 'garage')) { b.asleep = true; b.powered = false; continue; }   // nobody works outdoors in a storm
    if (full && b.type === 'printer') { b.asleep = true; b.powered = false; continue; }
    if (d.priority <= ESSENTIAL) nightDraw += drawOf(b, true);
    const draw = drawOf(b, night);
    f.demand += draw;
    if (draw > 0) loads.push({ b, draw, pr: d.priority }); else b.powered = true;
  }
  f.nightDeficit = nightDraw - steady;
  // With dt = 0 this only reports who would be powered; with dt > 0 it spends energy.
  const step = dt || TICK;
  let avail = f.gen * step + s.charge;
  loads.sort((a, b) => a.pr - b.pr || a.b.uid - b.b.uid);
  for (const l of loads) {
    const want = l.draw * step;
    if (avail + 1e-9 >= want) { avail -= want; l.b.powered = true; f.load += l.draw; }
    else { l.b.powered = false; f.offline++; }
  }
  if (dt) s.charge = Math.min(f.battCap, Math.max(0, avail));

  let recycling = false, habR = 0, nR = 0, habV = 0, nV = 0, shops = 0;
  for (const b of s.buildings) {
    const d = BUILDINGS[b.type];
    f.upkeep += b.progress >= 1 ? d.upkeep * (grows(b.type) ? b.level : 1) : 0;
    if (s.cargo?.wear && b.progress >= 1) f.parts += (PARTS_KG / gain(s, 'glass')) * d.upkeep * (grows(b.type) ? b.level : 1);
    if (!b.powered || !working(b)) continue;
    if (b.type === 'o2plant') f.o2Rate += O2_PLANT;
    else if (b.type === 'recycler') recycling = true;
    else if (b.type === 'greenhouse') { f.foodRate += GREENHOUSE_FOOD; f.o2Rate += 0.02; f.waterRate -= 0.04; }
    else if (b.type === 'printer') { const out = b.level * f.staff * gain(s, 'metal') * (1 + richOf(s, b) * gain(s, 'he3')); if (s.cargo) f.make += FOUNDRY_KG * out; else f.earn.foundry += FOUNDRY * out; }
    else if (b.type === 'habitat') { f.housing += bedsOf(b); habR += habAt(s, b.x, b.y) * b.level; nR += b.level; }
    else if (b.type === 'lodge') { f.lodging += bedsOf(b); habV += habAt(s, b.x, b.y) * b.level; nV += b.level; }
    else if (b.type === 'market') shops += b.level;
  }
  f.habHomes = nR ? habR / nR : 50; f.habLodges = nV ? habV / nV : 50;
  f.o2Rate -= O2_USE * pop;
  f.waterRate -= WATER_USE * pop * (recycling ? 1 - RECYCLE : 1);
  f.foodRate -= FOOD_USE * pop;
  // Money. Rent and room rates follow habitability and the price you set. Earth's founding grant fades as the base grows.
  const employed = f.jobs > 0 ? Math.min(1, f.jobs / Math.max(1, f.workers)) : 0;
  f.earn.rent = s.residents * RENT * s.price * (0.5 + f.habHomes / 100) * (0.6 + 0.4 * employed);
  f.earn.visitors = s.tourists * VISITOR_RATE * gain(s, 'view') * s.price * (0.5 + f.habLodges / 100) * (s.mood / 100) * (0.5 + 0.5 * f.staff);
  f.earn.shops = Math.min(aliveCount(s) + s.residents, shops * 16) * 0.035 * s.price * f.staff;   // people spend their wages
  f.earn.grant = Math.max(0, 0.8 - 0.04 * (pop - 4));
  f.upkeep += (suppliesRate(pop) / gain(s, 'ice')) * Math.max(0, pop - 4);
  f.income = f.earn.foundry + f.earn.rent + f.earn.visitors + f.earn.shops + f.earn.grant - f.upkeep;
  s.flows = f;
}

/**
 * What a growing base needs beyond air and power. Each need switches on at a population, and until it is met
 * no new settlers will build and no habitat will expand.
 */
export function needs(s: State): { name: string; met: boolean; text: string }[] {
  const pop = population(s), locals = aliveCount(s) + s.residents;
  const n = (t: BuildingType) => s.buildings.filter(b => b.type === t && working(b)).length;
  const out: { name: string; met: boolean; text: string }[] = [];
  if (locals >= 10) out.push({ name: 'A Garden Dome for every 20 people living here', met: n('garden') >= Math.ceil(locals / 20), text: 'people want a garden' });
  if (locals >= 14) out.push({ name: 'A Concourse to eat, trade and meet in', met: n('market') >= 1, text: 'people want a Concourse, zone Commercial land' });
  if (pop >= 20) out.push({ name: 'A Clinic', met: n('clinic') >= 1, text: 'people want a clinic' });
  if (locals >= 30) out.push({ name: 'Two Concourses', met: s.buildings.filter(b => b.type === 'market' && working(b)).reduce((a, b) => a + b.level, 0) >= 2, text: 'the Concourse is overcrowded, zone more Commercial land' });
  return out;
}

/** What the base is asking for. Each value runs from -1 (far too much) to 1 (badly wanted). */
function computeDemand(s: State) {
  const f = s.flows;
  const count = (t: BuildingType) => s.buildings.filter(b => b.type === t && working(b)).length;
  const locals = aliveCount(s) + s.residents;
  const freeBeds = f.housing - locals;
  const priceR = s.price > 1 ? -0.25 : s.price < 1 ? 0.15 : 0;
  // Habitat: people come for unfilled jobs and stay away from empty beds they would have to fill.
  s.want.r = clamp((f.jobs - f.workers) / 5 + 0.2 + priceR + (f.habHomes - 50) / 200 - Math.max(0, freeBeds) / 4, -1, 1);
  // Industry: companies come when there are hands to hire.
  s.want.i = clamp((f.workers - f.jobs) / 4 + 0.2, -1, 1);
  if (oreLot(s)) s.want.i = Math.max(s.want.i, 0.4);   // a company will come for a deposit whether or not there are hands to hire
  // Commercial: lodges come when there is something to see and a way to get here.
  // Concourses come when enough people live here to keep one busy.
  const pad = count('pad') > 0;
  const draw = pad ? (6 + count('garage') * 6 + count('garden') * 4) * (s.mood / 100) / s.price : 0;
  const film = s.deals.find(d => d.kind === 'broadcast');   // a signed broadcast makes lodge keepers want to build
  const tourism = pad ? clamp((Math.max(draw, film ? (film.amount ?? 6) + 2 : 0) - f.lodging) / 6, -1, 1) : 0;
  const shops = s.buildings.filter(b => b.type === 'market').reduce((a, b) => a + b.level, 0);
  const retail = clamp((locals - 10 - shops * 16) / 4, -1, 1);
  s.shopping = retail > 0.15 && retail >= tourism - 0.2;
  s.want.v = Math.max(tourism, retail);
}

/** Every few hours, whoever most wants to build looks for a lot. One new building or one expansion at a time. */
function grow(s: State) {
  computeDemand(s);
  const cap = support(s), room = cap.limit - population(s);
  // Whoever wants it most builds first. What the crew has asked for jumps the queue.
  const asked = MISSIONS[s.mission]?.zone ?? 0;
  const order = ZONES.map(z => z).sort((a, b) => s.want[b.key] + (b.z === asked ? 0.6 : 0) - s.want[a.key] - (a.z === asked ? 0.6 : 0));
  let done = false;
  for (const z of order) {
    const key = z.key, type: BuildingType = z.z === 3 && s.shopping ? 'market' : ZONE_BUILDS[z.z], d = BUILDINGS[type];
    s.block[key] = '';
    if (s.want[key] < 0.15) continue;
    if (s.materials < 0) { s.block[key] = 'the base is in debt'; continue; }
    // Nobody builds a second foundry beside a yard that is filling up with what the first one made.
    if (z.z === 2 && s.cargo && s.cargo.room < s.cargo.cap / 2) { s.block[key] = 'goods are piling up in the yard'; continue; }
    const people = type === 'habitat' || type === 'lodge';
    const first = false;
    const unmet = type === 'habitat' ? needs(s).find(q => !q.met) : undefined;
    if (unmet) { s.block[key] = unmet.text; continue; }
    if (people && !first && room <= 0) { s.block[key] = cap.why; continue; }
    if (s.buildings.some(b => b.type === type && b.progress < 1)) { s.block[key] = ''; continue; }   // one going up already
    // a new building on an empty lot
    let best: [number, number] | null = null, bestScore = -Infinity, anyLot = false, raw = false;
    const n = s.size;
    for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) {
      const k = y * n + x;
      if (s.zone[k] !== z.z || s.zone[k + 1] !== z.z || s.zone[k + n] !== z.z || s.zone[k + n + 1] !== z.z) continue;
      if (!(s.linked[k] && s.linked[k + 1] && s.linked[k + n] && s.linked[k + n + 1])) continue;
      if (siteProblem(s, type, x, y, true)) continue;
      if (!lotLevel(s, x, y)) { raw = true; continue; }
      anyLot = true;
      const hab = habAt(s, x, y);
      if (people && hab < 30) continue;
      const score = (people ? hab : -hab) - Math.hypot(x - n / 2, y - n / 2) * 0.3 + (type === 'printer' ? richOf(s, { type, x, y }) * 200 : 0);
      if (score > bestScore) { bestScore = score; best = [x, y]; }
    }
    const pw = first ? '' : powerFor(s, d.priority <= ESSENTIAL ? d.drawNight : 0, d.drawDay);
    if (best) {
      if (pw) s.block[key] = pw;
      else if (!done) { addBuilding(s, type, best[0], best[1], 0); s.stats.grown++; done = true; }
      continue;
    }
    // no lot: an existing building may expand instead
    if (grows(type) && !done && s.want[key] > 0.3) {
      const cands = s.buildings.filter(b => b.type === type && working(b) && b.level < 3
        && (!people || habAt(s, b.x, b.y) >= (b.level === 1 ? 58 : 74)));
      const up = cands.sort((a, b) => habAt(s, b.x, b.y) - habAt(s, a.x, a.y))[0];
      const upw = up ? powerFor(s, d.priority <= ESSENTIAL ? d.drawNight * 0.5 : 0, d.drawDay * 0.5) : '';
      if (up && !upw) {
        up.level++; s.rev++; s.stats.upgrades++; done = true;
        pushAlert(s, 'good', `A ${d.name} has expanded to level ${up.level}.`);
        const [cx, cy] = centre(up); s.pops.push({ id: s.nextPop++, x: cx, y: cy, text: `LEVEL ${up.level}` });
        continue;
      }
      if (up && upw) { s.block[key] = upw; continue; }
    }
    s.block[key] = raw && !anyLot ? 'the graders are still levelling the ground' : anyLot ? 'low habitability' : people && s.buildings.some(b => b.type === type && b.level < 3) ? 'no free land, and habitability too low to expand' : 'no zoned land';
  }
}

function tickShuttle(s: State, dt: number) {
  const sh = s.shuttle, f = s.flows;
  const pad = s.buildings.find(b => b.type === 'pad');
  const open = !!pad && working(pad) && pad.powered;
  if (sh.phase === 'away') {
    if (open && s.nextShuttle > 0 && s.t >= s.nextShuttle && !stormActive(s)) { sh.phase = 'landing'; sh.timer = 3; sh.flight++; }
    return;
  }
  sh.timer -= dt;
  if (sh.timer > 0) return;
  if (sh.phase === 'landing') {
    sh.phase = 'landed'; sh.timer = 5; s.stats.flights++;
    const [px, py] = pad ? centre(pad) : [0, 0];
    if (isNight(s.t)) {
      // Night flights carry cargo only. Whoever is on the Moon at sunset stays until sunrise.
      s.water = Math.min(f.waterCap, s.water + SHUTTLE_WATER + population(s)); s.food += SHUTTLE_FOOD;
      pushAlert(s, 'info', `Shuttle ${sh.flight} has landed with water and food. Night flights carry cargo only.`);
      return;
    }
    const left = (stock: number, rate: number) => (rate < -1e-6 ? stock / -rate : Infinity);
    const safe = !f.lackO2 && !f.lackWater && !f.lackFood && f.exposed === 0 && f.atRisk === 0 && s.mood >= 60
      && left(s.o2, f.o2Rate) > 60 && left(s.food, f.foodRate) > 40;
    const gone = s.tourists;
    s.tourists = 0;
    const cap = support(s);
    let room = Math.max(0, cap.limit - population(s));
    const beds = Math.max(0, f.housing - aliveCount(s) - s.residents);
    const pull = Math.max(0, Math.ceil(f.jobs - f.workers) + 2);   // people come for work, and a few on hope
    const movers = safe ? Math.min(4, beds, room, pull) : 0; room -= movers;
    const guests = safe ? Math.min(f.lodging, room) : 0;
    const turnedAway = safe ? Math.min(4, beds, pull) + f.lodging - movers - guests : 0;
    s.residents += movers; s.tourists = guests;
    s.water = Math.min(f.waterCap, s.water + SHUTTLE_WATER + population(s)); s.food += SHUTTLE_FOOD;
    if (guests) earn(s, guests * LANDING_FEE * s.price, px, py);
    const parts = [movers ? `${movers} new resident${movers > 1 ? 's' : ''}` : '', guests ? `${guests} visitors` : '', gone ? `${gone} visitors heading home` : ''].filter(Boolean);
    pushAlert(s, 'good', `Shuttle ${sh.flight} has landed with water and food${parts.length ? ': ' + parts.join(', ') : ''}.`
      + (!safe ? ' Earth held back all passengers until the base is stable.'
        : turnedAway > 0 ? ` Earth held back ${turnedAway} more: the base can only support ${cap.limit} people. The limit is ${cap.why}.` : ''));
  } else if (sh.phase === 'landed') { sh.phase = 'launching'; sh.timer = 3; }
  else { sh.phase = 'away'; sh.timer = 0; s.nextShuttle = s.t + SHUTTLE_EVERY; }
}

function tickRovers(s: State, dt: number) {
  // A new bay comes with two rovers.
  for (const b of s.buildings) {
    if (b.type !== 'garage' || b.progress < 1 || s.rovers.some(r => r.bay === b.uid)) continue;
    const [hx, hy] = centre(b);
    for (let i = 0; i < 2; i++) s.rovers.push({ bay: b.uid, x: hx, y: hy, hx, hy, tx: hx, ty: hy, phase: 'idle', pax: 0, poi: 0, timer: 2 + i * 5 });
  }
  let away = 0;
  for (const r of s.rovers) if (r.phase !== 'idle') away += r.pax;
  for (const r of s.rovers) {
    if (r.phase === 'idle') {
      r.timer -= dt;
      const bay = s.buildings.find(b => b.uid === r.bay);
      if (r.timer > 0 || !bay || !working(bay) || !bay.on || !bay.powered) continue;
      r.poi = Math.floor(rnd(s) * s.pois.length);
      r.pax = Math.max(0, Math.min(2, s.tourists - away)); away += r.pax;
      r.tx = s.pois[r.poi].x; r.ty = s.pois[r.poi].y; r.phase = 'out';
      continue;
    }
    if (r.phase === 'visit') { r.timer -= dt; if (r.timer <= 0) { r.phase = 'back'; r.tx = r.hx; r.ty = r.hy; } continue; }
    const dx = r.tx - r.x, dy = r.ty - r.y, dist = Math.hypot(dx, dy), step = ROVER_SPEED * dt;
    if (dist > step) { r.x += (dx / dist) * step; r.y += (dy / dist) * step; continue; }
    r.x = r.tx; r.y = r.ty;
    if (r.phase === 'out') { r.phase = 'visit'; r.timer = 2; continue; }
    const poi = s.pois[r.poi];
    earn(s, r.pax > 0 ? r.pax * FARE * poi.bonus * s.price : SURVEY_GRANT, r.hx, r.hy);
    s.stats.trips++; maybeFind(s);
    if (r.pax > 0 && poi.bonus > 1) alertOnce(s, 'heritage', 'good', 'Visitors are back from Tranquility Base, where Eagle landed in 1969. They paid double.', 400);
    r.phase = 'idle'; r.pax = 0; r.timer = 1.5;
  }
}

export function tick(s: State) {
  ground(s);
  if (s.phase !== 'playing') return;
  const dt = TICK;
  const before = phaseOf(s.t);
  s.t += dt;
  const after = phaseOf(s.t);

  for (const b of s.buildings) {
    const d = BUILDINGS[b.type];
    if (b.progress < 1) {
      b.progress = Math.min(1, b.progress + dt / d.buildHours);
      if (b.progress >= 1) {
        s.netDirty = true; s.rev++; s.stats.built++;
        if (b.type !== 'conduit') pushAlert(s, 'good', d.zone && s.zone[b.y * s.size + b.x] ? `A new ${d.name} has opened.` : `${d.name} complete.`);
        if (b.type === 'pad') { s.nextShuttle = s.t + 24; pushAlert(s, 'info', 'Earth has cleared the pad. First shuttle in 24 hours.'); }
      }
    }
    if (b.damaged && b.repair > 0) {
      b.repair -= dt;
      if (b.repair <= 0) { b.repair = 0; b.damaged = false; s.rev++; pushAlert(s, 'good', `${d.name} repaired.`); }
    }
  }
  if (s.netDirty) recomputeNetwork(s);
  if (s.habRev !== s.rev) computeHab(s);

  computeFlows(s, dt);
  const f = s.flows;
  s.stats.peakCharge = Math.max(s.stats.peakCharge, s.charge);

  s.o2 = Math.min(f.o2Cap, s.o2 + f.o2Rate * dt);
  s.water = Math.min(f.waterCap, s.water + f.waterRate * dt);
  s.food = s.food + f.foodRate * dt;
  s.materials += f.income * dt; if (f.income > 0) s.stats.earned += f.income * dt;
  if (s.cargo && f.make > 0) { const made = Math.min(f.make * dt, s.cargo.room); s.cargo.made += made; s.cargo.room -= made; if (s.cargo.stock !== undefined) s.cargo.stock += made; if (made < f.make * dt - 1e-9) s.cargo.full = true; }
  // Buildings wear. Parts come out of the yard; when it has none Earth lands them, at Earth's price.
  if (s.cargo?.wear && f.parts > 0 && dt > 0) {
    const c = s.cargo, need = f.parts * dt, take = Math.min(need, Math.max(0, c.stock ?? 0));
    c.stock = (c.stock ?? 0) - take; c.used = (c.used ?? 0) + take; c.room = Math.min(c.cap, c.room + take);
    const short = need - take;
    if (short > 1e-9) {
      c.landed = (c.landed ?? 0) + short; s.materials -= short * (c.importAt ?? 0);
      alertOnce(s, 'parts', 'warn', 'The yard is out of spare parts, so Earth is landing them at twice what goods fetch at the port. Keep goods in the yard for the buildings, or buy them at the Flats.', 240);
    }
  }
  f.lackO2 = s.o2 <= 0; f.lackWater = s.water <= 0; f.lackFood = s.food <= 0;
  s.o2 = Math.max(0, s.o2); s.water = Math.max(0, s.water); s.food = Math.max(0, s.food);

  // Shelter. Crew take habitat beds first, then residents. Whoever is left over falls back to the
  // lander, which holds four and burns its canisters. Visitors live in lodges.
  const crew = aliveCount(s);
  const outside = Math.max(0, crew + s.residents - f.housing);
  const inLander = s.canisters > 0 ? Math.min(4, outside) : 0;
  if (inLander > 0) s.canisters = Math.max(0, s.canisters - dt);
  const unsheltered = outside - inLander;
  const exposedResidents = Math.min(s.residents, unsheltered);
  f.exposed = unsheltered - exposedResidents;
  f.atRisk = exposedResidents + Math.max(0, s.tourists - f.lodging);

  const clinic = s.buildings.some(b => b.type === 'clinic' && working(b) && b.powered);
  let seen = 0;
  for (const c of s.crew) {
    if (!c.alive) continue;
    const exposed = seen >= crew - f.exposed;
    seen++;
    const harm = (f.lackO2 ? 40 : 0) + (exposed ? 3 : 0) + (f.lackWater ? 1.5 : 0) + (f.lackFood ? 0.4 : 0);
    if (harm > 0) c.health -= (harm * dt) / c.grit;
    else c.health = Math.min(100, c.health + (clinic ? 1.5 : 0.5) * dt);
    if (c.health <= 0) { c.health = 0; c.alive = false; pushAlert(s, 'bad', `${c.name} has died.`); }
  }
  // Residents and visitors have no health bars. When they have no air or no warm bed, Earth pulls them out
  // if there is a working pad, at a cost in compensation. Without a pad they are lost.
  const others = s.residents + s.tourists;
  if (others > 0 && (f.atRisk > 0 || f.lackO2)) {
    s.risk += (f.lackO2 ? others / 3 : f.atRisk / 10) * dt;
    const pad = s.buildings.find(b => b.type === 'pad' && working(b));
    while (s.risk >= 1 && s.residents + s.tourists > 0) {
      s.risk -= 1;
      if (s.tourists > f.lodging || s.residents === 0) s.tourists--; else s.residents--;
      if (pad) { s.stats.evacuated++; s.materials -= EVAC_COST; }
      else s.stats.lost++;
      alertOnce(s, 'lostone', 'bad', pad
        ? `Earth is evacuating people: ${f.lackO2 ? 'there is no oxygen' : 'there are not enough warm, powered beds'}. Each one costs ${EVAC_COST} credits in compensation.`
        : `People are dying: ${f.lackO2 ? 'there is no oxygen' : 'there are not enough warm, powered beds'}.`, 15);
    }
  } else s.risk = 0;

  const target = 100 - (f.lackFood ? 35 : 0) - (f.lackWater ? 35 : 0) - (f.exposed + f.atRisk > 0 ? 40 : 0) - (f.offline > 0 ? 10 : 0)
    - (s.price > 1 ? 8 : 0) - (s.materials < 0 ? 15 : 0) - (stormActive(s) && !clinic ? 15 : 0);
  s.mood += (target - s.mood) * Math.min(1, dt / 24);

  tickShuttle(s, dt);
  tickRovers(s, dt);
  tickContracts(s);
  tickGraders(s, dt);
  tickEvents(s);
  if (s.t >= s.nextGrow) { s.nextGrow = s.t + GROW_EVERY; grow(s); } else computeDemand(s);
  s.stats.peakPop = Math.max(s.stats.peakPop, population(s));

  // Micrometeorite strikes.
  while (s.strikes.length && s.t >= s.strikes[0]) {
    s.strikes.shift();
    const night = isNight(s.t);
    const targets = s.buildings.filter(b => b.progress >= 1 && !b.damaged && b.type !== 'lander' && b.type !== 'conduit'
      && !(night && (b.type === 'battery' || b.type === 'habitat' || b.type === 'lodge')));
    if (!targets.length) continue;
    const hit = targets[Math.floor(rnd(s) * targets.length)];
    hit.damaged = true; hit.repair = 0; s.rev++; s.stats.strikes++;
    pushAlert(s, 'bad', `Micrometeorite strike. ${BUILDINGS[hit.type].name} is offline until repaired.`);
  }

  // Missions: the crew asks, the player delivers, Earth pays.
  const m = MISSIONS[s.mission];
  if (m && m.done(s)) {
    earn(s, m.reward);
    pushAlert(s, 'good', `${m.goal}: done. Earth pays ${m.reward} credits.`, m.who);
    s.mission++;
  }

  // Warnings.
  const left = (stock: number, rate: number) => (rate < -1e-6 ? stock / -rate : Infinity);
  const o2h = left(s.o2, f.o2Rate), wh = left(s.water, f.waterRate), fh = left(s.food, f.foodRate);
  if (f.lackO2) alertOnce(s, 'o2out', 'bad', 'No oxygen. The crew is suffocating.', 12);
  else if (o2h < 48 && !isNight(s.t)) alertOnce(s, 'o2low', 'warn', `Oxygen for ${Math.round(o2h)} hours.`);
  if (f.lackWater) alertOnce(s, 'wout', 'bad', 'The water is gone.', 30);
  else if (wh < 48) alertOnce(s, 'wlow', 'warn', `Water for ${Math.round(wh)} hours.`);
  if (f.lackFood) alertOnce(s, 'fout', 'bad', 'The food is gone. People are going hungry.', 60);
  else if (fh < 48) alertOnce(s, 'flow', 'warn', `Food for ${Math.round(fh)} hours.`);
  if (f.exposed > 0) alertOnce(s, 'exposed', 'bad', 'No safe shelter. Canisters are spent and the habitat is cold or missing.', 20);
  else if (inLander > 0 && s.canisters < 50) alertOnce(s, 'can', 'warn', `Lander canisters: ${Math.round(s.canisters)} hours left. Build and power a Habitat Module.`, 25);
  if (f.offline > 0) alertOnce(s, 'short', 'warn', `Power shortfall. ${f.offline} building${f.offline > 1 ? 's' : ''} shut down.`, 60);
  if (s.materials < 0) alertOnce(s, 'debt', 'warn', 'The base is in debt. Nothing new will be built until it is back in credit.', 120);

  if (before < LIGHT - 60 && after >= LIGHT - 60) {
    const need = nightNeed(s), have = f.battCap;
    pushAlert(s, have >= need ? 'info' : 'warn', have >= need
      ? 'Sunset in 60 hours. Battery capacity is enough for life support.'
      : `Sunset in 60 hours. Life support needs ${Math.round(need)} kWh for the night and you can store ${Math.round(have)}.`);
  }
  if (before < LIGHT && after >= LIGHT) pushAlert(s, 'info', `Sunset. The night lasts ${Math.round(LUNAR_DAY - LIGHT)} hours. Foundries, farms and rovers rest until sunrise.`);
  if (after < before) {
    pushAlert(s, 'good', `Sunrise. Day ${dayNumber(s.t)} on the Moon.`);
    s.strikes.push(s.t + 190 + rnd(s) * 110, s.t + 420 + rnd(s) * 180);
  }

  if (aliveCount(s) === 0) { s.phase = 'lost'; pushAlert(s, 'bad', 'The outpost has fallen silent.'); }
}

/** Refresh derived values after loading a save or applying an intent while paused. */
export function refresh(s: State) {
  ground(s);
  if (s.netDirty) recomputeNetwork(s);
  if (s.habRev !== s.rev) computeHab(s);
  const keep = { exposed: s.flows.exposed, atRisk: s.flows.atRisk, lackO2: s.flows.lackO2, lackWater: s.flows.lackWater, lackFood: s.flows.lackFood };
  computeFlows(s, 0);
  Object.assign(s.flows, keep);
  computeDemand(s);
}

export { ZONE };
