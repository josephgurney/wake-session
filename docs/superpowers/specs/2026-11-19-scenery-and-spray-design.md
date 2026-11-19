# Scenery and spray: the first realism pass

*2026-11-19 · branch `scenery-spray`*

## Why

Joseph watched GTA 6 footage and wants Thursday Yacht Club to look more real. We agreed not to change engine: stay on three.js (WebGL), in the browser. In the current picture, the two things that most give away "game" are the shoreline scenery and the spray, so this pass does those. Water colour, ambient occlusion and lens effects come later.

## What's there now

- **Trees** (`coniferGeometry`, `broadleafGeometry`): stacked 8-sided cones and a squashed icosahedron, vertex-coloured. About 6,300 instances in two `InstancedMesh`es, all drawn every frame (`frustumCulled=false`).
- **Banks** (`landGeometry`): an 8 m vertex-coloured grid, with a flat sand strip at the waterline and grass above it.
- **Far hills** (`makeRidge`): two flat-shaded ring meshes in dark green.
- **Spray** (`Spray`): 3,000 CPU-updated round soft points. They're emitted by the board while riding, by the prop wash, by landings and bails, and by the ragdoll.
- **Board foam** (`dropFoam`): 420 blob decals that fade in 3.2 s.

## Goals

- From the follow and long-lens cameras, the shore reads as a real wooded lake: a dense, varied treeline, a believable waterline, and hills that fade into haze.
- Spray reads as water: sheets and streaked droplets off the board's edge in a cut, mist hanging behind the board and the boat, proper splashes on landings and falls, and a foam trail that lingers.
- Each machine stays on the quality setting it gets today: this Mac holds "high" on auto now and still should afterwards.
- Still one HTML file with no build step that opens from disk, and no new downloads.

## Non-goals (later passes)

Water colour, ambient occlusion, depth of field, motion blur, glare, WebGPU and rider textures. No changes to physics, tricks, scoring or controls.

## Anti-goals

- **A different game.** Keep the bright summer afternoon, the lake layout (banks 76 m out, endless straight course), the sun direction and the Lobster colours.
- **Longer loading.** Building the scenery stays a small part of the existing "building the world" stage.
- **Slower phones.** The low setting costs no more than it does today.

## Approaches

**Trees and scenery**
1. **Built in code (picked).** Trunks and branches as geometry. Foliage as alpha-tested cards, with needle and leaf textures painted on canvas at boot. This is how the boat and board are already built: nothing to download, and it works offline.
2. **Ready-made photoscanned models** (CC0, such as Poly Haven). These look best up close, but each species is 5–30 MB, which means a long load on phones. They'd also break opening from disk as one file. The trees sit 90 m or more from the camera, so most of that detail would be wasted.
3. **Flat billboards only.** Cheapest, but they look flat and pop as the camera swings round. Used only as the furthest level of detail inside option 1, if needed.

**Spray**
1. **Restyle the CPU particles.** Stuck at around 3,000 particles.
2. **Particles positioned on the GPU (picked).** Each particle stores where, when and how fast it was emitted, and the vertex shader works out its arc. That makes 15–20k particles cheap, and only new particles are uploaded each frame. The existing `spray.emit(...)` calls keep working.

## Design

### Scenery

- **Species**: spruce/pine, a broadleaf (oak-like), birch, and willow at the water's edge. Each species is generated once at boot in two or three variants. Foliage is lit with a little back-light glow (leaves and needles brighten with the sun behind them) and darkened inside the canopy and low down, as a baked stand-in for ambient occlusion. A gentle wind sway runs in the vertex shader.
- **Placement**: a noise field makes clumps and clearings instead of an even scatter. Trees get taller further back. Species change with distance from the water: willow and birch at the edge, conifers behind. Each instance gets some colour variation. Bushes and undergrowth run along the forest edge so trunks don't stand on bare grass.
- **Cost**: trees are split into chunks along the course so off-screen trees aren't drawn. Far trees use a cheaper variant with fewer cards. The quality settings still scale density.
- **Ground**: the banks get a shader that blends grass, dirt, sand and rock by height and slope, broken up with noise, with a dark wet band at the waterline.
- **Waterline**: varied stretches of reed beds, rocks, small beaches and grassy bank. A few jetties with boats tied up and a boathouse give it scale. All of it repeats with the existing 900 m period, so the forward snap stays invisible.
- **Hills**: smooth-shaded with a forest texture, layered, and fading into blue haze with distance instead of flat green.

### Spray

- **One GPU particle system** replaces `Spray`, with three kinds of particle:
  - **droplets**: small, streaked along their motion;
  - **sheets**: larger soft translucent shapes for the curtain off the edge;
  - **mist**: big, faint and slow, lingering and drifting up a little.
- **Light**: spray glows when the sun is behind it and is greyer on the shadow side. It stays in HDR, so bright spray catches the bloom.
- **Emitters**:
  - the board's edge in a cut: a fan of sheets and droplets, scaled by edge angle and speed;
  - a mist trail behind the board;
  - churn and mist from the boat's prop wash;
  - a crown splash on landings.
  - The ragdoll's existing splashes pick up the new look.
- **Foam trail**: the board's foam lasts about 10 s and lies in streaks and lacing rather than blobs, with more decals.

### Quality settings

| | Low | Medium | High |
|---|---|---|---|
| Spray particles | about today's count | about 60% of high | all |
| Trees | simplest variant, density as now | density as now, cheaper far trees | full |
| Undergrowth and props | off | on | on |

### Checks

- Before and after screenshots from all three cameras at the same spots.
- Frame time on high on this Mac, before and after, and on low in a phone-sized window.
- Time spent in the "building the world" loading stage, before and after.
- `tools/jump_bench.py` unchanged (no physics changes).

## Calls made (open to correction)

- Keep the current lake (wooded hills, pines and broadleaf trees, sandy patches) rather than recreating a particular real place.
- Everything is generated in code; no model downloads.
- Add a few jetties and a boathouse for scale.
- One PR from `scenery-spray`, with the version going to v0.7.0.

## Left to the builder

Exact tree shapes, card counts, chunk sizes, particle budgets per setting, and how the textures are painted.
