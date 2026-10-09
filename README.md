# Thursday Yacht Club

*Lobster presents. No Risk, No Story.*

A browser wakeboarding sim in the spirit of EA Skate. You ride a 65 ft line behind a boat holding 21 mph, carve out wide, edge back into the wake, pop off the lip and land spins, rolls and grabs. One HTML file, no build step.

## Run it

Open `index.html` in any desktop browser. Everything is self-contained apart from three CDN loads: three.js r128 (cdnjs), its glTF loader (jsDelivr) and the Barlow Condensed / DM Sans fonts (Google Fonts). The rider model ships as `assets/rider.js`, so opening the file straight from disk works. A local server works too:

```bash
python3 -m http.server 8000
```

then visit http://localhost:8000/.

Keyboard, gamepad or touch. Sound starts on the first input. On a phone, landscape works best.

## Controls

| Input | On the water | In the air |
|---|---|---|
| `←` `→` / left stick | heelside / toeside edge | spin, wound up off the lip: tap for a 180, hold longer for more (release the edge through neutral first). Then keep pushing to tuck and turn faster, or push back to open up and slow down |
| `Space` / `A` button or right stick pulled down | hold to load the line, release at the lip to pop | |
| `↑` `↓` / left stick up/down | | front roll / backroll (set off the lip the same way; hold through it to tuck) |
| `Q` `E` / right stick left/right | | tantrum / front flip |
| `A` `D` / LB RB | | melon / indy grab |
| `W` `S` / LT RT | | nose / tail grab |
| `V` | cycle cameras: follow, long lens, boat tower | |
| `P` | cycle quality: high, medium, low, auto | |
| `R` | reset behind the boat | |
| `M` | mute | |

**Touch:** drag anywhere on the left half for a floating stick (left/right to edge, and off the lip to spin; up/down in the air for front roll / backroll). Right side: hold **Pop** to load and release at the lip, hold a grab button while airborne, hold **Tantrum** or **Front flip** to rotate, tap **Cam** or **Reset**.

## How it works

- **Water** is one analytic surface sampled by both the shader and the physics from the same formula: a boat-frame V wake whose outside is a ramp that steepens to a crisp lip (about 30° where a 65 ft line puts you), a steep inside face, a trough about half as deep as the crest is tall, prop wash, and ambient chop. The wake is tallest about 18 m behind the stern. On top of that the shader adds multi-octave ripple normals, a planar reflection of the boat, rider, shore and sky (mip-blurred with distance so far water smears the reflection like real chop), GGX sun glitter, crest translucency, and foam broken up by noise with the prop wash streaked along the boat's track. The water receives real shadow maps from the rider and boat.
- **Lighting** is linear HDR. The scene renders into a multisampled offscreen target and a post pass adds bloom, ACES tone mapping, a mild grade, vignette and grain. An analytic sky with a procedural cloud layer doubles as the environment map, so gelcoat, skin and the wet board pick up proper reflections.
- **Shoreline** sits 76 m either side of the course: sand, grass and a few thousand instanced trees, built three periods long so the whole bank snaps forward seamlessly as the boat travels. Hazy ridges close the horizon.
- **Rope** is a stiff spring that only pulls (a poly-E line stretches 2–3% under a hard cut). It goes slack when you run at the boat and snaps tight with a jolt; pull more than 2.8 times your body weight and the handle is gone. The HUD shows the line load. Cutting out and edging back in gives the real pendulum effect, and the edge's side force comes with drag, so a rider tops out around 1.2–1.35 times boat speed.
- **Takeoff** happens at the lip, where the surface falls away faster than gravity can follow, and the board leaves with the speed it had going up the ramp. Relaxed legs soak up about 2.4 m/s of that, so cutting out over the wake is just a bump. Hold Space and you stand tall through the lip; let go partway up the ramp and your legs extend through it, adding 0.5–1.5 m/s. Let go on flat water and it's an ollie.
- **Rider** is a skinned human (see below) posed from the physics. The body leans along the force the water puts on the board, so it hangs back against the rope and tips into a cut, and it is sprung rather than snapped so it carries weight. The chest and shoulders square up to the handle, held overhand in front of the belly at one fixed arm's reach: the body leans and folds, the arms never stretch or shorten. The legs soak up a wake face and extend as it drops away, the knees come up in the air, grabs tuck right down to the board, spins and flips pull the handle in to the waist and pass it behind the back (the near hand holds it on each side, the free arm out for balance), and the head watches the boat or the landing. The board edges and tilts to the surface normal.
- **Cameras**: a close follow cam, a long-lens chase from about 24 m back (the compressed look of wake films), and the boat's tower. Hard landings and falls jolt the camera unless the system asks for reduced motion.
- **Rotation** is set at takeoff, the way a rider winds up against the line and lets it go at the lip. In the first 0.45 s off the lip, holding a direction charges angular momentum for up to a quarter second, and a bigger pop gives you more to work with. After that you can't add or take away spin, only change how fast it turns: keep pushing the same way to tuck (knees up, handle in), which turns faster, or push back to open up, which slows it. A tap is a 180; a full wind-up opened up is a 360, tucked a 540 (do neither off a big pop and it's too much for a 360). Inverts work the same way. The body turns about its centre of mass, not its feet, so in a backroll the board goes over the top. In the last 0.3 s the body is nudged at most 25° toward the nearest clean landing.
- **Landing** is judged on what the board meets: speed into the surface measured against the wake's own slope (so landing on the second wake's downslope is soft, while casing it or sailing past into the flats is not), and how far the board is from straight. More than 45° out on a spin catches an edge, and which one depends on which way you're sliding: catch the toe edge and you go over face-first, catch the heel edge and you slam onto your back. More than 60° out on an invert is a fall, and an invert that comes round short or long puts the head or back in before the board. Heavy landings cost points and scrub speed.
- **Bails** hand the rider to a ragdoll that carries their speed and spin into the water, so no two falls are the same. It's a home-made position-based solver: particles at the joints held by bone lengths and joint limits (knees, elbows, ankles, a spine that bends and twists), with the board and boots one rigid piece. The water holds up each part by its volume and drags on it. The hips and legs sink and the vest floats the chest. The board skims along its length but digs in on an edge or slaps down flat, and that's what throws the body over it when an edge catches. Spray bursts where each part hits and streams off it while it skids. The handle is let go; overload the line and it yanks the arms toward the boat first. After about a second the rider comes round, lifts their head and sits back in the water to wait for the boat.
- **Scoring** names tricks properly (Mobe, Scarecrow, Whirlybird, Backroll to Blind, wake-to-wake bonuses) and multiplies for clean landings.
- **Performance** scales automatically: water mesh density, render resolution, shader detail, reflection resolution, bloom, shadow map size and tree density step down when frames run long and back up with headroom. Low quality drops the reflection pass and uses the analytic sky instead.

