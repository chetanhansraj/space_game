// The 2D isometric view. It reads the simulation state and draws it; it never
// changes it. A 3D view can replace this file without touching the simulation.
// Buildings are pictures rendered from 3D models at this angle; a type with no picture falls back to a flat-shaded prism
// with a two-letter label. The ground is one lit picture built per town (ground.ts).

import { Application, Container, Graphics, Text, Sprite, Texture, Matrix, Mesh, MeshGeometry } from './pixi';
import { buildGround, buildLand, landNet, LANDS, BALL, GP, Stamp, SOIL } from './ground';
// @ts-ignore
import craterA from '../art/craterA.png';
// @ts-ignore
import craterB from '../art/craterB.png';
// @ts-ignore
import craterC from '../art/craterC.png';
// @ts-ignore
import craterD from '../art/craterD.png';
// @ts-ignore a picture, resolved by the bundler
import regolithJpg from '../art/regolith.jpg';
// @ts-ignore
import rock0 from '../art/rock0.png';
// @ts-ignore
import rock1 from '../art/rock1.png';
// @ts-ignore
import rock2 from '../art/rock2.png';
// @ts-ignore
import rock3 from '../art/rock3.png';
// @ts-ignore
import rock4 from '../art/rock4.png';
// @ts-ignore
import rock5 from '../art/rock5.png';
import type { Texture as Tex } from './pixi';
import { ART, MARS_ART, Art } from '../art/art';
import { BUILDINGS, BuildingType, ZONES } from '../sim/buildings';
import { ORES, hazeActive } from '../sim/world';
import { State, GROUND, SIZE, sunFactor, population, phaseOf, lightHours, dayHours, span } from '../sim/sim';

const TW = 64, TH = 32;
// Zoomed far out, a picture is drawn many times smaller than it was made. Smaller copies are kept ready so it does not sparkle.
const soft = (t: Tex): Tex => { t.source.autoGenerateMipmaps = true; return t; };
const iso = (x: number, y: number, z = 0): [number, number] => [(x - y) * (TW / 2), (x + y) * (TH / 2) - z];

interface Look { top: number; hgt: number; inset: number; ink: number; cap?: number; }
const LOOK: Record<BuildingType, Look> = {
  lander: { top: 0xd2a84c, hgt: 24, inset: 0.12, ink: 0x2a1e05, cap: 0xe9e4d6 },
  conduit: { top: 0x8f8ba6, hgt: 0, inset: 0, ink: 0 },
  solar: { top: 0x234a8c, hgt: 4, inset: 0.05, ink: 0xcfe0ff },
  battery: { top: 0x3f8f63, hgt: 12, inset: 0.18, ink: 0x06200f },
  reactor: { top: 0x4a4858, hgt: 26, inset: 0.16, ink: 0xffd9a8, cap: 0xff8a3d },
  habitat: { top: 0xe2ded5, hgt: 18, inset: 0.08, ink: 0x2b2a33 },
  o2plant: { top: 0x69b4e3, hgt: 22, inset: 0.14, ink: 0x06202f },
  recycler: { top: 0x3a9bb0, hgt: 14, inset: 0.2, ink: 0x031d22 },
  o2tank: { top: 0xb5def4, hgt: 17, inset: 0.24, ink: 0x0b2836 },
  watertank: { top: 0x4a78dc, hgt: 17, inset: 0.24, ink: 0xe6eeff },
  printer: { top: 0xb47a3f, hgt: 15, inset: 0.1, ink: 0x2a1603 },
  greenhouse: { top: 0x58b874, hgt: 13, inset: 0.07, ink: 0x06220f },
  pad: { top: 0x5b5868, hgt: 2, inset: 0.03, ink: 0xf2efe6 },
  lodge: { top: 0xe8c9a0, hgt: 20, inset: 0.1, ink: 0x3a2408, cap: 0x8fd0ff },
  market: { top: 0x86b6ff, hgt: 16, inset: 0.09, ink: 0x0a1c38, cap: 0xffe2a8 },
  garage: { top: 0x9aa3ad, hgt: 12, inset: 0.08, ink: 0x14181d },
  garden: { top: 0x3fa66a, hgt: 10, inset: 0.06, ink: 0x06220f, cap: 0xb9f0c8 },
  clinic: { top: 0xf4f1ea, hgt: 16, inset: 0.1, ink: 0x2b2a33, cap: 0xff6b6b },
  drill: { top: 0x7fd0e8, hgt: 26, inset: 0.14, ink: 0x06202f },
  wind: { top: 0xc8c2b4, hgt: 28, inset: 0.3, ink: 0x2b2a33 },
  sabatier: { top: 0xe0a04a, hgt: 22, inset: 0.12, ink: 0x2a1603 },
};

const TEX = new Map<Art, Tex>();
const GLOW = new Map<Art, Tex>();    // what each picture lights up at night
const PIC = new Map<Art, HTMLImageElement>();
const EDGE = new Map<Art, Tex>();
// A building's picture as a flat white shape, for drawing a line round it when it is selected. Made the first time it is needed.
function edgeOf(a: Art): Tex | undefined {
  let t = EDGE.get(a); const img = PIC.get(a);
  if (!t && img) {
    const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
    const x = c.getContext('2d')!; x.drawImage(img, 0, 0); x.globalCompositeOperation = 'source-in'; x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height);
    t = soft(Texture.from(c)); EDGE.set(a, t);
  }
  return t;
}
let DUST: HTMLImageElement | null = null;          // the dust texture, once loaded
const ROCKS: Tex[] = [];
const STAMPS: Stamp[] = [];                       // crater shading rendered in Blender, used once all four are in
// The picture for a building at its level: the upgraded one from level 2 when there is one.
/** The pictures for the world of the town on screen. */
let SET: Partial<Record<BuildingType, Art>> = ART;
const artOf = (b: { type: BuildingType; level?: number }): Art | undefined => { const a = SET[b.type]; if (!a || !a.levels || (b.level || 1) < 2) return a; return a.levels[Math.min((b.level || 1) - 2, a.levels.length - 1)]; };

