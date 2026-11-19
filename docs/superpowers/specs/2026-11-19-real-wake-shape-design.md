# Real wake shape: ramps, trough and width from measured wakes

*2026-11-19 · branch `real-wake` (off `scenery-spray`)*

## Why

Joseph wants the wake to look and ride like a real wake boat's: the ramp each side and the shape in the middle. The choice was to match real numbers (width and height too), not just reshape it at today's size.

## What real wakes look like (research)

- **Measured** (Goudey & Girod 2015, WSIA: Nautique G-23, 2,850 lb ballast, 22.2 mph, sensor about 3 m from the track, close to where a 65 ft line meets the wake): 0.55 m (21.8 in) trough to crest. Near the boat, the dip in front of the wake is deeper than the crest is tall: 0.30 m down, then a crest 0.25 m above lake level. Only about 3 waves near the boat (the main crest, then smaller ones), spreading into 14 small ones 80 m out. The wakes lose height fast by breaking near the boat, then slowly: about 55% of their near-boat height at 200 ft from the track.
- **Rider terms**: "the trough" is the sunken water the hull digs between the two wakes; "the flats" is the flat water outside them. Wakes are "steep" (0.6–1.2 m from trough to lip, a defined kick) or "rampy" (a long gradual climb). "Washy" means white water on the top. A longer rope gives a wider wake; faster gives narrower and firmer.
- **Physics**: a crest can't stand steeper than about 30° without breaking, which is why real tops are white. For a boat this length at 21 mph (hull Froude number about 1.2), the biggest waves fan out at about 9–10° to the track (Rabaud & Moisy 2013), not the textbook 19.5°.

## What's there now

`wakeH` / `WAKE_GLSL` in `index.html` (one formula, CPU and GPU). At the rider (about 16.5 m behind the transom):

- Crest 0.62 m above lake level; crest line at 6° from 0.9 m off the centreline, so 5.6 m (18 ft) wake to wake.
- Outside: lake level right up to a parabolic ramp 1.9 m wide that kicks to 33° at the lip.
- Inside: a 44° face (steeper than the ramp) into a narrow trough 0.31 m deep, 1.2 m inside the crest, and the centre comes back up to lake level.
- Same profile all along, scaled by a height envelope that peaks at 18 m and has nearly gone by 80 m.
- Drawn on a uniform water grid with vertices 0.7 m apart (1.0 m on medium, 1.4 m on low).

## Goals

- At the rider's distance the cross-section reads like the measurements and photos: flats, a dip, a ramp kicking to about 30°, a washy crest, a gentler back face with a ripple or two, one wide trough below lake level across the middle with the prop wash boiling down it.
- It changes along the course the way real wakes do: steep, narrow and washy close to the boat; lower, wider and rounder further back, with more and smaller ripples; still visible as a V well down the course.
- Jumps still meet the jump bench's real-world targets: popped airtime 0.9–1.3 s, height above the lip 1.0–1.8 m, rider speed 1.15–1.35 × boat, line loads as now.
- Each quality setting runs about as fast as now (this Mac stays on high on auto).

## Non-goals

Wake shaping (surf wakes, ballast or speed settings), a different boat, a bow wave outside the main wake (about 5 cm, too small to matter), changing tricks or scoring beyond the checks below, and the loading-screen wake drawing.

## Anti-goals

- A wake you can't clear: popped jumps from a proper cut-out must still go wake to wake.
- A lip that throws you differently every time: it stays a crisp, predictable kick.
- Jagged or shimmering water from the finer detail.

## Approaches

1. **Reshape only, keep today's size.** The dip, the wide trough, ripples and prop wash, at today's width and height. Jumps barely change. Rejected because Joseph wants the real numbers.
2. **Match the real numbers, then retune the jumps (picked).** The new shape at the measured width and height. Then the physics constants are retuned until the jump bench passes again.
3. **A fully simulated wave field.** Real dispersion and breaking. Rejected: far too costly for the browser, and it would break the shared CPU/GPU formula the physics relies on.

