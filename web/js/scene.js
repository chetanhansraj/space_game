/* The view out of the window.
 *
 * Rendering only. Every position here comes from the server: node sites from
 * orbital's anchors, ships from the world tick, planets from the ephemerides
 * at the world's sky time, and the Sun's direction from the Moon's real phase.
 * Nothing in this file decides anything; it draws what the server says.
 */
(function () {
  "use strict";
  const R = 2;                       // lunar radius in scene units
  const DEG = Math.PI / 180;
  const COL = {
    cyan: 0x06b6d4, cyanSoft: 0x67e8f9, violet: 0x8b5cf6, violetSoft: 0xa78bfa,
    pink: 0xf472b6, amber: 0xfbbf24, white: 0xe2e8f0,
  };

  // Same mapping as lunarark.com's moon_sim, so a site sits on the same pixel.
  function ll(lat, lon, r) {
    const phi = (90 - lat) * DEG, th = (lon + 180) * DEG;
    return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(th), r * Math.cos(phi),
      r * Math.sin(phi) * Math.sin(th));
  }

  function rng(seed) {                // mulberry32: the same Moon every load
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function glowTexture(inner, outer) {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d"), grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0, inner); grad.addColorStop(0.25, outer);
    grad.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  // Real craters, real places. Diameters in km. The albedo map carries the
  // maria; these give the surface its bite when you zoom in, and put
  // Shackleton and Peary exactly where the anchors say the ports are.
  const LANDMARKS = [
    [-89.67, 129.78, 21], [88.63, 30.3, 73], [-43.31, -11.36, 85], [9.62, -20.08, 96],
    [-58.8, -14.1, 225], [51.6, -9.4, 101], [-25.1, 60.4, 188], [-8.9, 61.1, 132],
    [-11.4, 26.4, 99], [-5.2, -68.6, 172], [-9.3, -1.9, 153], [8.1, -38.0, 31],
    [23.7, -47.4, 40], [-88.5, -87.1, 32], [-88.1, 44.9, 51], [-87.45, -5.0, 51],
    [-87.3, 77.0, 39], [86.0, -89.9, 104], [-84.9, 142, 110], [-83.8, 172, 97],
    [-79.4, 30, 180], [80.2, 80, 72], [62.0, -86, 96], [-76.7, -49, 225],
  ];
  const RAYED = [[-43.31, -11.36, 85], [9.62, -20.08, 96], [8.1, -38.0, 31], [23.7, -47.4, 40]];

  function moonTextures(img) {
    const W = 2048, H = 1024, rand = rng(2190);
    const map = document.createElement("canvas"); map.width = W; map.height = H;
    const bump = document.createElement("canvas"); bump.width = W; bump.height = H;
    const m = map.getContext("2d"), b = bump.getContext("2d");
    m.imageSmoothingQuality = "high";
    m.filter = "contrast(1.3) brightness(0.96)";
    m.drawImage(img, 0, 0, W, H); m.filter = "none";
    // The source map is 256 px wide, and its polar rows are a handful of
    // pixels smeared around a whole circle. Fade to highland grey there and
    // let the 3D relief and the real polar craters carry the poles.
    for (const [y0, y1] of [[0, H * 0.1], [H, H * 0.9]]) {
      const g = m.createLinearGradient(0, y0, 0, y1);
      g.addColorStop(0, "rgba(150,150,154,1)"); g.addColorStop(0.45, "rgba(150,150,154,0.85)");
      g.addColorStop(1, "rgba(150,150,154,0)");
      m.fillStyle = g; m.fillRect(0, Math.min(y0, y1), W, Math.abs(y1 - y0));
    }
    b.fillStyle = "rgb(128,128,128)"; b.fillRect(0, 0, W, H);

    // Fine relief from 3D noise sampled on the sphere itself, so it is
    // continuous over the poles. A flat noise texture stretched across the
    // map projection streaks at the poles -- exactly where the ports are.
    const NW = 1024, NH = 512, detail = document.createElement("canvas");
    detail.width = NW; detail.height = NH;
    const dc = detail.getContext("2d"), dd = dc.createImageData(NW, NH);
    const perm = new Uint8Array(512);
    for (let i = 0; i < 256; i++) perm[i] = i;
    for (let i = 255; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [perm[i], perm[j]] = [perm[j], perm[i]]; }
    for (let i = 0; i < 256; i++) perm[i + 256] = perm[i];
    const h3 = (x, y, z) => perm[(perm[(perm[x & 255] + y) & 255] + z) & 255] / 255;
    const sm = (q) => q * q * (3 - 2 * q);
    function vnoise(x, y, z) {
      const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
      const xf = sm(x - xi), yf = sm(y - yi), zf = sm(z - zi);
      const l = (a, c, f) => a + (c - a) * f;
      return l(l(l(h3(xi, yi, zi), h3(xi + 1, yi, zi), xf), l(h3(xi, yi + 1, zi), h3(xi + 1, yi + 1, zi), xf), yf),
        l(l(h3(xi, yi, zi + 1), h3(xi + 1, yi, zi + 1), xf), l(h3(xi, yi + 1, zi + 1), h3(xi + 1, yi + 1, zi + 1), xf), yf), zf);
    }
    for (let py = 0; py < NH; py++) {
      const lat = (0.5 - (py + 0.5) / NH) * Math.PI, cl = Math.cos(lat), sl = Math.sin(lat);
      for (let px = 0; px < NW; px++) {
        const lon = ((px + 0.5) / NW) * 2 * Math.PI;
        const x = cl * Math.cos(lon), y = sl, z = cl * Math.sin(lon);
        let f = 0, amp = 0.5, fr = 6;
        for (let o = 0; o < 5; o++) { f += amp * vnoise(x * fr + 17, y * fr + 31, z * fr + 7); amp *= 0.5; fr *= 2.1; }
        const v = 128 + (f - 0.48) * 150, k = (py * NW + px) * 4;
        dd.data[k] = dd.data[k + 1] = dd.data[k + 2] = v; dd.data[k + 3] = 255;
      }
    }
    dc.putImageData(dd, 0, 0);
    b.drawImage(detail, 0, 0, W, H);
    m.globalAlpha = 0.16; m.globalCompositeOperation = "overlay";
    m.drawImage(detail, 0, 0, W, H);
    m.globalAlpha = 1; m.globalCompositeOperation = "source-over";

    function crater(lat, lon, rDeg, fresh) {
      const y = (90 - lat) / 180 * H, x = (lon + 180) / 360 * W;
      const ry = Math.max(0.7, rDeg / 180 * H);
      const stretch = Math.min(24, 1 / Math.max(Math.cos(lat * DEG), 0.04));
      for (const dx of [0, -W, W]) {
        const cx = x + dx;
        if (cx + ry * stretch * 1.3 < 0 || cx - ry * stretch * 1.3 > W) continue;
        b.save(); b.translate(cx, y); b.scale(stretch, 1);
        const g = b.createRadialGradient(0, 0, 0, 0, 0, ry * 1.25);
        g.addColorStop(0, "rgba(0,0,0,0.26)"); g.addColorStop(0.55, "rgba(0,0,0,0.16)");
        g.addColorStop(0.78, "rgba(255,255,255,0.18)"); g.addColorStop(0.92, "rgba(255,255,255,0.05)");
        g.addColorStop(1, "rgba(255,255,255,0)");
        b.fillStyle = g; b.beginPath(); b.arc(0, 0, ry * 1.25, 0, Math.PI * 2); b.fill(); b.restore();
        if (fresh) {
          m.save(); m.translate(cx, y); m.scale(stretch, 1);
          const h = m.createRadialGradient(0, 0, ry * 0.6, 0, 0, ry * 2.4);
          h.addColorStop(0, "rgba(255,255,255,0.16)"); h.addColorStop(1, "rgba(255,255,255,0)");
          m.fillStyle = h; m.beginPath(); m.arc(0, 0, ry * 2.4, 0, Math.PI * 2); m.fill(); m.restore();
        }
      }
    }
    // A power-law crater population: many small, few large.
    for (let i = 0; i < 2600; i++) {
      const lat = Math.asin(rand() * 2 - 1) / DEG, lon = rand() * 360 - 180;
      const rDeg = 0.06 + Math.pow(rand(), 6) * 2.4;
      crater(lat, lon, rDeg, rand() < 0.05);
    }
    for (const [lat, lon, d] of LANDMARKS) crater(lat, lon, d / 2 / 1737.4 / DEG, false);
    // Ray systems of the young craters.
    m.strokeStyle = "rgba(255,255,255,0.08)";
    for (const [lat, lon, d] of RAYED) {
      const x = (lon + 180) / 360 * W, y = (90 - lat) / 180 * H;
      const len = d * 0.35, stretch = 1 / Math.max(Math.cos(lat * DEG), 0.1);
      for (let k = 0; k < 28; k++) {
        const a = rand() * Math.PI * 2, l = len * (0.5 + rand());
        m.lineWidth = 0.6 + rand() * 1.6;
        m.beginPath(); m.moveTo(x, y);
        m.lineTo(x + Math.cos(a) * l * stretch, y + Math.sin(a) * l); m.stroke();
      }
      crater(lat, lon, d / 2 / 1737.4 / DEG, true);
    }
    const tMap = new THREE.CanvasTexture(map), tBump = new THREE.CanvasTexture(bump);
    tMap.anisotropy = tBump.anisotropy = 8;
    return { map: tMap, bump: tBump };
  }

  function fresnelMaterial(a, b, power, strength) {
    return new THREE.ShaderMaterial({
      uniforms: { ca: { value: new THREE.Color(a) }, cb: { value: new THREE.Color(b) } },
      vertexShader: `varying vec3 vN; varying vec3 vV;
        void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0);
          vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz);
          gl_Position = projectionMatrix*mv; }`,
      fragmentShader: `uniform vec3 ca; uniform vec3 cb; varying vec3 vN; varying vec3 vV;
        void main(){ float f = pow(1.0 - max(dot(vN, vV), 0.0), ${power.toFixed(1)});
          gl_FragColor = vec4(mix(ca, cb, f) * f * ${strength.toFixed(2)}, f); }`,
      blending: THREE.AdditiveBlending, transparent: true, depthWrite: false,
    });
  }

  function beamMaterial(color) {
    return new THREE.ShaderMaterial({
      uniforms: { c: { value: new THREE.Color(color) }, t: { value: 0 } },
      vertexShader: `varying float vY; void main(){ vY = uv.y;
        gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
      fragmentShader: `uniform vec3 c; uniform float t; varying float vY;
        void main(){ float a = pow(1.0 - vY, 2.2) * (0.75 + 0.25*sin(t*2.0));
          gl_FragColor = vec4(c * a, a); }`,
      blending: THREE.AdditiveBlending, transparent: true, depthWrite: false,
      side: THREE.DoubleSide,
    });
  }

  // -- state ------------------------------------------------------------------
  let renderer, camera, controls, moonScene, sysScene, active = "moon";
  let moon, sunLight, earth, earthGroup, labelsEl, cb = {};
  const nodes = {};             // id -> {data, group, pos, normal, tag, beam, ring}
  const ships = {};             // id -> {sprite, trail, data}
  const lanes = [];
  const bodies = {};            // system view: id -> {obj, tag}
  let world = null, meShip = null, clockFn = () => 0, selected = null;
  let tween = null, introSpin = false;
  const savedCam = { moon: null, system: null };
  const tex = {};

  function tag(html, cls, onClick) {
    const el = document.createElement("div");
    el.className = "tag " + (cls || ""); el.innerHTML = html;
    if (onClick) el.addEventListener("click", onClick);
    labelsEl.appendChild(el);
    return el;
  }

  // -- the Moon -----------------------------------------------------------------
  // The Tycho-2 star catalogue on a cube that rides with the camera, tinted
  // down: at full brightness a real star field reads as noise behind a globe.
  let stars = null;
  function starBox() {
    if (!stars) {
      const loader = new THREE.TextureLoader();
      stars = ["px", "mx", "py", "my", "pz", "mz"].map((f) => {
        const tx = loader.load(`assets/sky/${f}.jpg`); tx.encoding = THREE.sRGBEncoding;
        return new THREE.MeshBasicMaterial({ map: tx, color: 0x5a5870, side: THREE.BackSide,
          depthWrite: false, fog: false });
      });
    }
    const box = new THREE.Mesh(new THREE.BoxGeometry(300, 300, 300), stars);
    box.renderOrder = -1; box.userData.sky = true;
    return box;
  }

  function buildMoon() {
    moonScene = new THREE.Scene();
    moonScene.add(starBox());

    const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, metalness: 0 });
    moon = new THREE.Mesh(new THREE.SphereGeometry(R, 192, 128), mat);
    moonScene.add(moon);
    const img = new Image();
    img.onload = () => {
      const t = moonTextures(img);
      mat.map = t.map; mat.bumpMap = t.bump; mat.bumpScale = 0.014; mat.needsUpdate = true;
      if (cb.onReady) cb.onReady();
    };
    img.src = "assets/moon_albedo.jpg";

    moonScene.add(new THREE.Mesh(new THREE.SphereGeometry(R * 1.045, 96, 64),
      fresnelMaterial(COL.violet, COL.cyan, 3.2, 0.95)));

    // A faint schematic graticule: lunarark.com is luminous, not photographic.
    const gmat = new THREE.LineBasicMaterial({ color: COL.violetSoft, transparent: true, opacity: 0.09 });
    for (let lat = -60; lat <= 60; lat += 30) {
      const pts = []; for (let lon = -180; lon <= 180; lon += 3) pts.push(ll(lat, lon, R * 1.002));
      moonScene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gmat));
    }
    for (let lon = -180; lon < 180; lon += 30) {
      const pts = []; for (let lat = -90; lat <= 90; lat += 3) pts.push(ll(lat, lon, R * 1.002));
      moonScene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gmat));
    }

    sunLight = new THREE.DirectionalLight(0xfff4e0, 1.35);
    sunLight.position.copy(ll(0, 90, 20));
    moonScene.add(sunLight);
    moonScene.add(new THREE.AmbientLight(0x1b1a3a, 0.55));
    // Earthshine comes from where the Earth is: over longitude 0, always.
    const earthshine = new THREE.DirectionalLight(0x5b7bd6, 0.22);
    earthshine.position.copy(ll(0, 0, 20)); moonScene.add(earthshine);

    earthGroup = new THREE.Group();
    const eMat = new THREE.MeshStandardMaterial({ roughness: 0.8, metalness: 0 });
    new THREE.TextureLoader().load("assets/earth_ne2.jpg", (t) => { eMat.map = t; eMat.needsUpdate = true; });
    earth = new THREE.Mesh(new THREE.SphereGeometry(1.25, 64, 48), eMat);
    earth.rotation.z = 23.44 * DEG;
    earthGroup.add(earth);
    earthGroup.add(new THREE.Mesh(new THREE.SphereGeometry(1.25 * 1.06, 48, 32),
      fresnelMaterial(0x3b82f6, 0x93c5fd, 2.4, 1.2)));
    earthGroup.position.copy(ll(4, 0, 70));
    moonScene.add(earthGroup);

    tex.dot = glowTexture("rgba(255,255,255,1)", "rgba(255,255,255,0.35)");
  }

  function buildNodes(list) {
    for (const n of list) {
      if (nodes[n.id]) { nodes[n.id].data = n; continue; }
      const normal = ll(n.lat, n.lon, 1).normalize();
      const pos = normal.clone().multiplyScalar(R);
      const group = new THREE.Group();
      const pin = new THREE.Mesh(new THREE.SphereGeometry(0.014, 16, 12),
        new THREE.MeshBasicMaterial({ color: COL.cyanSoft }));
      pin.position.copy(pos); group.add(pin);
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.03, 0.037, 48),
        new THREE.MeshBasicMaterial({ color: COL.cyan, transparent: true, opacity: 0.8,
          side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
      ring.position.copy(normal.clone().multiplyScalar(R * 1.001));
      ring.lookAt(normal.clone().multiplyScalar(R * 2)); group.add(ring);
      const beamGeo = new THREE.CylinderGeometry(0.0035, 0.0035, 0.45, 8, 1, true);
      beamGeo.translate(0, 0.225, 0);
      const beam = new THREE.Mesh(beamGeo, beamMaterial(COL.cyan));
      beam.position.copy(pos);
      beam.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal); group.add(beam);
      const hit = new THREE.Mesh(new THREE.SphereGeometry(0.09, 8, 8),
        new THREE.MeshBasicMaterial({ visible: false }));
      hit.position.copy(pos); hit.userData.node = n.id; group.add(hit);
      moonScene.add(group);
      const t = tag("", "", () => select(n.id, true));
      nodes[n.id] = { data: n, group, pos, normal, ring, beam, hit, tag: t };
    }
    buildLanes();
  }

  function arcPoint(a, b, t, lift) {
    // Great-circle slerp, lifted into a ballistic arc: a suborbital hop.
    const angle = a.angleTo(b), s = Math.sin(angle);
    let dir;
    if (s < 1e-4) dir = a.clone();
    else dir = a.clone().multiplyScalar(Math.sin((1 - t) * angle) / s)
      .add(b.clone().multiplyScalar(Math.sin(t * angle) / s));
    return dir.normalize().multiplyScalar(R * 1.004 + Math.sin(Math.PI * t) * lift);
  }
  function hopLift(a, b) { return 0.12 + 0.5 * (a.angleTo(b) / Math.PI); }

  function buildLanes() {
    if (lanes.length) return;
    const ids = Object.keys(nodes);
    for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
      const a = nodes[ids[i]].normal, b = nodes[ids[j]].normal, lift = hopLift(a, b);
      const pts = []; for (let k = 0; k <= 96; k++) pts.push(arcPoint(a, b, k / 96, lift));
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const mat = new THREE.LineDashedMaterial({ color: COL.violetSoft, dashSize: 0.04, gapSize: 0.03,
        transparent: true, opacity: 0.25, blending: THREE.AdditiveBlending, depthWrite: false });
      const line = new THREE.Line(geo, mat); line.computeLineDistances();
      moonScene.add(line);
      lanes.push({ a: ids[i], b: ids[j], line });
    }
  }

  // How much a lane is worth flying right now: the best spread between its
  // two ends, as a share of the price. Public prices, display only.
  function laneHeat(a, b) {
    const pa = nodes[a].data.prices || {}, pb = nodes[b].data.prices || {};
    let best = 0;
    for (const asset of Object.keys(pa)) {
      const x = pa[asset], y = pb[asset]; if (!x || !y) continue;
      if (x.ask && y.bid) best = Math.max(best, (y.bid - x.ask) / x.ask);
      if (y.ask && x.bid) best = Math.max(best, (x.bid - y.ask) / y.ask);
    }
    return Math.max(0, Math.min(1, best * 2));
  }

  // -- ships --------------------------------------------------------------------
  function shipColour(s) {
    if (meShip && s.id === meShip) return COL.cyanSoft;
    if (s.player) return COL.pink;
    return COL.amber;
  }

  function syncShips(list) {
    const seen = new Set();
    for (const s of list) {
      seen.add(s.id);
      let o = ships[s.id];
      if (!o) {
        const mat = new THREE.SpriteMaterial({ map: tex.dot, color: shipColour(s), transparent: true,
          blending: THREE.AdditiveBlending, depthWrite: false });
        const sprite = new THREE.Sprite(mat);
        const trailMat = new THREE.LineBasicMaterial({ color: shipColour(s), transparent: true,
          opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false });
        const trail = new THREE.Line(new THREE.BufferGeometry(), trailMat);
        trail.frustumCulled = false;
        moonScene.add(sprite); moonScene.add(trail);
        o = ships[s.id] = { sprite, trail, data: s, tag: null };
      }
      o.data = s;
      o.sprite.material.color.setHex(shipColour(s));
      o.trail.material.color.setHex(shipColour(s));
      const mine = meShip && s.id === meShip;
      const size = mine ? 0.11 : s.player ? 0.075 : 0.05;
      o.sprite.scale.set(size, size, 1);
      // Ships are named only in flight. Docked, the port's own label says
      // where everyone is, and a stack of names on one pin is unreadable.
      const flying = s.state === "in_transit" && (mine || s.player);
      if (o.tag && !flying) { o.tag.remove(); o.tag = null; }
      if (flying && !o.tag) o.tag = mine ? tag('<div class="name">YOUR KESTREL</div>', "here")
        : tag(`<div class="sub">${escapeHtml(s.company || "")}</div>`, "dim");
    }
    for (const id of Object.keys(ships)) if (!seen.has(id)) {
      moonScene.remove(ships[id].sprite); moonScene.remove(ships[id].trail);
      if (ships[id].tag) ships[id].tag.remove(); delete ships[id];
    }
  }

  function placeShips(now, t) {
    const parked = {};
    for (const id of Object.keys(ships)) {
      const o = ships[id], s = o.data;
      const from = nodes[s.location], to = s.destination && nodes[s.destination];
      if (!from) { o.sprite.visible = false; continue; }
      o.sprite.visible = true;
      if (s.state === "in_transit" && to) {
        const span = Math.max(1, s.arrive_tick - s.depart_tick);
        const p = Math.max(0, Math.min(1, (now - s.depart_tick) / span));
        const lift = hopLift(from.normal, to.normal);
        o.sprite.position.copy(arcPoint(from.normal, to.normal, p, lift));
        const pts = []; const n = 48;
        for (let k = 0; k <= n; k++) pts.push(arcPoint(from.normal, to.normal, p * k / n, lift));
        o.trail.geometry.setFromPoints(pts); o.trail.visible = true;
      } else {
        const k = (parked[s.location] = (parked[s.location] || 0) + 1);
        // Docked ships hold station above their port, slowly circling it.
        const tangent = new THREE.Vector3(0, 1, 0).cross(from.normal);
        if (tangent.lengthSq() < 1e-6) tangent.set(1, 0, 0);
        tangent.normalize();
        const bi = from.normal.clone().cross(tangent).normalize();
        const ang = t * 0.25 + k * 2.39, rad = 0.05 + 0.012 * k;
        o.sprite.position.copy(from.normal).multiplyScalar(R + 0.04 + 0.006 * k)
          .add(tangent.multiplyScalar(Math.cos(ang) * rad)).add(bi.multiplyScalar(Math.sin(ang) * rad));
        o.trail.visible = false;
      }
    }
  }

  // -- the solar system ---------------------------------------------------------
  const SYS_COLOURS = { mercury: 0x9ca3af, venus: 0xfde68a, earth: 0x60a5fa, mars: 0xf87171,
    jupiter: 0xfbbf24, saturn: 0xfcd34d, ceres: 0xa78bfa, vesta: 0xa78bfa, pallas: 0xa78bfa,
    psyche: 0xf472b6, eros: 0x67e8f9 };
  const SYS_NOTES = {
    earth: ["The Moon · lunarark.com", "v1 · you are here"],
    mars: ["marsbase.app", "v3 · Industry"], ceres: ["The Belt's capital", "v2"],
    psyche: ["The prize", "v2"],
  };
  // Distances compressed by a square root so Saturn and Mercury share a
  // screen; directions are exactly the ephemeris directions.
  function sysPos(b) {
    const r = Math.hypot(b.x, b.y), k = r > 0 ? 6 * Math.sqrt(r) / r : 0;
    return new THREE.Vector3(b.x * k, b.z * k * 0.6, -b.y * k);
  }

  function buildSystem() {
    sysScene = new THREE.Scene();
    sysScene.add(starBox());
    const sun = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTexture("rgba(255,244,214,1)", "rgba(251,191,36,0.55)"), blending: THREE.AdditiveBlending,
      depthWrite: false, transparent: true }));
    sun.scale.set(3.2, 3.2, 1); sysScene.add(sun);
    sysScene.add(new THREE.Mesh(new THREE.SphereGeometry(0.32, 32, 24),
      new THREE.MeshBasicMaterial({ color: 0xfff1c1 })));
    // The Belt, as a haze between Mars and Jupiter.
    const rand = rng(7), pts = [];
    for (let i = 0; i < 2600; i++) {
      const au = 2.1 + rand() * 1.2 + (rand() - 0.5) * 0.25, a = rand() * Math.PI * 2;
      const r = 6 * Math.sqrt(au);
      pts.push(Math.cos(a) * r, (rand() - 0.5) * 0.5, Math.sin(a) * r);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    sysScene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0x8b7fd6, size: 0.05,
      transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false })));
    const belt = tag('<div class="name">The Belt</div><div class="sub">asteroidbelt.app · opens in v2</div>', "body dim");
    bodies.__belt = { obj: null, tag: belt, pos: new THREE.Vector3(0, 0, -6 * Math.sqrt(2.75)) };
  }

  function syncSky(sky) {
    if (!sky) return;
    // The Sun over the Moon: where it really is at this sky time.
    if (sunLight) sunLight.position.copy(ll(0, sky.moon.subsolar_lon, 20));
    if (!sysScene) return;
    for (const b of sky.bodies) {
      let o = bodies[b.id];
      const pos = sysPos(b);
      if (!o) {
        const planet = b.kind === "planet";
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(planet ? 0.2 : 0.09, 24, 16),
          new THREE.MeshBasicMaterial({ color: SYS_COLOURS[b.id] || 0xffffff }));
        const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex.dot, color: SYS_COLOURS[b.id] || 0xffffff,
          transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
        halo.material.opacity = 0.55;
        halo.scale.set(planet ? 0.8 : 0.4, planet ? 0.8 : 0.4, 1);
        const grp = new THREE.Group(); grp.add(mesh); grp.add(halo);
        grp.userData.body = b.id; mesh.userData.body = b.id;
        sysScene.add(grp);
        const r = Math.hypot(b.x, b.y);
        if (planet) {
          const ring = []; for (let k = 0; k <= 180; k++) {
            const a = k / 180 * Math.PI * 2; ring.push(new THREE.Vector3(Math.cos(a) * 6 * Math.sqrt(r), 0, Math.sin(a) * 6 * Math.sqrt(r)));
          }
          sysScene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(ring),
            new THREE.LineBasicMaterial({ color: b.id === "earth" ? COL.cyan : COL.violetSoft,
              transparent: true, opacity: b.id === "earth" ? 0.5 : 0.16 })));
        }
        const note = SYS_NOTES[b.id];
        const cls = "body" + (b.id === "earth" ? " here" : note ? "" : " dim");
        o = bodies[b.id] = { obj: grp, mesh, pos, tag: tag(
          `<div class="name">${b.name}</div>${note ? `<div class="sub">${note[0]} · ${note[1]}</div>` : ""}`,
          cls, b.id === "earth" ? () => setView("moon") : null) };
      }
      o.pos = pos; o.obj.position.copy(pos);
    }
    const ceres = sky.bodies.find((b) => b.id === "ceres");
    if (ceres) {
      const a = Math.atan2(-ceres.y, ceres.x) + Math.PI * 0.62, r = 6 * Math.sqrt(2.75);
      bodies.__belt.pos = new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r);
    }
  }

  // -- camera -------------------------------------------------------------------
  function flyTo(pos, target, ms) {
    tween = { p0: camera.position.clone(), p1: pos, t0: controls.target.clone(), t1: target,
      start: performance.now(), ms: ms || 1400 };
  }

  function select(id, fly) {
    selected = id;
    for (const k of Object.keys(nodes)) nodes[k].tag.classList.toggle("sel", k === id);
    if (fly && nodes[id]) {
      const n = nodes[id].data, lat = Math.max(-58, Math.min(58, n.lat));
      flyTo(ll(lat, n.lon, 6.0), new THREE.Vector3(0, 0, 0));
    }
    if (cb.onSelect) cb.onSelect(id);
  }

  function setView(v) {
    if (v === active) return;
    const fade = document.getElementById("fade");
    fade.style.opacity = 1;
    setTimeout(() => {
      savedCam[active] = { p: camera.position.clone(), t: controls.target.clone() };
      active = v;
      const s = savedCam[v];
      tween = null;
      if (v === "system") {
        camera.position.copy(s ? s.p : new THREE.Vector3(0, 16, 20));
        controls.minDistance = 4; controls.maxDistance = 60;
      } else {
        camera.position.copy(s ? s.p : ll(-18, 28, 6.2));
        controls.minDistance = 2.18; controls.maxDistance = 16;
      }
      controls.target.copy(s ? s.t : new THREE.Vector3());
      controls.update();
      for (const k of Object.keys(nodes)) nodes[k].tag.style.display = v === "moon" ? "" : "none";
      for (const k of Object.keys(ships)) if (ships[k].tag) ships[k].tag.style.display = v === "moon" ? "" : "none";
      for (const k of Object.keys(bodies)) bodies[k].tag.style.display = v === "system" ? "" : "none";
      fade.style.opacity = 0;
      if (cb.onView) cb.onView(v);
    }, 420);
  }

  // -- the loop -----------------------------------------------------------------
  const tmp = new THREE.Vector3();
  function projectTag(el, pos, facing) {
    tmp.copy(pos).project(camera);
    const off = tmp.z > 1 || !facing;
    if (off) { el.style.opacity = 0; el.style.pointerEvents = "none"; return; }
    el.style.opacity = ""; el.style.pointerEvents = "";
    el.style.left = ((tmp.x + 1) / 2 * innerWidth) + "px";
    el.style.top = ((1 - tmp.y) / 2 * innerHeight) + "px";
  }

  function frame(ms) {
    requestAnimationFrame(frame);
    const t = ms / 1000;
    if (tween) {
      const k = Math.min(1, (performance.now() - tween.start) / tween.ms);
      const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      camera.position.lerpVectors(tween.p0, tween.p1, e);
      controls.target.lerpVectors(tween.t0, tween.t1, e);
      if (k >= 1) tween = null;
    }
    controls.autoRotate = introSpin;
    controls.update();
    for (const sc of [moonScene, sysScene]) for (const c of sc.children)
      if (c.userData.sky) c.position.copy(camera.position);
    if (active === "moon") {
      const now = clockFn();
      placeShips(now, t);
      for (const k of Object.keys(nodes)) {
        const n = nodes[k], s = 1 + 0.18 * Math.sin(t * 2 + k.length);
        n.ring.scale.set(s, s, s);
        n.beam.material.uniforms.t.value = t + k.length;
        const facing = n.normal.dot(tmp.copy(camera.position).sub(n.pos)) > 0;
        projectTag(n.tag, n.pos.clone().add(n.normal.clone().multiplyScalar(0.05)), facing);
      }
      for (const k of Object.keys(ships)) {
        const o = ships[k]; if (!o.tag) continue;
        const p = o.sprite.position, facing = p.clone().normalize().dot(tmp.copy(camera.position).sub(p)) > -0.2;
        projectTag(o.tag, p.clone().add(p.clone().normalize().multiplyScalar(0.02)), facing);
      }
      for (const l of lanes) {
        const h = laneHeat(l.a, l.b);
        l.line.material.opacity = 0.1 + 0.55 * h;
        l.line.material.color.setHex(h > 0.25 ? COL.cyanSoft : COL.violetSoft);
      }
      if (earth) earth.rotation.y = t * 0.01;
      renderer.render(moonScene, camera);
    } else {
      for (const k of Object.keys(bodies)) {
        const b = bodies[k];
        const below = k === "psyche" || k === "vesta";
        projectTag(b.tag, b.pos.clone().add(new THREE.Vector3(0, below ? -0.9 : 0.45, 0)), true);
      }
      renderer.render(sysScene, camera);
    }
  }

  function onClick(ev) {
    if (ev.target !== renderer.domElement) return;
    const mouse = new THREE.Vector2((ev.clientX / innerWidth) * 2 - 1, -(ev.clientY / innerHeight) * 2 + 1);
    const ray = new THREE.Raycaster(); ray.setFromCamera(mouse, camera);
    if (active === "moon") {
      const hits = ray.intersectObjects(Object.values(nodes).map((n) => n.hit));
      if (hits.length) select(hits[0].object.userData.node, true);
    } else {
      const hits = ray.intersectObjects(Object.values(bodies).filter((b) => b.mesh).map((b) => b.mesh));
      if (hits.length && hits[0].object.userData.body === "earth") setView("moon");
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // -- public -------------------------------------------------------------------
  window.Scene = {
    init(container, labels, callbacks) {
      labelsEl = labels; cb = callbacks || {};
      renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
      renderer.setSize(innerWidth, innerHeight);
      renderer.outputEncoding = THREE.sRGBEncoding;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 0.95;
      container.appendChild(renderer.domElement);
      camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.01, 400);
      camera.position.copy(ll(-18, 28, 6.2));
      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true; controls.dampingFactor = 0.06;
      controls.rotateSpeed = 0.45; controls.zoomSpeed = 0.8; controls.enablePan = false;
      controls.minDistance = 2.18; controls.maxDistance = 16; controls.autoRotateSpeed = 0.35;
      controls.addEventListener("start", () => { tween = null; });
      buildMoon(); buildSystem();
      addEventListener("resize", () => {
        camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
        renderer.setSize(innerWidth, innerHeight);
      });
      renderer.domElement.addEventListener("click", onClick);
      requestAnimationFrame(frame);
    },
    setWorld(w) {
      world = w; buildNodes(w.nodes); syncShips(w.ships);
      for (const n of w.nodes) {
        const node = nodes[n.id], p = n.prices || {};
        const lead = p.PROP || p.ICE || p.HE3 || p.REGOLITH;
        const leadName = p.PROP ? "PROP" : p.ICE ? "ICE" : p.HE3 ? "HE3" : "REGOLITH";
        const price = lead ? (lead.last || lead.bid || lead.ask) : null;
        node.tag.innerHTML = `<div class="name">${n.name}${n.contracts ? `<span class="jobs">${n.contracts}</span>` : ""}</div>` +
          (price ? `<div class="sub">${leadName} ${price.toLocaleString()} cr</div>` : "");
      }
    },
    setSky: syncSky,
    setMe(shipId) { meShip = shipId; if (world) syncShips(world.ships); },
    setClock(fn) { clockFn = fn; },
    select, setView, flyTo,
    view() { return active; },
    intro(on) { introSpin = !!on; },
    frameRoute(a, b) {
      if (!nodes[a] || !nodes[b]) return;
      const na = nodes[a].normal, sun = sunLight.position.clone().normalize();
      const mid = na.clone().add(nodes[b].normal);
      // Pole to pole, every meridian is a midpoint: take the sunlit one.
      if (mid.length() < 0.3) mid.copy(sun).sub(na.clone().multiplyScalar(sun.dot(na)));
      mid.normalize();
      // Lean toward the Sun so the route is not framed on the night side.
      const dir = mid.multiplyScalar(0.7).add(sun.multiplyScalar(0.5)).normalize();
      flyTo(dir.multiplyScalar(6.6), new THREE.Vector3(), 1600);
    },
    focusShip() {
      const o = meShip && ships[meShip]; if (!o) return;
      const p = o.sprite.position.clone().normalize();
      const lat = Math.max(-62, Math.min(62, Math.asin(p.y) / DEG));
      const lon = Math.atan2(p.z, -p.x) / DEG - 180;
      flyTo(ll(lat, lon, 4.6), new THREE.Vector3());
    },
  };
})();
