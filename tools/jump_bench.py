"""Jump test bench for Wake Session.

Runs the game's own physics (index.html, in headless Chromium) through a set of scripted wake jumps, checks the
results against real-world targets, and draws the jump arcs over the wake so you can tune by eye.

    pip install playwright matplotlib numpy
    playwright install chromium
    python tools/jump_bench.py                 # writes tools/out/jump_bench.png and prints a pass/fail table
    python tools/jump_bench.py --three path/to/three.min.js   # use a local three.js when offline

Each run cuts out a set distance beyond the wake, settles, then edges hard back in. Three rider styles:
  relaxed  no Space: the legs soak up the wake
  hold     Space held through the lip: stands tall and keeps the ramp's lift
  pop      Space released partway up the ramp: legs extend through the lip

The physics constants live at the top of the script in index.html (EDGE_LD, ROPE_K, ABSORB, ...); edit, re-run, compare.
"""
import argparse
import functools
import http.server
import pathlib
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
THREE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"

RUNS = [
    {"cut": 3, "mode": "relaxed"},
    {"cut": 3, "mode": "hold"},
    {"cut": 3, "mode": "pop"},
    {"cut": 6, "mode": "hold"},
    {"cut": 6, "mode": "pop"},
]

# (label, metric key, low, high, which runs it applies to). Ranges come from the research behind the plan:
# airtime and height are derived from wake-ramp physics and rider reports; speed and line load from water-ski studies.
TARGETS = [
    ("Popped airtime (s)", "airT", 0.9, 1.3, "pop"),
    ("Popped height above lip (m)", "aboveLip", 1.0, 1.8, "pop"),
    ("Rider speed (x boat)", "speedRatio", 1.15, 1.35, "pop"),
    ("Cruising line load (x body weight)", "cruiseT", 0.2, 0.4, "all"),
    ("Hard-cut line load (x body weight)", "maxT", 1.0, 1.5, "pop"),
]

