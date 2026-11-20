// The lunar ground as one lit picture, built once per town.
// A height field (the town's own craters and a scatter of small ones) is shaded by the same sun the
// buildings are lit by, then multiplied into a dust texture. Drawing only: the simulation is not read back from it.

import { State, GROUND } from '../sim/sim';

export const GP = 48;   // texture pixels per tile, looking straight down

const hash2 = (x: number, y: number, s: number) => {
  let h = (x * 374761393 + y * 668265263 + s * 974711) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
};
function vnoise(x: number, y: number, s: number) {
  const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi;
  const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
  const a = hash2(xi, yi, s), b = hash2(xi + 1, yi, s), c = hash2(xi, yi + 1, s), d = hash2(xi + 1, yi + 1, s);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
// A box blur, across then down, with running sums.
function blur(src: Float32Array, tmp: Float32Array, N: number, r: number) {
  const w = 2 * r + 1;
  for (let y = 0; y < N; y++) {
    const o = y * N; let acc = 0;
    for (let x = -r; x <= r; x++) acc += src[o + Math.min(N - 1, Math.max(0, x))];
    for (let x = 0; x < N; x++) { tmp[o + x] = acc / w; acc += src[o + Math.min(N - 1, x + r + 1)] - src[o + Math.max(0, x - r)]; }
  }
  for (let x = 0; x < N; x++) {
    let acc = 0;
    for (let y = -r; y <= r; y++) acc += tmp[Math.min(N - 1, Math.max(0, y)) * N + x];
    for (let y = 0; y < N; y++) { src[y * N + x] = acc / w; acc += tmp[Math.min(N - 1, y + r + 1) * N + x] - tmp[Math.max(0, y - r) * N + x]; }
  }
}

// Crater stamps rendered in Blender: shading only, 128 = level ground, with a soft edge. rim = where the crest sits, as a share of half the picture.
export interface Stamp { img: HTMLImageElement; rim: number; }

export function buildGround(s: State, detail: HTMLImageElement | null, stamps: Stamp[] = []): HTMLCanvasElement {
  const n = s.size, N = n * GP;
  const h = new Float32Array(N * N), tmp = new Float32Array(N * N);

  // Find each of the town's craters from its marker (the marker sits just above the crater's top edge), then measure its
  // radius against the floor tiles. Each one gets a rendered stamp; floor that no stamp covers keeps the calculated bowl.
  const big: { x: number; y: number; r: number }[] = [];
  if (stamps.length) for (const p of s.pois) {
    if (p.bonus > 1) continue;
    let best = -1e9, br = 0;
    for (let r = 1.5; r <= 4.2; r += 0.1) {
      const cx = p.x, cy = p.y + r + 1.2; let sc = 0;
      for (let ty = Math.max(0, Math.floor(cy - r - 2)); ty < Math.min(n, Math.ceil(cy + r + 2)); ty++) for (let tx = Math.max(0, Math.floor(cx - r - 2)); tx < Math.min(n, Math.ceil(cx + r + 2)); tx++) {
        const d = Math.hypot(tx + 0.5 - cx, ty + 0.5 - cy), fl = s.ground[ty * n + tx] === GROUND.floor;
        if (d < r - 0.55) sc += fl ? 1 : -3; else if (d > r + 0.55 && d < r + 1.5 && fl) sc -= 1;
      }
      if (sc > best) { best = sc; br = r; }
    }
    if (best > 2) big.push({ x: p.x, y: p.y + br + 1.2, r: br });
  }
  const stamped = (tx: number, ty: number) => big.some(b => Math.hypot(tx + 0.5 - b.x, ty + 0.5 - b.y) < b.r + 0.75);

  // The town's craters, from its tiles: a sunken floor inside a raised rim, smoothed into a bowl.
  for (let ty = 0; ty < n; ty++) for (let tx = 0; tx < n; tx++) {
    const k = s.ground[ty * n + tx], v = k === GROUND.floor ? -1 : k === GROUND.rim ? 0.42 : 0;
    if (!v || stamped(tx, ty)) continue;
    for (let y = ty * GP; y < (ty + 1) * GP; y++) { const o = y * N; for (let x = tx * GP; x < (tx + 1) * GP; x++) h[o + x] = v; }
  }
  const r = Math.round(GP * 0.42);
  blur(h, tmp, N, r); blur(h, tmp, N, r);

  // A scatter of small craters: many tiny, few large, each a bowl with a low rim.
  let seed = (s.seed | 0) ^ 0x5f3759df;
  const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) | 0; return (seed >>> 0) / 4294967296; };
  // Shading from the rendered stamps: one grey picture, 128 where the ground is level.
  const sc = document.createElement('canvas'); sc.width = sc.height = N;
  const sctx = sc.getContext('2d')!; sctx.fillStyle = 'rgb(128,128,128)'; sctx.fillRect(0, 0, N, N);
  const put = (k: number, cx: number, cy: number, rPx: number) => { const st = stamps[k % stamps.length], d = 2 * rPx / st.rim; sctx.drawImage(st.img, cx - d / 2, cy - d / 2, d, d); };
  for (let i = 0; i < 300; i++) {
    const cr = (0.08 + Math.pow(rnd(), 3.1) * 0.95) * GP, cx = rnd() * N, cy = rnd() * N, dep = (0.3 + 0.25 * rnd()) * cr / GP + 0.035, R = cr * 1.7;
    if (stamps.length && cr > 0.3 * GP) { if (!big.some(b => Math.hypot(cx / GP - b.x, cy / GP - b.y) < b.r + cr / GP + 0.6)) put(i, cx, cy, cr); continue; }
    for (let y = Math.max(0, Math.floor(cy - R)); y < Math.min(N, Math.ceil(cy + R)); y++) {
      const o = y * N;
      for (let x = Math.max(0, Math.floor(cx - R)); x < Math.min(N, Math.ceil(cx + R)); x++) {
        const d = Math.hypot(x - cx, y - cy) / cr;
        if (d > 1.7) continue;
        h[o + x] += d < 1 ? -dep * (1 - d * d) + 0.22 * dep * d * d * d * d : 0.22 * dep * Math.exp(-((d - 1) * (d - 1)) / 0.06);
      }
    }
  }

  big.forEach((b, i) => put([0, 3, 1, 0, 2, 3][i % 6], b.x * GP, b.y * GP, b.r * GP));
  const spx = sctx.getImageData(0, 0, N, N).data;

  // The dust texture, repeated; then light it.
  const cv = document.createElement('canvas'); cv.width = cv.height = N;
  const ctx = cv.getContext('2d')!;
  if (detail) { const dw = detail.width * GP / 64; for (let y = 0; y < N; y += dw) for (let x = 0; x < N; x += dw) ctx.drawImage(detail, x, y, dw, dw); }
  else { ctx.fillStyle = '#808080'; ctx.fillRect(0, 0, N, N); }
  const img = ctx.getImageData(0, 0, N, N), px = img.data;
  // The sun stands toward +x, +y (the near corner of the map), as it does for the buildings, a little lower so relief shows.
  const Lx = 0.42, Ly = 0.62, Lz = 0.6, Ln = Math.hypot(Lx, Ly, Lz), lx = Lx / Ln, ly = Ly / Ln, lz = Lz / Ln;
  const K = GP * 0.5 * 1.15, sd = s.seed | 0;
  for (let y = 0; y < N; y++) {
    const o = y * N, om = (y > 0 ? y - 1 : y) * N, op = (y < N - 1 ? y + 1 : y) * N, ty = (y / GP) | 0;
    for (let x = 0; x < N; x++) {
      const gx = (h[o + (x < N - 1 ? x + 1 : x)] - h[o + (x > 0 ? x - 1 : x)]) * K, gy = (h[op + x] - h[om + x]) * K;
      let sh = (-gx * lx - gy * ly + lz) / Math.sqrt(gx * gx + gy * gy + 1) / lz;
      sh = sh < 0.2 ? 0.2 : sh > 1.65 ? 1.65 : sh;
      const k = s.ground[ty * n + ((x / GP) | 0)];
      // large soft patches of lighter and darker soil, so the repeat of the texture does not show
      const patch = 0.84 + 0.2 * vnoise(x / GP / 7 + 31, y / GP / 7 + 17, sd) + 0.1 * vnoise(x / GP / 2.2, y / GP / 2.2, sd + 5);
      const i = (o + x) * 4, f = sh * patch * (spx[i] / 128) * 0.83;
      const warm = k === GROUND.heritage ? 1 : 0;
      const rr = px[i] * f * (0.985 + 0.1 * warm), gg = px[i + 1] * f * (0.975 + 0.04 * warm), bb = px[i + 2] * f * (1.04 - 0.14 * warm);
      px[i] = rr > 255 ? 255 : rr; px[i + 1] = gg > 255 ? 255 : gg; px[i + 2] = bb > 255 ? 255 : bb;
    }
  }
  ctx.putImageData(img, 0, 0);
  return cv;
}

