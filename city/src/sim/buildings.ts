// Building catalogue. Pure data: the simulation reads numbers from here, the
// view reads colours and shapes from its own table keyed by the same ids.
// `codex` points at the Lunar Ark Codex system each building belongs to.
// These are system-level references (L1) and are provisional until each
// building is mapped to its exact Codex component.

export type BuildingType =
  | 'lander' | 'conduit' | 'solar' | 'battery' | 'reactor' | 'habitat'
  | 'o2plant' | 'recycler' | 'o2tank' | 'watertank' | 'printer'
  | 'greenhouse' | 'pad' | 'lodge' | 'garage' | 'garden' | 'clinic' | 'market'
  // Mars only (root docs/DECISIONS.md D94)
  | 'drill' | 'wind' | 'sabatier';

/** The worlds a town can stand on. The rules are one set; a world is the numbers they run on. */
export type WorldId = 'moon' | 'mars';

export interface BuildingDef {
  id: BuildingType;
  name: string;
  short: string;          // two-letter label for grey-box art
  cluster: string;        // Codex cluster name
  codex: string;          // Codex L1 system code (provisional)
  w: number; h: number;   // footprint in tiles
  cost: number;           // credits
  buildHours: number;
  gen: number;            // kW produced (peak, for solar)
  solar: boolean;
  drawDay: number;        // kW consumed in daylight
  drawNight: number;      // kW consumed at night
  priority: number;       // lower number keeps power longer in a shortfall
  battery: number;        // kWh of storage
  o2Store: number;        // kg
  waterStore: number;     // kg
  housing: number;        // crew
  toggle: boolean;        // can the player switch it off
  buildable: boolean;
  desc: string;
  effect: string;
  jobs: number;           // workers needed to run at full output
  upkeep: number;         // credits per hour
  zone: number;           // 0 = placed by hand, otherwise the zone it grows in
  hidden: boolean;        // not part of the world the town stands on
}

const def = (d: Partial<BuildingDef> & Pick<BuildingDef, 'id' | 'name' | 'short' | 'cluster' | 'codex' | 'desc' | 'effect'>): BuildingDef => ({
  w: 1, h: 1, cost: 0, buildHours: 1, gen: 0, solar: false, drawDay: 0, drawNight: 0,
  priority: 9, battery: 0, o2Store: 0, waterStore: 0, housing: 0, toggle: false, buildable: true, jobs: 0, upkeep: 0, zone: 0, hidden: false, ...d,
});