## Design

### The cross-section

Lateral offset `u`, distance behind the transom `d`, `s = |u| − xc(d)` (positive outside the crest). Figures at the rider's distance; the builder tunes the curves to hit them.

| Part | Target at d ≈ 16.5 m |
|---|---|
| Crest line `xc(d)` | about 9° to the track from the transom corners: about 1.1 + 0.155·d, so **3.65 m each side, 7.3 m (24 ft) wake to wake** |
| Crest height | **about 0.34 m above lake level** |
| Dip in front | bottom about **0.29 m below lake level**, about 2 m outside the crest; rising back to lake level within about another ramp width |
| Ramp | concave, from the dip to the lip in about 2 m, kicking to **about 30° at the lip**: 0.63 m of climb, so the "wake" is about 2 ft from outside |
| Crest | a crisp kick, rounded over only a few centimetres, so takeoff still happens right at the lip |
| Back face | **about 22–25° at most** (gentler than the ramp, as on any wave moving outward), down to the trough in about 1.5–2 m |
| Ripples | one or two inside each crest, about 1.4 m apart, about 20% then 8% of the crest |
| Middle | **one wide flat trough about 0.24 m below lake level**, wall to wall |
| Prop wash | a band about the boat's width down the centre: white water as now, plus a low boil of 3–4 cm lumps that fades by about 40 m, in the shared formula so the board feels it |

That gives about 0.6 m trough to crest, between the 0.55 m measured with stock ballast and what a heavier modern ballast load makes.

### Along the course

- **Crest height**: about 0.15 m at the transom, full height from about 10 to 20 m, then fading slowly: about 75% at 60 m and 55% at 200 m.
- **Dip**: deeper than the crest is tall close to the boat (as measured), about 0.85 of the crest at the rider, shallower further back.
- **Trough**: the hole right behind the transom about 0.45 m deep, about 0.24 m at the rider, about 0.1 m by 40 m, level by about 70 m.
- **Ramp and back face**: widen with distance, as the waves stretch out.
- **Ripples**: more and smaller further back.

### Drawing it

- **Finer water across the wake.** The near grid gets vertices about 0.2 m apart across the boat's track out to about ±12 m (0.3 m on medium, 0.45 m on low), and stays as now beyond that. The band stays centred on the track; the boat never leaves it. My estimate is about 94k vertices on high, against 66k now.
- **Normals from the formula per pixel**, so the lip and ripples shade crisply even between vertices. The vertices still carry the height.
- **Foam**: lip foam keyed to the crest (washy close to the boat, cleaner further back, as now), spill down the new back face, and the prop wash as now. `wake()`'s second value becomes "closeness to the crest" so the lip foam keeps working.

### Physics and scoring

- **Retune** with `tools/jump_bench.py`: `EDGE_LD`, the pop impulse, `ABSORB` and the takeoff check, until the targets pass.
- **"Clear the second wake" check**: applies to popped jumps from the 6 m cut. A 3 m cut-out is too short an approach for a 24 ft wake; real riders cut out wider as the wake widens. *(My call.)*
- **Code that assumes the old shape**:
  - `takeoffWake`: now `|wakeH| > 0.12`, which would count the dip and the trough. It becomes "took off within about a metre of a crest".
  - Wake-to-wake bonus: `|x| > 1.5` becomes "landed beyond the far crest".
  - `inside` (`|u| < xc − 0.4`): stays as is.
- **Tooling**: the bench's Python dependencies (Playwright, matplotlib) go in a throwaway environment in the scratchpad, not the repo.

### Docs and version

README's water paragraph gets the new numbers. Version goes to v0.8.0 (start card and README).

## Left to the builder

The exact curves (powers, blends, envelopes) within the targets above. How the ripples and boil are written so the CPU and GPU agree and stay smooth. The retune values. The fine band's exact edge and spacing, as long as each setting holds its frame rate.
