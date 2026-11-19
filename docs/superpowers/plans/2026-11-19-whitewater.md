# Whitewater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** White water on the wake: breaking crests that trail lace into the V, and a long churned strip down the middle, plus spray off the crests near the boat.

**Architecture:** The wake is steady in the boat's frame, so the water shader works out per pixel where foam sits and how old it is (from where that water crossed the crest), then breaks it up with noise in lake coordinates, tints the aerated water and lights the foam. Crest spray is a few more `spray.emitRate` emitters in `updateEffects`. Checks are probe functions in `tools/probe.js` that return a list of what's wrong, run in the live page through the browser pane.

**Tech Stack:** three.js r186 (WebGL 2), one `index.html`, `tools/probe.js` (ES module run in the page).

**Spec:** `docs/superpowers/specs/2026-11-19-whitewater-design.md`

## Global Constraints

- Still one HTML file, no build step, opens from disk; no new downloads.
- Physics untouched: `wakeH`, `WAKE_GLSL`'s height and the jump bench don't change.
- No `sin()` of a raw world position on the GPU; noise uses the sin-free `hash`.
- No foam mask multiplied by zero where a smoothstep's edges can cross: branch instead (the NaN trap).
- High quality frame time (`P.render(60)`) within about 10% of the Task 1 baseline. Changing quality compiles no new shader.
- Version goes to v0.9.0 in the `.ver` div and README's "Run it" section.

## Review Focus

1. Ahead of the transom (`d <= 0`) and right at it: no white patches or NaN (Task 2 check `foamCover` region `ahead`).
2. Where the near mesh meets the far plane: foam doesn't stop in a hard line (Task 2: tower-camera screenshot looking down the course).
3. Distance: no shimmer or sparkle from the lace far off; it fades into the haze (Task 2: long-lens screenshot).
4. The ramp face the rider rides up stays readable: mostly dark water up to the lip (Task 2 region `face20`).
5. Low quality: still shows the foam layers, with no cellular pattern (Task 2: `setQuality(0)` screenshot, `checkQuality()`).

---

### Task 1: Probe for foam coverage, and baselines

**Files:**
- Modify: `tools/probe.js` (new `foamCover()`, `checkFoam()`)

**Interfaces:**
- Produces: `foamCover(regions?) -> {[name]: percent}`: for each region `{name, u:[u0,u1], d:[d0,d1]}` (boat frame, `d` behind the transom, `u` signed; a region with `crest:true` takes `u` as `s = |u| − crestX(d)` instead, both sides), points the camera straight down from 14 m over the region's centre, hides the board's foam, spray and rider, renders, and returns the share of a 6×6 grid of points per metre in the region whose pixel is foam (max channel over 170). Restores the game camera after (`cam.snap = true; step(0.05)`), like `lodPop`.
- Produces: `checkFoam() -> string[]`: runs `foamCover()` on the regions below and lists every one outside its range.

| Region | u (or s) | d | Want (% foam) |
|---|---|---|---|
| `ahead` | 3 to 8 | −12 to −1 | 0 |
| `mid5` | −0.8 to 0.8 | 3 to 7 | ≥ 60 |
| `mid50` | −0.8 to 0.8 | 45 to 55 | 15–60 |
| `mid100` | −0.8 to 0.8 | 95 to 105 | ≥ 3 |
| `mid150` | −0.8 to 0.8 | 145 to 155 | < 3 |
| `crest5` | s −0.4 to 0.2 | 4 to 7 | ≥ 50 |
| `crest20` | s −0.4 to 0.2 | 18 to 23 | 15–60 |
| `crest40` | s −0.4 to 0.2 | 38 to 43 | ≥ 5 |
| `crest80` | s −0.4 to 0.2 | 78 to 83 | < 5 |
| `face20` | s 0.5 to 1.5 | 18 to 23 | < 10 |
| `lace10` | s −3 to −1 | 8 to 12 | 10–50 |
| `lace60` | s −3 to −1 | 58 to 62 | < 10 |
| `flats` | s 4 to 6 | 18 to 23 | < 2 |

