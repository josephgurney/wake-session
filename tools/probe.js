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
