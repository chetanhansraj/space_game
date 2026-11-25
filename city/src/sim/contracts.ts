// Contracts. Once there is a landing pad, nations and companies start making offers.
// Each offer comes with one advisor for it and one against. Accepting creates a deal with a deadline:
// meet its terms and it pays, miss the date and it costs.

import { words } from './buildings';
import { State, world, dayHours, span, phaseOf, addBuilding, aliveCount, earn, isNight, population, pushAlert, rnd, siteProblem, support, working } from './sim';

export type DealKind = 'team' | 'oxygen' | 'works' | 'broadcast';
export interface Offer { kind: DealKind; amount?: number; from: string; title: string; text: string; need: string; pay: number; penalty: number; hours: number; expires: number;
  pro: { who: number; say: string }; con: { who: number; say: string }; }
export interface Deal { id: number; kind: DealKind; amount?: number; from: string; title: string; need: string; pay: number; penalty: number; due: number; }

const NATIONS = ['India', 'Japan', 'Brazil', 'Kenya', 'the Emirates', 'Canada', 'South Korea', 'Nigeria'];
const MOON_FIRMS = ['Selene Metals', 'Kestrel Propulsion', 'Mare Glassworks', 'Aldrin Volatiles', 'Tycho Robotics'];
const MARS_FIRMS = ['Tharsis Metals', 'Kestrel Propulsion', 'Arcadia Glassworks', 'Deimos Volatiles', 'Olympus Robotics'];
const ASHA = 0, KENJI = 1, LENA = 2, RAFAEL = 3;
const RESERVE = 100;   // hours of breathing kept back before any oxygen is sold
/** Real minutes an offer stays open in the world. Chetan, 21 November 2026: thirty to forty-five. */
export const OFFER_MINUTES = 40;
/** Contracts grow with the town: a deal worth 90 to an outpost is worth 270 to a town of sixty. */
const scale = (s: State) => 1 + Math.min(4, Math.floor(population(s) / 15)) * 0.5;
/** A deadline never falls in the dark, when no passenger ship flies: it slides to 60 hours after the next sunrise. */
const inDaylight = (t: number) => (isNight(t) ? t + (dayHours() - phaseOf(t)) + span(60) : t);
const pick = <T,>(s: State, list: T[]) => list[Math.floor(rnd(s) * list.length)];

function freeIndustryLot(s: State): [number, number] | null {
  const n = s.size;
  for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) {
    const ks = [y * n + x, y * n + x + 1, (y + 1) * n + x, (y + 1) * n + x + 1];
    if (ks.every(k => s.zone[k] === 2 && s.linked[k] && s.prep[k] >= 1) && !siteProblem(s, 'printer', x, y, true)) return [x, y];
  }
  return null;
}

function makeOffer(s: State): Offer | null {
  const o = draftOffer(s);
  if (!o) return null;
  // in the words of the world the town stands on
  return { ...o, title: words(o.title), text: words(o.text), need: words(o.need), pro: { ...o.pro, say: words(o.pro.say) }, con: { ...o.con, say: words(o.con.say) } };
}

