"""Jump test bench for Thursday Yacht Club.

Runs the game's own physics (index.html, in headless Chromium) through a set of scripted wake jumps, checks the
results against real-world targets, and draws the jump arcs over the wake so you can tune by eye.

    pip install playwright matplotlib numpy
    playwright install chromium
    python tools/jump_bench.py                 # writes tools/out/jump_bench.png and prints a pass/fail table
    python tools/jump_bench.py --three path/to/three           # offline: an unpacked three.js package, same version as
                                                               # index.html (npm pack three@<version>, or node_modules/three)

Each run cuts out a set distance beyond the wake, settles, then edges hard back in. Three rider styles:
  relaxed  no Space: the legs soak up the wake
  hold     Space held through the lip: stands tall and keeps the ramp's lift
  pop      Space released partway up the ramp: legs extend through the lip

Then a trick table: the same popped jump with a scripted rotation input, wound up off the lip for a set time and then
relaxed, tucked (kept pushing) or opened (pushed back), to check what each input lands as.

Then a crash table: scripted crashes followed through the ragdoll for 2.3 s, checking which way the rider goes over,
how far they slide, how deep the head goes and that they end up floating.

The physics constants live at the top of the script in index.html (EDGE_LD, ROPE_K, ABSORB, ...); edit, re-run, compare.
"""
import argparse
import functools
import http.server
import pathlib
import re
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
# the game loads three.js from jsDelivr through an import map; keep the bench on the same version
THREE_VERSION = re.search(r"three@([0-9.]+)/build/three\.module\.js", (ROOT / "index.html").read_text()).group(1)
THREE_CDN = f"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/"

RUNS = [
    {"cut": 3, "mode": "relaxed"},
    {"cut": 3, "mode": "hold"},
    {"cut": 3, "mode": "pop"},
    {"cut": 6, "mode": "hold"},
    {"cut": 6, "mode": "pop"},
]

# Popped 6 m jumps with a rotation input: wound up for `charge` seconds off the lip, then 'relax' (let go), 'tuck' (keep
# pushing) or 'open' (push back). `expect` is (rotation it should land as, whether it should ride away).
TRICKS = [
    {"name": "tap for a 180", "axis": "spin", "charge": 0.12, "after": "relax", "expect": (180, True)},
    {"name": "wind up, open: 360", "axis": "spin", "charge": 0.3, "after": "open", "expect": (360, True)},
    {"name": "wind up, tuck: 540", "axis": "spin", "charge": 0.3, "after": "tuck", "expect": (540, True)},
    {"name": "backroll, hold", "axis": "flip", "charge": 0.3, "after": "tuck", "expect": (-360, True)},
    {"name": "backroll, let go", "axis": "flip", "charge": 0.3, "after": "relax", "expect": (0, False)},
]

