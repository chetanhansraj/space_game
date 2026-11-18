// The interface: a resource strip, a rail of crew and drawers, one-line notices, build categories, inspector, alerts, dialogs.
// Rule: status is always on screen, detail opens when asked for and closes again.
// Plain DOM over the canvas. It reads state and reports clicks; it changes nothing itself.

import { BUILDINGS, BUILD_MENU, BuildingType, ZONES, ZONE_COST } from '../sim/buildings';
import { MISSIONS } from '../sim/missions';
import { FOUNDRY_KG, Plot, PlotKey,
  State, Building, LUNAR_DAY, SHUTTLE_EVERY, TIERS, aliveCount, dayNumber, hoursToSunrise, hoursToSunset,
  PRICES, needs, bedsOf, habAt, jobsOf, drawOf, isNight, nightCover, nightNeed, phaseOf, population, support, tierOf,
} from '../sim/sim';
import { ORES, dusty, eventLine, rawTiles, repairCost, richOf } from '../sim/world';
import { urgent } from './advisor';

export type Tool = BuildingType | 'zone0' | 'zone1' | 'zone2' | 'zone3';
/** The zone a tool paints: 1 to 3, 0 to clear, -1 when the tool is a building. */
export const zoneOf = (t: Tool | null) => (t && t.startsWith('zone') ? Number(t.slice(4)) : -1);

export interface Handlers {
  pickTool(t: Tool | null): void;
  price(level: number): void;
  overlay(): void;
  setSpeed(n: number): void;
  toggle(uid: number): void;
  repair(uid: number): void;
  demolish(uid: number): void;
  start(resume: boolean): void;
  help(): void;
  resume(): void;
  setOn(types: BuildingType[], on: boolean): void;
  readOffer(): void;
  offer(accept: boolean): void;
  deselect(): void;
  /** The yard, in a town on the shared world: change the standing instruction, sell now, or load the ship. */
  yard?(act: YardAct): void;
  /** Hire a caretaker for a town on the shared world, or let one go. */
  caretaker?(on: boolean): void;
}
/** A hired caretaker, as the server reports it. Whole credits. */
export interface Caretaker { on: boolean; fee: number; paid: number; kcr: number; }
/** A live town's yard as the server reports it. Kilograms and whole credits; the page only shows it. */
export interface Yard {
  held_kg: number; cap_kg: number; lot_kg: number; anchor: number; kcr: number;
  make_kg_per_hour: number; foundries: number; full: boolean;
  bid: number | null; last: number | null; sell: boolean; min_price: number;
  sold_kg: number; sales: number; sold_today: number; sales_today: number; sold_yesterday: number; sales_yesterday: number;
  open: boolean; pad: boolean; needs: number;
  /** Spare parts: what the buildings take from the yard, what a standing sale keeps back for them, and Earth's price when it is empty. */
  parts?: { wear: boolean; kg_per_hour: number; keep_kg: number; keep_t: number | null; auto_kg: number; used_kg: number; landed_kg: number; import: number; buy: boolean; max_price: number; bought_kg: number; spent: number; on_order_kg: number };
  ship: { here: boolean; aboard_kg: number; room_kg: number };
}
export type YardAct = 'sell' | 'hold' | 'now' | 'load' | 'keep' | 'keepnone' | 'buy' | 'nobuy';
/** One town on the Moon, as the server lists them all: most people first. */
export interface TownRow { company: string; house: boolean; kind?: string; plot?: Partial<Plot>; lost: boolean; crews: number; age_days: number; population: number; tier: string; buildings: number; sold_t: number; }
export interface UiState { tool: Tool | null; selected: number | null; speed: number; hint: string; overlay: boolean; yard?: Yard | null; caretaker?: Caretaker | null; league?: TownRow[] | null; company?: string; plot?: Partial<Plot> | null; }

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const num = (n: number, dp = 0) => n.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
const hrs = (h: number) => (h === Infinity ? 'stable' : h >= 1000 ? '999+ h' : `${Math.max(0, Math.round(h))} h`);
const left = (stock: number, rate: number) => (rate < -1e-6 ? stock / -rate : Infinity);
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));
const SWATCH: Record<BuildingType, string> = {
  lander: '#d2a84c', conduit: '#b9b4d6', solar: '#3f6fc4', battery: '#3f8f63', reactor: '#ff8a3d', habitat: '#e2ded5',
  o2plant: '#69b4e3', recycler: '#3a9bb0', o2tank: '#b5def4', watertank: '#4a78dc', printer: '#b47a3f', greenhouse: '#58b874', pad: '#8a8799',
  lodge: '#e8c9a0', market: '#86b6ff', garage: '#9aa3ad', garden: '#3fa66a', clinic: '#f4f1ea',
};
const BAR: Record<string, string> = {
  conduit: 'Conduit', solar: 'Solar', battery: 'Battery', habitat: 'Habitat', o2plant: 'O2 Plant', recycler: 'Recycler',
  o2tank: 'O2 Tank', watertank: 'Water Tank', printer: 'Foundry', greenhouse: 'Greenhouse', pad: 'Landing Pad', reactor: 'Reactor',
  lodge: 'Lodge', market: 'Concourse', garage: 'Rover Bay', garden: 'Garden', clinic: 'Clinic',
};
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '='];
const FACE = ['#ffc15e', '#62d394', '#86b6ff', '#ff9a3d'];   // one colour per crew member
const initials = (name: string) => name.split(' ').map(w => w[0]).join('');

export function stateLine(b: Building): { text: string; tone: string } {
  const d = BUILDINGS[b.type];
  if (b.progress < 1) return { text: `Under construction, ${Math.round(b.progress * 100)}%`, tone: 'sun' };
  if (b.damaged) return b.repair > 0 ? { text: `Repairing, ${Math.ceil(b.repair)} h left`, tone: 'warn' } : { text: 'Damaged and offline', tone: 'bad' };
  if (!b.connected) return { text: 'Not linked to the lander', tone: 'warn' };
  if (!b.on) return { text: 'Switched off', tone: 'dim' };
  if ((d.drawDay > 0 || d.drawNight > 0) && !b.powered) return { text: 'No power', tone: 'bad' };
  return { text: 'Running', tone: 'ok' };
}

const ic = (d: string) => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const ICON = {
  money: '<circle cx="12" cy="12" r="8"/><path d="M14.5 9.5a3.5 3.5 0 1 0 0 5"/>',
  people: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7"/>',
  deals: '<path d="M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5"/>',
  log: '<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0"/>',
  towns: '<path d="M3 20h18M5 20v-7l4-3 4 3v7M13 20V8l3-3 3 3v12M8 20v-3M16 12v.01M16 16v.01"/>',
  zones: '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
  power: '<path d="M13 3 5 14h6l-1 7 8-11h-6z"/>',
  life: '<path d="M4 18a8 8 0 0 1 16 0zM2 18h20M12 10v8"/>',
  transport: '<path d="M12 3c3 2.5 4.5 6 4.5 9.5L14 16h-4l-2.5-3.5C7.5 9 9 5.5 12 3zM10 16l-1 4M14 16l1 4"/><circle cx="12" cy="9.5" r="1.5"/>',
  community: '<path d="M12 21v-6M12 15c-3.5 0-6-2.4-6-5.5S8.7 3 12 3s6 3.4 6 6.5-2.5 5.5-6 5.5z"/>',
};
/** The build menu in five drawers. Zones come first because zoning is how the town grows. */
const CATS: { id: string; name: string; icon: string; tools: Tool[] }[] = [
  { id: 'zones', name: 'Zones', icon: ICON.zones, tools: ['zone1', 'zone2', 'zone3', 'zone0'] },
  { id: 'power', name: 'Power', icon: ICON.power, tools: ['conduit', 'solar', 'battery', 'reactor'] },
  { id: 'life', name: 'Life support', icon: ICON.life, tools: ['habitat', 'o2plant', 'recycler', 'greenhouse', 'o2tank', 'watertank'] },
  { id: 'transport', name: 'Transport', icon: ICON.transport, tools: ['pad', 'garage'] },
  { id: 'community', name: 'Community', icon: ICON.community, tools: ['garden', 'clinic'] },
];
const catOf = (t: Tool) => CATS.find(c => c.tools.includes(t))!.id;
type DrawerId = 'demand' | 'money' | 'people' | 'deals' | 'towns' | 'log' | 'crew0' | 'crew1' | 'crew2' | 'crew3';
const RES_NOTE: Record<string, string> = {
  people: 'Everyone on the base. The limit is how many your life support can carry through a night, and what holds it there.',
  mat: 'Credits pay for everything you build and zone. The rate leaves out rover fares, landing fees and contracts, which come on top.',
  power: 'What the base makes right now against what it uses. Solar follows the Sun and gives nothing at night.',
  store: 'Battery charge. It has to carry heat, air and light through the whole of the dark.',
  o2: 'Oxygen in the tanks. Plants make it from regolith, and people breathe it day and night.',
  water: 'Water in the tanks. A recycler returns most of what people use.',
  food: 'Food in store. The shuttle feeds about nine, and each greenhouse about nine more.',
};
const RES_NAME: Record<string, string> = { people: 'People', mat: 'Credits', power: 'Power', store: 'Storage', o2: 'Oxygen', water: 'Water', food: 'Food' };