function draftOffer(s: State): Offer | null {
  const f = s.flows, pop = population(s), cap = support(s);
  const has = (k: DealKind) => s.deals.some(d => d.kind === k);
  const kinds: DealKind[] = (['team', 'oxygen', 'works', 'broadcast'] as DealKind[]).filter(k => !has(k)
    && (k !== 'oxygen' || s.buildings.some(b => b.type === 'o2plant' && working(b))));
  if (!kinds.length) return null;
  // An offer waits for a person, so it waits in the person's time: forty real minutes in the world, however fast
  // the world's clock runs, and never less than the seventy hours it always was.
  const kind = pick(s, kinds), expires = s.t + Math.max(70, OFFER_MINUTES * (s.pace ?? 1)), k = scale(s), kg = Math.round(150 * k / 50) * 50;
  const pay = (n: number) => Math.round(n * k / 10) * 10;
  const fit = (h: number) => Math.round(inDaylight(s.t + h) - s.t);
  if (kind === 'team') {
    const from = pick(s, NATIONS);
    return { kind, from, expires, pay: pay(90), penalty: pay(40), hours: fit(160), title: `Station four researchers from ${from}`,
      text: `${from}'s space agency wants to station four researchers at Tranquility for good.`,
      need: 'Four free Habitat beds, and life support with room for four more',
      pro: { who: ASHA, say: 'Every flag on our wall brings the next one. And researchers pay rent like anyone else.' },
      con: { who: KENJI, say: cap.limit - pop < 4 ? `Right now we can keep ${cap.limit} people alive and we are ${pop}. The limit is ${cap.why}. Fix that first or we pay the penalty.` : 'Four more people breathing our air through the night. I can carry them, but only just.' } };
  }
  if (kind === 'oxygen') {
    const from = pick(s, world().id === 'mars' ? MARS_FIRMS : MOON_FIRMS);
    return { kind, from, expires, pay: pay(120), penalty: pay(30), hours: fit(220), amount: kg, title: `Sell ${kg} kg of oxygen to ${from}`,
      text: `${from} will buy ${kg} kg of liquid oxygen for an engine test. A shuttle collects it in daylight, the moment the tanks can spare it.`,
      need: `${kg} kg of oxygen in the tanks, above a ${RESERVE} hour reserve for breathing`,
      pro: { who: RAFAEL, say: world().id === 'mars' ? 'Oxygen is the one thing we make out of thin air. Every engine that leaves this planet could burn ours.' : 'Oxygen is the one thing we make out of dirt. This is what the foundry was always going to become.' },
      con: { who: KENJI, say: `That is ${Math.max(1, Math.round(kg / (0.035 * pop)))} hours of breath for everyone here. We hold ${Math.round(s.o2)} kg and the tanks take ${Math.round(f.o2Cap)}. I want more tanks before I sell a gram.` } };
  }
  if (kind === 'works') {
    const from = pick(s, world().id === 'mars' ? MARS_FIRMS : MOON_FIRMS);
    return { kind, from, expires, pay: pay(100), penalty: pay(30), hours: fit(160), title: `Lease an Industry lot to ${from}`,
      text: `${from} wants a serviced Industry lot. They will build a two-deck works on it at their own cost and pay on the day they break ground.`,
      need: 'One empty, linked Industry lot of two tiles by two',
      pro: { who: RAFAEL, say: 'A real company on our land. Six jobs, and they pay us to open.' },
      con: { who: LENA, say: 'A two-deck works pulls nine kilowatts by day and needs six workers we may not have. And its dust falls on whoever lives next door.' } };
  }
  const from = pick(s, NATIONS), beds = Math.max(6, f.lodging + 4);
  return { kind, from, expires, amount: beds, pay: pay(110), penalty: pay(40), hours: fit(200), title: `Host a live broadcast for ${from}`,
    text: `A broadcaster from ${from} wants to send a crew to film a live programme from Tranquility Base.`,
    need: `${beds} Visitor Lodge beds, where we have ${f.lodging}, and a working Rover Bay`,
    pro: { who: ASHA, say: 'The whole Earth watching Tranquility Base from the seat of one of our rovers. You cannot buy that.' },
    con: { who: LENA, say: `${beds} lodge beds means more Commercial land with power and air behind it, and the rover bay has to be up. If we are late, we pay.` } };
}

function fulfil(s: State, d: Deal): boolean {
  const f = s.flows, pop = population(s);
  if (d.kind === 'team') {
    if (isNight(s.t) || f.housing - aliveCount(s) - s.residents < 4 || support(s).limit - pop < 4) return false;
    s.residents += 4; return true;
  }
  if (d.kind === 'oxygen') {
    const kg = d.amount ?? 150;
    if (isNight(s.t) || s.o2 < kg + 0.035 * pop * RESERVE) return false;
    s.o2 -= kg; return true;
  }
  if (d.kind === 'works') {
    const lot = freeIndustryLot(s);
    if (!lot) return false;
    const b = addBuilding(s, 'printer', lot[0], lot[1], 0); b.level = 2; s.stats.grown++; return true;
  }
  return f.lodging >= (d.amount ?? 6) && s.buildings.some(b => b.type === 'garage' && working(b));
}

export function tickContracts(s: State) {
  const pad = s.buildings.some(b => b.type === 'pad' && working(b));
  if (s.offer && s.t >= s.offer.expires) { pushAlert(s, 'info', `${s.offer.from} has withdrawn its offer.`); s.offer = null; }
  if (!s.offer && pad && !isNight(s.t) && s.deals.length < 3) {
    if (s.nextOffer === 0) s.nextOffer = s.t + 30;
    else if (s.t >= s.nextOffer) {
      s.offer = makeOffer(s); s.nextOffer = s.t + 100 + rnd(s) * 60;
      if (s.offer) pushAlert(s, 'info', `${s.offer.from} has made an offer. It is waiting under Contracts.`);
    }
  }
  for (const d of [...s.deals]) {
    if (fulfil(s, d)) {
      earn(s, d.pay); s.stats.deals++; s.deals.splice(s.deals.indexOf(d), 1);
      pushAlert(s, 'good', `Contract complete: ${d.title}. ${d.from} pays ${d.pay} credits.`);
    } else if (s.t >= d.due) {
      s.materials -= d.penalty; s.stats.broken++; s.deals.splice(s.deals.indexOf(d), 1);
      pushAlert(s, 'bad', `Contract broken: ${d.title}. The penalty is ${d.penalty} credits.`);
    }
  }
}

export function answerOffer(s: State, accept: boolean): { ok: boolean; reason?: string } {
  const o = s.offer;
  if (!o) return { ok: false, reason: 'There is no offer on the table' };
  if (accept) s.deals.push({ id: s.nextDeal++, kind: o.kind, amount: o.amount, from: o.from, title: o.title, need: o.need, pay: o.pay, penalty: o.penalty, due: inDaylight(s.t + o.hours) });
  s.offer = null;
  return { ok: true };
}
