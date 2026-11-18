// Urgent advice. Missions say what to do next; this says what needs attention right now,
// in the voice of the crew member whose job it is. Rules are checked in order; the first that applies wins.
// It returns null when nothing is urgent.

import { BUILDINGS, BuildingType, ZONE_COST } from '../sim/buildings';
import { MISSIONS } from '../sim/missions';
import { State, darkHours, carryHours, ESSENTIAL, POWER_MARGIN, drawOf, hoursToSunrise, hoursToSunset, isNight, nightCover, population, sunFactor } from '../sim/sim';
import { repairCost } from '../sim/world';

export interface Advice { who: number; title: string; why: string; tool?: BuildingType; zone?: number; off?: BuildingType[]; on?: BuildingType[]; }
const ASHA = 0, KENJI = 1, LENA = 2, RAFAEL = 3;

const r0 = (n: number) => Math.round(n).toLocaleString('en-US');
const left = (stock: number, rate: number) => (rate < -1e-6 ? stock / -rate : Infinity);

export function urgent(s: State): Advice | null {
  if (s.phase !== 'playing') return null;
  const f = s.flows, night = isNight(s.t), cr = Math.floor(s.materials), pop = population(s);
  const all = (t: BuildingType) => s.buildings.filter(b => b.type === t);
  const exists = (t: BuildingType) => all(t).length > 0;
  const can = (t: BuildingType) => cr >= BUILDINGS[t].cost;
  const pick = (t: BuildingType) => (can(t) ? t : undefined);

  const hurt = s.buildings.find(b => b.damaged && b.repair === 0);
  if (hurt) return { who: LENA, title: `Repair the ${BUILDINGS[hurt.type].name}`,
    why: `It is damaged and has stopped working. Click it on the map, it has a red dot, then press Repair. ${repairCost(hurt)} credits, 8 hours.` };

  const loose = s.buildings.find(b => b.progress >= 1 && !b.connected && b.type !== 'conduit');
  if (loose) return { who: LENA, title: `The ${BUILDINGS[loose.type].name} is not linked`, tool: pick('conduit'),
    why: 'It has an orange dot because nothing leads from it back to the lander, so it does nothing. Run Conduit from it to the base: pick Conduit, then click or drag across the ground.' };
  if (s.zone.some((z, k) => z > 0 && !s.linked[k])) return { who: LENA, title: 'Some zoned land is cut off', tool: pick('conduit'),
    why: 'Zoned land only gets built on when it touches the base, other zoned land, or a conduit. The cut-off tiles are drawn faded. Join them up with more zoning or a line of Conduit.' };

  if (s.materials < 0) return { who: RAFAEL, title: 'We are in debt',
    why: `We are ${r0(-s.materials)} credits down and ${f.income >= 0 ? 'earning' : 'losing'} ${Math.abs(f.income).toFixed(1)} an hour. Nothing new gets built until we are back in credit. Upkeep is ${f.upkeep.toFixed(1)} an hour: demolish what we do not use, zone Industry if people are idle, or raise prices.` };

  // No money and nothing coming in, early on.
  const m = MISSIONS[s.mission];
  const cost = m ? (m.tool ? BUILDINGS[m.tool].cost : m.zone ? ZONE_COST * 4 : 0) : 0;
  if (m && cost > cr && f.income < 0.05 && !night) return { who: RAFAEL, title: 'We are out of credits',
    why: `We have ${cr} and the next job costs ${cost}. Nothing is earning. Zone Industry so a company builds a foundry, or demolish something we can spare for a half refund.` };

  if (!night && f.offline > 0 && sunFactor(s.t) > 0.6) return { who: LENA, title: 'We are short of power', tool: pick('solar'),
    why: `The base wants ${f.demand.toFixed(1)} kW and the arrays give ${f.gen.toFixed(1)} kW, so some buildings have shut down. They have red dots. Add Solar Arrays.` };

  if (f.exposed + f.atRisk > 0 && !night) return { who: KENJI, title: 'People have no powered bed',
    why: `${f.exposed + f.atRisk} of our ${pop} people have nowhere safe to sleep. Check that every Habitat and Lodge has power. If Habitat is wanted and blocked, the demand bars say by what.` };

  const o2h = left(s.o2, f.o2Rate);
  const plants = all('o2plant');
  if (o2h < 60 && !night) {
    if (!plants.length) return { who: KENJI, title: 'We are running out of oxygen', tool: pick('o2plant'),
      why: `${pop} people breathe ${(pop * 0.035 * 24).toFixed(1)} kg a day and we have ${r0(o2h)} hours left. Build an Oxygen Plant.` };
    if (plants.every(b => b.progress >= 1 && b.powered)) return { who: KENJI, title: 'One Oxygen Plant is no longer enough', tool: pick('o2plant'),
      why: `${pop} people breathe ${(pop * 0.035 * 24).toFixed(1)} kg a day, more than the plants make by day. We have ${r0(o2h)} hours left. Build another.` };
  }
  // The tank has to hold a whole night of breathing, because the plants rest in the dark.
  const o2Night = 0.035 * pop * (darkHours() + 40) + 8;
  if (!night && plants.length && f.o2Cap < o2Night && !all('o2tank').some(b => b.progress < 1) && (s.mission > 6 || hoursToSunset(s.t) < 200))
    return { who: KENJI, title: 'The oxygen tank is too small for the night', tool: pick('o2tank'),
      why: `${pop} people need ${r0(o2Night)} kg to breathe until the plant has sunlight again, and we can store ${r0(f.o2Cap)} kg. An Oxygen Tank adds 240 kg.` };

  const wh = left(s.water, f.waterRate);
  if (wh < 60 && !exists('recycler')) return { who: KENJI, title: 'Water is running out', tool: pick('recycler'),
    why: `Water for ${r0(wh)} hours. A Water Recycler makes it last six times longer.` };
  if (wh < 60 && exists('pad') && f.waterCap < 60 * pop && !all('watertank').some(b => b.progress < 1)) return { who: KENJI, title: 'We need more water storage', tool: pick('watertank'),
    why: `Water for ${r0(wh)} hours. Each shuttle brings more than we can hold. A Water Tank adds 300 kg.` };
  const fh = left(s.food, f.foodRate);
  if (fh < 60 && !night && !all('greenhouse').some(b => b.progress < 1)) return { who: KENJI, title: 'Food is running out', tool: pick('greenhouse'),
    why: `Food for ${r0(fh)} hours with ${pop} mouths. The shuttle feeds about nine. Each Greenhouse feeds about nine more.` };

  // What life support will need tonight, counting buildings still going up.
  let essential = 0, steady = 0;
  for (const b of s.buildings) { const d = BUILDINGS[b.type]; if (d.priority <= ESSENTIAL) essential += drawOf(b, true); if (!d.solar) steady += d.gen; }
  const need = Math.max(0, essential - steady) * carryHours();

  if (!night) {
    const sunset = hoursToSunset(s.t);
    const planned = BUILDINGS.lander.battery + all('battery').length * BUILDINGS.battery.battery;
    if (planned < need * (s.mission > 6 ? POWER_MARGIN : 1) && exists('habitat') && (s.mission > 6 || sunset < 150) && sunset > 12) {
      const more = Math.ceil((need * POWER_MARGIN - planned) / BUILDINGS.battery.battery);
      if (more >= 4 && sunset > 55) return { who: LENA, title: 'Build a Fission Reactor for the night', tool: pick('reactor') ?? pick('battery'),
        why: `Life support draws ${(need / carryHours()).toFixed(1)} kW all night. With a safe margin that is ${r0(need * POWER_MARGIN)} kWh and we can store ${r0(planned)}. It would take ${more} more Battery Banks, or one reactor that gives 10 kW day and night.` };
      return { who: ASHA, title: `Tonight needs ${more} more Battery Bank${more > 1 ? 's' : ''}`, tool: pick('battery'),
        why: `Habitats, lodges and the recycler draw ${(need / carryHours()).toFixed(1)} kW all night. With a safe margin that is ${r0(need * POWER_MARGIN)} kWh and we can store ${r0(planned)}.` };
    }
    return null;
  }

  const cover = nightCover(s), toDawn = hoursToSunrise(s.t);
  if (cover < toDawn - (pop <= 4 ? s.canisters : 0)) return { who: ASHA, title: 'The batteries will not last',
    why: `They run dry in ${r0(cover)} hours with ${r0(toDawn)} to go. ${pop <= 4 ? `Then the crew falls back to the lander, which has ${r0(s.canisters)} hours of air filters.` : 'When they do, Earth will start pulling people out. More storage, or a reactor, before the next sunset.'}` };
  return null;
}