export class Hud {
  private lastAlert = 0; private seenAlert = 0;
  private inspKey = ''; private drawerKey = ''; private advKey = ''; private misKey = ''; private offerKey = ''; private railKey = '';
  private advTool: Tool | null = null;
  private advOff: BuildingType[] | null = null;
  private advOn: BuildingType[] | null = null;
  private misTool: Tool | null = null;
  private curTool: Tool | null = null;
  private cat: string | null = null;        // which build category has its tray open
  private drawer: DrawerId | null = null;   // which left drawer is open
  private pop: string | null = null;        // which resource has its detail open
  private more = false;                     // whether the inspector's reading is unfolded
  private res: Record<string, { value: string; sub: string; frac: number; tone: string }> = {};
  // messages: what has been read, per crew member, and the preview bubble on screen
  private seenMis = -1; private seenUrg = ''; private seenBy = [0, 0, 0, 0];
  private lastMis = -2; private lastUrg = '';
  private bubbleFor: 'mis' | 'urg' | 'offer' | null = null; private bubbleUntil = 0; private bubbleKey = ''; private lastOffer = '';
  private moonKey = -1; private time0 = true; private curMis = 0;
  private pressing = false; private drawerAt = 0; private drawerStruct = '';

  constructor(private h: Handlers) {
    // ----- build: five categories, each with a tray -----
    const cats = $('cats'), tray = $('tray');
    for (const c of CATS) {
      const b = document.createElement('button');
      b.className = 'cat'; b.id = `cat-${c.id}`; b.type = 'button'; b.setAttribute('aria-pressed', 'false');
      b.innerHTML = `${ic(c.icon)}<span>${esc(c.name)}</span>`;
      b.addEventListener('click', () => { this.cat = this.cat === c.id ? null : c.id; this.showTray(); });
      cats.appendChild(b);
      for (const t of c.tools) {
        const z = zoneOf(t), el = document.createElement('button');
        el.type = 'button'; el.id = `tool-${t}`; el.dataset.cat = c.id;
        if (z > 0) { const zd = ZONES[z - 1]; el.className = 'tool zone'; el.innerHTML = `<i style="background:${zd.css}"></i><span class="tn">${esc(zd.short)}</span><span class="tz">${ZONE_COST} cr a tile</span>`; el.title = `Zone land for ${zd.name}: ${zd.desc}`; }
        else if (z === 0) { el.className = 'tool zone'; el.innerHTML = '<i style="background:#55526a"></i><span class="tn">Unzone</span><span class="tz">clear</span>'; el.title = 'Clear zoning from empty land'; }
        else { const bt = t as BuildingType, d = BUILDINGS[bt], k = KEYS[BUILD_MENU.indexOf(bt)]; el.className = 'tool'; el.innerHTML = `<i style="background:${SWATCH[bt]}"></i><span class="tn">${esc(BAR[bt] ?? d.name)}</span><span class="tc">${d.cost}</span>${k ? `<kbd>${k}</kbd>` : ''}`; el.title = `${d.name}: ${d.effect}`; }
        el.addEventListener('click', () => h.pickTool(t));
        tray.appendChild(el);
      }
    }
    // ----- left rail: crew, then drawers -----
    const rail = $('rail');
    const railBtn = (id: DrawerId, inner: string, label: string, title: string) => {
      const b = document.createElement('button');
      b.className = 'rb'; b.id = `rb-${id}`; b.type = 'button'; b.title = title; b.setAttribute('aria-pressed', 'false');
      b.innerHTML = `${inner}<span>${esc(label)}</span><em class="bd" hidden></em>`;
      b.addEventListener('click', () => this.openDrawer(this.drawer === id ? null : id));
      rail.appendChild(b);
    };
    const NAMES = ['Asha', 'Kenji', 'Lena', 'Rafael'], ROLES = ['Commander', 'Flight surgeon', 'Systems engineer', 'Geologist'];
    NAMES.forEach((n, i) => railBtn(`crew${i}` as DrawerId, `<span class="face" style="background:${FACE[i]}">${n[0]}${['R', 'M', 'O', 'C'][i]}</span>`, n, `${n}, ${ROLES[i]}`));
    rail.appendChild(Object.assign(document.createElement('i'), { className: 'rsep' }));
    railBtn('demand', '<i class="rci" id="rci"><b><i></i></b><b><i></i></b><b><i></i></b></i>', 'Demand', 'What the base wants: Habitat, Industry, Commercial');
    railBtn('money', ic(ICON.money), 'Money', 'Income, upkeep and prices');
    railBtn('people', ic(ICON.people), 'People', 'Crew, residents, visitors, shuttle and rovers');
    railBtn('deals', ic(ICON.deals), 'Deals', 'Contracts with nations and companies');
    railBtn('towns', ic(ICON.towns), 'Towns', 'Every town on the Moon, and where yours stands');
    $('rb-towns').hidden = true;   // only a town on the shared world has neighbours
    railBtn('log', ic(ICON.log), 'Log', 'Everything that has happened');

    document.querySelectorAll<HTMLButtonElement>('.speed button').forEach(b =>
      b.addEventListener('click', () => h.setSpeed(Number(b.dataset.speed))));
    $('btn-help').addEventListener('click', () => h.help());
    $('btn-map').addEventListener('click', () => h.overlay());
    for (const id of Object.keys(RES_NAME)) $(`g-${id}`).addEventListener('click', () => { this.pop = this.pop === id ? null : id; this.showPop(); });
    for (const id of ['drawer', 'inspector']) $(id).addEventListener('pointerdown', () => { this.pressing = true; });
    window.addEventListener('pointerup', () => { window.setTimeout(() => { this.pressing = false; }, 0); });
    window.addEventListener('pointercancel', () => { this.pressing = false; });
    $('drawer').addEventListener('click', e => {
      const el = e.target as HTMLElement;
      const pr = el.closest('button[data-price]') as HTMLButtonElement | null;
      if (pr) { h.price(Number(pr.dataset.price)); this.drawerKey = '?'; }
      const yd = el.closest('button[data-yard]') as HTMLButtonElement | null;
      if (yd && h.yard) { h.yard(yd.dataset.yard as YardAct); this.drawerKey = '?'; }
      const ck = el.closest('button[data-care]') as HTMLButtonElement | null;
      if (ck && h.caretaker) { h.caretaker(ck.dataset.care === '1'); this.drawerKey = '?'; }
      if (el.closest('[data-act="close"]')) this.openDrawer(null);
      if (el.closest('[data-act="read"]')) h.readOffer();
      if (el.closest('[data-act="adv"]')) this.doAdv();
      if (el.closest('[data-act="mis"]')) this.doMis();
    });
    $('bubble').addEventListener('click', e => {
      const kind = this.bubbleFor, who = Number($('bubble').dataset.who);
      if (kind === 'mis') this.seenMis = this.curMis;
      if ((e.target as HTMLElement).closest('.nb')) { if (kind === 'mis') this.doMis(); else if (kind === 'urg') this.doAdv(); else if (kind === 'offer') h.readOffer(); }
      else this.openDrawer(kind === 'offer' ? 'deals' : (`crew${who}` as DrawerId));
      this.hideBubble();
    });
    const insp = $('inspector');
    insp.addEventListener('click', e => {
      const t = (e.target as HTMLElement).closest('button[data-act]') as HTMLButtonElement | null;
      if (!t) return;
      const uid = Number(t.dataset.uid), act = t.dataset.act;
      if (act === 'toggle') h.toggle(uid); else if (act === 'repair') h.repair(uid);
      else if (act === 'demolish') h.demolish(uid); else if (act === 'cancel') h.pickTool(null); else if (act === 'close') h.deselect();
    });
    insp.addEventListener('toggle', e => { const d = e.target as HTMLDetailsElement; if (d.classList?.contains('more')) this.more = d.open; }, true);
  }

  keyTool(key: string): BuildingType | null {
    const i = KEYS.indexOf(key);
    return i >= 0 && i < BUILD_MENU.length ? BUILD_MENU[i] : null;
  }

