# Wake Session

A browser wakeboarding sim in the spirit of EA Skate. You ride a 65 ft line behind a boat holding 21 mph, carve out wide, edge back into the wake, pop off the lip and land spins, rolls and grabs. One HTML file, no build step.

## Run it

Open `index.html` in any desktop browser. Everything is self-contained apart from two CDN loads: three.js r128 (cdnjs) and the Barlow Condensed / DM Sans fonts (Google Fonts). A local server works too:

```bash
python3 -m http.server 8000
```

then visit http://localhost:8000/.

Keyboard, gamepad or touch. Sound starts on the first input. On a phone, landscape works best.

## Controls

| Input | On the water | In the air |
|---|---|---|
| `←` `→` / left stick | heelside / toeside edge | spin (release the edge through neutral first, then push to spin) |
| `Space` / `A` button or right stick pulled down | hold to load the line, release at the lip to pop | |
| `↑` `↓` / left stick up/down | | front roll / backroll |
| `Q` `E` / right stick left/right | | tantrum / front flip |
| `A` `D` / LB RB | | melon / indy grab |
| `W` `S` / LT RT | | nose / tail grab |
| `V` | follow cam / tower cam | |
| `P` | cycle quality: high, medium, low, auto | |
| `R` | reset behind the boat | |
| `M` | mute | |

**Touch:** drag anywhere on the left half for a floating stick (left/right to edge, and to spin in the air; up/down in the air for front roll / backroll). Right side: hold **Pop** to load and release at the lip, hold a grab button while airborne, hold **Tantrum** or **Front flip** to rotate, tap **Cam** or **Reset**.

## How it works

- **Water** is one analytic surface sampled by both the shader and the physics from the same formula: a boat-frame V wake with a steep outer ramp and a trough behind the lip, prop wash, and ambient chop. On top of that the shader adds multi-octave ripple normals, a planar reflection of the boat, rider, shore and sky (mip-blurred with distance so far water smears the reflection like real chop), GGX sun glitter, crest translucency, and foam broken up by noise with the prop wash streaked along the boat's track. The water receives real shadow maps from the rider and boat.
- **Lighting** is linear HDR. The scene renders into a multisampled offscreen target and a post pass adds bloom, ACES tone mapping, a mild grade, vignette and grain. An analytic sky with a procedural cloud layer doubles as the environment map, so gelcoat, skin and the wet board pick up proper reflections.
- **Shoreline** sits 76 m either side of the course: sand, grass and a few thousand instanced trees, built three periods long so the whole bank snaps forward seamlessly as the boat travels. Hazy ridges close the horizon.
- **Rope** is an inelastic constraint to the tower pylon. Cutting out and releasing gives the real pendulum effect, so a progressive edge into the wake builds speed past the boat.
- **Takeoff** happens when the ramp falls away faster than gravity can follow. Air height comes from how hard you edge in; a well-timed pop adds to it.
- **Rider** is a small IK rig (knees, elbows, handle pass, grabs reach the actual edge). The board edges and tilts to the surface normal.
- **Landing** checks rotation against the nearest 180 or 360, impact speed, and whether you cased the second wake. A gentle assist helps only when you are already within 45° of clean.
- **Scoring** names tricks properly (Mobe, Scarecrow, Whirlybird, Backroll to Blind, wake-to-wake bonuses) and multiplies for clean landings.
- **Performance** scales automatically: water mesh density, render resolution, shader detail, reflection resolution, bloom, shadow map size and tree density step down when frames run long and back up with headroom. Low quality drops the reflection pass and uses the analytic sky instead.

## Tuning

The physics constants sit at the top of the script in `index.html`: boat speed, rope length, edge grip and cap, drag, pop strength, spin and flip rates. The wake shape is the `wake()` function, written once in GLSL and once in JavaScript; keep the two in step.

Look and feel lives in a few places: the sun direction and fog colour next to the renderer, the sky colours in `SKY_GLSL`, the water colours, glitter and foam thresholds in `waterMaterial()`, the post grade in `post.finalMat`, and the quality tiers in `QUALITY`.

One trap worth knowing about: never zero out a shader term by multiplying by `step()` or a `uNear`-style flag. If the other factor is NaN or infinite (an `exp()` overflow, a `smoothstep()` whose edges have crossed, a `sin()` of a huge world coordinate), `0 * NaN` is still NaN and it shows up as white patches on the water. Branch instead.