## The rider model

The rider is the MakeHuman base body (CC0) with MPFB2's 53-bone game skeleton, dressed in board shorts, an impact vest, wake boots, a helmet and sunglasses. `tools/build_rider.py` builds it with plain Python and numpy: it morphs the body with MPFB2's shape targets, fits the skeleton and its skin weights, grows the clothing out of the body surface (so it bends exactly like the skin) and deletes the skin it hides, then writes `assets/rider.glb` and `assets/rider.js` (the same bytes as base64, so the game loads it without a web server).

```bash
git clone --depth 1 https://github.com/makehumancommunity/mpfb2 ../mpfb2
python tools/build_rider.py --mpfb ../mpfb2
```

Body shape (gender, age, muscle, weight, height, proportions) and outfit colours are constants at the top of the script. In the game, the pose solver works out where the hips, chest, hands, feet and gaze should be, and `driveRig()` turns that into bone rotations, re-solving arms and legs on the model's own bone lengths so the hands stay on the handle and the boots on the board. If the model can't load, the game falls back to the primitive rider.

## Tuning

`tools/jump_bench.py` runs the game's own physics headless through scripted wake jumps (relaxed, standing tall, popped), checks them against real-world targets (airtime, height above the lip, rider speed, line load) and draws the jump arcs over the wake. A trick table then runs the same popped jump with scripted rotation inputs (a tap, a wind-up opened or tucked, a backroll held or let go) and checks what each lands as. A crash table follows heel and toe edge catches and a short backroll through the ragdoll, checking which way the rider goes over, how far they slide, how deep the head goes and that they end up floating:

```bash
pip install playwright matplotlib numpy && playwright install chromium
python tools/jump_bench.py        # table in the terminal, plot in tools/out/jump_bench.png
```


The physics constants sit at the top of the script in `index.html`: boat speed, rope length, edge grip and cap, drag, pop strength, and `ROT` (how fast each rotation turns open and tucked, and the most a takeoff can wind up). The ragdoll is tuned by the `RAG_` constants in its own section: each body part's mass, size, volume and drag, the board's drag along, across and through it, and how soon the rider comes round. The wake shape is the `wake()` function, written once in GLSL and once in JavaScript; keep the two in step.

Look and feel lives in a few places: the sun direction and fog colour next to the renderer, the sky colours in `SKY_GLSL`, the water colours, glitter and foam thresholds in `waterMaterial()`, the post grade in `post.finalMat`, and the quality tiers in `QUALITY`.

One trap worth knowing about: never zero out a shader term by multiplying by `step()` or a `uNear`-style flag. If the other factor is NaN or infinite (an `exp()` overflow, a `smoothstep()` whose edges have crossed, a `sin()` of a huge world coordinate), `0 * NaN` is still NaN and it shows up as white patches on the water. Branch instead.

## Credits

Rider body, skeleton and skin weights: the MakeHuman base mesh and MPFB2 game-engine rig, released as CC0 by the MakeHuman team (Data Collection AB, Joel Palmius, Jonas Hauquier).

## Branding

The game is presented by Lobster Eyewear. The logo (`assets/lobster-logo.png`) comes from the Lobster logo pack, and the HUD colours are sampled from it: navy `#1f1b48`, yellow `#ffed00`, hot pink `#e6007e`. On-screen copy follows the Lobster voice in the `twg-brand-skills` repo (`skills/lobster-eyewear.md`): short sentences, UK English, cheeky, no em dashes.