export const BUILDINGS: Record<BuildingType, BuildingDef> = {
  lander: def({
    id: 'lander', name: 'Lander', short: 'LD', cluster: 'Thermal & Habitat', codex: 'L1-HAB',
    w: 2, h: 2, gen: 1.5, drawDay: 1, drawNight: 1, priority: 0, battery: 40, o2Store: 60, waterStore: 250,
    buildable: false,
    desc: 'Your ship and first shelter. A small radioisotope generator keeps its own life support running, but its CO2 canisters are finite.',
    effect: '1.5 kW always · 40 kWh · shelter while canisters last',
  }),
  conduit: def({
    id: 'conduit', name: 'Conduit', short: '', cluster: 'Power Systems', codex: 'L1-PDM',
    cost: 1, buildHours: 0.25,
    desc: 'Carries power, air and water. Anything not linked back to the lander does nothing.',
    effect: 'Links buildings into one network',
  }),
  solar: def({
    id: 'solar', name: 'Solar Array', short: 'SA', cluster: 'Power Systems', codex: 'L1-PWR',
    upkeep: 0.01,
    w: 2, h: 2, cost: 12, buildHours: 1.5, gen: 12, solar: true,
    desc: 'Cheap power that follows the Sun. Output peaks at lunar noon and is zero for the whole night.',
    effect: 'Up to 12 kW by day · 0 kW at night',
  }),
  battery: def({
    id: 'battery', name: 'Battery Bank', short: 'BT', cluster: 'Power Systems', codex: 'L1-ESS',
    upkeep: 0.005,
    cost: 22, buildHours: 1.5, battery: 500,
    desc: 'Stores daytime surplus. The night is long, so count carefully.',
    effect: 'Stores 500 kWh',
  }),
  reactor: def({
    id: 'reactor', name: 'Fission Reactor', short: 'FR', cluster: 'Power Systems', codex: 'L1-PWR',
    upkeep: 0.2, jobs: 1,
    w: 2, h: 2, cost: 180, buildHours: 10, gen: 10,
    desc: 'Steady power that ignores the Sun. Expensive, slow to build, and it must stand well away from living quarters.',
    effect: '10 kW day and night · 6 tiles from crew',
  }),
  habitat: def({
    id: 'habitat', name: 'Habitat Module', short: 'HB', cluster: 'Thermal & Habitat', codex: 'L1-HAB',
    upkeep: 0.02, zone: 1,
    w: 2, h: 2, cost: 30, buildHours: 5, drawDay: 2, drawNight: 3, priority: 1, housing: 4,
    desc: 'Pressurised quarters. Build the first ones yourself. After that, zone land for Habitat and settlers build their own, and expand them when the neighbourhood is good.',
    effect: 'Beds for 4 people per level · 2 kW day · 3 kW night',
  }),
  o2plant: def({
    id: 'o2plant', name: 'Oxygen Plant', short: 'OX', cluster: 'Resource Systems', codex: 'L1-ISR',
    upkeep: 0.05, jobs: 1,
    w: 2, h: 2, cost: 35, buildHours: 4, drawDay: 8, drawNight: 8, priority: 4, toggle: true,
    desc: 'Cooks oxygen out of mare regolith. Power hungry, so run it by day and live off the tank at night.',
    effect: '+1 kg O2 per hour by day · 8 kW · breath for 13 people',
  }),
  recycler: def({
    id: 'recycler', name: 'Water Recycler', short: 'WR', cluster: 'Resource Systems', codex: 'L1-WTR',
    upkeep: 0.02,
    cost: 20, buildHours: 2.5, drawDay: 1.5, drawNight: 1.5, priority: 2, toggle: true,
    desc: 'There is no water in the mare. Every litre came from Earth, and this recovers most of what the crew uses.',
    effect: 'Cuts water use by 85% · 1.5 kW',
  }),
  o2tank: def({
    id: 'o2tank', name: 'Oxygen Tank', short: 'O2', cluster: 'Resource Systems', codex: 'L1-ISR',
    upkeep: 0.005,
    cost: 12, buildHours: 1.25, o2Store: 240,
    desc: 'Extra oxygen storage so the plant can rest through the night.',
    effect: 'Stores 240 kg O2 · a night of breath for 15 people',
  }),
  watertank: def({
    id: 'watertank', name: 'Water Tank', short: 'H2', cluster: 'Resource Systems', codex: 'L1-WTR',
    upkeep: 0.005,
    cost: 12, buildHours: 1.25, waterStore: 300,
    desc: 'Extra water storage for what the shuttles bring.',
    effect: 'Stores 300 kg water',
  }),
  printer: def({
    id: 'printer', name: 'Regolith Foundry', short: 'RF', cluster: 'Operational Support', codex: 'L1-MFG',
    upkeep: 0.03, jobs: 3, zone: 2, buildable: false,
    w: 2, h: 2, cost: 0, buildHours: 3.5, drawDay: 6, drawNight: 6, priority: 6, toggle: true,
    desc: 'Sinters moon dust into parts that Earth pays for. Contractors build these on land you zone for Industry. They need workers, and they are dusty neighbours.',
    effect: '+0.6 credits per hour per level when fully staffed · 3 jobs per level',
  }),
  greenhouse: def({
    id: 'greenhouse', name: 'Greenhouse', short: 'GH', cluster: 'Thermal & Habitat', codex: 'L1-HAB',
    upkeep: 0.03, jobs: 1,
    w: 2, h: 2, cost: 30, buildHours: 6, drawDay: 2, drawNight: 6, priority: 5, toggle: true,
    desc: 'Fresh food and a little oxygen. The shuttle feeds about nine people. Past that, the base eats what you grow.',
    effect: '+0.6 kg food per hour by day · feeds about 9 people · 1 job',
  }),
  pad: def({
    id: 'pad', name: 'Landing Pad', short: 'LP', cluster: 'Comms & Navigation', codex: 'L1-NAV',
    upkeep: 0.1, jobs: 1,
    w: 3, h: 3, cost: 30, buildHours: 4.5, drawDay: 0.5, drawNight: 0.5, priority: 2,
    desc: 'A sintered pad with a beacon. A shuttle from Earth lands every 60 hours with water and food. By day it also brings residents and visitors. It is the dustiest, loudest thing on the base, so keep homes away from it.',
    effect: 'Shuttle every 60 hours',
  }),
  lodge: def({
    id: 'lodge', name: 'Visitor Lodge', short: 'VL', cluster: 'Thermal & Habitat', codex: 'L1-HAB',
    upkeep: 0.06, jobs: 2, zone: 3, buildable: false,
    w: 2, h: 2, cost: 0, buildHours: 6, drawDay: 3, drawNight: 4, priority: 2,
    desc: 'Tourists pay to sleep under an Earth that never sets. Operators build lodges on Commercial land when there is something to see, and they pay more for a good spot: quiet, green, with a crater view.',
    effect: '6 visitors per level · income rises with habitability',
  }),
  garage: def({
    id: 'garage', name: 'Rover Bay', short: 'RB', cluster: 'Autonomous Intelligence', codex: 'L1-ROB',
    upkeep: 0.08, jobs: 2,
    w: 2, h: 2, cost: 45, buildHours: 4, drawDay: 2, drawNight: 2, priority: 6, toggle: true,
    desc: 'Two pressurised rovers. With visitors on base they run paid excursions to the craters and to Tranquility Base. With none, the geologist takes them on survey runs for a small science grant.',
    effect: '2 rovers · excursions pay 5 credits per visitor, double at Tranquility Base · 2 jobs'
  }),
  garden: def({
    id: 'garden', name: 'Garden Dome', short: 'GD', cluster: 'Thermal & Habitat', codex: 'L1-HAB',
    upkeep: 0.05, w: 2, h: 2, cost: 70, buildHours: 5, drawDay: 1, drawNight: 1, priority: 2,
    desc: 'Trees, water and Earth overhead. Nothing raises habitability more. Habitats nearby expand, lodges nearby charge more, and visitors come for it.',
    effect: 'Raises habitability for 6 tiles around · draws visitors',
  }),
  clinic: def({
    id: 'clinic', name: 'Clinic', short: 'CL', cluster: 'Thermal & Habitat', codex: 'L1-HAB',
    upkeep: 0.1, jobs: 2, w: 2, h: 2, cost: 100, buildHours: 6, drawDay: 1.5, drawNight: 1.5, priority: 2,
    desc: 'A surgery, a pharmacy and a quiet ward. People settle more readily where there is one, and the crew recovers faster.',
    effect: 'Raises habitability for 7 tiles around · 2 jobs',
  }),
  market: def({
    id: 'market', name: 'Concourse', short: 'CC', cluster: 'Operational Support', codex: 'L1-SSM',
    upkeep: 0.04, jobs: 2, zone: 3, buildable: false,
    w: 2, h: 2, cost: 0, buildHours: 4.5, drawDay: 2, drawNight: 2, priority: 5,
    desc: 'A canteen, a market, a workshop, a bar. Traders open one on Commercial land once enough people live here to keep it busy. Residents spend their wages in it, and it makes the streets around it better to live on.',
    effect: 'Serves 16 residents per level · raises habitability nearby · 2 jobs per level',
  }),
  // ----- Mars only. Hidden on the Moon, so a Moon town is exactly what it was. -----
  drill: def({
    id: 'drill', name: 'Ice Drill', short: 'ID', cluster: 'Resource Systems', codex: 'L1-WTR', hidden: true,
    upkeep: 0.04, jobs: 1,
    w: 2, h: 2, cost: 35, buildHours: 4, drawDay: 5, drawNight: 5, priority: 4, toggle: true,
    desc: 'A heated drill into the glacier under Arcadia. No ship brings water to Mars: what the town drinks, grows with and turns into propellant comes out of this.',
    effect: '+0.5 kg water per hour by day, more on icy ground · 5 kW · 1 job',
  }),
  wind: def({
    id: 'wind', name: 'Wind Turbine', short: 'WT', cluster: 'Power Systems', codex: 'L1-PWR', hidden: true,
    upkeep: 0.02,
    cost: 25, buildHours: 2, gen: 1.5,
    desc: 'The air is thin, so it gives little. But it gives it at night and in a dust storm, when the arrays do not.',
    effect: '1.5 kW day and night, dust or not',
  }),
  sabatier: def({
    id: 'sabatier', name: 'Sabatier Plant', short: 'SP', cluster: 'Resource Systems', codex: 'L1-ISR', hidden: true,
    upkeep: 0.06, jobs: 2,
    w: 2, h: 2, cost: 90, buildHours: 6, drawDay: 8, drawNight: 8, priority: 6, toggle: true,
    desc: 'Makes methane and oxygen propellant out of the Martian air and water from the drills. Propellant is what every ship in the system burns.',
    effect: '+0.9 credits per hour by day when staffed · uses 0.2 kg water per hour · 8 kW · 2 jobs',
  }),
};