const shade = (c: number, k: number) => {
  const r = Math.min(255, ((c >> 16) & 255) * k) | 0, g = Math.min(255, ((c >> 8) & 255) * k) | 0, b = Math.min(255, (c & 255) * k) | 0;
  return (r << 16) | (g << 8) | b;
};
const mix = (a: number, b: number, t: number) => {
  const ch = (s: number) => (((a >> s) & 255) + (((b >> s) & 255) - ((a >> s) & 255)) * t) | 0;
  return (ch(16) << 16) | (ch(8) << 8) | ch(0);
};
const hash = (x: number, y: number) => {
  let h = (x * 374761393 + y * 668265263) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
};

function prism(g: Graphics, x: number, y: number, w: number, h: number, z0: number, hgt: number, inset: number, top: number, alpha = 1) {
  const a = iso(x + inset, y + inset, z0 + hgt), b = iso(x + w - inset, y + inset, z0 + hgt);
  const c = iso(x + w - inset, y + h - inset, z0 + hgt), d = iso(x + inset, y + h - inset, z0 + hgt);
  if (hgt > 0) {
    g.poly([d[0], d[1], c[0], c[1], c[0], c[1] + hgt, d[0], d[1] + hgt]).fill({ color: shade(top, 0.62), alpha });
    g.poly([c[0], c[1], b[0], b[1], b[0], b[1] + hgt, c[0], c[1] + hgt]).fill({ color: shade(top, 0.42), alpha });
  }
  g.poly([a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]]).fill({ color: top, alpha });
}

export class View {
  app!: Application;
  world = new Container();
  private terrain = new Graphics();
  private zones = new Graphics();
  private findLabels = new Container();
  private heat = new Graphics();
  private heatRev = -1;
  private objects = new Container();
  private overlay = new Graphics();
  private lights = new Graphics();
  private ghost = new Graphics();
  private mark = new Graphics();        // the selected building's plot, on the ground under the buildings
  private halo = new Container();       // a line round the selected building's picture, at its own depth so nearer buildings still stand in front
  private haloKey = '';
  private glows = new Map<number, Sprite>();   // each building's night lights, by building
  private bodyTint = -1;
  private stars = new Graphics();
  private landJob = 0;
  private groundTex: Tex[] = [];        // the two ground pictures of the town on screen, freed when the ground is redrawn
  private labels = new Container();
  private fx = new Container();
  private seenPop = 0;
  private walkers: { ax: number; ay: number; bx: number; by: number; t: number; v: number }[] = [];
  private spots: [number, number][] = [];
  private lastNow = 0;
  private drawnRev = -1;
  private drawnSeed = -1;
  scale = 1;

  static async create(host: HTMLElement): Promise<View> {
    const v = new View();
    v.app = new Application();
    await v.app.init({
      resizeTo: host, backgroundAlpha: 0, antialias: true, preference: 'webgl',
      resolution: Math.min(window.devicePixelRatio || 1, 2), autoDensity: true,
    });
    host.appendChild(v.app.canvas);
    v.app.canvas.style.touchAction = 'none';
    v.objects.sortableChildren = true;
    { const img = new Image(); img.onload = () => { DUST = img; v.drawnSeed = -1; }; img.src = regolithJpg as string; }
    { const got: (Stamp | null)[] = [null, null, null, null]; [[craterA, 0.4], [craterB, 0.425], [craterC, 0.3625], [craterD, 0.375]].forEach(([u, rim], i) => { const img = new Image(); img.onload = () => { got[i] = { img, rim: rim as number }; if (got.every(Boolean)) { STAMPS.push(...(got as Stamp[])); v.drawnSeed = -1; } }; img.src = u as string; }); }
    [rock0, rock1, rock2, rock3, rock4, rock5].forEach((u, i) => { const img = new Image(); img.onload = () => { ROCKS[i] = soft(Texture.from(img)); v.drawnSeed = -1; }; img.src = u as string; });
    // the building pictures are fetched when the first town is drawn, once it is known which world it stands on (useArt)
    v.lights.blendMode = 'add';
    v.world.addChild(v.terrain, v.zones, v.heat, v.labels, v.findLabels, v.mark, v.objects, v.ghost, v.overlay, v.lights, v.fx);
    v.app.stage.addChild(v.stars, v.world);
    for (let i = 0; i < 260; i++) {
      const r = hash(i, 7) < 0.9 ? 0.7 : 1.3;
      v.stars.circle(hash(i, 1) * 2800, hash(i, 2) * 1700, r).fill({ color: 0xffffff, alpha: 0.25 + hash(i, 3) * 0.55 });
    }
    return v;
  }

  // ----- camera -----
  centreOn(tx: number, ty: number) {
    const [sx, sy] = iso(tx, ty);
    this.world.scale.set(this.scale);
    this.world.position.set(this.app.screen.width / 2 - sx * this.scale, this.app.screen.height / 2 - sy * this.scale);
  }
  // The middle of the screen stays over the claim, so the town can never be lost off the edge of the land.
  private hold() {
    const W = this.app.screen.width, H = this.app.screen.height, k = this.scale, e = SIZE * TW / 2, p = this.world.position;
    p.x = W / 2 - Math.max(-e, Math.min(e, (W / 2 - p.x) / k)) * k;
    p.y = H / 2 - Math.max(0, Math.min(e, (H / 2 - p.y) / k)) * k;
  }
  panBy(dx: number, dy: number) { if (this.riseFrom) return; this.world.position.x += dx; this.world.position.y += dy; this.hold(); }
  // ----- rising to the Moon -----
  // Past the furthest zoom the view can go on pulling back, until the bent land is a ball in the middle of the screen
  // with the town near its top. That last picture is the one the globe opens on, so the two can be dissolved together.
  static readonly FAR = 0.012;                       // the scale of that last picture
  get ballRadius() { return BALL.side * View.FAR; }  // how big it draws the Moon, in screen pixels
  private riseFrom: { k: number; x: number; y: number } | null = null;
  /** u from 0 (the town as it was) to 1 (the ball). Call riseEnd when back at 0. */
  rise(u: number) {
    const W = this.app.screen.width, H = this.app.screen.height, mid = SIZE * TH / 2;   // the middle of the claim, in the town's units
    if (!this.riseFrom) this.riseFrom = { k: this.scale, x: this.world.position.x, y: this.world.position.y + mid * this.scale };
    const f = this.riseFrom, e = u * u * (3 - 2 * u);
    const k = Math.exp(Math.log(f.k) + (Math.log(View.FAR) - Math.log(f.k)) * e);
    const tx = W / 2, ty = H / 2 - (BALL.below - BALL.above) / 2 * View.FAR;            // where the claim sits when the ball is centred
    this.scale = k; this.world.scale.set(k);
    this.world.position.set(f.x + (tx - f.x) * e, f.y + (ty - f.y) * e - mid * k);
  }
  riseEnd() {
    const f = this.riseFrom; if (!f) return; this.riseFrom = null;
    this.scale = f.k; this.world.scale.set(f.k); this.world.position.set(f.x, f.y - SIZE * TH / 2 * f.k); this.hold();
  }
  get atFurthest() { return this.scale <= 0.0451; }