  /** A click on the map: the message preview and any resource detail close. Drawers stay, they were opened on purpose. */
  fold() {
    if (!this.time0) this.hideBubble();
    if (this.pop) { this.pop = null; this.showPop(); }
  }
  private hideBubble() { this.bubbleFor = null; this.bubbleKey = ''; $('bubble').hidden = true; }
  private doAdv() {
    if (this.advTool) { if (this.curTool !== this.advTool) this.h.pickTool(this.advTool); }
    else if (this.advOff) this.h.setOn(this.advOff, false);
    else if (this.advOn) this.h.setOn(this.advOn, true);
  }
  private doMis() { if (this.misTool && this.curTool !== this.misTool) this.h.pickTool(this.misTool); }
  /** Escape with nothing in hand closes whatever is open, nearest first. True if something closed. */
  escape(): boolean {
    if (this.pop) { this.pop = null; this.showPop(); return true; }
    if (this.cat) { this.cat = null; this.showTray(); return true; }
    if (this.drawer) { this.openDrawer(null); return true; }
    return false;
  }
  private openDrawer(id: DrawerId | null) {
    this.drawer = id; this.drawerKey = '?'; this.railKey = '?';
    if (id === 'log') this.seenAlert = this.lastAlert;
    if (id && (id.startsWith('crew') ? this.bubbleFor !== 'offer' : this.bubbleFor === 'mis')) this.hideBubble();   // a drawer opened on purpose is not talked over
    if (id === 'deals' && this.bubbleFor === 'offer') this.hideBubble();
  }
  private showTray() {
    const tray = $('tray');
    tray.hidden = !this.cat;
    for (const el of Array.from(tray.children) as HTMLElement[]) el.hidden = el.dataset.cat !== this.cat;
    for (const c of CATS) { const b = $(`cat-${c.id}`); b.setAttribute('aria-pressed', String(this.cat === c.id)); b.classList.toggle('has', !!this.curTool && c.tools.includes(this.curTool)); }
  }
  private showPop() {
    const box = $('respop'), id = this.pop;
    for (const k of Object.keys(RES_NAME)) $(`g-${k}`).setAttribute('aria-expanded', String(k === id));
    box.hidden = !id;
    if (!id) return;
    const r = this.res[id], chip = $(`g-${id}`).getBoundingClientRect(), app = $('app').getBoundingClientRect();
    box.dataset.tone = r.tone;
    box.innerHTML = `<p class="eyebrow">${RES_NAME[id]}</p><h2>${esc(r.value)}</h2><p class="rs">${esc(r.sub)}</p><div class="gb"><i style="width:${Math.round(Math.max(0, Math.min(1, r.frac)) * 100)}%"></i></div><p class="rn">${RES_NOTE[id]}</p>`;
    box.style.left = `${Math.max(12, Math.min(app.width - 276, chip.left - app.left + chip.width / 2 - 132))}px`;
  }

  update(s: State, ui: UiState) {
    const f = s.flows, night = isNight(s.t), ph = phaseOf(s.t);
    $('phase').textContent = night ? 'Night' : 'Day';
    $('phase').className = night ? 'night' : 'day';
    $('countdown').textContent = s.phase !== 'playing' ? 'Mission over' : night ? `Sunrise in ${num(hoursToSunrise(s.t))} h` : `Sunset in ${num(hoursToSunset(s.t))} h`;
    $('hour').textContent = `Lunar day ${dayNumber(s.t)} · hour ${num(ph)} of ${LUNAR_DAY}`;
    this.moon(ph, night);
    this.time0 = s.t === 0;
    const ev = eventLine(s), evEl = $('event');
    evEl.hidden = !ev; if (ev) { evEl.textContent = ev.text; evEl.dataset.tone = ev.tone; }
    document.querySelectorAll<HTMLButtonElement>('.speed button').forEach(b =>
      b.setAttribute('aria-pressed', String(Number(b.dataset.speed) === ui.speed)));

    const tile = (id: string, value: string, sub: string, frac: number, tone: string) => {
      const key = id.slice(2), el = $(id), was = this.res[key];
      if (was && was.value === value && was.sub === sub && was.tone === tone && Math.abs(was.frac - frac) < 0.005) return;
      this.res[key] = { value, sub, frac, tone };
      (el.querySelector('.cv') as HTMLElement).textContent = value;
      (el.querySelector('.cb i') as HTMLElement).style.width = `${Math.max(0, Math.min(1, frac)) * 100}%`;
      el.dataset.tone = tone; el.title = `${RES_NAME[key]}: ${sub}`;
      if (this.pop === key) this.showPop();
    };
    const pop = population(s), cap = support(s);
    const hasPad = s.buildings.some(b => b.type === 'pad' && b.progress >= 1);
    tile('g-people', `${pop}`, !hasPad ? 'founding crew · no landing pad yet' : pop >= cap.limit ? `full · limit: ${cap.why}` : `room for ${cap.limit - pop} more · then ${cap.why}`,
      cap.limit && hasPad ? pop / cap.limit : 1, f.exposed + f.atRisk > 0 ? 'bad' : hasPad && pop >= cap.limit ? 'warn' : 'ok');
    tile('g-mat', num(Math.floor(s.materials)), `${f.income >= 0 ? '+' : ''}${num(f.income, 1)} an hour${f.saving && !night ? ' · saving power' : ''}`, Math.min(1, Math.max(0, s.materials) / 400), s.materials < 0 ? 'bad' : f.income < 0 ? 'warn' : 'sun');
    const net = f.gen - f.load;
    tile('g-power', `${num(f.gen, 1)} kW`, f.offline ? `${f.offline} shut down · needs ${num(f.demand, 1)} kW` : net >= 0 ? `using ${num(f.load, 1)} kW · ${num(net, 1)} spare` : `using ${num(f.load, 1)} kW · draining storage`,
      f.demand > 0 ? f.gen / Math.max(f.demand, f.gen) : 1, f.offline ? 'bad' : net < 0 && !night ? 'warn' : 'ok');
    const cover = nightCover(s), toDawn = hoursToSunrise(s.t), needKwh = nightNeed(s);
    const anyHabitat = s.buildings.some(b => b.type === 'habitat' && b.progress >= 1);
    const storeText = !anyHabitat ? 'no habitat to keep warm yet'
      : night ? (cover === Infinity ? 'night load covered' : `lasts ${hrs(cover)} · sunrise in ${num(toDawn)} h`)
      : needKwh <= 0 ? `of ${num(f.battCap)} · night covered` : `of ${num(f.battCap)} · night needs ${num(needKwh)}`;
    const storeTone = !anyHabitat ? 'ok' : night ? (cover >= toDawn ? 'ok' : cover >= toDawn * 0.6 ? 'warn' : 'bad')
      : f.battCap >= needKwh ? 'ok' : f.battCap >= needKwh * 0.6 ? 'warn' : 'bad';
    tile('g-store', `${num(s.charge)} kWh`, storeText, f.battCap ? s.charge / f.battCap : 0, storeTone);
    const o2h = left(s.o2, f.o2Rate), wh = left(s.water, f.waterRate), fh = left(s.food, f.foodRate);
    const tone = (h: number) => (h < 48 ? 'bad' : h < 150 ? 'warn' : 'ok');
    const rate = (r: number, dp = 2) => `${r >= 0 ? '+' : ''}${num(r, dp)}/h`;
    tile('g-o2', `${num(s.o2)} kg`, o2h === Infinity ? `of ${num(f.o2Cap)} · filling` : `of ${num(f.o2Cap)} · ${hrs(o2h)} left`, s.o2 / f.o2Cap, tone(o2h));
    tile('g-water', `${num(s.water)} kg`, wh === Infinity ? `${rate(f.waterRate)}` : `${rate(f.waterRate)} · ${hrs(wh)} left`, s.water / f.waterCap, tone(wh));
    tile('g-food', `${num(s.food)} kg`, fh === Infinity ? `${rate(f.foodRate)} · growing` : `${rate(f.foodRate)} · ${hrs(fh)} left`, Math.min(1, s.food / 200), tone(fh));

    // a tool picked from a notice or a key opens the tray it lives in, so the player learns where it is
    if (ui.tool !== this.curTool) { this.curTool = ui.tool; if (ui.tool) this.cat = catOf(ui.tool); this.showTray(); }
    for (const t of BUILD_MENU) {
      const b = $(`tool-${t}`);
      b.classList.toggle('active', ui.tool === t);
      b.classList.toggle('poor', s.materials < BUILDINGS[t].cost);
    }
    for (let z = 0; z <= ZONES.length; z++) $(`tool-zone${z}`).classList.toggle('active', ui.tool === `zone${z}`);
    $('btn-map').setAttribute('aria-pressed', String(ui.overlay));
    $('hint').textContent = ui.hint;
    this.messages(s);
    this.alerts(s);
    this.rail(s, ui);
    this.drawerBody(s, ui);
    this.inspector(s, ui);
  }

  /** The Moon as Earth sees it. The synodic month is the lunar day, so the shadow line crosses the base at sunrise and sunset. */
  private moon(ph: number, night: boolean) {
    const key = Math.floor(ph);
    if (key === this.moonKey) return;
    this.moonKey = key;
    const BASE_LON = 23.5, R = 34;
    let sun = BASE_LON + 90 - (360 / LUNAR_DAY) * ph;          // longitude under the Sun, east positive
    sun = ((sun + 180) % 360 + 360) % 360 - 180;
    const lit = (1 + Math.cos(sun * Math.PI / 180)) / 2, rx = Math.abs(Math.cos(sun * Math.PI / 180)) * R;
    const east = sun >= 0;                                       // Sun to the east: the right limb is lit, the Moon is waxing
    // the dark part: the unlit limb, closed by the shadow line (half an ellipse)
    const limb = east ? 0 : 1, bulge = (east ? lit > 0.5 : lit < 0.5) ? 1 : 0;
    ($('moon-shade') as unknown as SVGPathElement).setAttribute('d', `M 0 ${-R} A ${R} ${R} 0 0 ${limb} 0 ${R} A ${rx.toFixed(2)} ${R} 0 0 ${bulge} 0 ${-R} Z`);
    $('moon-base').setAttribute('class', night ? 'night' : '');
    $('moon-name').textContent = lit < 0.03 ? 'New Moon' : lit > 0.97 ? 'Full Moon' : Math.abs(lit - 0.5) < 0.04 ? (east ? 'First quarter' : 'Last quarter') : `${east ? 'Waxing' : 'Waning'} ${lit < 0.5 ? 'crescent' : 'gibbous'}`;
  }

