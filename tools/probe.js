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
  for (const k of TREE_KINDS) for (const lod of [0, 1]) {
    const g = treeGeometry(k, lod, 1);
    for (const a of ['position', 'normal', 'uv', 'color', 'aSway']) if (!g.attributes[a]) bad.push(`${k} lod${lod} has no ${a}`);
  }
  const kinds = new Set(trees.map(m => m.userData.kind));
  for (const k of ['spruce', 'pine', 'broadleaf', 'birch', 'willow']) if (!kinds.has(k)) bad.push(`no ${k} planted`);
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
  if (!('props' in QUALITY[0])) bad.push('QUALITY has no props field');
  else { const q = quality; setQuality(0); const lo = props.visible; setQuality(2); const hi = props.visible; setQuality(q); if (lo || !hi) bad.push(`props visible low ${lo}, high ${hi}`); }
  return bad;
}

// Press P through every setting mid-ride: the label, tree density, spray rate, props and far-tree distance must all follow
/* global onDown, TREE_GEO */
export function checkQuality() {
  const bad = [], seen = [];
  (0, eval)('qualityAuto=true'); setQuality(2);
  for (let i = 0; i < 4; i++) {
    onDown('KeyP'); step(0.3);
    const Q = QUALITY[quality], label = document.getElementById('quality').textContent; seen.push(label);
    if (!label.includes(Q.name)) bad.push(`label "${label}" for ${Q.name}`);
    if (trees.some(m => m.count !== Math.round(m.userData.full * Q.trees))) bad.push(`tree density off on ${Q.name}`);
    if (spray.rate !== Q.spray) bad.push(`spray rate ${spray.rate} on ${Q.name}`);
    if (props.visible !== Q.props) bad.push(`props ${props.visible} on ${Q.name}`);
    const far = Q.treeFar, cz = camera.position.z - shore.position.z;
    if (trees.some(m => (Math.abs(cz - m.userData.zmid) - 225 > far ? 1 : 0) !== m.userData.lod)) bad.push(`tree detail off on ${Q.name}`);
  }
  if (!seen[3].includes('auto')) bad.push(`fourth press should return to auto, got "${seen[3]}"`);
  return { bad, seen };
}

const RUNS = [{ cut: 3, mode: 'relaxed' }, { cut: 3, mode: 'hold' }, { cut: 3, mode: 'pop' }, { cut: 6, mode: 'hold' }, { cut: 6, mode: 'pop' }];
export async function bench() {
  const src = await (await fetch('/tools/jump_bench.py?' + Date.now())).text();
  const js = src.split('RUN_JS = """')[1].split('"""')[0];
  const run = (0, eval)('(' + js + ')');
  return RUNS.map(cfg => {
    const r = run(cfg);
    return { run: `${cfg.cut} m ${cfg.mode}`, result: r.result, airT: +r.airT.toFixed(3), aboveLip: +r.aboveLip.toFixed(3),
             speedRatio: +r.speedRatio.toFixed(3), maxT: +r.maxT.toFixed(3) };
  });
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
