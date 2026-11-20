// The building pictures: models rendered at the game's angle, and their upgrades drawn from those renders.
// Generated from the sprite metadata; see docs/DECISIONS.md D87 and the art notes in the project.
// The night lights were drawn by an image model from each picture and cut out as light alone (D90).
// ax, ay: where the middle of the footprint sits in the picture. k: scale to the tiles. top: height above the ground at 1x.
import type { BuildingType } from '../sim/buildings';
// @ts-ignore a picture, resolved by the bundler
import printerPng from './printer.png';
// @ts-ignore a picture, resolved by the bundler
import habitatPng from './habitat.png';
// @ts-ignore a picture, resolved by the bundler
import landerPng from './lander.png';
// @ts-ignore a picture, resolved by the bundler
import solarPng from './solar.png';
// @ts-ignore a picture, resolved by the bundler
import reactorPng from './reactor.png';
// @ts-ignore a picture, resolved by the bundler
import o2plantPng from './o2plant.png';
// @ts-ignore a picture, resolved by the bundler
import lodgePng from './lodge.png';
// @ts-ignore a picture, resolved by the bundler
import garagePng from './garage.png';
// @ts-ignore a picture, resolved by the bundler
import clinicPng from './clinic.png';
// @ts-ignore a picture, resolved by the bundler
import marketPng from './market.png';
// @ts-ignore a picture, resolved by the bundler
import greenhousePng from './greenhouse.png';
// @ts-ignore a picture, resolved by the bundler
import batteryPng from './battery.png';
// @ts-ignore a picture, resolved by the bundler
import recyclerPng from './recycler.png';
// @ts-ignore a picture, resolved by the bundler
import o2tankPng from './o2tank.png';
// @ts-ignore a picture, resolved by the bundler
import watertankPng from './watertank.png';
// @ts-ignore a picture, resolved by the bundler
import padPng from './pad.png';
// @ts-ignore a picture, resolved by the bundler
import gardenPng from './garden.png';
// @ts-ignore a picture, resolved by the bundler
import habitat_1Png from './habitat_1.png';
// @ts-ignore a picture, resolved by the bundler
import habitat_2Png from './habitat_2.png';
// @ts-ignore a picture, resolved by the bundler
import habitat_3Png from './habitat_3.png';
// @ts-ignore a picture, resolved by the bundler
import lodge_2Png from './lodge_2.png';
// @ts-ignore a picture, resolved by the bundler
import lodge_3Png from './lodge_3.png';
// @ts-ignore a picture, resolved by the bundler
import market_2Png from './market_2.png';
// @ts-ignore a picture, resolved by the bundler
import market_3Png from './market_3.png';
// @ts-ignore a picture, resolved by the bundler
import printer_2Png from './printer_2.png';
// @ts-ignore a picture, resolved by the bundler
import printer_3Png from './printer_3.png';
// @ts-ignore a picture, resolved by the bundler
import printerNightPng from './printer_night.png';
// @ts-ignore a picture, resolved by the bundler
import landerNightPng from './lander_night.png';
// @ts-ignore a picture, resolved by the bundler
import solarNightPng from './solar_night.png';
// @ts-ignore a picture, resolved by the bundler
import reactorNightPng from './reactor_night.png';
// @ts-ignore a picture, resolved by the bundler
import o2plantNightPng from './o2plant_night.png';
// @ts-ignore a picture, resolved by the bundler
import lodgeNightPng from './lodge_night.png';
// @ts-ignore a picture, resolved by the bundler
import garageNightPng from './garage_night.png';
// @ts-ignore a picture, resolved by the bundler
import clinicNightPng from './clinic_night.png';
// @ts-ignore a picture, resolved by the bundler
import marketNightPng from './market_night.png';
// @ts-ignore a picture, resolved by the bundler
import greenhouseNightPng from './greenhouse_night.png';
// @ts-ignore a picture, resolved by the bundler
import batteryNightPng from './battery_night.png';
// @ts-ignore a picture, resolved by the bundler
import recyclerNightPng from './recycler_night.png';
// @ts-ignore a picture, resolved by the bundler
import o2tankNightPng from './o2tank_night.png';
// @ts-ignore a picture, resolved by the bundler
import watertankNightPng from './watertank_night.png';
// @ts-ignore a picture, resolved by the bundler
import padNightPng from './pad_night.png';
// @ts-ignore a picture, resolved by the bundler
import gardenNightPng from './garden_night.png';
// @ts-ignore a picture, resolved by the bundler
import habitat_1NightPng from './habitat_1_night.png';
// @ts-ignore a picture, resolved by the bundler
import habitat_2NightPng from './habitat_2_night.png';
// @ts-ignore a picture, resolved by the bundler
import habitat_3NightPng from './habitat_3_night.png';
// @ts-ignore a picture, resolved by the bundler
import lodge_2NightPng from './lodge_2_night.png';
// @ts-ignore a picture, resolved by the bundler
import lodge_3NightPng from './lodge_3_night.png';
// @ts-ignore a picture, resolved by the bundler
import market_2NightPng from './market_2_night.png';
// @ts-ignore a picture, resolved by the bundler
import market_3NightPng from './market_3_night.png';
// @ts-ignore a picture, resolved by the bundler
import printer_2NightPng from './printer_2_night.png';
// @ts-ignore a picture, resolved by the bundler
import printer_3NightPng from './printer_3_night.png';
// glow: what is lit at night (windows, lamps, furnaces), on black, the same size as the picture. Added over it when the building has power.
// levels[0] is the picture from level 2, levels[1] from level 3.
export interface Art { url: string; glow?: string; ax: number; ay: number; k: number; top: number; levels?: Art[]; }
export const ART: Partial<Record<BuildingType, Art>> = {
  printer: { url: printerPng as string, glow: printerNightPng as string, ax: 304/608, ay: 386/554, k: 0.5, top: 55, levels: [{ url: printer_2Png as string, glow: printer_2NightPng as string, ax: 128.0/237, ay: 226.0/258, k: 0.5, top: 103 }, { url: printer_3Png as string, glow: printer_3NightPng as string, ax: 128.0/236, ay: 290.5/325, k: 0.5, top: 135 }] },
  habitat: { url: habitat_1Png as string, glow: habitat_1NightPng as string, ax: 74.5/152, ay: 79.0/116, k: 0.5, top: 29, levels: [{ url: habitat_2Png as string, glow: habitat_2NightPng as string, ax: 74.5/152, ay: 134.0/170, k: 0.5, top: 57 }, { url: habitat_3Png as string, glow: habitat_3NightPng as string, ax: 74.5/152, ay: 190.0/226, k: 0.5, top: 85 }] },
  lander: { url: landerPng as string, glow: landerNightPng as string, ax: 304/608, ay: 426/594, k: 0.5, top: 65 },
  solar: { url: solarPng as string, glow: solarNightPng as string, ax: 304/608, ay: 243/411, k: 0.5, top: 19 },
  reactor: { url: reactorPng as string, glow: reactorNightPng as string, ax: 304/608, ay: 384/552, k: 0.5, top: 54 },
  o2plant: { url: o2plantPng as string, glow: o2plantNightPng as string, ax: 304/608, ay: 580/748, k: 0.5, top: 103 },
  lodge: { url: lodgePng as string, glow: lodgeNightPng as string, ax: 304/608, ay: 421/589, k: 0.5, top: 63, levels: [{ url: lodge_2Png as string, glow: lodge_2NightPng as string, ax: 93.0/194, ay: 215.0/263, k: 0.5, top: 97 }, { url: lodge_3Png as string, glow: lodge_3NightPng as string, ax: 93.0/194, ay: 278.5/326, k: 0.5, top: 129 }] },
  garage: { url: garagePng as string, glow: garageNightPng as string, ax: 304/608, ay: 321/489, k: 0.5, top: 38 },
  clinic: { url: clinicPng as string, glow: clinicNightPng as string, ax: 304/608, ay: 350/518, k: 0.5, top: 45 },
  market: { url: marketPng as string, glow: marketNightPng as string, ax: 304/608, ay: 300/468, k: 0.5, top: 33, levels: [{ url: market_2Png as string, glow: market_2NightPng as string, ax: 94.0/188, ay: 173.0/225, k: 0.5, top: 76 }, { url: market_3Png as string, glow: market_3NightPng as string, ax: 94.0/188, ay: 233.0/285, k: 0.5, top: 106 }] },
  greenhouse: { url: greenhousePng as string, glow: greenhouseNightPng as string, ax: 304/608, ay: 293/461, k: 0.5, top: 31 },
  battery: { url: batteryPng as string, glow: batteryNightPng as string, ax: 176/352, ay: 231/335, k: 0.5, top: 32 },
  recycler: { url: recyclerPng as string, glow: recyclerNightPng as string, ax: 176/352, ay: 272/376, k: 0.5, top: 42 },
  o2tank: { url: o2tankPng as string, glow: o2tankNightPng as string, ax: 176/352, ay: 255/359, k: 0.5, top: 38 },
  watertank: { url: watertankPng as string, glow: watertankNightPng as string, ax: 176/352, ay: 257/361, k: 0.5, top: 38 },
  pad: { url: padPng as string, glow: padNightPng as string, ax: 432/864, ay: 288/520, k: 0.5, top: 14 },
  garden: { url: gardenPng as string, glow: gardenNightPng as string, ax: 304/608, ay: 345/513, k: 0.5, top: 44 },
};