# Crashes off a popped 3 m jump, followed through the ragdoll. `fall` is which way the chest should face 0.3 s in:
# 'up' (thrown on their back), 'down' (thrown on their face) or None.
CRASHES = [
    {"name": "heel edge catch", "trick": {"axis": "spin", "charge": 0.24, "after": "open", "dir": 1}, "reason": "heel edge", "fall": "up"},
    {"name": "toe edge catch", "trick": {"axis": "spin", "charge": 0.24, "after": "open", "dir": -1}, "reason": "toe edge", "fall": "down"},
    {"name": "short backroll", "trick": {"axis": "flip", "charge": 0.3, "after": "relax"}, "reason": "Under-rotated the backroll", "fall": None},
]
CRASH_TARGETS = [("slide", "slide m", 1.5, 6.0), ("stopT", "stops in s", 0.3, 1.2), ("deepHead", "head deepest m", 0.0, 0.6),
                 ("headEnd", "head at 2.3 s m", -0.05, 0.6)]

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
  const dt = 1/120, traj = [], bail0 = bail;
  let failReason = null, rot = 0, crash = null;
  bail = (...a) => { failReason = a[0]; bail0(...a); };
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
    } else {
      R.steerIn = 0; R.flipIn = 0;
      const tr = cfg.trick;
      if (tr && R.state === 'air') {
        const inp = (R.airT < tr.charge ? 1 : tr.after === 'tuck' ? 1 : tr.after === 'open' ? -1 : 0) * (tr.dir || 1);
        if (tr.axis === 'spin') R.steerIn = inp; else R.flipIn = -inp;   // down arrow: backroll
      }
    }
    const was = R.state;
    boatZ += BOAT_SPEED*dt; simTime += dt; stepRider(dt); updateRiderVisual(dt);   // the pose feeds the ragdoll
    if (phase === 'edge' || phase === 'go') {
      maxT = Math.max(maxT, R.tension/(RIDER_M*G));
      maxSpeed = Math.max(maxSpeed, Math.hypot(R.vel.x, R.vel.z));
      if (was === 'riding' && R.state === 'air') takeoff = {x: R.pos.x, y: R.pos.y, vy: R.vel.y, lip: wakeH(-crestX(d), d)};
      if (R.state === 'air') { traj.push([R.pos.x, R.pos.y, R.airT]); rot = cfg.trick && cfg.trick.axis === 'flip' ? R.flip : R.spin; }
      if (takeoff && R.state !== 'air') { landed = R.pos.x; result = R.state === 'bail' ? 'bail' : 'landed'; break; }
    }
    t += dt;
  }
  if (cfg.follow && result === 'bail') {
    // follow the ragdoll: slide, when it stops, how deep the head goes, which way the chest faces, whether it floats
    const g = RAG, I = g.I, start = R.pos.clone(), head = () => g.p[I.head];
    const chestUp = () => g.p[I.cf].clone().sub(g.p[I.shF].clone().add(g.p[I.shB]).multiplyScalar(0.5)).normalize().y;
    let stopT = null, deepHead = 0, chest = null;
    for (let bt = 0; bt < 2.3; bt += dt) {
      boatZ += BOAT_SPEED*dt; simTime += dt; stepRider(dt); updateRiderVisual(dt);
      const h = head(); deepHead = Math.max(deepHead, waterAt(h.x, h.z, boatZ, simTime) - h.y);
      if (stopT === null && bt > 0.05 && R.vel.length() < 1) stopT = bt;
      if (chest === null && bt >= 0.3) chest = chestUp();
    }
    const h = head();
    crash = {slide: Math.hypot(R.pos.x - start.x, R.pos.z - start.z), stopT: stopT === null ? 9 : stopT, deepHead,
             headEnd: h.y - waterAt(h.x, h.z, boatZ, simTime), chest};
  }
  bail = bail0;
  const d = boatZ - STERN_OFF - R.pos.z;
  const wake = [];
  for (let u = -7; u <= 7.001; u += 0.05) wake.push([u, wakeH(u, d)]);
  const peak = traj.reduce((m, p) => Math.max(m, p[1]), -9);
  return {cfg, result, traj, wake, takeoff, landed, farCrest: crestX(d), cruiseT, maxT, rot, failReason, crash,
          landingSpeed: R.lastLanding ? R.lastLanding.vn : null,
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
            # answer every three.js module request (the core, the glTF loader and what it imports) from the local package
            root = pathlib.Path(three_path)

            def local_three(route):
                f = root / route.request.url[len(THREE_CDN):].split("?")[0]
                if f.is_file():
                    route.fulfill(body=f.read_bytes(), content_type="text/javascript")
                else:
                    route.fulfill(status=404, body="")
            page.route(THREE_CDN + "**", local_three)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_function("typeof stepRider === 'function'")
        page.click("#go")
        for cfg in RUNS:
            results.append(page.evaluate(RUN_JS, cfg))
        tricks = [page.evaluate(RUN_JS, {"cut": 6, "mode": "pop", "trick": tr}) for tr in TRICKS]
        crashes = [page.evaluate(RUN_JS, {"cut": 3, "mode": "pop", "trick": c["trick"], "follow": True}) for c in CRASHES]
        browser.close()
    server.shutdown()
    if errors:
        raise SystemExit("page errors:\n" + "\n".join(errors))
    return results, tricks, crashes


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


def report_tricks(tricks):
    print(f"\n{'trick (popped 6 m)':<22}{'turned':>8}{'lands as':>10}{'landing m/s':>13}  result")
    ok_all = True
    for r in tricks:
        tr = r["cfg"]["trick"]
        per = 180 if tr["axis"] == "spin" else 360
        lands_as = round(r["rot"] / per) * per
        rode = r["result"] == "landed"
        want_rot, want_ride = tr["expect"]
        ok = rode == want_ride and (lands_as == want_rot or not want_ride)
        ok_all &= ok
        speed = f"{r['landingSpeed']:.1f}" if r["landingSpeed"] is not None else "-"
        outcome = "rode away" if rode else (r["failReason"] or r["result"])
        print(f"{tr['name']:<22}{r['rot']:>7.0f}°{lands_as:>9}°{speed:>13}  {'PASS' if ok else 'MISS'}  {outcome}")
    return ok_all


def report_crashes(crashes):
    print(f"\n{'crash (popped 3 m)':<18}{'slide m':>9}{'stops s':>9}{'head deepest m':>16}{'head at end m':>15}{'chest 0.3 s':>13}  result")
    ok_all = True
    for spec, r in zip(CRASHES, crashes):
        c = r["crash"]
        if c is None:
            print(f"{spec['name']:<18}  MISS  no crash ({r['result']})")
            ok_all = False
            continue
        ok = spec["reason"] in (r["failReason"] or "")
        ok &= all(lo <= c[key] <= hi for key, _, lo, hi in CRASH_TARGETS)
        if spec["fall"] == "up":
            ok &= c["chest"] > 0.3
        elif spec["fall"] == "down":
            ok &= c["chest"] < -0.3
        ok_all &= ok
        print(f"{spec['name']:<18}{c['slide']:>9.2f}{c['stopT']:>9.2f}{c['deepHead']:>16.2f}{c['headEnd']:>15.2f}{c['chest']:>13.2f}"
              f"  {'PASS' if ok else 'MISS'}  {r['failReason']}")
    print("targets: " + ", ".join(f"{label} {lo}-{hi}" for _, label, lo, hi in CRASH_TARGETS)
          + "; chest faces up (>0.3) after a heel catch, down (<-0.3) after a toe catch")
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
    ap.add_argument("--three", help=f"an unpacked three.js {THREE_VERSION} package (with build/ and examples/) to use instead of the CDN")
    ap.add_argument("--out", default=str(ROOT / "tools" / "out" / "jump_bench.png"))
    args = ap.parse_args()
    res, tricks, crashes = run_bench(args.three)
    passed = report(res)
    passed &= report_tricks(tricks)
    passed &= report_crashes(crashes)
    plot(res, pathlib.Path(args.out))
    raise SystemExit(0 if passed else 1)