/**
 * What is different about a building on Mars: its name and words, and the few numbers the planet changes.
 * Everything not named here is the same building as on the Moon, at the same cost.
 * Sunlight at Mars is 43% of what it is at the Moon, so an array gives 5 kW where it gave 12. That makes a
 * town of arrays a very large field of them, which is why the reactor here is a pair and cheaper: over a sol
 * it gives what a dozen arrays do, for about what they cost, and it is what a Mars base would really run on.
 * Its price and power are invented; D94.
 */
const MARS: Partial<Record<BuildingType, Partial<BuildingDef>>> = {
  lander: { name: 'Arcadia Command', desc: 'The landed ship and first shelter, with the airlock everything else joins to. A small radioisotope generator keeps its own life support running, but its CO2 canisters are finite.' },
  conduit: { desc: 'Carries power, air and water. Anything not linked back to the command module does nothing.' },
  solar: { gen: 5, desc: 'Cheap power that follows the Sun. The Sun is weak here and sets every twelve hours, and a dust storm takes three quarters of what is left.', effect: 'Up to 5 kW by day · 0 kW at night · a quarter of that in a dust storm' },
  battery: { name: 'Megapack Battery', desc: 'Stores daytime surplus. A night here is short. A dust storm is not, and this is what carries the town through one.' },
  reactor: { name: 'Twin Kilopower', cost: 150, gen: 20, desc: 'Two small fission reactors. Steady power that ignores the Sun and the dust: one does the work of a dozen arrays over a sol, with no battery behind it. Slow to build, and it must stand well away from living quarters.', effect: '20 kW day and night, dust or not · 6 tiles from crew' },
  habitat: { desc: 'Pressurised quarters. Build the first ones yourself. After that, zone land for Habitat and settlers build their own, and expand them when the neighbourhood is good.' },
  o2plant: { name: 'MOXIE Plant', desc: 'Splits oxygen out of the carbon dioxide air. Power hungry, so run it by day and live off the tank at night.' },
  recycler: { name: 'Water Scrubber', desc: 'Washes the perchlorate out and recovers most of what the crew uses. Without it the drills cannot keep up.' },
  o2tank: { name: 'Oxygen Tank', desc: 'Extra oxygen storage so the plant can rest through the night.', effect: 'Stores 240 kg O2' },
  watertank: { name: 'Water Tank', desc: 'Extra water storage for what the drills bring up.' },
  printer: { name: 'Basalt Printer', desc: 'Sinters Martian basalt into parts. Contractors build these on land you zone for Industry. They need workers, and they are dusty neighbours.' },
  greenhouse: { name: 'Bio-Dome', desc: 'Food, a little oxygen, and the only green for a hundred million kilometres. No ship brings food to Mars, so the town eats what it grows, and people want to live beside one.',
    effect: '+0.6 kg food per hour by day · feeds about 9 people · raises habitability nearby · 1 job' },
  pad: { desc: 'A sintered pad with a beacon. Transports come half as often as a shuttle does to the Moon and carry twice as many: up to eight settlers at a time, and nothing to eat or drink. It is the dustiest, loudest thing in the town, so keep homes away from it.', effect: 'Transport every 120 hours' },
  lodge: { name: 'Areology Lab', desc: 'Scientists on rotation pay to work here. Institutes build labs on Commercial land when there is something to study, and they pay more for a good spot: quiet, green, near a crater.', effect: '6 visiting scientists per level · income rises with habitability' },
  garage: { desc: 'Two pressurised rovers. With visiting scientists in town they run paid field trips to the craters. With none, the geologist takes them on survey runs for a small science grant, and they sweep the arrays after a storm.', effect: '2 rovers · field trips pay 5 credits per scientist · sweeps dust off arrays · 2 jobs' },
  clinic: { name: 'Med-Bay', desc: 'A surgery, a pharmacy and a storm shelter. People settle more readily where there is one, and the crew recovers faster.' },
  market: { name: 'Commons', desc: 'A canteen, a market, a workshop, a bar. Traders open one on Commercial land once enough people live here to keep it busy. Residents spend their wages in it, and it makes the streets around it better to live on.' },
  garden: { hidden: true },
  drill: { hidden: false }, wind: { hidden: false }, sabatier: { hidden: false },
};
const MOON: Record<string, BuildingDef> = Object.fromEntries(Object.entries(BUILDINGS).map(([k, d]) => [k, { ...d }]));
let current: WorldId = 'moon';
/**
 * Make the catalogue the one for this world. The rules read one catalogue and work on one town at a
 * time, so the world is set at the top of every way into them (sim.ground) and nothing else has to know.
 */
