// In-page probes for Thursday Yacht Club, for checking the look and the cost of a change against a baseline.
// Serve the repo (python3 -m http.server 8791), open index.html, take the handle, then in the console:
//   const P = await import('/tools/probe.js?' + Date.now());
//   P.build()           ms the game script spent building the world (needs the tyc:game / tyc:built marks)
//   P.render(60)        ms per frame over a tight render loop, plus draw calls and triangles for one frame
//   await P.bench()     tools/jump_bench.py's scripted jumps, run on the live page; freezes the game, so run it last
// Everything the game declares at the top level of its script is global, so a module can reach it by name.
/* global performance, renderer, renderReflection, renderPost, boatZ */

export function build() {
  const m = performance.getEntriesByName('tyc:built');
  if (!m.length) return null;
  return +performance.measure('tyc:build', 'tyc:game', 'tyc:built').duration.toFixed(1);
}

export function render(n = 60) {
  const gl = renderer.getContext(), px = new Uint8Array(4);
  const frame = () => { renderer.shadowMap.needsUpdate = true; renderReflection(); renderPost(); };
  frame(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);   // warm up and flush
  const t0 = performance.now();
  for (let i = 0; i < n; i++) frame();
  gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);           // wait for the GPU to finish
  const ms = (performance.now() - t0) / n;
  const auto = renderer.info.autoReset; renderer.info.autoReset = false; renderer.info.reset();
  frame();
  const info = { calls: renderer.info.render.calls, triangles: renderer.info.render.triangles };
  renderer.info.autoReset = auto;
  return { ms: +ms.toFixed(2), ...info, quality: document.getElementById('quality')?.textContent };
}