- [ ] **Step 1:** Write `foamCover` and `checkFoam`. While the camera is placed, also move the near water grid over the region (`waterNear.position.z`, snapped to `WATER_SP`) and update `uNearRect`, as `tick()` does.
- [ ] **Step 2:** Run on the current build: `const P = await import('/tools/probe.js?'+Date.now()); P.checkFoam()`. Expected: fails on the crest, mid and lace regions (today's foam has gone by 20 m), passes `ahead`, `face20` and `flats`. Record the numbers.
- [ ] **Step 3:** Record the baseline `P.render(60)` on high, and screenshots from the follow, long-lens and tower cameras plus `foamCover`'s camera over `crest5` and over the rider, into `tools/out/whitewater-before-*.jpg`.
- [ ] **Step 4:** Commit: `git add tools/probe.js tools/out/whitewater-before-* && git commit -m "Foam coverage probe and before shots"`

### Task 2: Whitewater in the water shader

**Files:**
- Modify: `index.html` (water material, around lines 776–905: vertex foam block, fragment foam block; `NOISE_GLSL` gains `lace()`)

**Interfaces:**
- Consumes: `WakeK wakeK(float d)` (`xc`, `ramp` and the rest), `hash`, `vnoise`, `uDetail` (0 on low), `uBoat`, `uTime`.
- Produces (GLSL, in the water fragment shader): `float crestStrength(float d)` (`C(d)` from the spec); `vec4 foamMasks(float u, float d, WakeK k)` returning `(cap, lace, mid, aer)`, all in 0–1, with `aer` the smooth sum used for the turquoise tint; `float lace(vec2 p)` in `NOISE_GLSL`, a cellular pattern (1 on cell edges, 0 in the middle; 3×3 cells, feature points from `hash`, drifting slowly with `uTime`).

- [ ] **Step 1:** Remove `vFoam` from the vertex and fragment stages. In the fragment stage, compute `WakeK` once per pixel and share it between `wakeSlope` and `foamMasks` (change `wakeSlope` to take it). Skip all foam work when `d <= 0` or the pixel is more than `2·W + 4` m outside the crest, by branching.
- [ ] **Step 2:** Implement the masks from the spec's figures: cap across `s` from about −1 to +0.3 (+0.6 near the boat); lace for `s < 0` as `C(d0)·exp(−a/L)` with `a = −s/0.155`, `d0 = d − a`, zero where `d0 <= 0`; middle with half-width `1.2 + 0.035·d` and strength `0.35 + 0.65·e^(−d/18)` fading out 60–110 m.
- [ ] **Step 3:** Texture: noise thresholds fall as strength rises (strong is solid, weak is streaks). Cap and lace use `lace()` on high and medium, `vnoise` on low; middle uses noise stretched along the track. Noise is in lake coordinates (`vWorld.xz`) with a slow drift.
- [ ] **Step 4:** Shading: the aeration tint toward pale turquoise under and around foam; foam lit by the sun through a lumpy normal from the foam value's screen-space derivatives (`dFdx`, `dFdy`), plus sky; thin foam lets the water through; foam covers reflection and glitter.
- [ ] **Step 5:** Run `P.checkFoam()`. Expected: `[]`. Tune the curves until it is.
- [ ] **Step 6:** Run `P.render(60)` on high. Expected: within 10% of the Task 1 baseline. Run `P.checkQuality()`. Expected: `bad` empty.
- [ ] **Step 7:** Screenshots from the three cameras, straight down over `crest5` and the rider, and on low. Compare with the reference photos and the Review Focus list; tune by eye.
- [ ] **Step 8:** Commit: `git commit -am "Whitewater on the wake: breaking crests, lace inside the V, a long churned middle"`

### Task 3: Spray off the breaking crests

**Files:**
- Modify: `index.html` (`updateEffects`, after the prop-wash emitters)

**Interfaces:**
- Consumes: `spray.emitRate(acc, key, ratePerSec, dt, fn)`, `spray.emit(x,y,z, vx,vy,vz, life, size, kind)`, `crestX(d)`, `wakeH`, `STERN_OFF`, `boatZ`, `SPRAY_DROP`, `SPRAY_MIST`. A JS `crestStrength(d)` matching the GLSL one.
- Produces: emitter keys `crestDrop`, `crestMist` in `sprayAcc`.

- [ ] **Step 1:** Add drops (about 220/s over both sides) and mist (about 16/s), at a random `d` from 1 to 12 m weighted by `crestStrength(d)`, a random side, on the crest (`x = ±crestX(d)`, `y = wakeH` there), thrown outward about 1.5 m/s and up 0.5–2 m/s, `vz` about +0.25 m/s. Scaled by `spray.rate` like the rest (inside `emitRate`).
- [ ] **Step 2:** Run `P.checkSpray()`. Expected: `[]`. Run `P.render(60)`. Expected: still within 10% of the baseline.
- [ ] **Step 3:** Tower and follow screenshots: spray visible over the near crests, not a fog. Tune.
- [ ] **Step 4:** Commit: `git commit -am "Spray off the breaking crests near the boat"`

### Task 4: README, version, after shots

**Files:**
- Modify: `index.html` (`.ver` → v0.9.0), `README.md` (Water and Spray bullets, version in "Run it")

- [ ] **Step 1:** Update the README's Water bullet (foam on the crests, lace from the crests' age, the long middle, aeration, foam lighting) and Spray bullet (crest spray). Version to v0.9.0 in both places.
- [ ] **Step 2:** Save after shots matching Task 1's into `tools/out/whitewater-after-*.jpg`. Run `P.checkFoam()`, `P.checkSpray()`, `P.checkQuality()` once more. Expected: all empty.
- [ ] **Step 3:** Commit: `git add -A tools/out README.md index.html && git commit -m "v0.9.0: whitewater on the wake"`