  /** Messages from the crew. A new one shows a short preview beside the face, then stays as a badge until it is read. */
  private messages(s: State) {
    const u = urgent(s), m = MISSIONS[s.mission], now = performance.now();
    this.advTool = u ? u.tool ?? (u.zone ? (`zone${u.zone}` as Tool) : null) : null; this.advOff = u?.off ?? null; this.advOn = u?.on ?? null;
    this.misTool = m ? m.tool ?? (m.zone ? (`zone${m.zone}` as Tool) : null) : null;
    this.curMis = s.mission;
    const ukey = u ? `${u.who}${u.title}` : '';
    if (ukey !== this.lastUrg) { this.lastUrg = ukey; if (u) { this.bubbleFor = 'urg'; this.bubbleUntil = now + 12000; } else if (this.bubbleFor === 'urg') this.hideBubble(); }
    if (s.mission !== this.lastMis) { this.lastMis = s.mission; if (m && this.bubbleFor !== 'urg') { this.bubbleFor = 'mis'; this.bubbleUntil = now + 12000; } }
    const okey = s.offer ? s.offer.title : '';
    if (okey !== this.lastOffer) { this.lastOffer = okey; if (s.offer && !this.bubbleFor) { this.bubbleFor = 'offer'; this.bubbleUntil = now + 12000; } else if (!s.offer && this.bubbleFor === 'offer') this.hideBubble(); }
    // reading: an open thread marks that person's messages as seen
    if (this.drawer && this.drawer.startsWith('crew')) {
      const i = Number(this.drawer.slice(4));
      if (m && m.who === i) this.seenMis = s.mission;
      if (u && u.who === i) this.seenUrg = ukey;
      this.seenBy[i] = this.lastAlert;
    }
    if (this.bubbleFor && !this.time0 && now > this.bubbleUntil) this.hideBubble();
    if (this.bubbleFor === 'mis' && !m) this.hideBubble();
    const kind = this.bubbleFor, box = $('bubble');
    if (!kind) { if (!box.hidden) box.hidden = true; return; }
    const who = kind === 'urg' ? u!.who : kind === 'mis' ? m!.who : 0;
    const afford = kind === 'mis' && m!.tool ? s.materials >= BUILDINGS[m!.tool].cost : true;
    const label = kind === 'offer' ? 'Read the offer' : kind === 'urg' ? this.actLabel(u!.tool, u!.zone, u!.off, u!.on, true) : this.actLabel(m!.tool, m!.zone, undefined, undefined, afford);
    const title = kind === 'offer' ? s.offer!.title : kind === 'urg' ? u!.title : m!.goal;
    const text = kind === 'offer' ? `${s.offer!.from} pays ${s.offer!.pay} credits. The crew have views.` : kind === 'urg' ? u!.why : m!.say;
    const key = `${kind}:${who}:${title}:${label}`;
    if (key !== this.bubbleKey) {
      this.bubbleKey = key;
      box.dataset.tone = kind === 'urg' ? 'bad' : 'sun'; box.dataset.who = String(who);
      box.innerHTML = `<p class="bw">${kind === 'offer' ? 'Offer' : `${esc(s.crew[who].name)} · ${kind === 'urg' ? 'urgent' : esc(s.crew[who].role)}`}</p><p class="bt">${esc(title)}</p><p class="bs">${esc(text)}</p>
        <div class="br">${label ? `<button type="button" class="nb${afford ? '' : ' wait'}">${esc(label)}</button>` : ''}<span>Click to read</span></div>`;
      const anchor = $(kind === 'offer' ? 'rb-deals' : `rb-crew${who}`).getBoundingClientRect(), app = $('app').getBoundingClientRect();
      box.style.top = `${Math.round(anchor.top - app.top)}px`;
      box.hidden = false;
    }
  }
  private actLabel(tool?: BuildingType, zone?: number, off?: BuildingType[], on?: BuildingType[], afford = true): string {
    if (tool) return afford ? `Build ${BAR[tool] ?? BUILDINGS[tool].name} · ${BUILDINGS[tool].cost}` : `Needs ${BUILDINGS[tool].cost} credits`;
    if (zone) return `Zone ${ZONES[zone - 1].name}`;
    if (off) return 'Switch them off';
    if (on) return 'Switch it on';
    return '';
  }

  /** Badges and the little demand meter on the rail. A green count is unread messages, as in a chat app. */
  private rail(s: State, ui: UiState) {
    const u = urgent(s), m = MISSIONS[s.mission], nd = needs(s);
    const blocked = ZONES.some(z => s.want[z.key] > 0.15 && !!s.block[z.key]);
    const unmet = nd.some(q => !q.met), soon = s.deals.some(d => d.due - s.t < 40);
    const unread = this.drawer === 'log' ? 0 : s.alerts.filter(a => a.id > this.seenAlert).length;
    if (this.drawer === 'log') this.seenAlert = this.lastAlert;
    const crewTone = s.crew.map(c => (!c.alive ? 'dead' : c.health < 35 ? 'bad' : c.health < 70 ? 'warn' : 'ok'));
    const fresh = s.crew.map((_, i) => (m && m.who === i && s.mission > this.seenMis ? 1 : 0) + s.alerts.filter(a => a.who === i && a.id > this.seenBy[i] && !a.msg.includes(': done.')).length);
    const want = ZONES.map(z => Math.round(s.want[z.key] * 10));
    const rank = ui.league ? ui.league.findIndex(t => t.company === ui.company) + 1 : 0;
    const key = [u?.who, m?.who, blocked, unmet, soon, !!s.offer, s.materials < 0, !!ui.yard?.full, unread, this.drawer, crewTone.join(), fresh.join(), want.join(), rank, ui.league?.length].join('|');
    if (key === this.railKey) return;
    this.railKey = key;
    const badge = (id: DrawerId, tone: string | null, text = '') => {
      const b = $(`rb-${id}`), bd = b.querySelector('.bd') as HTMLElement;
      bd.hidden = !tone; if (tone) { bd.dataset.tone = tone; bd.textContent = text; }
      b.setAttribute('aria-pressed', String(this.drawer === id));
    };
    s.crew.forEach((_, i) => {
      badge(`crew${i}` as DrawerId, u?.who === i ? 'urgent' : fresh[i] ? 'new' : null, u?.who === i ? '!' : String(fresh[i] > 9 ? '9+' : fresh[i]));
      const b = $(`rb-crew${i}`); b.dataset.tone = crewTone[i]; b.classList.toggle('asking', m?.who === i);
    });
    badge('demand', blocked ? 'warn' : unmet ? 'warn' : null);
    badge('money', s.materials < 0 ? 'bad' : ui.yard?.full ? 'warn' : null);
    $('rb-towns').hidden = !ui.league;
    badge('towns', rank && ui.league!.length > 1 ? 'new' : null, `${rank}`);
    badge('people', s.flows.exposed + s.flows.atRisk > 0 ? 'bad' : null);
    badge('deals', s.offer ? 'sun' : soon ? 'warn' : null);
    badge('log', unread ? 'dim' : null, unread > 9 ? '9+' : String(unread || ''));
    const bars = $('rci').querySelectorAll<HTMLElement>('b > i');
    ZONES.forEach((z, i) => {
      const w = s.want[z.key], hgt = Math.round(Math.abs(w) * 50);
      bars[i].style.cssText = w >= 0 ? `bottom:50%;height:${hgt}%;background:${z.css}` : `top:50%;height:${hgt}%;background:#6a6780`;
    });
  }

  /** One paragraph from each crew member about their side of the base, built from the live numbers. */
  private report(s: State, who: number): string {
    const f = s.flows, pop = population(s);
    const h = (stock: number, r: number) => (r < -1e-6 ? `${hrs(stock / -r)}` : 'no end in sight');
    if (who === 0) { const next = TIERS.find(t => t[0] > pop); return `We are ${tierOf(pop) === 'Outpost' ? 'an' : 'a'} ${tierOf(pop)} of ${pop}.${next ? ` ${next[1]} at ${next[0]} people.` : ''} ${s.deals.length ? `${s.deals.length} contract${s.deals.length > 1 ? 's' : ''} signed and open.` : 'No contracts open.'} ${Math.floor(s.materials)} credits in hand, ${f.income >= 0 ? 'gaining' : 'losing'} ${Math.abs(f.income).toFixed(1)} an hour.`; }
    if (who === 1) return `Oxygen for ${h(s.o2, f.o2Rate)}, water for ${h(s.water, f.waterRate)}, food for ${h(s.food, f.foodRate)}. ${f.exposed + f.atRisk > 0 ? `${f.exposed + f.atRisk} people have no safe bed.` : 'Everyone has a powered bed.'}`;
    if (who === 2) { const need = nightNeed(s); return `We make ${num(f.gen, 1)} kW and use ${num(f.load, 1)}. Storage holds ${num(s.charge)} of ${num(f.battCap)} kWh${need > 0 ? `, and a night needs ${num(need)}` : ''}.${f.offline ? ` ${f.offline} machines are shut down for lack of power.` : ''}`; }
    const raw = rawTiles(s);
    return `${s.rovers.length ? `${s.stats.trips} rover trips so far` : 'No rovers yet'}, ${s.finds.length} survey find${s.finds.length === 1 ? '' : 's'}. ${raw ? `${raw} zoned tile${raw > 1 ? 's' : ''} still to level.` : 'The graders are idle.'}`;
  }