// The land around the claim, so the town stands on the Moon and not on a slab: the same soil and light at a coarser
// grain, M tiles out on every side, with its own scatter of rendered craters. Soil patches and the dust texture line up
// with the claim's own picture so the join does not show.
export function buildOutskirts(s: State, detail: HTMLImageElement | null, stamps: Stamp[], M: number, gp: number): HTMLCanvasElement {
  const n = s.size, T = n + 2 * M, N = T * gp;
  const cv = document.createElement('canvas'); cv.width = cv.height = N;
  const ctx = cv.getContext('2d')!;
  if (detail) { const dw = 16 * gp; for (let y = 0; y < N; y += dw) for (let x = 0; x < N; x += dw) ctx.drawImage(detail, x, y, dw, dw); }
  else { ctx.fillStyle = '#808080'; ctx.fillRect(0, 0, N, N); }
  const sc = document.createElement('canvas'); sc.width = sc.height = N;
  const sctx = sc.getContext('2d')!; sctx.fillStyle = 'rgb(128,128,128)'; sctx.fillRect(0, 0, N, N);
  let seed = (s.seed | 0) ^ 0x2545f491;
  const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) | 0; return (seed >>> 0) / 4294967296; };
  if (stamps.length) for (let i = 0; i < 420; i++) {
    const r = 0.5 + Math.pow(rnd(), 2.6) * 7, tx = rnd() * T - M, ty = rnd() * T - M, k = Math.floor(rnd() * stamps.length);
    if (tx > -r * 1.4 - 1 && tx < n + r * 1.4 + 1 && ty > -r * 1.4 - 1 && ty < n + r * 1.4 + 1) continue;   // none cut by the claim's edge
    const st = stamps[k], d = 2 * r * gp / st.rim; sctx.drawImage(st.img, (tx + M) * gp - d / 2, (ty + M) * gp - d / 2, d, d);
  }
  const spx = sctx.getImageData(0, 0, N, N).data, img = ctx.getImageData(0, 0, N, N), px = img.data, sd = s.seed | 0;
  for (let y = 0; y < N; y++) {
    const ty = y / gp - M;
    for (let x = 0; x < N; x++) {
      const tx = x / gp - M, i = (y * N + x) * 4;
      const patch = 0.84 + 0.2 * vnoise(tx / 7 + 31, ty / 7 + 17, sd) + 0.1 * vnoise(tx / 2.2, ty / 2.2, sd + 5);
      const f = patch * (spx[i] / 128) * 0.83 * bend(tx - n / 2, ty - n / 2);
      const rr = px[i] * f * 0.985, gg = px[i + 1] * f * 0.975, bb = px[i + 2] * f * 1.04;
      px[i] = rr > 255 ? 255 : rr; px[i + 1] = gg > 255 ? 255 : gg; px[i + 2] = bb > 255 ? 255 : bb;
    }
  }
  ctx.putImageData(img, 0, 0);
  return cv;
}