# Scripted rider, run inside the page. Freezes the live loop and steps the sim by hand at 120 Hz.
RUN_JS = """
(cfg) => {
  physics = function(){}; gatherInput = function(){};
  boatZ = 0; simTime = 0; resetRider();   // same water, same chop, every run
  const dt = 1/120, traj = [];
  let t = 0, phase = 'settle', cruiseT = 0, maxT = 0, maxSpeed = 0, takeoff = null, landed = null, result = 'no jump';
  while (t < 30) {
    const d = boatZ - STERN_OFF - R.pos.z, xc = crestX(d);
    if (phase === 'settle') { R.steerIn = 0; if (t > 1) phase = 'cut'; if (t > 0.8) cruiseT = R.tension/(RIDER_M*G); }
    else if (phase === 'cut') { R.steerIn = -1; if (R.pos.x < -(xc + cfg.cut)) phase = 'hold'; }
    else if (phase === 'hold') { R.steerIn = 0; if (R.state === 'riding' && Math.abs(R.vel.x) < 0.5) phase = 'edge'; }
    else if (phase === 'edge') {
      R.steerIn = 1;
      if (cfg.mode !== 'relaxed' && R.state === 'riding') R.loading = true;
      if (R.state === 'riding' && R.vySurf > 1.5 && R.pos.x < 0) { if (cfg.mode === 'pop') { R.popRequest = true; R.loading = false; } phase = 'go'; }
      if (R.state === 'air') phase = 'go';
    } else R.steerIn = 0;
    const was = R.state;
    boatZ += BOAT_SPEED*dt; simTime += dt; stepRider(dt);
    if (phase === 'edge' || phase === 'go') {
      maxT = Math.max(maxT, R.tension/(RIDER_M*G));
      maxSpeed = Math.max(maxSpeed, Math.hypot(R.vel.x, R.vel.z));
      if (was === 'riding' && R.state === 'air') takeoff = {x: R.pos.x, y: R.pos.y, vy: R.vel.y, lip: wakeH(-crestX(d), d)};
      if (R.state === 'air') traj.push([R.pos.x, R.pos.y, R.airT]);
      if (takeoff && R.state !== 'air') { landed = R.pos.x; result = R.state === 'bail' ? 'bail' : 'landed'; break; }
    }
    t += dt;
  }
  const d = boatZ - STERN_OFF - R.pos.z;
  const wake = [];
  for (let u = -7; u <= 7.001; u += 0.05) wake.push([u, wakeH(u, d)]);
  const peak = traj.reduce((m, p) => Math.max(m, p[1]), -9);
  return {cfg, result, traj, wake, takeoff, landed, farCrest: crestX(d), cruiseT, maxT,
          speedRatio: maxSpeed/BOAT_SPEED, airT: traj.length ? traj[traj.length-1][2] : 0,
          aboveLip: takeoff ? peak - takeoff.lip : 0};
}
"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(root):
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_bench(three_path=None):
    from playwright.sync_api import sync_playwright
    server = serve(ROOT)
    url = f"http://127.0.0.1:{server.server_port}/index.html"
    results = []
    with sync_playwright() as p:
        # software WebGL so it runs on machines (and containers) without a GPU
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 640, "height": 360})
        if three_path:
            body = pathlib.Path(three_path).read_bytes()
            page.route(THREE_CDN, lambda route: route.fulfill(body=body, content_type="text/javascript"))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_function("typeof stepRider === 'function'")
        page.click("#go")
        for cfg in RUNS:
            results.append(page.evaluate(RUN_JS, cfg))
        browser.close()
    server.shutdown()
    if errors:
        raise SystemExit("page errors:\n" + "\n".join(errors))
    return results


def report(results):
    print(f"{'run':<16}{'result':<9}{'air s':>7}{'above lip m':>13}{'lands at m':>12}{'far crest m':>13}{'speed x':>9}{'line max':>10}")
    for r in results:
        c = r["cfg"]
        lands = f"{r['landed']:.2f}" if r["landed"] is not None else "-"
        print(f"{c['mode'] + ' ' + str(c['cut']) + ' m':<16}{r['result']:<9}{r['airT']:>7.2f}{r['aboveLip']:>13.2f}{lands:>12}"
              f"{r['farCrest']:>13.2f}{r['speedRatio']:>9.2f}{r['maxT']:>10.2f}")
    print()
    ok_all = True
    for label, key, lo, hi, which in TARGETS:
        vals = [r[key] for r in results if which == "all" or r["cfg"]["mode"] == which]
        ok = all(lo <= v <= hi for v in vals)
        ok_all &= ok
        print(f"{'PASS' if ok else 'MISS'}  {label:<38} target {lo}-{hi}   got {', '.join(f'{v:.2f}' for v in vals)}")
    cleared = [r for r in results if r["cfg"]["mode"] == "pop"]
    ok = all(r["landed"] is not None and r["landed"] > r["farCrest"] for r in cleared)
    ok_all &= ok
    print(f"{'PASS' if ok else 'MISS'}  {'Popped jumps clear the second wake':<38}")
    return ok_all


def plot(results, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    colors = {"relaxed": "#8a9aa5", "hold": "#d08a00", "pop": "#00806f"}
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [2.3, 1]})
    wake = np.array(results[0]["wake"])
    ax.fill_between(wake[:, 0], wake[:, 1], -0.6, color="#cfe3e6", zorder=0)
    ax.plot(wake[:, 0], wake[:, 1], color="#3b6d78", lw=1.5, label="wake at the rider's distance")
    for r in results:
        tr = np.array(r["traj"]) if r["traj"] else None
        if tr is None:
            continue
        c = r["cfg"]
        ax.plot(tr[:, 0], tr[:, 1], color=colors[c["mode"]], lw=2 if c["mode"] == "pop" else 1.3,
                ls="-" if c["cut"] == 3 else "--", label=f"{c['mode']}, cut {c['cut']} m: {r['airT']:.2f} s")
    ax.set_xlabel("sideways distance from the boat's centre line (m)")
    ax.set_ylabel("height (m)")
    ax.set_xlim(-7, 7)
    ax.set_ylim(-0.6, 3.2)
    ax.set_title("Jump arcs over the wake")
    ax.legend(fontsize=8, loc="upper left", frameon=False)
    ax.grid(alpha=0.25)

    labels = [f"{r['cfg']['mode']}\n{r['cfg']['cut']} m" for r in results]
    air = [r["airT"] for r in results]
    bx.axhspan(0.9, 1.3, color="#00806f", alpha=0.12, label="target, popped jump")
    bx.bar(labels, air, color=[colors[r["cfg"]["mode"]] for r in results])
    bx.set_ylabel("airtime (s)")
    bx.set_title("Airtime against the target")
    bx.legend(fontsize=8, frameon=False, loc="upper left")
    bx.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    print(f"\nplot written to {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--three", help="local three.min.js (r128) to use instead of the CDN")
    ap.add_argument("--out", default=str(ROOT / "tools" / "out" / "jump_bench.png"))
    args = ap.parse_args()
    res = run_bench(args.three)
    passed = report(res)
    plot(res, pathlib.Path(args.out))
    raise SystemExit(0 if passed else 1)
