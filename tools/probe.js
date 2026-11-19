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
export function step(sec, fps = 60) { const n = Math.round(sec * fps); for (let i = 0; i < n; i++) tick(1 / fps); }
export function hud(show) { for (const id of ['hud', 'touch']) { const e = document.getElementById(id); if (e) e.style.visibility = show ? '' : 'hidden'; } }
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
    const c0 = spray.clock; openSettings(); step(0.5); const c1 = spray.clock;
    settingsEl.close(); await new Promise(r => setTimeout(r, 0)); step(0.5); const c2 = spray.clock;   // 'close' fires as its own task
    if (c1 !== c0) bad.push('spray clock runs while paused');
    if (!(c2 > c1 + 0.4)) bad.push('spray clock stuck after unpause');
    // quality sets the emission rate
    const q = quality; setQuality(0); const r0 = spray.rate; setQuality(2); const r2 = spray.rate; setQuality(q);
    if (!(r0 > 0 && r0 < r2 && r2 === 1)) bad.push(`spray.rate low ${r0}, high ${r2}`);
  }
  return bad;
}
/* global openSettings, settingsEl */

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