  /** The yard: what the foundries have made, what the port will pay, and what to do with it. */
  private yardHtml(y: Yard): string {
    const t = (kg: number, dp = 1) => `${num(kg / 1000, dp)} t`;
    const per = (cr: number | null) => (cr === null ? 'no buyer' : `${num(cr / y.kcr, 1)} a tonne`);
    const p = y.parts, wear = !!p?.wear && p.kg_per_hour > 0, kept = p?.wear ? p.keep_kg : 0;
    const whole = Math.floor(y.held_kg / y.lot_kg), spare = Math.floor(Math.max(0, y.held_kg - kept) / y.lot_kg), tone = y.full ? '#ff6b6b' : y.held_kg > y.cap_kg / 2 ? '#f0a04e' : 'var(--cyan)';
    const making = y.full ? 'Yard full: the foundries have stopped' : y.foundries === 0 ? 'No foundry yet. Zone land for Industry'
      : y.make_kg_per_hour > 0 ? `Making ${num(y.make_kg_per_hour)} kg an hour` : 'Foundries resting';
    const sold = (kg: number, cr: number) => (kg ? `${t(kg, 0)} · +${num(cr / y.kcr)}` : 'nothing');
    const gate = !y.open ? `<p class="txt">Nothing leaves the yard until the town has ${y.pad ? '' : 'a working landing pad and '}${y.needs} people. What is made waits here.</p>` : '';
    const acts = y.open ? `<div class="prices"><span>As made</span><button type="button" data-yard="sell" aria-pressed="${y.sell}">Sell</button><button type="button" data-yard="hold" aria-pressed="${!y.sell}">Hold</button></div>
      <div class="acts" style="margin-bottom:8px">${spare >= 1 && y.bid !== null && y.bid >= y.min_price ? `<button type="button" class="primary" data-yard="now">Sell ${spare} t now</button>` : ''}${y.ship.here && whole >= 1 && y.ship.room_kg >= y.lot_kg ? `<button type="button" data-yard="load">Load ${Math.min(whole, Math.floor(y.ship.room_kg / y.lot_kg))} t into your ship</button>` : ''}</div>` : '';
    return `<h3>Yard · manufactured goods</h3><p class="sub">${t(y.held_kg)} of ${t(y.cap_kg, 0)} · ${esc(making)}</p>
      <span class="dbar yard"><i style="left:0;width:${Math.min(100, Math.round((y.held_kg / y.cap_kg) * 100))}%;background:${tone}"></i></span>
      <dl class="budget one"><div><dt>Best bid at the Flats</dt><dd>${per(y.bid)}</dd></div><div><dt>Earth pays</dt><dd>${per(y.anchor)}</dd></div><div><dt>Sold today</dt><dd>${sold(y.sold_today, y.sales_today)}</dd></div><div><dt>Sold in all</dt><dd>${sold(y.sold_kg, y.sales)}</dd></div></dl>
      ${acts}${gate}${this.partsHtml(y)}<p class="txt">Goods sell by the tonne to whoever at the port bids most${y.sell && y.open ? ', and never below Earth\'s price' : ''}.${y.ship.aboard_kg ? ` ${t(y.ship.aboard_kg, 0)} aboard your ship.` : ''}</p><h3>The town</h3>`;
  }

  /** The ground this town stands on: where it is and its six readings, which add up to the same for everyone. */
  private groundHtml(plot?: Partial<Plot> | null): string {
    if (!plot || plot.sun === undefined) return '';
    const rows: [PlotKey, string, string][] = [
      ['sun', 'Sunlight', 'what the arrays make'], ['ice', 'Water ice', 'less to bring from Earth'], ['metal', 'Iron and titanium', 'what a foundry makes'],
      ['glass', 'Aluminium and silicon', 'fewer spare parts'], ['he3', 'Helium-3', 'richer survey finds'], ['view', 'What there is to see', 'what visitors pay'],
    ];
    const where = `${Math.abs(plot.lat ?? 0).toFixed(1)}° ${(plot.lat ?? 0) >= 0 ? 'N' : 'S'}, ${Math.abs(plot.lon ?? 0).toFixed(1)}° ${(plot.lon ?? 0) >= 0 ? 'E' : 'W'}`;
    const bars = rows.map(([k, name, what]) => { const v = plot[k] ?? 0.5; return `<li><b>${name}</b><span class="dbar"><i style="left:0;width:${Math.round(v * 100)}%;background:${v >= 0.66 ? 'var(--cyan)' : v <= 0.25 ? '#55526a' : '#8b8aa8'}"></i></span><em>${what}</em></li>`; }).join('');
    return `<h3>Your ground</h3><p class="sub">${esc(plot.name ?? 'The Moon')} · ${where}</p><ul class="ground">${bars}</ul>
      <p class="txt">Every plot on the Moon adds up to the same. Yours is strong where the bars are long, and what it lacks another town has.</p>`;
  }

  /** Spare parts: the same goods, used up by the town's own buildings once it is big enough to trade. */
  private partsHtml(y: Yard): string {
    const p = y.parts;
    if (!p) return '';
    const t = (kg: number, dp = 1) => `${num(kg / 1000, dp)} t`;
    if (!p.wear) return y.open ? '' : '<p class="txt">Once the town trades, its buildings will wear and take spare parts from this yard.</p>';
    const need = p.kg_per_hour, lasts = need > 0 ? y.held_kg / need : Infinity, dry = need > 0 && y.held_kg < 1;
    const cost = (need * p.import) / 1000 / y.kcr;
    return `<h3>Spare parts</h3>
      <dl class="budget one"><div><dt>Buildings use</dt><dd>${num(need, 1)} kg an hour</dd></div><div${dry ? ' class="bad"' : ''}><dt>Yard lasts</dt><dd>${dry ? 'empty' : hrs(lasts)}</dd></div><div><dt>Fitted so far</dt><dd>${t(p.used_kg)}</dd></div>${p.bought_kg ? `<div><dt>Bought at the port</dt><dd>${t(p.bought_kg, 0)} · −${num(p.spent / y.kcr)}</dd></div>` : ''}${p.landed_kg >= 1 ? `<div><dt>Landed from Earth</dt><dd>${t(p.landed_kg)}</dd></div>` : ''}</dl>
      <div class="prices"><span>Keep back</span><button type="button" data-yard="keep" aria-pressed="${p.keep_t === null}">${t(p.auto_kg)}</button><button type="button" data-yard="keepnone" aria-pressed="${p.keep_t === 0}">Nothing</button></div>
      <div class="prices"><span>When short</span><button type="button" data-yard="buy" aria-pressed="${p.buy}">Buy at the port</button><button type="button" data-yard="nobuy" aria-pressed="${!p.buy}">Earth only</button></div>
      <p class="txt">${dry ? `The yard is empty, so Earth is landing parts at ${num(p.import / y.kcr)} a tonne: ${num(cost, 2)} credits an hour.` : `Buildings wear out parts, and parts are these goods. What is kept back is a lunar night's worth and is never sold for you. ${p.buy ? `When the yard falls below that the town bids at the port for other towns' goods${p.on_order_kg ? ` (${t(p.on_order_kg, 0)} on order now)` : ''}, a little above the next bidder and never above Earth's price.` : ''} If the yard runs dry Earth lands them at ${num(p.import / y.kcr)} a tonne, twice what the port pays.`}</p>`;
  }

