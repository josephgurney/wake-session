# Whitewater on the wake

*2026-11-19 · branch `whitewater` (off main, after the real wake shape)*

## Why

Joseph wants the wake to look like a real boat's. The three reference photos (two from overhead, one from the side of a wake boat) all show whitewater: a churned white strip down the middle behind the boat, and white water breaking along the top of each crest as the V spreads out, trailing lace behind it. Today's wake reads as clean, glassy ramps.

## What's there now

- The water shader's vertex stage works out three foam masks (`vFoam`): a band on the lip (fades as `e^(−d/14)`), a spill down the inside face (`e^(−d/20)`, ×0.42) and a prop-wash column about 1.5 m wide (`e^(−d/13)`). All three have gone by 15–20 m behind the transom, so at the rider (about 20 m back) the wake is almost bare.
- The fragment stage breaks the masks up with value noise in lake coordinates and mixes in a flat foam colour. There's no tint of aerated water, and the foam isn't lit as a surface of its own.
- Separately: the board's foam trail (instanced quads, 10 s) and GPU spray, including drops, sheets and mist from the prop wash.

## Goals

- **Crests:** broken white along each crest, heavy for the first 10 m or so, thinning but still there past the rider to about 40 m. The outside ramp face stays mostly clean, with a few streaks spilling down it near the boat.
- **Lace inside the V:** water that went through a breaking crest carries its foam inward as the V widens, fading over about two seconds. Densest near the boat.
- **The middle:** a wide churned strip, solid white close to the transom, breaking into streaks further back and running 80–100 m down the course.
- **Look:** foam fixed to the lake (it streams back past the boat, it doesn't ride along with it), lumpy in the sun, pale turquoise aerated water under and around thin foam, slowly changing.
- **Spray** thrown off the breaking crests near the boat.
- **Cost:** high quality within about 10% of today's frame time; low stays cheap.

## Non-goals

Any change to the physics (foam is only a look), a simulated foam map, changes to the board's own foam trail or spray, the loading screen's wake drawing.

## Anti-goals

- Foam that slides along with the boat, like a decal.
- Hard-edged blobs, visible tiling, or shimmer far off.
- A ramp face so white the lip is hard to read.
- White NaN triangles (the existing trap: masks are branched, never multiplied by zero, where a smoothstep's edges can cross).

## Approaches

1. **Foam worked out in the water shader, plus crest spray (picked).** The wake is steady in the boat's frame, so where foam sits, and even how old it is, can be worked out from the formula per pixel. No new passes. Physics untouched.
2. **A simulated foam map.** A texture that follows the boat; foam is added and fades each frame, so the rider's cuts and landings would merge with the wake's foam. Rejected: an extra pass every frame (felt on phones) for a wake that would look about the same.
3. **Foam as particles.** Quads laid along the crests. Rejected: thousands of overlapping quads, and they can't tint the water under them.

Joseph picked 1.

## Design

Boat frame as in `wakeH`: lateral offset `u`, distance behind the transom `d`, `s = |u| − xc(d)` (positive outside the crest). Water moves straight back past the boat, and the crest line moves out 0.155 m for every metre.

- **Crest strength `C(d)`:** how hard the crest is breaking. It ramps in over the first metre or two, then runs as about `0.3 + 0.7·e^(−d/12)`, fading out between 35 and 60 m.
- **Cap:** white across the crest, from about 0.3 m down the outside face (about 0.6 m near the boat) to about 1 m down the back face. The noise threshold falls as `C` rises, so a strong crest is solid white and a weak one breaks into streaks.
- **Lace:** inside the crest (`s < 0`), the water crossed the crest `a = −s/0.155` metres of boat travel ago, at `d0 = d − a`. Lace = `C(d0)·e^(−a/L)`, with `L` about 15–20 m (about two seconds at 21 mph), and only where `d0 > 0` (water inside the transom's width never crossed a crest). It's drawn as a cellular pattern, so it reads as a web of foam rather than blotches.
- **The middle:** half-width about `1.2 + 0.035·d`. Strength about `0.35 + 0.65·e^(−d/18)`, fading out between 60 and 110 m. Its noise is stretched along the track: solid near the transom, streaks further back.
- **Aeration:** the smooth sum of the masks, before any noise, tints the water toward a pale turquoise under and around the foam.
- **Lighting:** foam is a diffuse white, lit by the sun through a lumpy normal taken from the foam pattern's screen-space derivatives, plus the sky. Thin foam lets the water show through. Where foam covers, it replaces the reflection and the sun glitter.
- **Per pixel:** the masks move from the vertex to the fragment stage and share the wake terms (`wakeK`) the per-pixel normal already works out, so foam edges stay crisp whatever the mesh spacing. The far plane works them out too, so foam doesn't stop dead at the near mesh's edge.
- **Low quality:** one noise lookup per layer, no cellular pattern.
- **Crest spray:** drops and a little mist along both crests from about 1 to 12 m behind the transom, at a rate that follows `C(d)`, thrown outward at about 1.5 m/s and up at 0.5–2 m/s, scaled by the quality setting's spray rate like the rest.

## Left to the builder

The exact curves, widths and thresholds, the noise scales and the spray rates: tuned by eye against the photos from the follow, long-lens and tower cameras and from a probe shot straight down. The figures above are starting points.

## Checks

- The water shader compiles with no warnings, and there are no white patches ahead of the boat or at the transom.
- Frame time on high (`P.render(60)`) within about 10% of the baseline taken before the change.
- `P.checkQuality()` still passes (a quality change compiles no new shader).
- Before and after screenshots from the three cameras and from straight down.
- `P.checkSpray()` still passes.
