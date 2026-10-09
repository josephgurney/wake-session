# Wake Session

A browser wakeboarding sim in the spirit of EA Skate. You ride a 65 ft line behind a boat holding 21 mph, carve out wide, edge back into the wake, pop off the lip and land spins, rolls and grabs. One HTML file, no build step.

## Run it

Open `index.html` in any desktop browser. Everything is self-contained apart from two CDN loads: three.js r128 (cdnjs) and the Barlow Condensed / DM Sans fonts (Google Fonts). A local server works too:

```bash
python3 -m http.server 8000
```

then visit http://localhost:8000/.

Keyboard or gamepad. Sound starts on the first input.

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

## How it works

- **Water** is one analytic surface sampled by both the shader and the physics from the same formula: a boat-frame V wake with a steep outer ramp and a trough behind the lip, prop wash, and ambient chop. Foam, fresnel, sun glints and the rider's wash trail sit on top.
- **Rope** is an inelastic constraint to the tower pylon. Cutting out and releasing gives the real pendulum effect, so a progressive edge into the wake builds speed past the boat.
- **Takeoff** happens when the ramp falls away faster than gravity can follow. Air height comes from how hard you edge in; a well-timed pop adds to it.
- **Rider** is a small IK rig (knees, elbows, handle pass, grabs reach the actual edge). The board edges and tilts to the surface normal.
- **Landing** checks rotation against the nearest 180 or 360, impact speed, and whether you cased the second wake. A gentle assist helps only when you are already within 45° of clean.
- **Scoring** names tricks properly (Mobe, Scarecrow, Whirlybird, Backroll to Blind, wake-to-wake bonuses) and multiplies for clean landings.
- **Performance** scales automatically: water mesh density, render resolution and shader detail step down when frames run long and back up with headroom.

## Tuning

The physics constants sit at the top of the script in `index.html`: boat speed, rope length, edge grip and cap, drag, pop strength, spin and flip rates. The wake shape is the `wake()` function, written once in GLSL and once in JavaScript; keep the two in step.