  zoomAt(px: number, py: number, factor: number) {
    if (this.riseFrom) return;
    const next = Math.max(0.045, Math.min(2.6, this.scale * factor));   // far enough out to see the land curve away, with the town small on it
    const k = next / this.scale;
    this.world.position.x = px - (px - this.world.position.x) * k;
    this.world.position.y = py - (py - this.world.position.y) * k;
    this.scale = next; this.world.scale.set(next); this.hold();
  }
  // The building whose picture is under a point on the screen, nearest first; 0 if none.
  pick(s: State, px: number, py: number): number {
    const wx = (px - this.world.position.x) / this.scale, wy = (py - this.world.position.y) / this.scale;
    let hit = 0, depth = -1;
    for (const b of s.buildings) {
      if (b.type === 'conduit') continue;
      const d = BUILDINGS[b.type], art = artOf(b), m = iso(b.x + d.w / 2, b.y + d.h / 2);
      const half = d.w * (TW / 2) * 0.86, top = (art ? art.top : LOOK[b.type].hgt) + 6, dx = Math.abs(wx - m[0]), dy = wy - m[1];
      // inside the footprint diamond, or inside the body standing on it
      const onGround = dx / (d.w * TW / 2) + Math.abs(dy) / (d.h * TH / 2) <= 1;
      const onBody = dx <= half && dy <= 0 && dy >= -top;
      if ((onGround || onBody) && b.x + b.y + d.w + d.h > depth) { depth = b.x + b.y + d.w + d.h; hit = b.uid; }
    }
    return hit;
  }
  screenToTile(px: number, py: number): { x: number; y: number } {
    const wx = (px - this.world.position.x) / this.scale, wy = (py - this.world.position.y) / this.scale;
    return { x: Math.floor((wx / (TW / 2) + wy / (TH / 2)) / 2), y: Math.floor((wy / (TH / 2) - wx / (TW / 2)) / 2) };
  }

  /** Use the pictures for this town's world, fetching them the first time. Until they arrive a building is a plain block. */
  private artFor = '';
  private useArt(s: State) {
    const id = s.world ?? 'moon';
    if (id === this.artFor) return;
    this.artFor = id; SET = id === 'mars' ? MARS_ART : ART; this.drawnRev = -1; this.drawnSeed = -1;
    for (const a0 of Object.values(SET)) for (const a of [a0!, ...(a0!.levels || [])]) {
      if (TEX.has(a)) continue;
      const img = new Image(); img.onload = () => { TEX.set(a, soft(Texture.from(img))); PIC.set(a, img); this.drawnRev = -1; }; img.src = a.url;   // an image element, because the page may not fetch
      if (a.glow) { const lit = new Image(); lit.onload = () => { GLOW.set(a, soft(Texture.from(lit))); this.drawnRev = -1; }; lit.src = a.glow; }
    }
  }

