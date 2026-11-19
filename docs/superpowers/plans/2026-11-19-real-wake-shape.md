# Real Wake Shape Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the wake the measured shape, width and height of a real wake boat's, and retune the jumps so they still hit the real-world targets.

**Architecture:** The wake is one analytic height function, written twice: `wakeH` in JS for the physics and `WAKE_GLSL` for the shaders. Both get the new profile. The near water grid gets a fine band across the boat's track, and the water shader works out the wake's normal per pixel. Checks live in `tools/probe.js` as functions that return a list of what's wrong (empty when it all holds), run in the live page through the browser pane, like the scenery pass.

**Tech Stack:** three.js r186 (WebGL 2), one `index.html`, `tools/probe.js` (ES module run in the page), `tools/jump_bench.py` (its `RUN_JS` is what `probe.bench()` runs).

**Spec:** `docs/superpowers/specs/2026-11-19-real-wake-shape-design.md`

## Global Constraints

- Still one HTML file, no build step, opens from disk; no new downloads.
- `wakeH` (JS) and `wake()` (GLSL) give the same height everywhere (within 1 mm).
- Each quality setting runs about as fast as now: GPU time per frame on high within 15% of the baseline taken in Task 1.
- No `sin()` of raw world position on the GPU (precision after a long session): anything fixed to the lake uses a phase reduced on the CPU.
- Jump bench targets: popped airtime 0.9–1.3 s, height above lip 1.0–1.8 m, rider speed 1.15–1.35 × boat, cruising line load 0.2–0.4, hard-cut line load 1.0–1.5; popped jumps from the 6 m cut clear the far crest.
- Version v0.8.0 in the `.ver` div and README's "Run it" section.

## Review Focus

1. Riding across the trough with Space held: the ripples and prop-wash boil must not launch the rider before the far crest (Task 3 check `checkTrough`).
2. Ahead of the transom (`d <= 0`) and the transom itself: no step, NaN or spike in height or normal (Task 1 check).
3. The seam where the near grid meets the flat far plane: no crack or step in the wake, from the follow, long-lens and tower cameras (Task 2 check and screenshots).
4. The fine band's edge: no visible seam in shading where the vertex spacing changes (Task 2 screenshots).
5. A relaxed rider cutting out over the wake must still just bump over it, not take off (Task 3 bench: "3 m relaxed" stays "no jump" or a small hop under 0.3 s).

---

### Task 1: The new wake profile, CPU and GPU

**Files:**
- Modify: `index.html` (`WAKE_GLSL`, `wakeH`, `crestX`, around lines 524–556)
- Test: `tools/probe.js` (new `checkWake()`, `checkWakeGPU()`)

**Interfaces:**
- Produces: `wakeH(u, d) -> number` (metres, lake level 0), `crestX(d) -> number` (crest half-width, m), `wakeTrough(d) -> number` (depth of the middle, m, positive down), GLSL `vec2 wake(float u, float d)` returning `(height, crest)`, where `crest` is 1 at the crest falling to 0 about 0.4 m either side (used by the lip foam).
- Spec figures at `d = 16.5`: `crestX ≈ 3.65`; crest +0.34 m (±0.03); dip −0.29 m (±0.04) about 2 m outside the crest; lip slope 28–33°; back face at most 25°; ripple(s) inside the crest; middle flat at −0.24 m (±0.03); prop-wash boil within ±0.04 m of the trough level; trough to crest 0.55–0.65 m. Along the course: crest 0.15 m (±0.05) at `d = 0.5`; full height from 10 to 20 m; about 75% at 60 m and 55% at 200 m; trough −0.45 at `d < 3`, −0.1 (±0.04) at 40 m, ~0 by 70 m.

- [ ] **Step 1: Baseline.** Start the `wake-session` preview, `start()`, record `gpu()` on high and medium, `bench()`, and screenshots from the three cameras (`view(0..2)`), so later tasks compare against them.
- [ ] **Step 2: Write `checkWake()`** in `tools/probe.js`: samples `wakeH` and `crestX` and returns a failure string for each spec figure above that misses. It also checks smoothness: no NaN, `|wakeH(u, d)| < 0.01` for `d <= 0`, and no jump bigger than 3 cm between samples 2 cm apart, except across the crest itself.
- [ ] **Step 3: Run it against the current wake.** Expected: several failures (crest 0.62, no dip, width 2.8).
- [ ] **Step 4: Write `checkWakeGPU()`.** It renders `WAKE_GLSL`'s `wake(u, d).x` for about 2,000 `(u, d)` samples (`u` from −12 to 12, `d` from −5 to 300) into a float target and compares each with `wakeH`. It returns the samples that differ by more than 1 mm.
- [ ] **Step 5: Implement the profile** in `wakeH`, `crestX`, `wakeTrough` and `WAKE_GLSL`, line for line the same maths. The boil's lake-fixed phase comes in through a third argument that the CPU reduces (`wakeH(u, d, ph)`, `wake(u, d, ph)`, with `ph` = world z of the stern mod the boil period, `uWakePh` uniform on the GPU). Callers pass the current phase.
- [ ] **Step 6: Run `checkWake()` and `checkWakeGPU()`.** Expected: both `[]`.
- [ ] **Step 7: Commit** "Wake shape from measured wakes: dip, ramp to a 30° lip, gentler back face with ripples, one wide trough, 24 ft wide".