// ----- the land curves away -----
// The claim stands on a level cap of ground. Past the cap the land bends down and away on a circle, like the top of a
// globe, so it ends in a true horizon: craters flatten as they near it and the edge belongs to the ground, not the screen.
// Seen as the town is drawn: from 30 degrees above, with no perspective.
export const CAP = 27;    // tiles from the claim's centre that stay level (the claim's corners are 25.5 out)
export const BEND = 60;   // radius of the bend, in tiles
const UP = 32 * Math.SQRT2 * Math.cos(Math.PI / 6);   // screen pixels for one tile of height
const SUN = (() => { const l = Math.hypot(0.42, 0.62, 0.6); return [0.42 / l, 0.62 / l, 0.6 / l]; })();
const LEVEL = SUN[2] / (SUN[2] + 0.5);

// How bright bent ground looks next to level ground. Moon dust does not darken toward the edge of the disc the way a
// matt ball does (the full Moon is as bright at its rim as at its centre), so this follows the dust, not the ball.
// Far round the bend, past what the picture covers, the land falls into shadow.
function bend(dx: number, dy: number): number {
  const s = Math.hypot(dx, dy);
  if (s <= CAP) return 1;
  const th = (s - CAP) / BEND, st = Math.sin(th), ct = Math.cos(th), cf = dx / s, sf = dy / s;
  const seen = Math.max(0, st * 0.8660254 * (cf + sf) * 0.70710678 + 0.5 * ct);
  const lit = st * (SUN[0] * cf + SUN[1] * sf) + SUN[2] * ct;
  let f = lit <= 0 ? 0.05 : lit / (lit + seen) / LEVEL;
  f = f < 0.3 ? 0.3 : f > 1.22 ? 1.22 : f;
  const k = th <= 0.7 ? 0 : th >= 0.9 ? 1 : (th - 0.7) / 0.2;
  return f * (1 - 0.95 * k * k * (3 - 2 * k));
}

