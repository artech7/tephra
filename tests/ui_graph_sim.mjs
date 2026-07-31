import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/' });
const { window } = dom;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

window.tephraApi = async () => ({ nodes: [], links: [] });
window.eval(fs.readFileSync(`${ROOT}/graph.js`, 'utf8'));
const I = window.__tephraGraphInternals;

// a graph the size of Dylan's vault after import
const N = 79;
const nodes = Array.from({ length: N }, (_, i) => ({
  i, slug: 's' + i, label: 'Node ' + i, kind: i % 9 === 0 ? 'stub' : 'note',
  deg: 0, category: 'c' + (i % 13),
}));
const links = [];
for (let i = 1; i < N; i++) links.push([i, i % 13]);          // category hubs
for (let i = 0; i < 20; i++) links.push([i, (i * 7 + 3) % N]); // cross links
links.forEach(([a, b]) => { nodes[a].deg++; nodes[b].deg++; });

console.log('── does it settle, and how fast? ──');
const sim = I.createSim(nodes, links);
ck('starts hot', sim.alpha === 1 && sim.running());
let ticks = 0, energyAt = {};
while (sim.running() && ticks < 2000) {
  sim.tick(); ticks++;
  if ([30, 60, 120, 180].includes(ticks)) energyAt[ticks] = sim.energy();
}
console.log(`        kinetic energy: t30=${energyAt[30]?.toFixed(0)} t60=${energyAt[60]?.toFixed(0)} t120=${energyAt[120]?.toFixed(1)} t180=${energyAt[180]?.toFixed(2)}`);
ck('comes to a complete stop', !sim.running() && sim.alpha === 0, `after ${ticks} ticks`);
ck('settles in under 3s at 60fps', ticks < 180, `${ticks} ticks = ${(ticks / 60).toFixed(1)}s`);
ck('energy monotonically decays', energyAt[60] < energyAt[30] && energyAt[120] < energyAt[60]);
ck('effectively still by 2s', energyAt[120] < 1, `E=${energyAt[120]?.toFixed(3)}`);
ck('layout is finite (no explosions)', nodes.every(d => Number.isFinite(d.x) && Number.isFinite(d.y)));
const spread = Math.max(...nodes.map(d => Math.hypot(d.x - I.W / 2, d.y - I.H / 2)));
ck('stays in a sane bounding area', spread < 900, `max radius ${spread.toFixed(0)}`);

console.log('\n── deterministic layout (same every open) ──');
const a = I.createSim(nodes.map(d => ({ ...d })), links);
const b = I.createSim(nodes.map(d => ({ ...d })), links);
for (let i = 0; i < 100; i++) { a.tick(); b.tick(); }
const same = a.nodes.every((d, i) => Math.abs(d.x - b.nodes[i].x) < 1e-9);
ck('identical layout across runs', same);

console.log('\n── overlapping nodes do not divide by zero ──');
const twins = [{ i: 0, x: 500, y: 350, label: 'a', deg: 1 }, { i: 1, x: 500, y: 350, label: 'b', deg: 1 }];
const ts = I.createSim(twins, [[0, 1]]);
for (let i = 0; i < 50; i++) ts.tick();
ck('separated without NaN', twins.every(d => Number.isFinite(d.x)) &&
   Math.hypot(twins[0].x - twins[1].x, twins[0].y - twins[1].y) > 1);

console.log('\n── hit testing respects pan and zoom ──');
const rad = (d) => 6;
const target = { i: 0, x: 300, y: 200 };
const only = [target];
let v = { k: 1, tx: 0, ty: 0 };
ck('hit at identity transform', I.hitTest(only, 300, 200, v, rad) === target);
ck('miss far away', I.hitTest(only, 600, 500, v, rad) === null);
v = { k: 2, tx: 50, ty: -30 };
const [sx, sy] = I.toScreen(300, 200, v);
ck('hit after zoom+pan', I.hitTest(only, sx, sy, v, rad) === target, `screen ${sx},${sy}`);
ck('round-trips world<->screen', (() => {
  const [wx, wy] = I.toWorld(sx, sy, v);
  return Math.abs(wx - 300) < 1e-9 && Math.abs(wy - 200) < 1e-9;
})());
v = { k: 0.4, tx: 10, ty: 10 };
const [zx, zy] = I.toScreen(300, 200, v);
ck('slop keeps small nodes clickable when zoomed out',
   I.hitTest(only, zx + 4, zy, v, rad) === target);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