  // ----- terrain, drawn once per site -----
  private drawTerrain(s: State) {
    const soil = SOIL[s.world ?? 'moon'] ?? SOIL.moon, mars = s.world === 'mars';
    const g0 = this.terrain; g0.clear();
    for (const c of g0.removeChildren()) c.destroy({ children: true });   // the boulder pictures are shared, so textures are freed by hand below
    for (const t of this.groundTex.splice(0)) t.destroy(true);
    const n = s.size;
    // The land around the claim: level near the town, then curving away like the globe it is. Three pictures, one inside
    // the next. The nearest is made now; the two far ones a moment later, so the town itself is on screen without waiting.
    const job = ++this.landJob, lands = new Container(); g0.addChild(lands);
    const lay = (i: number) => {
      const tex = soft(Texture.from(buildLand(s, DUST, STAMPS, LANDS[i], i, soil))); this.groundTex.push(tex);
      const m = new Mesh({ geometry: new MeshGeometry(landNet(n, LANDS[i])), texture: tex }); m.zIndex = -i; lands.addChild(m); lands.sortChildren();
    };
    lay(0);
    [2, 1].forEach((i, k) => setTimeout(() => { if (job === this.landJob) lay(i); }, 60 + 90 * k));
    // the ground: one lit picture seen from straight above, laid onto the tilted grid
    const tex = soft(Texture.from(buildGround(s, DUST, STAMPS, soil))); this.groundTex.push(tex);
    const land = new Sprite(tex); land.setFromMatrix(new Matrix(32 / GP, 16 / GP, -32 / GP, 16 / GP, 0, 0)); g0.addChild(land);
    const g = new Graphics(); g0.addChild(g);
    // the claim's edge: a line on the ground and a post at each corner
    { const a = iso(0, 0), b = iso(n, 0), c = iso(n, n), d = iso(0, n);
      g.poly([a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]]).stroke({ color: 0x22d3ee, width: 2, alpha: 0.55 });
      for (const q of [a, b, c, d]) g.rect(q[0] - 1.5, q[1] - 14, 3, 14).fill(0xd9dbe2).circle(q[0], q[1] - 15, 2.5).fill(0x22d3ee); }
    // a faint grid, so plots can still be counted
    for (let i = 0; i <= n; i++) { const a = iso(i, 0), b = iso(i, n), c = iso(0, i), d = iso(n, i); g.moveTo(a[0], a[1]).lineTo(b[0], b[1]).moveTo(c[0], c[1]).lineTo(d[0], d[1]); }
    g.stroke({ color: 0x000000, width: 1, alpha: 0.09 });
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      if (s.ground[y * n + x] !== GROUND.boulder) continue;
      const noise = hash(x, y), m = iso(x + 0.5, y + 0.5), rt = ROCKS[Math.floor(noise * 6) % 6];
      if (rt) { const sp = new Sprite(rt); if (mars) sp.tint = 0xc98a6a; sp.anchor.set(0.5, 0.82); const w = 30 + hash(y, x) * 20; sp.scale.set(w / rt.width); sp.position.set(m[0], m[1] + 4); g.ellipse(m[0] + 2, m[1] + 3, w * 0.5, w * 0.2).fill({ color: 0x000000, alpha: 0.28 }); g0.addChild(sp); }
      else { const r = 5 + noise * 4; g.poly([m[0] - r, m[1] + 2, m[0] - r * 0.4, m[1] - r * 0.9, m[0] + r * 0.7, m[1] - r * 0.6, m[0] + r, m[1] + 3, m[0], m[1] + 6]).fill(0x4a4855); }
    }
    // Places rovers visit: crater names, and the 1969 landing site with its descent stage and flag.
    for (const c of this.labels.removeChildren()) c.destroy();
    for (const p of s.pois) {
      const m = iso(p.x, p.y);
      if (p.bonus > 1) {
        prism(g, p.x - 0.45, p.y - 0.45, 0.9, 0.9, 0, 9, 0, 0xc9a24a);
        const f = iso(p.x + 0.9, p.y - 0.3);
        g.moveTo(f[0], f[1]).lineTo(f[0], f[1] - 22).stroke({ color: 0xe9e6f5, width: 1.5 });
        g.rect(f[0], f[1] - 22, 11, 7).fill(0xf2efe6).rect(f[0], f[1] - 22, 5, 3.5).fill(0x3a5fc4);
      } else g.circle(m[0], m[1], 3).fill({ color: 0x22d3ee, alpha: 0.75 });
      const t = new Text({ text: p.name.toUpperCase() + (p.bonus > 1 ? ' · 1969' : ''), style: { fontFamily: 'Space Mono, ui-monospace, monospace', fontSize: 10, fontWeight: '600', fill: p.bonus > 1 ? 0xffe2a8 : 0xe9e6f5, letterSpacing: 1 } });
      t.anchor.set(0.5, 0); t.position.set(m[0], m[1] + (p.bonus > 1 ? 14 : 7)); t.alpha = p.bonus > 1 ? 0.95 : 0.6; t.resolution = 2;
      this.labels.addChild(t);
    }
  }

  // ----- buildings, redrawn when the set of buildings changes -----
  private drawBuildings(s: State) {
    this.objects.removeChild(this.halo); this.haloKey = '';   // the selection line is kept and put back by the next frame
    const was = new Map<number, number>(); for (const [k, e] of this.glows) was.set(k, e.alpha);   // lights already on stay on through a redraw
    this.glows.clear(); this.bodyTint = -1;
    for (const c of this.objects.removeChildren()) c.destroy({ children: true });
    const n = s.size;
    this.spots = s.buildings.filter(b => b.type !== 'conduit' && b.progress >= 1 && b.connected).map(b => [b.x + BUILDINGS[b.type].w + 0.15, b.y + BUILDINGS[b.type].h * 0.5] as [number, number]);
    for (const b of s.buildings) {
      const d = BUILDINGS[b.type], L = LOOK[b.type], H = L.hgt * (1 + 0.55 * ((b.level || 1) - 1));
      const g = new Graphics();
      const built = b.progress >= 1;
      const alpha = built ? 1 : 0.42;
      let top = L.top;
      if (built && (!b.on || !b.connected)) top = mix(top, 0x5a5866, 0.65);
      if (b.damaged) top = mix(top, 0x8f2a2a, 0.6);
      if (b.type === 'conduit') {
        const m = iso(b.x + 0.5, b.y + 0.5);
        const col = built ? (b.connected ? 0xb9b4d6 : 0x77738a) : 0x55526a;
        const link = (dx: number, dy: number) => {
          const X = b.x + dx, Y = b.y + dy;
          if (X < 0 || Y < 0 || X >= n || Y >= n || !s.occ[Y * n + X]) return;
          const e = iso(b.x + 0.5 + dx * 0.5, b.y + 0.5 + dy * 0.5);
          g.moveTo(m[0], m[1]).lineTo(e[0], e[1]).stroke({ color: 0x15131f, width: 7, alpha: 0.7 * alpha });
          g.moveTo(m[0], m[1]).lineTo(e[0], e[1]).stroke({ color: col, width: 3.5, alpha });
        };
        link(1, 0); link(-1, 0); link(0, 1); link(0, -1);
        g.circle(m[0], m[1], 4.5).fill({ color: 0x15131f, alpha }).circle(m[0], m[1], 3).fill({ color: col, alpha });
        g.zIndex = (b.x + b.y) * 10;
      } else {
        // contact shadow
        const sa = iso(b.x, b.y), sb = iso(b.x + d.w, b.y), sc = iso(b.x + d.w, b.y + d.h), sd = iso(b.x, b.y + d.h);
        g.poly([sa[0], sa[1], sb[0], sb[1], sc[0], sc[1], sd[0], sd[1]]).fill({ color: 0x000000, alpha: 0.22 * alpha });
        const art = artOf(b), tex = art && TEX.get(art);
        if (art && tex) {
          const m = iso(b.x + d.w / 2, b.y + d.h / 2);
          const sp = new Sprite(tex); sp.anchor.set(art.ax, art.ay); sp.scale.set(art.k); sp.position.set(m[0], m[1]); sp.alpha = alpha;
          sp.tint = b.damaged ? 0xd98a8a : built && (!b.on || !b.connected) ? 0x8f8d99 : 0xffffff;
          g.addChild(sp);
        } else prism(g, b.x, b.y, d.w, d.h, 0, H, L.inset, top, alpha);
        if (b.type === 'solar') {
          for (let i = 1; i < 4; i++) {
            const p = iso(b.x + L.inset + (i * (d.w - 2 * L.inset)) / 4, b.y + L.inset, H), q = iso(b.x + L.inset + (i * (d.w - 2 * L.inset)) / 4, b.y + d.h - L.inset, H);
            g.moveTo(p[0], p[1]).lineTo(q[0], q[1]).stroke({ color: 0x9cc0ff, width: 1, alpha: 0.45 * alpha });
            const r = iso(b.x + L.inset, b.y + L.inset + (i * (d.h - 2 * L.inset)) / 4, H), t = iso(b.x + d.w - L.inset, b.y + L.inset + (i * (d.h - 2 * L.inset)) / 4, H);
            g.moveTo(r[0], r[1]).lineTo(t[0], t[1]).stroke({ color: 0x9cc0ff, width: 1, alpha: 0.45 * alpha });
          }
        }
        if (L.cap !== undefined) prism(g, b.x + d.w * 0.28, b.y + d.h * 0.28, d.w * 0.44, d.h * 0.44, H, 9, 0, b.damaged ? mix(L.cap, 0x8f2a2a, 0.6) : L.cap, alpha);
        if (b.type === 'pad') {
          const m = iso(b.x + d.w / 2, b.y + d.h / 2, H);
          g.ellipse(m[0], m[1], 44, 22).stroke({ color: 0x22d3ee, width: 2, alpha: 0.8 * alpha });
          g.ellipse(m[0], m[1], 22, 11).stroke({ color: 0xf2efe6, width: 1.5, alpha: 0.6 * alpha });
        }
        if (!built) {
          const a = iso(b.x, b.y), bb = iso(b.x + d.w, b.y), c = iso(b.x + d.w, b.y + d.h), dd = iso(b.x, b.y + d.h);
          g.poly([a[0], a[1], bb[0], bb[1], c[0], c[1], dd[0], dd[1]]).stroke({ color: 0x22d3ee, width: 1.5, alpha: 0.9 });
        }
        g.zIndex = (b.x + d.w + b.y + d.h) * 10 + 1;
        if (art && tex) {
          if (b.level > 1 + (SET[b.type]?.levels?.length || 0)) { const m = iso(b.x + d.w / 2, b.y + d.h / 2, art.top + 10); const t = new Text({ text: 'L' + b.level, style: { fontFamily: 'Space Mono, ui-monospace, monospace', fontSize: 11, fontWeight: '700', fill: 0xffc15e, stroke: { color: 0x0b0a14, width: 3 } } }); t.anchor.set(0.5); t.position.set(m[0], m[1]); t.resolution = 2; g.addChild(t); }
        } else if (d.short && b.type !== 'pad') {
          const capLift = L.cap !== undefined ? 9 : 0;
          const m = iso(b.x + d.w / 2, b.y + d.h / 2, H + capLift);
          const t = new Text({ text: d.short + (b.level > 1 ? b.level : ''), style: { fontFamily: 'Space Mono, ui-monospace, monospace', fontSize: d.w * d.h > 1 ? 13 : 10, fontWeight: '600', fill: L.cap !== undefined ? 0x2a1e05 : L.ink } });
          t.anchor.set(0.5); t.position.set(m[0], m[1]); t.alpha = alpha; t.resolution = 2;
          g.addChild(t);
        }
      }
      this.objects.addChild(g);
      // Night lights: the lit parts of the picture, added over it. They sit outside the body so the night tint, which
      // darkens the body, leaves them bright.
      const ga = b.type !== 'conduit' && built ? artOf(b) : undefined, gt = ga && TEX.get(ga) && GLOW.get(ga);
      if (ga && gt) {
        const m = iso(b.x + d.w / 2, b.y + d.h / 2), e = new Sprite(gt);
        e.anchor.set(ga.ax, ga.ay); e.scale.set(ga.k); e.position.set(m[0], m[1]); e.blendMode = 'add'; e.alpha = was.get(b.uid) || 0; e.zIndex = g.zIndex + 0.2;
        this.objects.addChild(e); this.glows.set(b.uid, e);
      }
    }
  }

  // ----- every frame -----
  frame(s: State, selected: number | null, tool: string | null, hover: { x: number; y: number } | null, hoverOk: 'ok' | 'warn' | 'bad', now: number, speed = 1, overlay = false) {
    this.useArt(s);
    if (this.drawnSeed !== s.seed) { this.drawTerrain(s); this.drawnSeed = s.seed; this.drawnRev = -1; }
    if (this.drawnRev !== s.rev) { this.drawBuildings(s); this.drawZones(s); this.drawnRev = s.rev; }
    this.heat.visible = overlay;
    if (overlay && this.heatRev !== s.rev) { this.drawHeat(s); this.heatRev = s.rev; }

    // light: quick dawn and dusk, warm near the horizon, blue-black at night
    // Daylight comes up fast after sunrise; a short twilight either side of the night keeps the cut from being abrupt.
    const ph = phaseOf(s.t), day = lightHours(), sun = sunFactor(s.t);
    const tw = Math.max(0.7, span(8));   // hours of twilight: eight on the Moon, well under one on Mars
    const light = ph < day ? Math.min(1, 0.35 + sun * 10) : Math.max(0, 0.35 * (1 - (ph - day) / tw), 0.35 * (1 - (dayHours() - ph) / tw));
    // The Moon's low sun is warm and its day is white. On Mars the twilight is blue and the day is butterscotch, and a
    // dust storm turns everything the colour of the dust and takes most of the light.
    const mars = s.world === 'mars', haze = mars && hazeActive(s);
    let tint = mars ? (light < 0.5 ? mix(0x3d4468, 0xa9b8dc, light * 2) : mix(0xa9b8dc, 0xfff0e2, (light - 0.5) * 2))
      : light < 0.5 ? mix(0x4c5a86, 0xffcf9a, light * 2) : mix(0xffcf9a, 0xffffff, (light - 0.5) * 2);
    if (haze) tint = shade(mix(tint, 0xd08a55, 0.55), 0.74);
    this.terrain.tint = tint; this.labels.tint = tint; this.zones.tint = mix(tint, 0xffffff, 0.5);
    const dark = 1 - light;
    // Buildings take the tint one by one, so their night lights and the selection line, which sit beside them, stay bright.
    if (tint !== this.bodyTint) { this.bodyTint = tint; const lit = new Set<unknown>(this.glows.values()); for (const c of this.objects.children) if (c !== this.halo && !lit.has(c)) c.tint = tint; }
    const dusk = dark <= 0.3 ? 0 : dark >= 0.75 ? 1 : (dark - 0.3) / 0.45, lamps = dusk * dusk * (3 - 2 * dusk);   // lights come on as the sun goes

    const o = this.overlay, l = this.lights; o.clear(); l.clear();
    const blink = Math.floor(now / 420) % 2 === 0;
    for (const b of s.buildings) {
      const d = BUILDINGS[b.type], L = LOOK[b.type], H = L.hgt * (1 + 0.55 * ((b.level || 1) - 1));
      if (b.type === 'conduit') continue;
      const art = artOf(b);
      const m = iso(b.x + d.w / 2, b.y + d.h / 2, art ? art.top + 4 : H + (L.cap !== undefined ? 9 : 0));
      const py = m[1] - 16;
      if (b.progress < 1) {
        o.rect(m[0] - 15, py - 2, 30, 5).fill({ color: 0x0b0a14, alpha: 0.85 });
        o.rect(m[0] - 14, py - 1, 28 * b.progress, 3).fill(0x22d3ee);
        continue;
      }
      const needsPower = d.drawDay > 0 || d.drawNight > 0;
      let pip = -1;
      if (b.damaged) pip = blink || b.repair > 0 ? 0xff5a5f : -1;
      else if (!b.connected) pip = 0xff9a3d;
      else if (!b.on) pip = 0x8e8aa3;
      else if (b.asleep) pip = 0x5f6fb5;
      else if (needsPower && !b.powered) pip = blink ? 0xff5a5f : -1;
      if (pip >= 0) {
        o.circle(m[0], py, 5.5).fill(0x0b0a14).circle(m[0], py, 3.6).fill(pip);
        if (b.damaged && b.repair > 0) o.circle(m[0], py, 7.5).stroke({ color: 0xffc15e, width: 1.5 });
      }
      // Lights are on in a building that is running and has power; one that draws none is lit while the town has charge.
      const glow = this.glows.get(b.uid);
      if (glow) {
        const on = b.connected && !b.damaged && b.on && (needsPower ? b.powered : s.charge > 1 || (d.gen > 0 && !d.solar));
        glow.alpha += ((on ? lamps : 0) - glow.alpha) * 0.08; if (glow.alpha < 0.004) glow.alpha = 0;
        glow.visible = glow.alpha > 0;
      }
    }
    this.actors(s, o, l, tint, dark, now, speed);
    // The selected building: its plot lit on the ground beneath it, and a line round its picture. Both sit at the
    // building's own depth, so neither is drawn across a building standing in front.
    const mk = this.mark; mk.clear();
    const sb = selected !== null ? s.buildings.find(q => q.uid === selected) : undefined;
    const key = sb ? `${sb.uid}:${s.rev}:${TEX.size}` : '';
    if (key !== this.haloKey) {
      this.haloKey = key; this.objects.removeChild(this.halo);
      for (const c of this.halo.removeChildren()) c.destroy();
      const art = sb && artOf(sb), edge = art && edgeOf(art);
      if (sb && art && edge) {
        const d = BUILDINGS[sb.type], m = iso(sb.x + d.w / 2, sb.y + d.h / 2);
        for (let i = 0; i < 12; i++) { const sp = new Sprite(edge); sp.anchor.set(art.ax, art.ay); sp.scale.set(art.k); sp.position.set(m[0] + Math.cos(i * Math.PI / 6) * 3, m[1] + Math.sin(i * Math.PI / 6) * 3); sp.tint = 0x7af0ff; this.halo.addChild(sp); }
        this.halo.zIndex = (sb.x + d.w + sb.y + d.h) * 10 + 0.5; this.objects.addChild(this.halo);
      }
    }
    if (sb) {
      const d = BUILDINGS[sb.type], e = 0.14;
      const a = iso(sb.x - e, sb.y - e), b = iso(sb.x + d.w + e, sb.y - e), c = iso(sb.x + d.w + e, sb.y + d.h + e), f = iso(sb.x - e, sb.y + d.h + e);
      mk.poly([a[0], a[1], b[0], b[1], c[0], c[1], f[0], f[1]]).fill({ color: 0x22d3ee, alpha: 0.2 }).stroke({ color: 0x7af0ff, width: 2, alpha: 0.95 });
      if (!this.halo.children.length) this.outline(o, sb.x, sb.y, d.w, d.h, 0xffffff, 2);   // no picture: the old outline
    }
    // Zoomed far out the town is small: names would be specks, and the claim needs a line that stays visible.
    const tiny = this.scale < 0.3;
    this.labels.visible = this.findLabels.visible = !tiny;
    if (tiny) { const n = s.size, a = iso(0, 0), b = iso(n, 0), c = iso(n, n), f = iso(0, n); o.poly([a[0], a[1], b[0], b[1], c[0], c[1], f[0], f[1]]).stroke({ color: 0x22d3ee, width: 1.5 / this.scale, alpha: 0.8 }); }

    const gh = this.ghost; gh.clear();
    if (tool && hover) {
      const zone = tool.startsWith('zone') ? Number(tool.slice(4)) : -1;
      const d = zone >= 0 ? { w: 1, h: 1 } : BUILDINGS[tool as BuildingType];
      const zcol = zone > 0 ? ZONES[zone - 1].color : 0xffffff;
      const col = hoverOk === 'bad' ? 0xff5a5f : zone >= 0 ? zcol : hoverOk === 'warn' ? 0xff9a3d : 0x62d394;
      for (let j = 0; j < d.h; j++) for (let i = 0; i < d.w; i++) {
        const a = iso(hover.x + i, hover.y + j), b = iso(hover.x + i + 1, hover.y + j), c = iso(hover.x + i + 1, hover.y + j + 1), e = iso(hover.x + i, hover.y + j + 1);
        gh.poly([a[0], a[1], b[0], b[1], c[0], c[1], e[0], e[1]]).fill({ color: col, alpha: 0.38 });
      }
      this.outline(gh, hover.x, hover.y, d.w, d.h, col, 2);
    }
  }

  // ----- zoned land: a wash of the zone's colour, fainter where it is cut off from the base -----
  private drawZones(s: State) {
    const g = this.zones, n = s.size; g.clear();
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const k = y * n + x, z = s.zone[k], ore = s.ore[k], built = s.occ[k] > 0;
      if (!z && !ore) continue;
      const a = iso(x, y), b = iso(x + 1, y), c = iso(x + 1, y + 1), d = iso(x, y + 1), m = iso(x + 0.5, y + 0.5);
      if (z) {
        const col = ZONES[z - 1].color, linked = s.linked[k] > 0, level = s.prep[k] >= 1;
        // Raw ground is a faint outline strewn with rubble. Levelled ground is a clean, solid wash.
        g.poly([a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]]).fill({ color: col, alpha: built ? 0.16 : !linked ? 0.1 : level ? 0.4 : 0.13 }).stroke({ color: col, width: 1, alpha: linked ? 0.55 : 0.2 });
        if (!built && !level) {
          const h = (x * 7 + y * 13) % 5;
          for (const [dx, dy, r] of [[-9 + h, -2, 2.6], [6 - h, 3, 2.1], [1, -5 + h * 0.6, 1.7], [-3, 5, 1.5]]) g.poly([m[0] + dx - r, m[1] + dy + r * 0.5, m[0] + dx, m[1] + dy - r, m[0] + dx + r, m[1] + dy + r * 0.5]).fill({ color: 0x3a3848, alpha: 0.85 });
        } else if (!built) {
          const i1 = iso(x + 0.14, y + 0.14), i2 = iso(x + 0.86, y + 0.14), i3 = iso(x + 0.86, y + 0.86), i4 = iso(x + 0.14, y + 0.86);
          g.poly([i1[0], i1[1], i2[0], i2[1], i3[0], i3[1], i4[0], i4[1]]).stroke({ color: 0xffffff, width: 1, alpha: 0.16 });
        }
      }
      // A deposit the rovers found: a scatter of bright grains in the ore's colour.
      if (ore && !built) {
        const col = ORES[ore - 1].color, h = (x * 11 + y * 5) % 4;
        for (const [dx, dy] of [[-10 + h * 2, 0], [-2, -5 + h], [7 - h, 1], [1, 5], [-6, 4 - h]]) g.poly([m[0] + dx, m[1] + dy - 2.2, m[0] + dx + 3, m[1] + dy, m[0] + dx, m[1] + dy + 2.2, m[0] + dx - 3, m[1] + dy]).fill({ color: col, alpha: 0.9 });
      }
    }
    for (const c of this.findLabels.removeChildren()) c.destroy();
    for (const f of s.finds) {
      const m = iso(f.x, f.y), ore = ORES[f.kind];
      const t = new Text({ text: `${ore.name.toUpperCase()} · +${Math.round(ore.bonus * 100)}%`, style: { fontFamily: 'Space Mono, ui-monospace, monospace', fontSize: 11, fontWeight: '600', fill: ore.color, letterSpacing: 1 } });
      t.anchor.set(0.5, 0.5); t.position.set(m[0], m[1] - 30); t.resolution = 2;
      const plate = new Graphics(); plate.roundRect(m[0] - t.width / 2 - 6, m[1] - 30 - 9, t.width + 12, 18, 4).fill({ color: 0x15131f, alpha: 0.78 });
      this.findLabels.addChild(plate);
      this.findLabels.addChild(t);
    }
  }

  // ----- habitability map: red where nobody wants to live, green where they do -----
  private drawHeat(s: State) {
    const g = this.heat, n = s.size; g.clear();
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      if (s.ground[y * n + x] !== GROUND.flat) continue;
      const h = s.hab[y * n + x];
      const col = h < 50 ? mix(0xe5484d, 0xf5b83d, h / 50) : mix(0xf5b83d, 0x3ecf7a, (h - 50) / 50);
      const a = iso(x, y), b = iso(x + 1, y), c = iso(x + 1, y + 1), d = iso(x, y + 1);
      g.poly([a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]]).fill({ color: col, alpha: 0.5 });
    }
  }

  // ----- things that move: people, rovers, the shuttle, credits earned -----
  private actors(s: State, o: Graphics, l: Graphics, tint: number, dark: number, now: number, speed: number) {
    const dt = Math.min(0.1, (now - this.lastNow) / 1000) * Math.min(speed, 4); this.lastNow = now;
    const lit = (c: number) => mix(mix(0x000000, c, 0.55 + 0.45 * (1 - dark)), tint, 0.25);

    // people walking between buildings
    const want = this.spots.length >= 2 ? Math.min(36, Math.round(population(s) * 0.7)) : 0;
    const pickSpot = () => this.spots[Math.floor(Math.random() * this.spots.length)];
    while (this.walkers.length < want) { const a = pickSpot(), b = pickSpot(); this.walkers.push({ ax: a[0], ay: a[1], bx: b[0], by: b[1], t: Math.random(), v: 0.5 + Math.random() * 0.5 }); }
    if (this.walkers.length > want) this.walkers.length = want;
    for (const w of this.walkers) {
      const dist = Math.hypot(w.bx - w.ax, w.by - w.ay) || 1;
      w.t += (dt * w.v) / dist;
      if (w.t >= 1) { const b = pickSpot(); w.ax = w.bx; w.ay = w.by; w.bx = b[0]; w.by = b[1]; w.t = 0; }
      const p = iso(w.ax + (w.bx - w.ax) * w.t, w.ay + (w.by - w.ay) * w.t);
      o.ellipse(p[0], p[1] + 1, 3.4, 1.7).fill({ color: 0x000000, alpha: 0.35 });
      o.rect(p[0] - 1.6, p[1] - 7, 3.2, 7).fill(lit(0xf7f4ee));
      o.circle(p[0], p[1] - 8.5, 2.2).fill(lit(0xffc15e));
    }

    // rovers
    for (const r of s.rovers) {
      if (r.phase === 'idle') continue;
      const a = iso(r.hx, r.hy), b = iso(s.pois[r.poi].x, s.pois[r.poi].y), p = iso(r.x, r.y);
      o.moveTo(a[0], a[1]).lineTo(b[0], b[1]).stroke({ color: 0x22d3ee, width: 1, alpha: 0.2 });
      o.ellipse(p[0], p[1] + 2, 9, 4.5).fill({ color: 0x000000, alpha: 0.3 });
      prism(o, r.x - 0.22, r.y - 0.22, 0.44, 0.44, 2, 6, 0, lit(r.pax > 0 ? 0xffc15e : 0xe6e9ee));
      prism(o, r.x - 0.12, r.y - 0.12, 0.24, 0.24, 8, 3, 0, lit(0x7fb6e8));
      if (dark > 0.05) l.ellipse(p[0], p[1], 20, 10).fill({ color: 0xfff1c9, alpha: 0.22 * dark });
    }

    // graders: yellow machines that level zoned ground, throwing dust while they work
    for (const gr of s.graders) {
      const home = Math.hypot(gr.x - s.size / 2, gr.y - s.size / 2) < 0.2;
      if (gr.phase === 'idle' && home) continue;
      const p = iso(gr.x, gr.y);
      o.ellipse(p[0], p[1] + 2, 10, 5).fill({ color: 0x000000, alpha: 0.3 });
      prism(o, gr.x - 0.26, gr.y - 0.2, 0.52, 0.4, 2, 5, 0, lit(0xf2b632));
      prism(o, gr.x - 0.08, gr.y - 0.12, 0.26, 0.24, 7, 4, 0, lit(0x2b2a33));
      prism(o, gr.x - 0.34, gr.y - 0.26, 0.08, 0.52, 1, 4, 0, lit(0x9aa3ad));
      if (gr.phase === 'work') {
        for (let i = 0; i < 4; i++) {
          const ph = (now / 900 + i * 0.25) % 1;
          o.circle(p[0] - 8 + i * 5 + Math.sin(i * 2.1) * 3, p[1] - 4 - ph * 14, 3 + ph * 5).fill({ color: 0xb9b3a6, alpha: 0.32 * (1 - ph) });
        }
      }
      if (dark > 0.05) l.ellipse(p[0], p[1], 18, 9).fill({ color: 0xffe9a8, alpha: 0.22 * dark });
    }

    // the shuttle
    const sh = s.shuttle, pad = s.buildings.find(q => q.type === 'pad');
    if (pad && sh.phase !== 'away') {
      const k = sh.phase === 'landing' ? Math.max(0, sh.timer) / 3 : sh.phase === 'launching' ? 1 - Math.max(0, sh.timer) / 3 : 0;
      const z = 460 * Math.pow(k, 1.6), cx = pad.x + 1.5, cy = pad.y + 1.5;
      const g0 = iso(cx, cy, 2);
      o.ellipse(g0[0], g0[1], 30 * (1 - k * 0.7), 15 * (1 - k * 0.7)).fill({ color: 0x000000, alpha: 0.35 * (1 - k * 0.8) });
      for (const [dx, dy] of [[-0.55, -0.55], [0.55, -0.55], [0.55, 0.55], [-0.55, 0.55]]) { const f = iso(cx + dx, cy + dy, z + 2), c = iso(cx + dx * 0.5, cy + dy * 0.5, z + 10); o.moveTo(f[0], f[1]).lineTo(c[0], c[1]).stroke({ color: lit(0xb9bec8), width: 2 }); }
      prism(o, cx - 0.5, cy - 0.5, 1, 1, z + 8, 26, 0, lit(0xe3e7ee));
      prism(o, cx - 0.3, cy - 0.3, 0.6, 0.6, z + 34, 12, 0, lit(0xffc15e));
      if (k > 0) { const e = iso(cx, cy, z + 4); l.ellipse(e[0], e[1] + 8, 16, 22).fill({ color: 0x9fd0ff, alpha: 0.5 }); l.ellipse(e[0], e[1] + 4, 8, 12).fill({ color: 0xffffff, alpha: 0.7 }); }
    }

    // credits floating up where they were earned
    for (const pop of s.pops) {
      if (pop.id <= this.seenPop) continue;
      this.seenPop = pop.id;
      const m = iso(pop.x, pop.y, 30);
      const t = new Text({ text: pop.text, style: { fontFamily: 'Space Mono, ui-monospace, monospace', fontSize: 15, fontWeight: '700', fill: 0x67e8f9, stroke: { color: 0x15131f, width: 3 } } });
      t.anchor.set(0.5); t.position.set(m[0], m[1]); t.resolution = 2; (t as any).born = now;
      this.fx.addChild(t);
    }
    for (const t of [...this.fx.children]) {
      const age = (now - (t as any).born) / 1800;
      if (age >= 1) { t.destroy(); continue; }
      t.position.y -= 0.45; t.alpha = 1 - age * age;
    }
  }
  resetActors(s: State) { this.seenPop = s.pops.length ? s.pops[s.pops.length - 1].id : 0; this.walkers.length = 0; for (const c of this.fx.removeChildren()) c.destroy(); }

  private outline(g: Graphics, x: number, y: number, w: number, h: number, color: number, width: number) {
    const a = iso(x, y), b = iso(x + w, y), c = iso(x + w, y + h), d = iso(x, y + h);
    g.poly([a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]]).stroke({ color, width, alpha: 0.95 });
  }
}

