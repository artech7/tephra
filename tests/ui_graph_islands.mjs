import { JSDOM } from 'jsdom';
import fs from 'fs';
const dom = new JSDOM('<html></html>', { runScripts: 'outside-only' });
dom.window.tephraApi = async () => ({ nodes: [], links: [] });
dom.window.eval(fs.readFileSync(new URL('../app/static/graph.js', import.meta.url).pathname, 'utf8'));
const I = dom.window.__tephraGraphInternals;

let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// Same vault shape as tests/ui_graph_tidy.mjs (root -> 13 categories -> 62
// topics), plus two direct root-to-deep-topic links -- the exact pattern
// that made the tidy tree's hierarchical bundling loop through the centre
// (a guide root linking straight to a specific topic several levels deep
// in some other note's branch). Islands has no bundling to loop with, so
// this is here to prove the hub link doesn't wreck the layout, not to
// exercise bundling.
function build() {
  const nodes = [{ label: 'FB Study Guide', deg: 0, category: '', index: true, kind: 'note' }];
  const links = [];
  let id = 1;
  const perCat = [13, 10, 9, 5, 5, 5, 3, 3, 3, 3, 1, 1, 1];
  for (let c = 0; c < perCat.length; c++) {
    const catIdx = id++;
    nodes.push({ label: 'Cat ' + c, deg: 0, category: 'c' + c, index: true, kind: 'note' });
    links.push([0, catIdx]);
    for (let t = 0; t < perCat[c]; t++) {
      nodes.push({ label: `T${c}.${t}`, deg: 0, category: 'c' + c, index: false, kind: 'note' });
      links.push([catIdx, id++]);
    }
  }
  links.push([0, 5], [0, 9]);   // root's direct shortcuts into a deep branch
  for (const [a, b] of links) { nodes[a].deg++; nodes[b].deg++; }
  return { nodes, links };
}

function settle(nodes, links) {
  I.packIslands(nodes, links);
  const sim = I.createSim(nodes, links,
    { charge: -900, linkDistance: 34, linkStrength: 0.25, gravity: 0.06, cluster: 0 });
  let t = 0;
  while (sim.running() && t < 3000) { sim.tick(); t++; }
  return t;
}

function metrics(nodes) {
  const R = 7;
  let minGap = Infinity, crossOverlaps = 0, sameOverlaps = 0;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      minGap = Math.min(minGap, d);
      if (d < R * 2) ((a.category || '') === (b.category || '') ? sameOverlaps++ : crossOverlaps++);
    }
  }
  const finite = nodes.every((d) => Number.isFinite(d.x) && Number.isFinite(d.y));
  return { minGap, crossOverlaps, sameOverlaps, finite };
}

const g = build();
const ticks = settle(g.nodes, g.links);
const m = metrics(g.nodes);

console.log(`  ${g.nodes.length} nodes, ${g.links.length} links, ${ticks} ticks`);
console.log(`  minGap=${m.minGap.toFixed(1)} crossOverlaps=${m.crossOverlaps} sameOverlaps=${m.sameOverlaps}`);
console.log('');

ck('settles within the same budget as the force layout', ticks <= 180, `${ticks} ticks`);
ck('every position is finite (no NaN from a degenerate anchor search)', m.finite);
ck('no two same-category nodes overlap', m.sameOverlaps === 0, String(m.sameOverlaps));
ck('no two different-category nodes overlap -- islands never collide',
   m.crossOverlaps === 0, String(m.crossOverlaps));
ck('nodes keep a real gap, not just barely non-overlapping', m.minGap > 14, m.minGap.toFixed(1));

// Each island should stay compact -- its own members close to their own
// centroid -- which is the actual "clustered like a constellation" claim.
console.log('\n  per-category spread (max distance from own centroid):');
let allCompact = true;
const cats = [...new Set(g.nodes.map((d) => d.category || ''))];
for (const c of cats) {
  const members = g.nodes.filter((d) => (d.category || '') === c);
  if (members.length < 2) continue;
  const cx = members.reduce((s, d) => s + d.x, 0) / members.length;
  const cy = members.reduce((s, d) => s + d.y, 0) / members.length;
  const spread = Math.max(...members.map((d) => Math.hypot(d.x - cx, d.y - cy)));
  console.log(`    ${(c || '(root)').padEnd(8)} n=${String(members.length).padEnd(3)} spread=${spread.toFixed(1)}`);
  if (spread > 90) allCompact = false;
}
ck('every island stays compact (no member strays more than 90u from its own centroid)', allCompact);

// The pathological case: two different islands, packed by packIslands
// alone (no settling), should never be placed overlapping to begin with --
// the spiral search itself is the thing under test here, not the sim.
console.log('\n  packing stays overlap-free across repeated vault shapes:');
let packOk = true;
for (const shape of [[1], [1, 1, 1, 1, 1, 1, 1, 1], [40], [1, 40], [5, 5, 5, 5, 5, 5, 5, 5, 5, 5]]) {
  const nodes = [];
  const links = [];
  let id = 0;
  shape.forEach((n, c) => {
    for (let i = 0; i < n; i++) { nodes.push({ category: 'c' + c }); id++; }
  });
  I.packIslands(nodes, links);
  const byCat = new Map();
  nodes.forEach((d) => { if (!byCat.has(d.category)) byCat.set(d.category, []); byCat.get(d.category).push(d); });
  const islands = [...byCat.values()].map((members) => {
    const cx = members.reduce((s, d) => s + d.x, 0) / members.length;
    const cy = members.reduce((s, d) => s + d.y, 0) / members.length;
    const r = Math.max(45, 24 * Math.sqrt(members.length));
    return { cx, cy, r };
  });
  for (let i = 0; i < islands.length; i++) {
    for (let j = i + 1; j < islands.length; j++) {
      const d = Math.hypot(islands[i].cx - islands[j].cx, islands[i].cy - islands[j].cy);
      if (d < islands[i].r + islands[j].r - 1) packOk = false;   // -1: float slop
    }
  }
}
ck('anchor packing never overlaps two islands\' footprints', packOk);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
