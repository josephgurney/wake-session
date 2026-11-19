# Scenery and Spray Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cone trees, flat banks, flat-shaded hills and round-dot spray with a believable wooded lakeshore and water-like spray, at no frame-rate cost.

**Architecture:** Everything stays in `index.html`'s game script (`<script type="text/plain" id="game">`), and everything is generated in code at boot. Spray moves to instanced quads positioned on the GPU from their emit state. Trees become card-foliage species, instanced in chunks along the course so that off-screen chunks are culled.

**Tech Stack:** three.js r186 (WebGL 2, via the import map), canvas-painted textures, GLSL through `ShaderMaterial` and `onBeforeCompile`.

**Spec:** `docs/superpowers/specs/2026-11-19-scenery-and-spray-design.md`

## Global Constraints

- One HTML file, no build step, opens from disk; no new asset downloads.
- No changes to physics, tricks, scoring or controls: the bench probe (below) must give identical numbers before and after.
- Keep the lake layout: `SHORE_X=76`, `LAND_P=900`, the three-period build and the forward snap in `frame()`.
- Keep the sun (`SUN`), the summer-afternoon grade and the Lobster colours.
- The low setting costs no more than it does today; this Mac must still hold "high" on auto.
- `spray.emit(x,y,z,vx,vy,vz,life,size)` keeps its signature, because the ragdoll, `sprayBurst` and the bench path call it.
- Version goes to v0.7.0 (the `.ver` div and README's "Run it" section).

## Review Focus

1. **Pause (Esc)**: spray and foam must freeze, not jump or vanish, because their clock only advances in `updateEffects`.
2. **Forward snap every 900 m**: no tree, rock, reed or jetty may pop at the seam, so every scenery item is placed with `z0 + m*LAND_P` for m = -1, 0, 1.
3. **Falls and the reset fade**: big splashes near the camera must not fill the screen with mist. Cap the mist's on-screen size.
4. **Quality changes mid-ride (P, or auto)**: changing tier must not leak GPU buffers or leave trees at the wrong density; `setTreeDensity` must still work.
5. **Phone-sized windows, touch, low setting**: draw calls and particle overdraw no higher than today.

The probes in Task 1 cover 1, 4 and 5. Task 3 and Task 5 each step through a full period to cover 2. Task 2 covers 3 with a scripted bail.

---

### Task 1: Probes and baseline

**Files:**
- Modify: `index.html`: add `performance.mark('tyc:game')` as the first statement after `'use strict';` in the game script, and `performance.mark('tyc:built')` just before `addEventListener('resize',resize)`.

**Interfaces:**
- Produces: the three in-page probes below, run through the browser's JS tool on `http://localhost:8791/index.html?nocache=N` after "Take the handle":
  - `BUILD`: `performance.measure('b','tyc:game','tyc:built').duration`
  - `RENDER`: render 60 frames in a tight loop (`renderReflection(); renderPost();`), then `renderer.getContext().readPixels` 1 px to sync. Return the ms per frame, plus `renderer.info.render.calls` and `.triangles` for one frame.
  - `BENCH`: the `RUN_JS` function from `tools/jump_bench.py`, run for its five `RUNS` configs. Record `airT`, `aboveLip`, `speedRatio`, `maxT` and `result` for each. Run this one last, because it freezes the live loop.

- [ ] Add the two marks; reload; record BUILD, RENDER on high (press P until the HUD reads `quality: high`), RENDER on low, and BENCH, in the PR notes as "before".
- [ ] Commit: `Timing marks around the world build`.

### Task 2: GPU spray and lingering foam

**Files:**
- Modify: `index.html`, in `// ---------- particles ----------` (replace `class Spray` and `const spray`), `foamTex`/`FOAM_N`/`updateFoam`, `sprayBurst`, `updateEffects`, and `resize()` (drop `spray.mat.uniforms.uScale`).

**Interfaces:**
- Produces: `const SPRAY_DROP=0, SPRAY_SHEET=1, SPRAY_MIST=2;` and `class Spray` with `constructor(capacity)`, `emit(x,y,z,vx,vy,vz,life,size,kind=SPRAY_DROP)`, `update(dt)`, `.rate` (0..1, set by `setQuality`), and `.clock` (seconds, advanced only by `update`). `const spray=new Spray(16384)`.

Design pins:
- One `InstancedMesh`-style draw: an `InstancedBufferGeometry` quad with per-instance attributes `aP0` (vec3), `aV0` (vec3), `aT` (vec4: emit clock, life, size, kind). `DynamicDrawUsage`; each frame upload only the ring-buffer ranges written since the last frame (`addUpdateRange`).
- Vertex shader, with τ = clock − t0:
  - horizontal: `p0 + v0*(1-exp(-k*τ))/k`;
  - vertical: `y0 + vy*τ - 0.5*g*τ²`.
  - k and g per kind:

    | kind | k | g |
    |---|---|---|
    | drop | 0.9 | 9.81 |
    | sheet | 1.6 | 6.0 |
    | mist | 2.5 | −0.4 (it rises) |

  - Dead when τ > life. Also dead when a drop or sheet is below `wake()+ambient()` at its xz: reuse `WAKE_GLSL` with a `uBoat` uniform.
- Droplets are stretched along their projected velocity (length += |v|·0.035 m). Every quad has at least 1.5 px on screen, and alpha is scaled by (true size / drawn size)², so tiny drops don't shimmer.
- Sheets grow ×1.8 and mist ×2.5 over their life. Mist alpha ≤ 0.10, and its drawn size is capped at 18% of the screen height (Review Focus 3).
- Light, in HDR: base `vec3(0.62,0.70,0.78)`, plus sun colour × (0.35 + 2.2·pow(max(dot(-V,uSun),0),6)) for the back-light glow, plus fog. Sheets and mist get noise break-up in the fragment shader (`NOISE_GLSL`).
- Emitters (rates per second, times `spray.rate`):
  - **Board in a cut**: 120 + 900·edge drops and 20 + 160·edge sheets in a fan off the down-side edge, plus mist at 6 + 30·edge, all times speed/boat speed.
  - **Prop wash**: 300 drops, 40 sheets and 18 mist per second, replacing today's 8 per frame.
  - **`sprayBurst` (landing crown)**: n·2.2 drops, n·0.5 sheets in a ring that throws outwards and up, and n·0.15 mist.
  - The ragdoll calls stay as they are (drops).
- **Foam**:
  - `FOAM_N=1200` decals with a life of 10 s;
  - each decal stretched 1 × 3 along travel;
  - the texture is streaky lacing (curved strokes) rather than a speckled blob;
  - alpha follows `pow(1-k,1.3)*0.38`.

- [ ] Implement; reload; ride, cut hard both ways, land a jump, bail once (R to reset); screenshot each from the follow and long-lens cameras.
- [ ] Check Review Focus 1: press Esc mid-spray and wait 2 s; the spray must stay put. Close Settings, and it carries on.
- [ ] Check Review Focus 3: bail with the camera close; no frame is more than ~30% mist.
- [ ] RENDER on high and low within +1.0 ms of baseline; BENCH identical to baseline.
- [ ] Commit: `Spray on the GPU: droplets, sheets and mist, lit from behind; foam that lingers`.

### Task 3: Trees and undergrowth

**Files:**
- Modify: `index.html`, in `// ---------- shoreline, trees and far hills ----------`: replace `coniferGeometry`, `broadleafGeometry` and the tree `make(...)` block; keep `trees` and `setTreeDensity(f)`.

**Interfaces:**
- Consumes: `landH`, `mulberry32`, `LAND_P`, `SHORE_X`, `shore` (Group), `SUN`.
- Produces: `paintFoliageAtlas()` returns a `CanvasTexture`, 1024², 2×2 cells: spruce spray, pine tuft, broadleaf cluster, birch/willow leaves. `treeGeometry(species, lod, seed)` returns a `BufferGeometry` with `position`, `normal`, `uv`, `color` (baked AO) and `aSway` (0 at the trunk base, rising to 1 at the tips). `const TREE_CHUNK=300;` `function updateTreeLod()` is called once per frame from `frame()`.

Design pins:
- **Species**:
  - spruce: conical whorls of drooping branch cards, 9–14 m;
  - pine: bare trunk with a high clumped crown, 12–18 m;
  - broadleaf: 3–5 limbs, 6–9 clumps of crossed cards, 9–14 m;
  - birch: white trunk with dark marks, slender, 8–12 m;
  - willow: drooping curtain cards, 6–9 m, only within 14 m of the waterline;
  - bush: 2–4 low clumps, 1–2.5 m, along the forest edge.
- **Foliage cards**:
  - normals point outwards from the crown centre (soft, rounded lighting);
  - `alphaTest:0.4` with `alphaToCoverage:true` (the scene target is 4× MSAA);
  - `side:DoubleSide`;
  - `MeshStandardMaterial({vertexColors:true, map:atlas, roughness:0.9})`, with `onBeforeCompile` adding:
    - wind sway: offset = `aSway²·0.12 m·sin(time·1.3 + worldPos·0.2)`;
    - back-light: sun colour × 0.6 × pow(max(dot(-V,SUN),0),4).
- **LOD**: the far version has about 30% of the cards, each larger. A chunk uses it when its nearest edge is more than 450 m from the camera along z.
- **Placement**: noise `clump(x,z)` from two `Math.sin` octaves, as in `landH`. Keep a tree when `rnd() < clump`. Trees taller further from the water. Species by distance from `SHORE_X`. Instance colour jitter of ±12%. About 1,600 trees and 500 bushes per period. Order within each chunk is shuffled, so `setTreeDensity` thins at random.
- **Chunks**: one `InstancedMesh` per species per 300 m chunk per side, over the three periods. `frustumCulled=true`, with each chunk's bounding sphere computed from its instances.

- [ ] Implement; reload; screenshot the shore from all three cameras.
- [ ] Review Focus 2: set `boatZ` forward by 850, 900 and 950 m (riding), and screenshot the long lens at each; no visible pop at 900.
- [ ] RENDER on high: draw calls ≤ baseline + 40, ms within +1.5 ms of baseline. On low: ms ≤ baseline. BUILD ≤ baseline + 250 ms.
- [ ] Commit: `Real trees: spruce, pine, broadleaf, birch and willow, with undergrowth, culled in chunks`.

### Task 4: Ground, waterline, jetties and hills

**Files:**
- Modify: `index.html`: `landH`, `landColor`, `landMat`, `makeRidge` and the `hills` group, in the same section.

**Interfaces:**
- Produces: `shoreType(z)` returns `{beach, rock, reed}` weights summing to 1, periodic in `LAND_P`. `buildProps()` adds rocks, reeds, jetties, moored boats and a boathouse to `shore`, and returns the props group. Its `.visible` follows the quality setting.

Design pins:
- **Banks**:
  - `landH` reads `shoreType`: beaches shelve gently, rocky stretches are steep, reed stretches stay low and flat;
  - `landMat` gets an `onBeforeCompile` driven by world position:
    - grass in two tones from noise, with dirt patches;
    - rock where `normal.y < 0.82`;
    - sand by height;
    - a wet band from y −0.3 to 0.25: colour × 0.55, roughness 0.35.
- **Props**, all placed with `z0 + m*LAND_P`:
  - rocks: deformed icosahedrons in instanced grey-browns along rocky stretches;
  - reeds: instanced card clumps using a new 5th atlas cell (the atlas grows to 3×2) along reed stretches;
  - 3 jetties per period, alternating sides: timber deck on posts, with a small moored boat (lathe hull, white or navy) at two of them;
  - 1 boathouse per period: dark timber, pitched roof, open to the water.
- **Hills**:
  - `makeRidge` builds 5 rows up the slope, smooth-shaded, with vertex colour going from forest green at the base to haze at the crest;
  - a fragment noise for tree texture;
  - aerial perspective: mix towards `FOG_COLOR` × 1.1, by 0.55 for the 1,500 m ridge and 0.75 for the 2,100 m ridge;
  - a third ridge at 3,000 m, mixed by 0.88.

- [ ] Implement; reload; screenshot all three cameras; step through a full period (as in Task 3) with the long lens.
- [ ] RENDER and BUILD against the Task 3 limits (cumulative); BENCH identical.
- [ ] Commit: `Banks that vary: beaches, rocks and reeds, jetties and a boathouse; hills in the haze`.

### Task 5: Quality settings and the speed check

**Files:**
- Modify: `index.html`: `QUALITY`, `setQuality`, and `frame()` (call `updateTreeLod()`).

**Interfaces:**
- Consumes: `spray.rate`, `setTreeDensity`, the props group from `buildProps()`, `updateTreeLod`.

Design pins:
- Add `spray` (low 0.3, medium 0.6, high 1) and `props` (low false, others true) to each `QUALITY` entry. `trees` stays 0.5/0.75/1. On low, `updateTreeLod` treats every chunk beyond 200 m as far.

- [ ] Implement; on high, medium and low, run RENDER and press P through every tier mid-ride. The tier label and the tree density must match each tier, with no console errors (Review Focus 4).
- [ ] Set a phone-sized viewport (Mobile preset) on low: RENDER ms ≤ baseline-low, and draw calls ≤ baseline-low (Review Focus 5).
- [ ] Leave auto on, on this Mac, for 30 s riding: the HUD still reads `high (auto)`.
- [ ] Commit: `Quality settings cover spray and props`.

### Task 6: Version, README and PR

**Files:**
- Modify: `index.html` `.ver` → `v0.7.0`; `README.md`: the "Run it" version, and the **Shoreline**, **Performance** and a new **Spray** bullet in "How it works".

- [ ] Update the README bullets to describe what was built (same style: plain, specific, numbers where they matter).
- [ ] Final screenshots from all three cameras, saved for the PR to `tools/out/` (gitignored, attached instead).
- [ ] Commit: `v0.7.0: scenery and spray`, push `scenery-spray`, and open the PR with before/after numbers and screenshots.