// Driving the game by hand, for when the page isn't animating (a hidden or background tab) or for repeatable shots.
/* global tick, keys, cam, R, boatZ, crestX, STERN_OFF, onDown, onUp, paused */
let stepN = 0;
export function step(sec, fps = 60) {
  const n = Math.max(1, Math.round(sec * fps)); for (let i = 0; i < n; i++) tick(1 / fps);
  // a hidden pane only repaints when something on the page visibly changes: flick a 1 px dot in the corner
  let dot = document.getElementById('probe-dot');
  if (!dot) { dot = document.createElement('div'); dot.id = 'probe-dot'; dot.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;z-index:99;pointer-events:none'; document.body.appendChild(dot); }
  dot.style.background = ++stepN % 2 ? '#010101' : '#020202';
}
export function hud(show) { for (const id of ['hud', 'touch', 'loader']) { const e = document.getElementById(id); if (e) e.style.visibility = show ? '' : 'hidden'; } }
export function view(mode) { cam.mode = mode; cam.snap = true; step(0.5); }
export function hold(sec, held = {}) { for (const k in held) keys[k] = held[k]; step(sec); for (const k in held) keys[k] = false; }
// cut out past the far wake, edge hard back in holding Space, let go at the lip; returns when the board is down again
export function jump(side = 1, out = 4) {
  const L = side > 0 ? 'ArrowLeft' : 'ArrowRight', Rt = side > 0 ? 'ArrowRight' : 'ArrowLeft';
  const d = () => boatZ - STERN_OFF - R.pos.z;
  for (let t = 0; t < 8 && side * R.pos.x < crestX(d()) + out; t += 1 / 60) { keys[L] = true; tick(1 / 60); }
  keys[L] = false; step(0.6);
  onDown('Space'); keys.Space = true;
  let popped = false;
  for (let t = 0; t < 8; t += 1 / 60) {
    keys[Rt] = true;
    if (!popped && R.state === 'riding' && R.vySurf > 1.5 && side * R.pos.x > 0) { keys.Space = false; onUp('Space'); popped = true; }
    tick(1 / 60);
    if (R.state === 'air') break;
  }
  keys[Rt] = false; if (keys.Space) { keys.Space = false; onUp('Space'); }
  for (let t = 0; t < 4 && R.state === 'air'; t += 1 / 60) tick(1 / 60);
  return R.state;
}

// Checks for the scenery and spray pass (docs/superpowers/plans/2026-11-19-scenery-and-spray.md): each returns the
// list of what's wrong, empty when it all holds.
/* global spray, FOAM_N, SPRAY_DROP, SPRAY_SHEET, SPRAY_MIST, setQuality, quality */
export async function checkSpray() {
  const bad = [];
  if (typeof SPRAY_MIST === 'undefined' || SPRAY_DROP !== 0 || SPRAY_SHEET !== 1 || SPRAY_MIST !== 2) bad.push('SPRAY_DROP/SHEET/MIST constants');
  if (!spray.geo || !spray.geo.attributes.aT || spray.geo.attributes.aT.itemSize !== 4) bad.push('instanced aT (t0, life, size, kind)');
  if (typeof spray.clock !== 'number') bad.push('spray.clock');
  if (typeof spray.rate !== 'number') bad.push('spray.rate');
  if (FOAM_N !== 1200) bad.push(`FOAM_N is ${FOAM_N}, want 1200`);
  // world coordinates run into the hundreds of thousands; GPU fast-math sin() of them returns NaN (see the README's trap)
  if (/sin\s*\(\s*dot\s*\(\s*aP0/.test(spray.mat.vertexShader)) bad.push('spray vertex shader takes sin() of a world position');
  if (!bad.length) {
    const i = spray.i; spray.emit(1, 2, 3, 4, 5, 6, 0.7, 0.3, SPRAY_MIST);
    const a = spray.geo.attributes, T = a.aT.array;
    if (a.aP0.array[i * 3 + 1] !== 2 || a.aV0.array[i * 3 + 2] !== 6) bad.push('emit position/velocity');
    if (T[i * 4] !== Math.fround(spray.clock) || Math.abs(T[i * 4 + 1] - 0.7) > 1e-6 || Math.abs(T[i * 4 + 2] - 0.3) > 1e-6 || T[i * 4 + 3] !== SPRAY_MIST) bad.push('emit t0/life/size/kind');
    // pause: the clock holds while Settings is open, and runs again after
    // the game's own pause flag (what Settings sets); flipped directly, since a hidden tab won't always open the dialog
    const c0 = spray.clock; (0, eval)('paused=true'); step(0.5); const c1 = spray.clock; (0, eval)('paused=false'); step(0.5); const c2 = spray.clock;
    if (c1 !== c0) bad.push('spray clock runs while paused');
    if (!(c2 > c1 + 0.4)) bad.push('spray clock stuck after unpause');
    // quality sets the emission rate
    const q = quality; setQuality(0); const r0 = spray.rate; setQuality(2); const r2 = spray.rate; setQuality(q);
    if (!(r0 > 0 && r0 < r2 && r2 === 1)) bad.push(`spray.rate low ${r0}, high ${r2}`);
  }
  return bad;
}

/* global trees, treeGeometry, paintFoliageAtlas, updateTreeLod, TREE_CHUNK, TREE_KINDS, setTreeDensity, LAND_P, THREE */
export function checkTrees() {
  const bad = [];
  if (typeof treeGeometry !== 'function' || typeof paintFoliageAtlas !== 'function' || typeof updateTreeLod !== 'function') return ['treeGeometry / paintFoliageAtlas / updateTreeLod'];
  if (TREE_CHUNK !== 450) bad.push('TREE_CHUNK');
  // the sway phase must stay small far down the course (sin() of a huge world coordinate goes NaN on fast-math GPUs)
  /* global treeMat */
  if (!/fract\(wp0\.z\//.test(treeMat.onBeforeCompile.toString())) bad.push('tree sway phase uses the raw world position');
  // near and far trees hand over smoothly: every chunk has a far twin sharing its instances
  if (trees.some(m => !m.userData.far || m.userData.far.instanceMatrix !== m.instanceMatrix)) bad.push('chunks need a far twin sharing their instances');
  for (const k of TREE_KINDS) for (const lod of [0, 1]) {
    const g = treeGeometry(k, lod, 1);
    for (const a of ['position', 'normal', 'uv', 'color', 'aSway', 'aLod']) if (!g.attributes[a]) bad.push(`${k} lod${lod} has no ${a}`);
  }
  const kinds = new Set(trees.map(m => m.userData.kind));
  for (const k of ['spruce', 'pine', 'broadleaf', 'birch', 'willow', 'bush']) if (!kinds.has(k)) bad.push(`no ${k} planted`);
  if (trees.some(m => !m.frustumCulled || !m.boundingSphere)) bad.push('chunks must be frustum-culled with bounding spheres');
  // every chunk repeats two chunks (one period) along, instance for instance, so the forward snap can't pop
  const key = m => `${m.userData.kind}|${m.userData.side}|${m.userData.chunk}`, by = new Map(trees.map(m => [key(m), m]));
  const per = LAND_P / TREE_CHUNK, a = new THREE.Matrix4(), b = new THREE.Matrix4();
  let pairs = 0;
  for (const m of trees) {
    const n = by.get(`${m.userData.kind}|${m.userData.side}|${m.userData.chunk + per}`); if (!n) continue; pairs++;
    if (n.userData.full !== m.userData.full) { bad.push(`period mismatch in count ${key(m)}`); continue; }
    for (let i = 0; i < m.userData.full; i++) {
      m.getMatrixAt(i, a); n.getMatrixAt(i, b); a.elements[14] += LAND_P;
      if (a.elements.some((v, j) => Math.abs(v - b.elements[j]) > 1e-3)) { bad.push(`period mismatch at ${key(m)} #${i}`); break; }
    }
  }
  if (!pairs) bad.push('no chunk pairs a period apart');
  const full = trees.reduce((s, m) => s + m.userData.full, 0);
  setTreeDensity(0.5); const half = trees.reduce((s, m) => s + m.count, 0); setTreeDensity(1);
  if (Math.abs(half / full - 0.5) > 0.02) bad.push(`density 0.5 gave ${half}/${full}`);
  return bad;
}

/* global shoreType, buildProps, props, landMat, hills, QUALITY, SHORE_SPAN, landH */
export function checkScenery() {
  const bad = [];
  if (typeof shoreType !== 'function' || typeof props === 'undefined') return ['shoreType / props'];
  for (const side of [-1, 1]) for (let z = -400; z < 400; z += 37) {
    const a = shoreType(side, z), b = shoreType(side, z + LAND_P);
    if (Math.abs(a.beach + a.rock + a.reed - 1) > 1e-6) { bad.push(`shoreType weights at ${side},${z}`); break; }
    if (['beach', 'rock', 'reed'].some(k => Math.abs(a[k] - b[k]) > 1e-6)) { bad.push(`shoreType not periodic at ${side},${z}`); break; }
    if (Math.abs(landH(side * 90, z) - landH(side * 90, z + LAND_P)) > 1e-6) { bad.push(`landH not periodic at ${side},${z}`); break; }
  }
  const kinds = new Set(); for (let z = -450; z < 450; z += 5) { const t = shoreType(1, z); kinds.add(t.rock > 0.5 ? 'rock' : t.reed > 0.5 ? 'reed' : 'beach'); }
  if (kinds.size < 3) bad.push(`only ${[...kinds]} along a bank`);
  if (props.userData.jetties !== 3 * SHORE_SPAN || props.userData.boathouses !== SHORE_SPAN) bad.push(`props: ${props.userData.jetties} jetties, ${props.userData.boathouses} boathouses`);
  if (!landMat.onBeforeCompile || landMat.onBeforeCompile.toString().length < 50) bad.push('landMat has no ground shader');
  if (hills.children.length !== 3) bad.push(`${hills.children.length} ridges, want 3`);
  // each period of ground is exactly one period long, so neighbours meet edge to edge instead of overlapping (z-fighting)
  /* global landParts */
  for (const g of landParts) { g.geometry.computeBoundingBox(); const b = g.geometry.boundingBox; if (Math.abs(b.max.z - b.min.z - LAND_P) > 1e-3) { bad.push(`ground period spans ${(b.max.z - b.min.z).toFixed(1)} m, want ${LAND_P}`); break; } }
  if (!('props' in QUALITY[0])) bad.push('QUALITY has no props field');
  else { const q = quality; setQuality(0); const lo = props.visible; setQuality(2); const hi = props.visible; setQuality(q); if (lo || !hi) bad.push(`props visible low ${lo}, high ${hi}`); }
  return bad;
}

// Press P through every setting mid-ride: the label, tree density, spray rate, props and far-tree distance must all follow
/* global onDown, TREE_GEO */
export function checkQuality() {
  const bad = [], seen = [];
  (0, eval)('qualityAuto=true'); setQuality(2); step(0.1);
  const progs0 = renderer.info.programs.length;   // a setting change mustn't compile a shader mid-ride (auto drops to low when frames are already slow)
  for (let i = 0; i < 4; i++) {
    onDown('KeyP'); step(0.3);
    const Q = QUALITY[quality], label = document.getElementById('quality').textContent; seen.push(label);
    if (!label.includes(Q.name)) bad.push(`label "${label}" for ${Q.name}`);
    if (trees.some(m => m.count !== Math.round(m.userData.full * Q.trees))) bad.push(`tree density off on ${Q.name}`);
    if (spray.rate !== Q.spray) bad.push(`spray rate ${spray.rate} on ${Q.name}`);
    if (props.visible !== Q.props) bad.push(`props ${props.visible} on ${Q.name}`);
    const cz = camera.position.z - shore.position.z;
    for (const m of trees) { const a = Math.abs(cz - m.userData.zmid), dmin = a - 225, dmax = a + 225; if (dmin >= Q.treeHide || (!Q.props && m.userData.kind === 'bush')) continue;
      if (m.visible !== dmin < Q.treeFar + 35 || m.userData.far.visible !== dmax > Q.treeFar - 35) { bad.push(`tree detail off on ${Q.name}`); break; } }
    if (quality === 0 && trees.some(m => m.visible)) bad.push('low should only draw the simple trees');
    if (quality === 0 && trees.some(m => m.userData.kind === 'bush' && (m.visible || m.userData.far.visible))) bad.push('low should leave out the undergrowth');
  }
  if (!seen[3].includes('auto')) bad.push(`fourth press should return to auto, got "${seen[3]}"`);
  if (renderer.info.programs.length !== progs0) bad.push(`changing setting compiled ${renderer.info.programs.length - progs0} new shader(s)`);
  return { bad, seen };
}

// A tree detail change mustn't pop: hold the long lens still where a chunk sits right at the high setting's detail
// distance, nudge that distance 0.6 m either way (what riding 0.6 m does), and count the pixels that change a lot.
// A whole chunk swapping at once changes thousands; a smooth hand-over almost none. Returns the share of the frame, %.
/* global sky, hills */
export function lodPop() {
  setQuality(2); const gl = renderer.getContext(), W = gl.drawingBufferWidth, H = gl.drawingBufferHeight, Q = QUALITY[2], far0 = Q.treeFar;
  const cz = 225 - 225 - far0;   // the chunk centred on z = 225 is at the detail distance from here
  const frame = far => {
    Q.treeFar = far;
    camera.position.set(0, 2.6, cz); camera.lookAt(70, 5, cz + 330); camera.fov = 19; camera.updateProjectionMatrix(); camera.updateMatrixWorld();
    sky.position.copy(camera.position); hills.position.set(0, 0, cz); shore.position.z = Math.round(cz / LAND_P) * LAND_P;
    updateTreeLod(); renderer.shadowMap.needsUpdate = true; renderReflection(); renderPost();
    const px = new Uint8Array(W * H * 4); gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px); return px;
  };
  const changed = (a, b) => { let n = 0; for (let i = 0; i < a.length; i += 4) if (Math.max(Math.abs(a[i] - b[i]), Math.abs(a[i + 1] - b[i + 1]), Math.abs(a[i + 2] - b[i + 2])) > 24) n++; return 100 * n / (a.length / 4); };
  const pct = changed(frame(far0 - 0.3), frame(far0 + 0.3)), same = changed(frame(far0 + 0.3), frame(far0 + 0.3));
  Q.treeFar = far0; updateTreeLod(); cam.snap = true; step(0.05);
  return { changedPct: +pct.toFixed(3), noisePct: +same.toFixed(3) };
}

const RUNS = [{ cut: 3, mode: 'relaxed' }, { cut: 3, mode: 'hold' }, { cut: 3, mode: 'pop' }, { cut: 6, mode: 'hold' }, { cut: 6, mode: 'pop' }];
// misses: every target in jump_bench.py's TARGETS table the runs miss, and popped 6 m jumps that don't clear the far crest
export async function bench() {
  const src = await (await fetch('/tools/jump_bench.py?' + Date.now())).text();
  const js = src.split('RUN_JS = """')[1].split('"""')[0];
  const run = (0, eval)('(' + js + ')');
  const targets = [...src.split('\nTARGETS = [')[1].split(']\n')[0].matchAll(/\("([^"]+)", "(\w+)", ([\d.]+), ([\d.]+), "(\w+)"\)/g)]
    .map(m => ({ label: m[1], key: m[2], lo: +m[3], hi: +m[4], which: m[5] }));
  if (targets.length !== 5) throw new Error(`read ${targets.length} jump targets from jump_bench.py, want 5`);
  const raw = RUNS.map(cfg => run(cfg)), misses = [];
  for (const t of targets) for (const r of raw) if ((t.which === 'all' || r.cfg.mode === t.which) && !(r[t.key] >= t.lo && r[t.key] <= t.hi))
    misses.push(`${r.cfg.cut} m ${r.cfg.mode}: ${t.label} ${fmt(r[t.key])} (want ${t.lo}-${t.hi})`);
  for (const r of raw) if (r.cfg.mode === 'pop' && r.cfg.cut === 6 && !(r.landed != null && r.landed > r.farCrest))
    misses.push(`6 m pop: landed at ${r.landed == null ? '-' : fmt(r.landed)}, short of the far crest ${fmt(r.farCrest)}`);
  const runs = raw.map(r => ({ run: `${r.cfg.cut} m ${r.cfg.mode}`, result: r.result, airT: +r.airT.toFixed(3), aboveLip: +r.aboveLip.toFixed(3),
    landed: r.landed == null ? null : +r.landed.toFixed(2), farCrest: +r.farCrest.toFixed(2), speedRatio: +r.speedRatio.toFixed(3), maxT: +r.maxT.toFixed(3) }));
  return { runs, misses };
}
// Riding across the trough with Space held (the line loaded), from the foot of the near wake's back face to the far
// wake, at 4-8 m/s sideways (8 is a hard cut or a short landing), over a spread of boil phases (the stern's place on the
// lake) and chop times: the ripples, the boil and the chop together mustn't launch the rider anywhere short of the far
// crest's last metre (going out over the far wake loaded is a jump: that's fine, and it's where nearCrest counts it).
// Freezes the game like bench(), so run it last.
/* global stepRider, resetRider, BOAT_SPEED, simTime */
export function checkTrough() {
  physics = function () {}; gatherInput = function () {};
  const bad = [], dt = 1 / 120;
  let runs = 0;
  for (let ph = 0; ph < 12; ph += 1.5) for (const t0 of [0, 1.7, 3.1]) for (const v0 of [4, 6, 7, 8]) for (const side of [1, -1]) {
    boatZ = ph; simTime = t0; resetRider(); runs++;
    for (let t = 0; t < 0.3; t += dt) { boatZ += BOAT_SPEED * dt; simTime += dt; stepRider(dt); }
    const d0 = boatZ - STERN_OFF - R.pos.z;
    R.pos.x = -side * (crestX(d0) - (1.3 + 0.04 * d0)); R.vel.x = side * v0; R.vySurf = 0; R.steerIn = side; R.loading = true;
    for (let t = 0; t < 3; t += dt) {
      boatZ += BOAT_SPEED * dt; simTime += dt; stepRider(dt);
      const xc = crestX(boatZ - STERN_OFF - R.pos.z), far = side * R.pos.x > xc - 1;
      if (R.state === 'air') { if (!far) bad.push(`launched at x=${fmt(R.pos.x)} (far crest ${fmt(side * xc)}) at ${v0} m/s, phase ${ph}, chop ${t0}`); break; }
      if (side * R.pos.x > xc) break;
    }
    R.loading = false; R.steerIn = 0;
  }
  return bad.length > 10 ? [`${bad.length} of ${runs} crossings launched early`, ...bad.slice(0, 10)] : bad;
}

// Look from anywhere: hold the camera at pos looking at target (the game's camera code is swapped out, since any frame
// the browser draws on its own would otherwise put it back), until unpeek(). Coordinates are world metres; the course
// runs along +z, the banks at x = ±76.
/* global camera, updateCamera */
export function peek(pos, target, fov = 54) {
  if (!window.__probeCam) window.__probeCam = window.updateCamera;   // on window, so a re-imported probe still finds it
  window.updateCamera = () => { camera.position.set(...pos); camera.lookAt(...target); camera.fov = fov; camera.updateProjectionMatrix(); };
  step(0.05);
}
export function unpeek() { if (window.__probeCam) { window.updateCamera = window.__probeCam; window.__probeCam = null; camera.fov = cam.fov; cam.snap = true; step(0.05); } }

// after a reload: wait for the loader, take the handle, fix quality on high, hide the HUD and ride a couple of seconds
/* global booted, qualityAuto */
export async function start(q = 2) {
  await new Promise(r => { const t = setInterval(() => { if (typeof booted !== 'undefined' && booted) { clearInterval(t); r(); } }, 100); setTimeout(() => { clearInterval(t); r(); }, 15000); });
  document.getElementById('go')?.click(); window.qualityAuto = false; qualityAuto = false; setQuality(q); hud(false); step(2.5);
}

// Save what the game just drew as a JPEG, by posting it to a local upload server on :8792 (for a hidden tab, where the
// browser's own screenshots go stale). Draws one frame first, then copies the canvas in the same task, before the
// drawing buffer is cleared.
export async function shot(name, w = 1280) {
  tick(1 / 60);
  const src = document.getElementById('c'), h = Math.round(w * src.height / src.width);
  const c = document.createElement('canvas'); c.width = w; c.height = h; c.getContext('2d').drawImage(src, 0, 0, w, h);
  const blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.88));
  await fetch(`http://127.0.0.1:8792/${name}.jpg`, { method: 'POST', body: blob });
  return name;
}

// GPU time per frame (ms), from timer queries: the reflection pass (with the shadow map, which the first render of a
// frame draws) and the main scene plus post. Unaffected by how busy the CPU is, unlike render().
export async function gpu(n = 30) {
  const gl = renderer.getContext(), ext = gl.getExtension('EXT_disjoint_timer_query_webgl2'); if (!ext) return null;
  const timed = fn => { const q = gl.createQuery(); gl.beginQuery(ext.TIME_ELAPSED_EXT, q); fn(); gl.endQuery(ext.TIME_ELAPSED_EXT); return q; };
  const qs = [];
  for (let i = 0; i < n; i++) { renderer.shadowMap.needsUpdate = true; qs.push([timed(() => renderReflection()), timed(() => renderPost())]); }
  await new Promise(r => setTimeout(r, 0));   // results only arrive after the task that issued them
  const sum = [0, 0];
  for (const pair of qs) for (let k = 0; k < 2; k++) {
    const q = pair[k]; for (let t = 0; t < 400 && !gl.getQueryParameter(q, gl.QUERY_RESULT_AVAILABLE); t++) await new Promise(r => setTimeout(r, 5));
    sum[k] += gl.getQueryParameter(q, gl.QUERY_RESULT) / 1e6; gl.deleteQuery(q);
  }
  return { refl: +(sum[0] / n).toFixed(2), main: +(sum[1] / n).toFixed(2), total: +((sum[0] + sum[1]) / n).toFixed(2) };
}

// Checks for the real wake shape (docs/superpowers/plans/2026-11-19-real-wake-shape.md): each returns the list of what's
// wrong, empty when it all holds. Figures are the spec's, at the rider's distance unless said.
/* global wakeH, crestX, wakeTrough, WAKE_GLSL, THREE */
const near = (v, want, tol) => Math.abs(v - want) <= tol;
const fmt = v => (+v).toFixed(3);
// the shape of one side of the wake at distance d: crest, the dip outside it, the ramp and back face, the middle
export function wakeProfile(d, ph = 0) {
  const xc = crestX(d), h = u => wakeH(u, d, ph), du = 0.01;
  let dip = { h: 9, s: 0 };
  for (let s = 0.2; s <= 5; s += du) { const v = h(xc + s); if (v < dip.h) dip = { h: v, s }; }
  const slope = (a, b) => Math.atan(Math.abs(h(a) - h(b)) / Math.abs(b - a)) / (Math.PI / 180);
  let back = 0, inMin = 9, ripples = 0;
  for (let s = -0.05; s >= -2.6; s -= du) back = Math.max(back, slope(xc + s, xc + s - du));
  for (let u = 0; u < xc - 0.05; u += du) inMin = Math.min(inMin, h(u));
  for (let s = -0.5; s >= -2.8 && xc + s > 0.3; s -= du) { const a = h(xc + s + du), b = h(xc + s), c = h(xc + s - du); if (b > a && b > c) ripples++; }
  let mid = [9, -9]; for (let u = -0.8; u <= 0.8; u += du) { const v = h(u); mid = [Math.min(mid[0], v), Math.max(mid[1], v)]; }
  return { xc, crest: h(xc), dip: dip.h, dipS: dip.s, lip: slope(xc + 0.02, xc + 0.08), back, ripples, inMin, mid, trough: -wakeTrough(d) };
}
export function checkWake() {
  const bad = [], miss = (what, got, want) => bad.push(`${what}: ${got} (want ${want})`);
  if (typeof wakeTrough !== 'function') return ['wakeTrough(d) missing'];
  const p = wakeProfile(16.5);
  if (!near(p.xc, 3.65, 0.15)) miss('crest half-width at 16.5 m', fmt(p.xc), '3.65 ±0.15');
  if (!near(p.crest, 0.34, 0.03)) miss('crest height', fmt(p.crest), '0.34 ±0.03');
  if (!near(p.dip, -0.29, 0.04)) miss('dip depth', fmt(p.dip), '-0.29 ±0.04');
  if (!(p.dipS > 1.4 && p.dipS < 2.8)) miss('dip distance outside the crest', fmt(p.dipS), '1.4-2.8 m');
  if (!(p.lip >= 28 && p.lip <= 33)) miss('lip slope deg', fmt(p.lip), '28-33');
  if (!(p.back <= 25 && p.back >= 15)) miss('back face max slope deg', fmt(p.back), '15-25');
  if (p.ripples < 1 || p.ripples > 2) miss('ripples inside the crest', p.ripples, '1-2');
  if (!near(p.trough, -0.24, 0.03)) miss('middle trough level', fmt(p.trough), '-0.24 ±0.03');
  if (!(p.mid[0] >= p.trough - 0.045 && p.mid[1] <= p.trough + 0.045)) miss('middle within ±4 cm of the trough', p.mid.map(fmt).join('..'), `${fmt(p.trough)} ±0.04`);
  if (!(p.crest - p.inMin >= 0.55 && p.crest - p.inMin <= 0.66)) miss('trough to crest', fmt(p.crest - p.inMin), '0.55-0.65');
  // along the course
  const c = d => wakeH(crestX(d), d, 0), c0 = c(16.5);
  if (!near(c(0.5), 0.15, 0.05)) miss('crest at the transom', fmt(c(0.5)), '0.15 ±0.05');
  for (const d of [10, 13, 20]) if (c(d) < 0.9 * c0) miss(`crest at ${d} m vs 16.5 m`, fmt(c(d) / c0), '>= 0.9');
  if (!near(c(60) / c0, 0.75, 0.08)) miss('crest at 60 m vs 16.5 m', fmt(c(60) / c0), '0.75 ±0.08');
  if (!near(c(200) / c0, 0.55, 0.08)) miss('crest at 200 m vs 16.5 m', fmt(c(200) / c0), '0.55 ±0.08');
  if (!near(-wakeTrough(1.5), -0.45, 0.05)) miss('trough behind the transom', fmt(-wakeTrough(1.5)), '-0.45 ±0.05');
  if (!near(-wakeTrough(40), -0.1, 0.04)) miss('trough at 40 m', fmt(-wakeTrough(40)), '-0.10 ±0.04');
  if (Math.abs(wakeTrough(70)) > 0.03) miss('trough at 70 m', fmt(-wakeTrough(70)), '0 ±0.03');
  // smooth and finite everywhere: nothing ahead of the transom, no steps (2 cm apart) except right at a crest
  for (let d = -5; d <= 300; d += d < 30 ? 0.5 : 5) {
    const xc = crestX(Math.max(d, 0));
    for (let u = -12; u <= 12; u += 0.02) {
      const v = wakeH(u, d, 0.37), w = wakeH(u + 0.02, d, 0.37);
      if (!Number.isFinite(v)) { bad.push(`not finite at u=${fmt(u)} d=${d}`); return bad; }
      if (d <= 0 && Math.abs(v) > 0.01) { bad.push(`height ahead of the transom at u=${fmt(u)} d=${d}: ${fmt(v)}`); return bad; }
      if (Math.abs(w - v) > 0.03 && Math.abs(Math.abs(u + 0.01) - xc) > 0.05) { bad.push(`step of ${fmt(w - v)} at u=${fmt(u)} d=${d}`); return bad; }
    }
  }
  for (let u = -8; u <= 8; u += 0.25) for (let d = 0; d < 120; d += 0.02)
    if (Math.abs(wakeH(u, d + 0.02, 0.37) - wakeH(u, d, 0.37)) > 0.03) { bad.push(`step along the course at u=${u} d=${fmt(d)}`); return bad; }
  return bad;
}
// The shaders' wake() against the physics' wakeH(): render wake(u, d, ph).x on a grid into a float target and compare.
// Returns the samples more than 1 mm apart (and shader errors), empty when they agree.
/* global renderer */
export function checkWakeGPU(ph = 0.37) {
  const NU = 121, ND = 98, uAt = i => -12 + i * 0.2, dAt = j => (j < 70 ? -5 + j * 0.5 : 30 + (j - 70) * 10);
  const rt = new THREE.WebGLRenderTarget(NU, ND, { type: THREE.FloatType, format: THREE.RGBAFormat, depthBuffer: false });
  const mat = new THREE.ShaderMaterial({ uniforms: { uPh: { value: ph } },
    vertexShader: 'void main(){ gl_Position=vec4(position.xy,0.0,1.0); }',
    fragmentShader: `uniform float uPh; ${WAKE_GLSL}
      void main(){ float i=floor(gl_FragCoord.x), j=floor(gl_FragCoord.y);
        float u=-12.0+i*0.2, d=j<70.0?-5.0+j*0.5:30.0+(j-70.0)*10.0;
        gl_FragColor=vec4(wake(u,d,uPh).x,0.0,0.0,1.0); }` });
  const sc = new THREE.Scene(), q = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat); q.frustumCulled = false; sc.add(q);
  const prev = renderer.getRenderTarget(), errs = [], log = console.error; console.error = (...a) => { errs.push(a.join(' ').slice(0, 300)); };
  renderer.setRenderTarget(rt); renderer.render(sc, new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)); renderer.setRenderTarget(prev);
  console.error = log;
  const px = new Float32Array(NU * ND * 4); renderer.readRenderTargetPixels(rt, 0, 0, NU, ND, px);
  rt.dispose(); mat.dispose(); q.geometry.dispose();
  if (errs.length) return errs;
  const bad = [];
  for (let j = 0; j < ND; j++) for (let i = 0; i < NU; i++) {
    const g = px[(j * NU + i) * 4], c = wakeH(uAt(i), dAt(j), ph);
    if (!(Math.abs(g - c) <= 0.001)) bad.push(`u=${uAt(i).toFixed(1)} d=${dAt(j)}: gpu ${fmt(g)} cpu ${fmt(c)}`);
  }
  return bad.length > 12 ? [...bad.slice(0, 12), `...and ${bad.length - 12} more`] : bad;
}
// The water grid across the wake: fine columns within ±12 m of the boat's track at the setting's `fine` spacing, the
// grid centred on the track, and the GPU cost on high within 15% of a baseline: the v0.7.0 page's best of five gpu(40)
// runs from the same camera, taken in the same session (GPU timings swing a lot run to run; the best is the steadiest).
// On this Mac's pane that was 8.98 ms from the follow camera.
/* global waterNear, QUALITY */
export async function bestGpu(n = 5) { let b = 1e9; for (let i = 0; i < n; i++) { step(0.2); b = Math.min(b, (await gpu(40)).total); } return b; }
export async function checkWater(baseMs = 8.98) {
  const bad = [], Q = QUALITY[quality];
  if (!Q.fine) return [`QUALITY[${quality}].fine missing`];
  const pos = waterNear.geometry.attributes.position, z0 = pos.getZ(0), xs = [];
  for (let i = 0; i < pos.count && pos.getZ(i) === z0; i++) xs.push(pos.getX(i));
  let gap = 0; for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i]) <= 12 && Math.abs(xs[i - 1]) <= 12) gap = Math.max(gap, xs[i] - xs[i - 1]);
  if (Math.abs(gap - Q.fine) > 0.01) bad.push(`spacing across the wake ${fmt(gap)} m (want ${Q.fine})`);
  if (waterNear.position.x !== 0) bad.push(`grid centred at x=${waterNear.position.x} (want 0, the boat's track)`);
  if (quality === 2 && baseMs) { const g = await bestGpu(); if (g > baseMs * 1.15) bad.push(`gpu ${g} ms on high (want <= ${fmt(baseMs * 1.15)})`); }
  return bad;
}
// What counts as a wake jump: taking off within a metre of a crest, not from the dip outside it or the trough inside.
/* global nearCrest, wakeToWake */
export function checkScoring() {
  if (typeof nearCrest !== 'function') return ['nearCrest(u, d) missing'];
  if (typeof wakeToWake !== 'function') return ['wakeToWake(takeoffU, x, d) missing'];
  const d = 16.5, xc = crestX(d), bad = [];
  // wake to wake: down on the other side, past the far crest (not on its upslope short of it)
  for (const [u0, x, want, what] of [[-xc, xc + 0.3, true, 'just past the far crest'], [-xc, xc - 0.3, false, 'on the far upslope, 0.3 m short'],
    [xc, -(xc + 1), true, 'past the far crest, other way'], [-xc, -(xc + 1), false, 'back on the same side'], [-xc, 0.5, false, 'in the trough']])
    if (wakeToWake(u0, x, d) !== want) bad.push(`wake to wake, ${what}: ${want ? "doesn't count" : 'counts'}`);
  for (const [u, want, what] of [[xc - 0.3, true, 'the lip, just inside'], [-(xc + 0.4), true, 'the ramp below the lip'], [xc + 2.1, false, 'the dip outside'],
    [0, false, 'the middle of the trough'], [-(xc - 1.6), false, 'the foot of the back face'], [xc + 6, false, 'the flats']])
    if (nearCrest(u, d) !== want) bad.push(`${what} (u=${fmt(u)}): ${!want ? 'counts' : "doesn't count"} as a wake takeoff`);
  return bad;
}
// The rest of jump_bench.py, in the page: its TRICKS, CRASHES and GRABS tables, read from the .py and judged the same
// way, after bench()'s runs. Returns { misses } (empty when the whole bench passes) and the rows. Freezes the game.
export async function benchAll() {
  const src = await (await fetch('/tools/jump_bench.py?' + Date.now())).text();
  const js = src.split('RUN_JS = """')[1].split('"""')[0], run = (0, eval)('(' + js + ')');
  const table = name => (0, eval)('[' + src.split(`\n${name} = [`)[1].split('\n]')[0]
    .replace(/\((-?\d+), (True|False)\)/g, '[$1, $2]').replace(/\bTrue\b/g, 'true').replace(/\bFalse\b/g, 'false').replace(/\bNone\b/g, 'null') + ']');
  const crashT = [...src.split('CRASH_TARGETS = [')[1].split(']\n')[0].matchAll(/\("(\w+)", "([^"]+)", (-?[\d.]+), (-?[\d.]+)\)/g)].map(m => [m[1], m[2], +m[3], +m[4]]);
  const crashOk = c => crashT.every(([k, , lo, hi]) => c[k] >= lo && c[k] <= hi);
  const b = await bench(), misses = [...b.misses], rows = {};
  rows.tricks = table('TRICKS').map(tr => {
    const r = run({ cut: 6, mode: 'pop', trick: tr }), per = tr.axis === 'spin' ? 180 : 360, landsAs = Math.round(r.rot / per) * per, rode = r.result === 'landed';
    const [wantRot, wantRide] = tr.expect, ok = rode === wantRide && (landsAs === wantRot || !wantRide);
    if (!ok) misses.push(`trick ${tr.name}: turned ${Math.round(r.rot)}, lands as ${landsAs}, ${rode ? 'rode away' : r.failReason || r.result}`);
    return { name: tr.name, rot: Math.round(r.rot), landsAs, rode, landing: r.landingSpeed && +r.landingSpeed.toFixed(2) };
  });
  rows.crashes = table('CRASHES').map(spec => {
    const r = run({ cut: 3, mode: 'pop', trick: spec.trick, follow: true }), c = r.crash;
    let ok = !!c && (r.failReason || '').includes(spec.reason) && crashOk(c);
    if (c && spec.fall === 'up') ok = ok && c.chest > 0.3; if (c && spec.fall === 'down') ok = ok && c.chest < -0.3;
    if (!ok) misses.push(`crash ${spec.name}: ${c ? JSON.stringify(Object.fromEntries(Object.entries(c).map(([k, v]) => [k, +v.toFixed(2)]))) : 'no crash'} ${r.failReason || r.result}`);
    return { name: spec.name, reason: r.failReason, crash: c };
  });
  const plain = b.runs.find(r => r.run === '6 m pop');
  rows.grabs = table('GRABS').map(g => {
    const until = g.until === 'late' ? plain.airT - 0.12 : g.until;
    const r = run({ cut: 6, mode: 'pop', grab: { name: g.grab, from: g.from, until }, follow: !g.ride });
    const text = (r.shown || []).filter((x, i) => i % 2 === 0 && x).join(' | '), rode = r.result === 'landed';
    let ok = rode === g.ride && g.has.every(h => text.includes(h)) && !g.not.some(n => text.includes(n));
    if (r.crash) ok = ok && crashOk(r.crash);
    if (!ok) misses.push(`grab ${g.name}: ${rode ? 'rode away' : r.failReason || r.result}, "${text}"`);
    return { name: g.name, text, rode };
  });
  return { misses, runs: b.runs, ...rows };
}

// Checks for the whitewater pass (docs/superpowers/plans/2026-11-19-whitewater.md).
// foamCover: for each region of the wake (boat frame: u across, d behind the transom; with crest:true, u is s = |u| - crest,
// measured on both sides), look straight down from 14 m (or the region's h) over it with the board's foam, the spray, the rider and the rope
// hidden, and return the share (%) of points, 6 per metre each way, whose pixel is foam (brightest channel over 170).
/* global foam, rider, ropeSegs, waterNear, waterFar, WATER_SP, waterAt, simTime */
export const FOAM_REGIONS = [
  { name: 'ahead', u: [3, 8], d: [-12, -1], want: [0, 0] },
  { name: 'mid5', u: [-0.8, 0.8], d: [3, 7], want: [60, 100] },
  { name: 'mid50', u: [-0.8, 0.8], d: [45, 55], want: [15, 60] },
  { name: 'mid100', u: [-0.8, 0.8], d: [95, 105], want: [3, 100] },
  { name: 'mid150', u: [-0.8, 0.8], d: [145, 155], want: [0, 3] },
  { name: 'crest5', crest: true, u: [-0.4, 0.2], d: [4, 7], want: [50, 100] },
  { name: 'crest20', crest: true, u: [-0.4, 0.2], d: [18, 23], want: [15, 60] },
  { name: 'crest40', crest: true, u: [-0.4, 0.2], d: [38, 43], want: [5, 100] },
  { name: 'crest80', crest: true, u: [-0.4, 0.2], d: [78, 83], want: [0, 5] },
  { name: 'face20', crest: true, u: [0.5, 1.5], d: [18, 23], want: [0, 10] },
  { name: 'lace20', crest: true, u: [-2.2, -1], d: [18, 23], want: [10, 50] },
  { name: 'lace60', crest: true, u: [-3, -1], d: [58, 62], want: [0, 10] },
  { name: 'flats', crest: true, u: [4, 6], d: [18, 23], want: [0, 2] },
  // from 75 m up, where a pixel covers about 15 cm of lake: the breaking crest must still read as white, not grey
  { name: 'crest5high', crest: true, u: [-0.4, 0.2], d: [4, 7], h: 75, want: [40, 100] },
];
export function foamCover(regions = FOAM_REGIONS) {
  const gl = renderer.getContext(), W = gl.drawingBufferWidth, H = gl.drawingBufferHeight, sz = boatZ - STERN_OFF;
  const hide = [foam, spray.mesh, rider, ...ropeSegs], vis = hide.map(o => o.visible); hide.forEach(o => { o.visible = false; });
  const fov0 = camera.fov, q0 = camera.quaternion.clone(), p = new THREE.Vector3(), px = new Uint8Array(W * H * 4), out = {};
  for (const r of regions) {
    let hit = 0, n = 0;
    for (const side of r.crest ? [-1, 1] : [1]) {
      const at = (a, d) => r.crest ? side * (crestX(d) + a) : a;
      const uc = at((r.u[0] + r.u[1]) / 2, (r.d[0] + r.d[1]) / 2), zc = sz - (r.d[0] + r.d[1]) / 2;
      camera.position.set(uc, r.h || 14, zc); camera.quaternion.setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0));
      camera.fov = 54; camera.updateProjectionMatrix(); camera.updateMatrixWorld();
      waterNear.position.set(0, 0, Math.round(zc / WATER_SP) * WATER_SP); waterFar.position.set(uc, -0.02, zc);
      const hw = waterNear.geometry.userData.half; waterFar.material.uniforms.uNearRect.value.set(waterNear.position.x, waterNear.position.z, hw[0] - 1, hw[1] - 1);
      renderer.shadowMap.needsUpdate = true; renderReflection(); renderPost();
      gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px);
      for (let a = r.u[0]; a <= r.u[1] + 1e-6; a += 1 / 6) for (let d = r.d[0]; d <= r.d[1] + 1e-6; d += 1 / 6) {
        const x = at(a, d), z = sz - d; p.set(x, waterAt(x, z, boatZ, simTime), z).project(camera);
        const ix = Math.floor((p.x + 1) / 2 * W), iy = Math.floor((p.y + 1) / 2 * H);
        if (ix < 0 || iy < 0 || ix >= W || iy >= H) continue;
        const k = (iy * W + ix) * 4; n++; if (Math.max(px[k], px[k + 1], px[k + 2]) > 170) hit++;
      }
    }
    out[r.name] = n ? +(100 * hit / n).toFixed(1) : NaN;
  }
  hide.forEach((o, i) => { o.visible = vis[i]; });
  camera.quaternion.copy(q0); camera.fov = fov0; camera.updateProjectionMatrix(); cam.snap = true; step(0.05);
  return out;
}
// every region outside the share of foam it should have, averaged over n moments half a second apart (the foam's pattern
// is fixed to the lake, so a few square metres can be lucky or unlucky at any one moment)
export function checkFoam(n = 4) {
  const runs = []; for (let i = 0; i < n; i++) { if (i) step(0.55); runs.push(foamCover()); }
  const got = Object.fromEntries(Object.keys(runs[0]).map(k => [k, +(runs.reduce((s, r) => s + r[k], 0) / n).toFixed(1)])), bad = [];
  for (const r of FOAM_REGIONS) { const v = got[r.name]; if (!(v >= r.want[0] && v <= r.want[1])) bad.push(`${r.name} ${v}% (want ${r.want[0]}-${r.want[1]})`); }
  return bad;
}
// Stills for screenshots: freeze() stops the game loop (the page keeps its last frame), freeze(false) starts it again.
// overhead(u, d, h) freezes and draws the view straight down from h metres over (u, d) in the boat frame.
/* global frame */
// The game's tick is swapped out too: a hidden pane holds back animation frames, so the one already queued can run later,
// at the screenshot, and draw over the still.
// The loop's next request is held (not dropped) while frozen, and unfreezing hands back only that: if the frame already
// queued when it froze hasn't run yet, the loop never stopped, and queueing another would run two.
export function freeze(on = true) {
  if (on && !window.__raf) { window.__raf = window.requestAnimationFrame; window.__tick = window.tick; window.__held = null; window.requestAnimationFrame = cb => { window.__held = cb; return 0; }; window.tick = () => {}; }
  else if (!on && window.__raf) { const held = window.__held; window.requestAnimationFrame = window.__raf; window.tick = window.__tick; delete window.__raf; delete window.__tick; delete window.__held; if (held) window.requestAnimationFrame(held); }
}
export function overhead(u = 0, d = 20, h = 14, fov = 54) {
  freeze(true); const sz = boatZ - STERN_OFF, z = sz - d;
  camera.position.set(u, h, z); camera.quaternion.setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0));
  camera.fov = fov; camera.updateProjectionMatrix(); camera.updateMatrixWorld();
  waterNear.position.set(0, 0, Math.round(z / WATER_SP) * WATER_SP); waterFar.position.set(u, -0.02, z);
  const hw = waterNear.geometry.userData.half; waterFar.material.uniforms.uNearRect.value.set(waterNear.position.x, waterNear.position.z, hw[0] - 1, hw[1] - 1);
  renderer.shadowMap.needsUpdate = true; renderReflection(); renderPost(); flick();
}
// a hidden pane only repaints when the page visibly changes, and a new WebGL frame alone doesn't count: flick a dot
export function flick() {
  let dot = document.getElementById('probe-dot');
  if (!dot) { dot = document.createElement('div'); dot.id = 'probe-dot'; dot.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;z-index:99;pointer-events:none'; document.body.appendChild(dot); }
  dot.style.background = ++stepN % 2 ? '#010101' : '#020202';
}
// a frozen still from one of the game's cameras (0 follow, 1 long lens, 2 tower)
export function still(mode) { freeze(false); hud(false); view(mode); freeze(true); renderer.shadowMap.needsUpdate = true; renderReflection(); renderPost(); flick(); }
// Crest spray: particles emitted over one second within half a metre of a crest, 2.5 to 13 m behind the transom (clear of
// the prop wash and the rider), as a share of what the high setting throws. Returns what's wrong.
/* global BOAT_SPEED, crestStrength */
export function checkCrestSpray() {
  const bad = [], q = quality;
  const count = () => {
    const c0 = spray.clock, i0 = spray.i; step(1);
    const T = spray.geo.attributes.aT.array, P0 = spray.geo.attributes.aP0.array; let n = 0;
    for (let k = 0; k < spray.size; k++) {
      const t0 = T[k * 4]; if (!(t0 > c0) || T[k * 4 + 1] <= 0) continue;
      const bz = boatZ - BOAT_SPEED * (spray.clock - t0), d = bz - STERN_OFF - P0[k * 3 + 2], x = P0[k * 3];
      if (d >= 2.5 && d <= 13 && Math.abs(Math.abs(x) - crestX(d)) < 0.5) n++;
    }
    return { n, wrapped: spray.i < i0 };
  };
  (0, eval)('qualityAuto=false'); setQuality(2); step(0.5);
  const hi = count(); setQuality(0); step(0.5); const lo = count(); setQuality(q);
  if (typeof crestStrength !== 'function' || !(crestStrength(3) > crestStrength(30))) bad.push('crestStrength(d) missing or not falling with d');
  if (hi.n < 80) bad.push(`only ${hi.n} crest particles a second on high, want 80+`);
  if (!(lo.n < hi.n * 0.5)) bad.push(`low throws ${lo.n}, high ${hi.n}: low should throw well under half`);
  return bad;
}
// freeze(false) must restart the loop only if freeze(true) actually stopped it (the frame already queued when it froze
// would otherwise carry on as a second loop). Spies on requestAnimationFrame; returns what's wrong.
export function checkFreeze() {
  const bad = [], raf = window.requestAnimationFrame; let calls = 0;
  window.requestAnimationFrame = cb => { calls++; return raf(cb); };
  try {
    freeze(true); freeze(false);
    if (calls !== 0) bad.push(`freeze then unfreeze before the queued frame ran queued ${calls} more loop(s)`);
    calls = 0; freeze(true); window.requestAnimationFrame(frame); freeze(false);   // the queued frame runs while frozen
    if (calls !== 1) bad.push(`unfreezing after the loop stopped queued ${calls} frame(s), want 1`);
  } finally { window.requestAnimationFrame = raf; }
  return bad;
}
// Shimmer: the share (%) of water pixels (the lower part of the frame) that flash and flash back over three 60 fps frames
// (brighter or darker than both neighbours by more than 40), averaged over n triples, from one of the game's cameras while
// it rides. Foam that really moves past changes a pixel once; only aliasing flips it and back.
export function shimmer(mode = 0, n = 6, from = 0.45) {
  freeze(false); hud(false); view(mode);
  const gl = renderer.getContext(), W = gl.drawingBufferWidth, H = gl.drawingBufferHeight, rows = Math.floor(H * (1 - from));
  const grab = () => { renderer.shadowMap.needsUpdate = true; renderReflection(); renderPost(); const px = new Uint8Array(W * rows * 4); gl.readPixels(0, 0, W, rows, gl.RGBA, gl.UNSIGNED_BYTE, px); return px; };
  const lum = (p, i) => 0.3 * p[i] + 0.59 * p[i + 1] + 0.11 * p[i + 2];
  let pct = 0;
  for (let k = 0; k < n; k++) {
    tick(1 / 60); const a = grab(); tick(1 / 60); const b = grab(); tick(1 / 60); const c = grab(); let f = 0;
    for (let i = 0; i < a.length; i += 4) { const da = lum(b, i) - lum(a, i), dc = lum(b, i) - lum(c, i); if (Math.abs(da) > 40 && Math.abs(dc) > 40 && Math.sign(da) === Math.sign(dc)) f++; }
    pct += 100 * f / (a.length / 4) / n;
  }
  return +pct.toFixed(3);
}
