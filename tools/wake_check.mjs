// Runs tools/probe.js's checkWake() and checkScoring() on the physics' wake formula from index.html, without a browser:
//   node tools/wake_check.mjs        prints what's wrong and exits 1, or "wake: ok"
// (checkWakeGPU() needs the page: run it from the console, see probe.js.)
import { readFileSync } from 'node:fs';
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const pick = (from, to) => { const a = html.indexOf(from), b = html.indexOf(to, a); if (a < 0 || b < 0) throw new Error(`can't find ${from}`); return html.slice(a, b); };
const src = [pick('const clamp=', '\n'), pick('const smoothstep=', '\n'), pick('const PYLON_H=', '\n'),
  pick('const WAKE_PH_PERIOD', 'function ambientH(')].join('\n');
Object.assign(globalThis, new Function(`${src}; return { wakeH, wakeTrough, crestX, nearCrest, wakePh, WAKE_GLSL };`)());
const { checkWake, checkScoring } = await import('./probe.js');
const bad = [...checkWake(), ...checkScoring()];
console.log(bad.length ? bad.join('\n') : 'wake: ok');
process.exit(bad.length ? 1 : 0);