export function useWorld(id: WorldId): void {
  if (id === current) return;
  current = id;
  for (const k of Object.keys(BUILDINGS) as BuildingType[]) Object.assign(BUILDINGS[k], MOON[k], id === 'mars' ? MARS[k] : undefined);
}

export const BUILD_MENU: BuildingType[] = [
  'conduit', 'solar', 'battery', 'habitat', 'o2plant', 'recycler', 'greenhouse', 'pad', 'garage', 'garden', 'clinic', 'o2tank', 'watertank', 'reactor',
  'drill', 'wind', 'sabatier',
];

// Zones. The player marks land; settlers, companies and traders build on it when conditions are right.
export const ZONE = { none: 0, habitat: 1, industry: 2, commercial: 3 } as const;
export const ZONE_BUILDS: Record<number, BuildingType> = { 1: 'habitat', 2: 'printer', 3: 'lodge' };
export const ZONE_COST = 4;
export interface ZoneDef { z: number; key: 'r' | 'i' | 'v'; name: string; short: string; grows: string; color: number; css: string; desc: string; }
export const ZONES: ZoneDef[] = [
  { z: 1, key: 'r', name: 'Habitat', short: 'Habitat', grows: 'Habitat Modules', color: 0x62d394, css: '#62d394', desc: 'Settlers build Habitat Modules here when there are jobs to come for and the base can keep them alive. They take the most habitable lots first, and expand where life is good.' },
  { z: 2, key: 'i', name: 'Industry', short: 'Industry', grows: 'Regolith Foundries', color: 0xd99a4e, css: '#d99a4e', desc: 'Companies build Regolith Foundries here when there are workers to hire and power to run on. They pay well and they are dusty neighbours.' },
  { z: 3, key: 'v', name: 'Commercial', short: 'Commercial', grows: 'Visitor Lodges and Concourses', color: 0x86b6ff, css: '#86b6ff', desc: 'Operators build Visitor Lodges here when there is something to see, and traders open Concourses once enough people live nearby. Both want pleasant ground.' },
];