// The bent land as a net of triangles, in the town's own screen units, with where each corner falls on the outskirts
// picture. It stops exactly at the horizon in every direction, so no hidden ground is drawn.
export function landNet(n: number, M: number): { positions: Float32Array; uvs: Float32Array; indices: Uint32Array } {
  const A = 180, K = 30, T = n + 2 * M, C = n / 2, reach = C + M - 1;
  const positions = new Float32Array(A * (K + 1) * 2), uvs = new Float32Array(A * (K + 1) * 2), indices: number[] = [];
  for (let j = 0; j < A; j++) {
    const f = 2 * Math.PI * j / A, cf = Math.cos(f), sf = Math.sin(f);
    const edge = Math.atan2(0.5, -0.8660254 * (cf + sf) * 0.70710678);   // how far round the bend the horizon lies, this way
    for (let k = 0; k <= K; k++) {
      const th = k < 2 ? 0 : edge * (k - 1) / (K - 1), r = k === 0 ? 0 : CAP + BEND * Math.sin(th), h = -BEND * (1 - Math.cos(th));
      const s = Math.min(k === 0 ? 0 : CAP + BEND * th, reach), i = (j * (K + 1) + k) * 2;
      positions[i] = (r * cf - r * sf) * 32; positions[i + 1] = (r * cf + r * sf) * 16 - h * UP + n * 16;
      uvs[i] = (C + s * cf + M) / T; uvs[i + 1] = (C + s * sf + M) / T;
    }
    const a = j * (K + 1), b = ((j + 1) % A) * (K + 1);
    for (let k = 0; k < K; k++) indices.push(a + k, a + k + 1, b + k + 1, a + k, b + k + 1, b + k);
  }
  return { positions, uvs, indices: new Uint32Array(indices) };
}
