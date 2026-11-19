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