  /** Whatever drawer is open. Only one at a time, and none by default. */
  private drawerBody(s: State, ui: UiState) {
    const box = $('drawer'), id = this.drawer;
    if (!id) { if (!box.hidden) { box.hidden = true; box.innerHTML = ''; } this.drawerKey = ''; return; }
    const f = s.flows, crew = aliveCount(s), pop = population(s);
    const head = (title: string) => `<div class="dh"><h2>${esc(title)}</h2><button type="button" class="x" data-act="close" aria-label="Close">×</button></div>`;
    let html = '';
    if (id === 'demand') {
      const word = (k: 'r' | 'i' | 'v') => { const w = s.want[k], bl = s.block[k]; return w > 0.15 ? (bl ? `blocked: ${bl}` : 'wanted, building') : w < -0.15 ? 'enough' : 'steady'; };
      const bars = ZONES.map(z => {
        const w = s.want[z.key], blocked = w > 0.15 && !!s.block[z.key];
        const fill = w >= 0 ? `left:50%;width:${Math.round(w * 50)}%;background:${z.css}` : `right:50%;width:${Math.round(-w * 50)}%;background:#55526a`;
        return `<li${blocked ? ' class="blocked"' : ''}><b>${esc(z.short)}</b><span class="dbar"><i style="${fill}"></i></span><em>${esc(word(z.key))}</em></li>`;
      }).join('');
      const nd = needs(s);
      html = `${head('Demand')}<h3>What the base wants</h3><ul class="demand">${bars}</ul>
        <h3>What people expect</h3>${nd.length ? `<ul class="needs">${nd.map(q => `<li data-met="${q.met}"><i></i>${esc(q.name)}</li>`).join('')}</ul>` : '<p class="txt">Nothing yet. Past ten people they will start to ask.</p>'}`;
    } else if (id === 'money') {
      const e = f.earn, money = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`;
      const pi = PRICES.indexOf(s.price);
      const y = ui.yard, c = ui.caretaker;
      const care = c ? `<h3>Caretaker</h3><div class="prices"><span>${num(c.fee / c.kcr, 1)} an hour</span><button type="button" data-care="1" aria-pressed="${c.on}">Hired</button><button type="button" data-care="0" aria-pressed="${!c.on}">None</button></div>
        <p class="txt">Looks after the town while you are away: repairs, air, water, food and power for the night. Builds nothing new and signs nothing.${c.paid ? ` Paid ${num(c.paid / c.kcr)} so far.` : ''}</p>` : '';
      html = `${head('Money')}${y ? this.yardHtml(y) : ''}<p class="sub">${num(Math.floor(s.materials))} credits · per hour</p>
        <dl class="budget">${y ? '' : `<div><dt>Foundries</dt><dd>${money(e.foundry)}</dd></div>`}<div><dt>Rent</dt><dd>${money(e.rent)}</dd></div><div><dt>Visitors</dt><dd>${money(e.visitors)}</dd></div><div><dt>Concourses</dt><dd>${money(e.shops)}</dd></div><div><dt>Earth grant</dt><dd>${money(e.grant)}</dd></div><div><dt>Upkeep</dt><dd>${money(-f.upkeep)}</dd></div><div class="net"><dt>Net an hour</dt><dd>${money(f.income)}</dd></div></dl>
        <div class="prices"><span>Prices</span>${['Low', 'Fair', 'High'].map((n, i) => `<button type="button" data-price="${i}" aria-pressed="${i === pi}">${n}</button>`).join('')}</div>
        <p class="txt">${y ? 'Goods sold, rover' : 'Rover'} fares, landing fees, contracts and mission rewards come on top of this.</p>${care}`;
    } else if (id === 'towns') {
      const all = ui.league ?? [];
      const rows = all.map((t, i) => `<li${t.company === ui.company ? ' class="me"' : ''}${t.lost ? ' data-lost="1"' : ''}><b>${i + 1}</b><span>${esc(t.company)}${t.house ? ' <i title="Run by the world, by the same rules as yours">agent</i>' : ''}<small>${t.lost ? 'silent' : `${esc(t.kind || t.tier)}${t.plot?.name ? ` · ${esc(t.plot.name)}` : ''} · day ${t.age_days + 1}`}${t.crews > 1 ? ` · crew ${t.crews}` : ''} · ${num(t.sold_t)} t sold</small></span><em>${t.lost ? '·' : num(t.population)}</em></li>`).join('');
      html = `${head('Towns')}${this.groundHtml(ui.plot)}<h3>Every town</h3><p class="sub">${all.length} on the Moon · by people</p><ol class="league">${rows}</ol>
        <p class="txt">Every town here plays by the same rules and sells into the same market at the Flats. The ones marked agent are run by the world, hour by hour, and never rest.</p>`;
    } else if (id === 'people') {
      const nextTier = TIERS.find(t => t[0] > pop), sh = s.shuttle;
      const pad = s.buildings.find(b => b.type === 'pad' && b.progress >= 1);
      const shuttle = !pad ? 'No landing pad yet' : sh.phase === 'landing' ? 'Shuttle on final descent' : sh.phase === 'landed' ? 'Shuttle on the pad' : sh.phase === 'launching' ? 'Shuttle lifting off'
        : s.nextShuttle > 0 ? `Next shuttle in ${Math.max(0, Math.ceil(s.nextShuttle - s.t))} h${isNight(s.t) ? ', cargo only' : ''}` : 'Waiting for Earth';
      const out = s.rovers.filter(r => r.phase !== 'idle').length;
      const rovers = s.rovers.length ? `${out} of ${s.rovers.length} rovers out · ${s.stats.trips} trips` : 'No rovers yet';
      const raw = rawTiles(s), busy = s.graders.filter(g => g.phase === 'go' || g.phase === 'work').length;
      const graders = raw ? `${busy} of ${s.graders.length} graders working · ${raw} tile${raw > 1 ? 's' : ''} to level` : `${s.graders.length} graders idle`;
      const housed = f.exposed + f.atRisk > 0 ? `${f.exposed + f.atRisk} with no safe bed` : crew + s.residents > f.housing ? `Crew in the lander · canisters ${Math.round(s.canisters)} h` : 'Everyone has a powered bed';
      const rows = s.crew.map((c, i) => {
        const tone = !c.alive ? 'dead' : c.health < 35 ? 'bad' : c.health < 70 ? 'warn' : 'ok';
        return `<li data-tone="${tone}" title="${esc(c.role)}"><span class="face sm" style="background:${FACE[i]}">${esc(initials(c.name))}</span><b>${esc(c.name)}</b><div class="hp"><i style="width:${c.health}%"></i></div><em>${c.alive ? Math.ceil(c.health) : '0'}</em></li>`;
      }).join('');
      html = `${head(tierOf(pop))}<p class="sub">${nextTier ? `${nextTier[1]} at ${nextTier[0]} people` : 'the largest settlement off Earth'}</p>
        <dl class="cstats"><div><dt>Crew</dt><dd>${crew}</dd></div><div><dt>Residents</dt><dd>${s.residents}</dd></div><div><dt>Visitors</dt><dd>${s.tourists}</dd></div><div><dt>Jobs filled</dt><dd>${Math.min(f.workers, f.jobs)} of ${f.jobs}</dd></div></dl>
        <p class="line">${esc(shuttle)}</p><p class="line">${esc(rovers)}</p><p class="line">${esc(graders)}</p><p class="line" data-tone="${f.exposed + f.atRisk > 0 ? 'bad' : 'ok'}">${esc(housed)}</p>
        <ul class="crewlist">${rows}</ul>`;
    } else if (id === 'deals') {
      const o = s.offer, hasPad = s.buildings.some(b => b.type === 'pad' && b.progress >= 1);
      const open = o ? `<h3>On the table</h3><ul class="deals"><li><b>${esc(o.title)}</b><span>${esc(o.from)} · pays ${o.pay} credits</span><em>open for ${Math.max(0, Math.ceil((o.expires - s.t) / 5) * 5)} h</em></li></ul><button type="button" class="dbtn" data-act="read">Read the offer</button>` : '';
      const signed = s.deals.length ? `<h3>Signed</h3><ul class="deals">${s.deals.map(d => {
        const hh = Math.max(0, Math.ceil((d.due - s.t) / 5) * 5);
        return `<li data-tone="${hh < 40 ? 'warn' : 'ok'}"><b>${esc(d.title)}</b><span>${esc(d.need)}</span><em>${hh} h left · pays ${d.pay} · penalty ${d.penalty}</em></li>`;
      }).join('')}</ul>` : '';
      html = `${head('Contracts')}<p class="sub">${s.stats.deals} kept · ${s.stats.broken} broken</p>${open}${signed}${!o && !s.deals.length ? `<p class="txt">${hasPad ? 'Nothing on the table. Nations and companies make an offer every few days of daylight.' : 'Offers start once ships can land. Build a Landing Pad.'}</p>` : ''}`;
    } else if (id === 'log') {
      html = `${head('Log')}<ul class="log">${[...s.alerts].reverse().map(a => `<li data-tone="${a.level}"><time>D${dayNumber(a.t)} ${String(Math.floor(phaseOf(a.t))).padStart(3, '0')}</time><span>${a.who !== undefined ? `${esc(s.crew[a.who].name.split(' ')[0])}: ` : ''}${esc(a.msg)}</span></li>`).join('')}</ul>`;
    } else {
      const i = Number(id.slice(4)), c = s.crew[i], u = urgent(s), m = MISSIONS[s.mission];
      const tone = !c.alive ? 'bad' : c.health < 35 ? 'bad' : c.health < 70 ? 'warn' : 'ok';
      const stamp = (t: number) => `Day ${dayNumber(t)} · hour ${Math.floor(phaseOf(t))}`;
      const msgs: string[] = [];
      if (u && u.who === i) { const lb = this.actLabel(u.tool, u.zone, u.off, u.on, true); msgs.push(`<li class="msg" data-kind="urgent"><span class="mm">Urgent</span><b>${esc(u.title)}</b><p>${esc(u.why)}</p>${lb ? `<button type="button" class="nb" data-act="adv">${esc(lb)}</button>` : ''}</li>`); }
      if (m && m.who === i) { const ok = m.tool ? s.materials >= BUILDINGS[m.tool].cost : true, lb = this.actLabel(m.tool, m.zone, undefined, undefined, ok); msgs.push(`<li class="msg" data-kind="ask"><b>${esc(m.goal)}</b><p class="say">${esc(m.say)}</p>${lb ? `<button type="button" class="nb${ok ? '' : ' wait'}" data-act="mis">${esc(lb)}</button>` : ''}<span class="mm"><em>+${m.reward} credits</em> · mission ${s.mission + 1} of ${MISSIONS.length}</span></li>`); }
      for (const a of [...s.alerts].reverse()) if (a.who === i) msgs.push(`<li class="msg" data-tone="${a.level}"><p>${esc(a.msg)}</p><time>${stamp(a.t)}</time></li>`);
      const done = MISSIONS.slice(0, s.mission).map((q, k) => ({ q, k })).filter(x => x.q.who === i).slice(-3).reverse();
      for (const d of done) msgs.push(`<li class="msg" data-kind="done">✓ ${esc(d.q.goal)}</li>`);
      html = `${head(c.name)}<p class="sub">${esc(c.role)} · health ${c.alive ? Math.ceil(c.health) : 0}</p><div class="hp" data-tone="${tone}"><i style="width:${c.health}%"></i></div>
        <h3 style="margin-top:12px">Report</h3><p class="txt">${esc(c.alive ? this.report(s, i) : 'Lost.')}</p>
        <h3>Messages</h3>${msgs.length ? `<ul class="thread">${msgs.join('')}</ul>` : '<p class="txt">Nothing from me right now, Commander.</p>'}`;
    }
    if (html === this.drawerKey) return;
    const now = performance.now();
    // What the drawer is made of (which messages, which offers, which reasons) redraws at once. Numbers ticking over wait a few seconds,
    // so a button is never swapped out from under the pointer.
    const u2 = urgent(s), m2 = MISSIONS[s.mission], ci = id.startsWith('crew') ? Number(id.slice(4)) : -1;
    const struct = ci >= 0 ? `${u2 && u2.who === ci ? u2.title : ''}|${m2 && m2.who === ci ? `${s.mission}:${m2.tool ? s.materials >= BUILDINGS[m2.tool].cost : ''}` : ''}|${s.alerts.filter(a => a.who === ci).length}`
      : id === 'towns' ? `${(ui.league ?? []).map(t => t.company).join()}|${ui.plot?.name}`
      : id === 'money' ? `${s.price}|${ui.yard ? [Math.floor(ui.yard.held_kg / 10), Math.round(ui.yard.make_kg_per_hour), ui.yard.bid, ui.yard.sell, ui.yard.open, ui.yard.sold_kg, ui.yard.ship.here, ui.yard.full, ui.yard.parts?.wear, ui.yard.parts?.keep_t, ui.yard.parts?.buy, ui.yard.parts?.bought_kg, ui.yard.parts?.on_order_kg, Math.round(ui.yard.parts?.kg_per_hour ?? 0)].join() : ''}|${ui.caretaker ? `${ui.caretaker.on}${Math.floor(ui.caretaker.paid / 1000)}` : ''}` : id === 'deals' ? `${s.offer?.title}|${s.deals.length}` : id === 'demand' ? ZONES.map(z => s.block[z.key]).join() : id === 'log' ? `${this.lastAlert}` : '';
    if (this.drawerKey !== '?' && (this.pressing || (struct === this.drawerStruct && now - this.drawerAt < 3000))) return;
    this.drawerKey = html; this.drawerAt = now; this.drawerStruct = struct;
    const top = box.scrollTop;
    box.innerHTML = html; box.hidden = false; box.scrollTop = top;
  }

  private inspector(s: State, ui: UiState) {
    const el = $('inspector');
    let html = '', key = '';
    const codex = (t: BuildingType) => `<a class="codex" href="https://lunarark.com/" target="_blank" rel="noopener">Codex · ${esc(BUILDINGS[t].cluster)} · ${BUILDINGS[t].codex}</a>`;
    const more = (inner: string) => `<details class="more"${this.more ? ' open' : ''}><summary>More</summary>${inner}</details>`;
    const zt = zoneOf(ui.tool);
    if (zt === 0) {
      key = 'zone0';
      html = `<p class="eyebrow">Zoning</p><h2>Unzone</h2><p>Drag across zoned land to clear it. Land with a building on it has to be demolished first.</p><div class="acts"><button type="button" data-act="cancel" data-uid="0">Stop <kbd>Esc</kbd></button></div>`;
    } else if (zt > 0) {
      const z = ZONES[zt - 1];
      const w = s.want[z.key], bl = s.block[z.key];
      key = `zone${zt}:${w > 0.15}:${bl}:${this.more}`;
      html = `<p class="eyebrow">Zoning</p><h2>${esc(z.name)}</h2><p class="state" data-tone="${w > 0.15 ? (bl ? 'warn' : 'ok') : 'dim'}">${w > 0.15 ? (bl ? `Wanted, but blocked: ${esc(bl)}` : 'Wanted right now') : 'No demand right now'}</p>
        <p class="effect">${esc(z.grows)} · ${ZONE_COST} credits a tile</p><p>Drag to paint blocks of two tiles by two.</p>
        ${more(`<p>${esc(z.desc)}</p><p>A block has to touch the base, other zoned land or a conduit. Graders level the ground first: 2 hours a tile on smooth ground, up to 6 where it is rough.</p>`)}
        <div class="acts"><button type="button" data-act="cancel" data-uid="0">Stop zoning <kbd>Esc</kbd></button></div>`;
    } else if (ui.tool) {
      const d = BUILDINGS[ui.tool as BuildingType];
      key = `tool:${ui.tool}:${s.materials >= d.cost}:${this.more}`;
      html = `<p class="eyebrow">Placing</p><h2>${esc(d.name)}</h2><p class="effect">${esc(d.effect)}</p>
        <dl><div><dt>Cost</dt><dd>${d.cost} cr</dd></div><div><dt>Upkeep</dt><dd>${d.upkeep}/h</dd></div><div><dt>Build</dt><dd>${d.buildHours} h</dd></div><div><dt>Size</dt><dd>${d.w} × ${d.h}</dd></div></dl>
        ${more(`<p>${esc(d.desc)}</p>${codex(ui.tool as BuildingType)}`)}<div class="acts"><button type="button" data-act="cancel" data-uid="0">Stop placing <kbd>Esc</kbd></button></div>`;
    } else if (ui.selected !== null) {
      const b = s.buildings.find(q => q.uid === ui.selected);
      if (b) {
        const d = BUILDINGS[b.type], st = stateLine(b);
        const night = isNight(s.t), draw = drawOf(b, night);
        const hab = Math.round(habAt(s, b.x, b.y, d.w, d.h)), beds = bedsOf(b), jobs = jobsOf(b);
        const acts: string[] = [];
        if (d.toggle && b.progress >= 1) acts.push(`<button type="button" data-act="toggle" data-uid="${b.uid}">${b.on ? 'Switch off' : 'Switch on'}</button>`);
        if (b.damaged && b.repair === 0) acts.push(`<button type="button" class="primary" data-act="repair" data-uid="${b.uid}">Repair · ${repairCost(b)} credits</button>`);
        if (b.type !== 'lander') acts.push(`<button type="button" class="danger" data-act="demolish" data-uid="${b.uid}">Demolish · refund ${b.progress < 1 ? d.cost : Math.floor(d.cost / 2)}</button>`);
        let now = '', read = '';   // `now` is live status worth seeing at once; `read` waits behind More
        if (b.type === 'pad') read = `<p>Flights so far: ${s.stats.flights}. A shuttle comes every ${SHUTTLE_EVERY} hours while the pad has power.</p>`;
        if (b.type === 'garage') { const mine = s.rovers.filter(r => r.bay === b.uid); now = `<p>${mine.map(r => r.phase === 'idle' ? 'In the bay' : `${r.phase === 'back' ? 'Returning from' : 'Out to'} ${esc(s.pois[r.poi].name)}${r.pax ? ` with ${r.pax} visitor${r.pax > 1 ? 's' : ''}` : ', survey run'}`).join('. ')}.</p>`; }
        if (b.type === 'printer') { const o = s.ore[b.y * s.size + b.x] || s.ore[(b.y + 1) * s.size + b.x + 1], r = richOf(s, b); if (r > 0 && o) now = `<p class="effect">On ${esc(ORES[o - 1].name.toLowerCase())}: ${s.cargo ? 'makes' : 'earns'} ${Math.round(r * 100)}% more.</p>`; else read = `<p>Plain regolith. A foundry on a survey find ${s.cargo ? 'makes' : 'earns'} more.</p>`;
          if (s.cargo) { now += `<p class="effect">${s.cargo.room <= 0 ? 'Standing idle: the yard is full.' : `Makes ${FOUNDRY_KG} kg of goods an hour a level into the yard, when fully staffed.`}</p>`; } }
        if (dusty(s, b)) now = '<p class="effect">Coated in dust from a hard landing: half power until it is swept off.</p>';
        key = `b:${b.uid}:${st.text}:${night}:${b.on}:${b.level}:${hab}:${b.asleep}:${Math.floor(s.materials) >= repairCost(b)}:${now}:${this.more}`;
        html = `<button type="button" class="x" data-act="close" data-uid="0" aria-label="Close">×</button><p class="eyebrow">${esc(d.cluster)}</p><h2>${esc(d.name)}${d.zone && b.type !== 'greenhouse' ? ` · level ${b.level}` : ''}</h2><p class="state" data-tone="${b.asleep ? 'dim' : st.tone}">${esc(b.asleep ? 'Resting to save the batteries' : st.text)}</p>
          ${now}<dl>${draw ? `<div><dt>Draw now</dt><dd>${draw} kW</dd></div>` : ''}${d.gen ? `<div><dt>Output</dt><dd>${d.solar ? 'follows the Sun' : d.gen + ' kW'}</dd></div>` : ''}${beds ? `<div><dt>Beds</dt><dd>${beds}</dd></div>` : ''}${jobs ? `<div><dt>Jobs</dt><dd>${jobs}</dd></div>` : ''}<div><dt>Habitability</dt><dd>${hab}</dd></div></dl>
          ${more(`<p class="effect">${esc(b.type === 'printer' && s.cargo ? `${FOUNDRY_KG} kg of goods an hour per level when fully staffed · 3 jobs per level` : d.effect)}</p><p>${esc(b.type === 'printer' && s.cargo ? 'Sinters moon dust into parts and fittings. They go to the yard and are sold at the port by the tonne. Contractors build these on land you zone for Industry. They need workers, and they are dusty neighbours.' : d.desc)}</p>${read}${codex(b.type)}`)}<div class="acts">${acts.join('')}</div>`;
      }
    }
    if (key === this.inspKey || (this.pressing && !!html && this.inspKey !== '?')) return;
    this.inspKey = key;
    el.innerHTML = html;
    el.classList.toggle('show', !!html);
  }

  private alerts(s: State) {
    const box = $('alerts');
    for (const a of s.alerts) {
      if (a.id <= this.lastAlert) continue;
      this.lastAlert = a.id;
      const el = document.createElement('div');
      el.className = 'toast'; el.dataset.tone = a.level;
      el.textContent = a.who !== undefined ? `${s.crew[a.who].name.split(' ')[0]}: ${a.msg}` : a.msg;
      box.appendChild(el);
      while (box.children.length > 2) box.firstElementChild!.remove();
      window.setTimeout(() => { el.classList.add('out'); window.setTimeout(() => el.remove(), 500); }, a.level === 'bad' ? 9000 : 5000);
    }
  }
  resetAlerts(s: State, fresh = false) {
    $('alerts').innerHTML = '';
    this.lastAlert = fresh || !s.alerts.length ? 0 : s.alerts[s.alerts.length - 1].id;
    this.seenAlert = this.lastAlert; this.seenBy = [this.lastAlert, this.lastAlert, this.lastAlert, this.lastAlert];
    this.seenMis = -1; this.seenUrg = ''; this.lastMis = -2; this.lastUrg = ''; this.lastOffer = ''; this.hideBubble(); this.moonKey = -1;
    this.drawer = null; this.pop = null; this.cat = null; this.showPop(); this.showTray();
    this.inspKey = '?'; this.drawerKey = '?'; this.advKey = '?'; this.misKey = '?'; this.offerKey = '?'; this.railKey = '?';
  }

  /** The offer on the table, with one advisor for it and one against. The clock is stopped while it is open. */
  offerDialog(s: State) {
    const o = s.offer, m = $('modal');
    if (!o) return;
    const voice = (v: { who: number; say: string }, side: string) => `<div class="voice" data-side="${side}"><span class="face" style="background:${FACE[v.who]}">${esc(initials(s.crew[v.who].name))}</span><div><b>${esc(s.crew[v.who].name)} · ${side === 'pro' ? 'for' : 'against'}</b><p>${esc(v.say)}</p></div></div>`;
    m.innerHTML = `<div class="card offercard">
      <p class="eyebrow">Offer from ${esc(o.from)}</p>
      <h2>${esc(o.title)}</h2>
      <p class="lede">${esc(o.text)}</p>
      <dl class="terms"><div><dt>They need</dt><dd>${esc(o.need)}</dd></div><div><dt>Within</dt><dd>${o.hours} hours of signing</dd></div><div><dt>Pays</dt><dd>${o.pay} credits</dd></div><div><dt>If we fail</dt><dd>${o.penalty} credits penalty</dd></div></dl>
      ${voice(o.pro, 'pro')}${voice(o.con, 'con')}
      <div class="acts"><button type="button" class="primary" id="o-yes">Sign</button><button type="button" id="o-no">Decline</button><button type="button" id="o-later">Decide later</button></div>
    </div>`;
    m.classList.add('show');
    const close = (fn?: () => void) => () => { m.classList.remove('show'); fn?.(); this.offerKey = '?'; this.h.resume(); };
    $('o-yes').addEventListener('click', close(() => this.h.offer(true)));
    $('o-no').addEventListener('click', close(() => this.h.offer(false)));
    $('o-later').addEventListener('click', close());
  }

  // ----- dialogs -----
  /** The opening briefing. With inGame set it is the same card reopened as help, with one button to go back. */
  briefing(saved: State | null, inGame = false) {
    const m = $('modal');
    const resume = !inGame && saved && saved.phase === 'playing' && saved.t > 1;
    const acts = inGame ? `<button type="button" class="primary" id="m-back">Back to the base</button><button type="button" id="m-new">Start over</button>`
      : resume ? `<button type="button" class="primary" id="m-resume">Continue: lunar day ${dayNumber(saved!.t)}, ${population(saved!)} people</button><button type="button" id="m-new">New landing</button>`
      : `<button type="button" class="primary" id="m-new">Begin</button>`;
    m.innerHTML = `<div class="card">
      <p class="eyebrow">Lunar Ark · Mare Tranquillitatis</p>
      <h1>Tranquility</h1>
      <p class="lede"><b>Plan a town on the Moon.</b> You land with four crew and one lander, a short drive from where Apollo 11 touched down. You build the base and zone the land around it. If the conditions are right, people and companies come and build on it themselves.</p>
      <ol class="brief">
        <li><b>You build the base.</b> Power, the first habitat, oxygen, water, greenhouses, the landing pad, rovers. Pick a category at the bottom, then a building, then click the ground.</li>
        <li><b>You zone, they build.</b> Paint land for Habitat, Industry and Commercial. Your graders drive out and level it, then settlers, companies and traders build there at their own cost when the base wants it. The Demand meter on the left rail shows what is wanted and what stands in the way.</li>
        <li><b>Where you put things matters.</b> Dust, noise and reactors drive people away. Gardens, clinics and crater views draw them in. Press <kbd>H</kbd> for the habitability map. Your rovers find ore, and a foundry standing on it earns far more.</li>
        <li><b>A growing town asks for more.</b> Past ten people they expect a garden, then a concourse, then a clinic, and each person costs more to supply. Once ships land, nations and companies bring contracts. Your crew will argue both sides.</li>
        <li><b>Things go wrong.</b> After the first sunrise expect solar storms, breaches, late shuttles and dust. Spare beds, reserves and a little money in hand are what get you through.</li>
        <li><b>The night is the limit.</b> Solar gives nothing all night, and across most of the Moon the night is 354 hours. Nobody builds what cannot be kept warm, so storage decides how far the town can grow.</li>
      </ol>
      <p class="keys">A green badge on a crew face means a message, as in a chat app. Click the face to read it and for a report. Each request pays credits · click any number at the top for its detail · everything must touch the base, zoned land or a conduit · the clock starts with your first move · <kbd>Space</kbd> pauses · 4× and 8× speed up time · drag to move the map · scroll to zoom · <kbd>?</kbd> reopens this page</p>
      <div class="acts">${acts}</div>
    </div>`;
    m.classList.add('show');
    $('m-new').addEventListener('click', () => { m.classList.remove('show'); this.h.start(false); });
    if (resume) $('m-resume').addEventListener('click', () => { m.classList.remove('show'); this.h.start(true); });
    if (inGame) $('m-back').addEventListener('click', () => { m.classList.remove('show'); this.h.resume(); });
  }

  ending(s: State) {
    const m = $('modal'), f = s.flows;
    const why = f.lackO2 ? 'The oxygen ran out.'
      : isNight(s.t) ? 'The habitat went cold. Storage ran dry before sunrise, and the lander had no canisters left.'
      : f.lackWater ? 'The water ran out.' : 'The lander ran out of CO2 canisters, and there was no powered habitat to move into.';
    m.innerHTML = `<div class="card">
      <p class="eyebrow">Lunar day ${dayNumber(s.t)} · hour ${Math.floor(phaseOf(s.t))}</p>
      <h1>Silence</h1>
      <p class="lede">${esc(why)} All four of the founding crew are gone, and Earth has closed the base.</p>
      <dl class="stats"><div><dt>Most people</dt><dd>${s.stats.peakPop}</dd></div><div><dt>Shuttles</dt><dd>${s.stats.flights}</dd></div><div><dt>Rover trips</dt><dd>${s.stats.trips}</dd></div><div><dt>Credits earned</dt><dd>${num(s.stats.earned)}</dd></div></dl>
      <div class="acts"><button type="button" class="primary" id="m-new">Land again</button></div>
    </div>`;
    m.classList.add('show');
    $('m-new').addEventListener('click', () => { m.classList.remove('show'); this.h.start(false); });
  }
}