### Task 2: Drawing it: fine band, per-pixel normals, foam, far wake

**Files:**
- Modify: `index.html` (`gridGeometry`, `waterNear` and quality `sp` table, `waterMaterial` vertex and fragment shaders, the per-frame placement around line 3380)
- Test: `tools/probe.js` (new `checkWater()`)

**Interfaces:**
- Consumes: `wake(u, d, ph)` and `uWakePh` from Task 1.
- Produces: `gridGeometry(w, l, sp, fine)`, where `fine = {half: 12, sp}` gives the x spacing inside `|x| < half`. The quality table gets `fine` spacings: high 0.2, medium 0.3, low 0.45.

- [ ] **Step 1: Write `checkWater()`**: the near grid's x spacing inside ±12 m is the setting's `fine` spacing; the mesh's x centre is the boat's track (0); and `gpu()` on high is within 15% of the Task 1 baseline. Run it: fails on spacing.
- [ ] **Step 2: Fine band.** Non-uniform x columns (fine inside ±12 m, the setting's `sp` outside, the band edge on a coarse column), the mesh x fixed at 0 and z still following the camera, placed along the camera's view direction so the tower camera looking back gets the grid behind the boat.
- [ ] **Step 3: Per-pixel wake normals.** The vertex shader passes the ambient-only normal. The fragment shader adds the wake gradient from `wake()` by central differences, about 5 cm apart. The far plane gets the same per-pixel wake normal, so the V carries on as shading down the course.
- [ ] **Step 4: Edge fade.** The near grid's displacement fades to 0 over its last 15 m in z (normals keep the shape), so there's no step where it meets the flat far plane.
- [ ] **Step 5: Foam.** Lip foam from `wake().y` (washy near the boat, `exp(-d/14)` as now), spill on the new back face, and the prop wash band as now.
- [ ] **Step 6: Check.** `checkWater()` returns `[]`, and `checkWake()` and `checkWakeGPU()` still pass. Take screenshots from the three cameras on high and low: the lip is crisp, no seam at the band edge or the grid's far edge, ripples are visible.
- [ ] **Step 7: Commit** "Finer water across the wake, wake normals per pixel, and the V runs on down the course".

### Task 3: Physics, scoring and the retune

**Files:**
- Modify: `index.html` (`takeoff`, the wake-to-wake test in `scoreTrick`, tuning constants `EDGE_LD`, `ABSORB` and the pop values in `stepRider` as the bench needs), `tools/jump_bench.py` (the "clear the second wake" check applies to `cut == 6` pop runs only), `tools/probe.js` (`bench()` prints pass/fail against the same targets, plus new `checkTrough()`)

**Interfaces:**
- Consumes: `crestX(d)`, `wakeH(u, d, ph)` from Task 1.

- [ ] **Step 1: Make `bench()` report targets.** Extend `probe.bench()` to return `{runs, misses}`, where `misses` lists every target from the jump bench's TARGETS table and the clear check that fails (6 m pop only). Write `checkTrough()`: from the middle, holding Space, edge across to the far wake, and fail if the rider is airborne before reaching `crestX(d) − 0.5`. Run both on the new wake. Expected: some misses (wider wake).
- [ ] **Step 2: Scoring.** `R.takeoffWake` becomes "took off within 1 m of a crest" (`Math.abs(Math.abs(x) − crestX(d)) < 1`). The wake-to-wake test becomes `Math.abs(R.pos.x) > crestX(d)` on the far side. Update the bench's clear check to the 6 m cut.
- [ ] **Step 3: Retune** `EDGE_LD`, `ABSORB` and the pop arm values until `bench().misses` and `checkTrough()` are both `[]`, and "3 m relaxed" stays a bump (no jump, or air under 0.3 s). Keep the trick table landing as before: `tap for a 180` lands 180, and so on, as `jump_bench.py`'s TRICKS expects. Check with a popped 6 m `jump()` plus the trick runs from the live page.
- [ ] **Step 4: Commit** "Jumps retuned for the wider, real-sized wake; wake-to-wake and takeoff checks follow the crest".

### Task 4: Docs, version, final look

**Files:**
- Modify: `index.html` (`.ver` → v0.8.0; the "How it works"-style comments over `wakeH`), `README.md` (Water paragraph, the takeoff paragraph if the numbers changed, v0.8.0 in "Run it")

- [ ] **Step 1:** Update the README's water paragraph with the new shape (dip, 30° lip, gentler back face with ripples, one wide trough 0.24 m below lake level, 24 ft wide at 65 ft, fading slowly down the course), and the version in both places.
- [ ] **Step 2:** Final pass in the browser: all four checks `[]`, `bench().misses` `[]`, screenshots from the three cameras, and a ridden jump.
- [ ] **Step 3: Commit** "v0.8.0: real wake shape".
