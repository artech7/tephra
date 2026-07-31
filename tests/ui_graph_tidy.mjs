import { JSDOM } from 'jsdom';
import fs from 'fs';
const dom = new JSDOM('<html></html>', { runScripts: 'outside-only' });
dom.window.tephraApi = async () => ({ nodes: [], links: [] });
dom.window.eval(fs.readFileSync('/home/claude/tephra/app/static/graph.js', 'utf8'));
const I = dom.window.__tephraGraphInternals;

// A vault shaped like Dylan's after import: root -> 13 categories -> 62 topics
function build() {
  const nodes = [{ label: 'FB Study Guide', deg: 13, category: '', index: true, kind: 'note' }];
  const links = [];
  let id = 1;
  const cats = 13;
  for (let c = 0; c < cats; c++) {
    const catIdx = id++;
    nodes.push({ label: 'Cat ' + c, deg: 0, category: 'c' + c, index: true, kind: 'note' });
    links.push([0, catIdx]);
    const topics = [13, 10, 9, 5, 5, 5, 3, 3, 3, 3, 1, 1, 1][c];
    for (let t = 0; t < topics; t++) {
      nodes.push({ label: `T${c}.${t}`, deg: 0, category: 'c' + c, index: false, kind: 'note' });
      links.push([catIdx, id++]);
    }
  }
  for (const [a, b] of links) { nodes[a].deg++; nodes[b].deg++; }
  return { nodes, links };
}

function metrics(nodes, links) {
  let minGap = Infinity, sum = 0, overlaps = 0;
  const R = 7;                              // drawn node radius
  for (let i = 0; i < nodes.length; i++) {
    let best = Infinity;
    for (let j = 0; j < nodes.length; j++) {
      if (i === j) continue;
      const d = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
      best = Math.min(best, d);
    }
    if (best < R * 2) overlaps++;
    minGap = Math.min(minGap, best); sum += best;
  }
  // edge crossings: the clearest single measure of visual clutter
  let cross = 0;
  const seg = links.map(([a, b]) => [nodes[a], nodes[b]]);
  const ccw = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  for (let i = 0; i < seg.length; i++) {
    for (let j = i + 1; j < seg.length; j++) {
      const [a, b] = seg[i], [c, d] = seg[j];
      if (a === c || a === d || b === c || b === d) continue;
      if (ccw(a, b, c) * ccw(a, b, d) < 0 && ccw(c, d, a) * ccw(c, d, b) < 0) cross++;
    }
  }
  return { minGap, avgGap: sum / nodes.length, overlaps, cross };
}

console.log(`  graph: ${build().nodes.length} nodes, ${build().links.length} links\n`);
const rows = [];

// old behaviour: no clustering
let g = build();
let sim = I.createSim(g.nodes, g.links, { cluster: 0 });
let t = 0; while (sim.running() && t < 3000) { sim.tick(); t++; }
rows.push(['force, no clustering', t, metrics(g.nodes, g.links)]);

// new default: clustered
g = build();
sim = I.createSim(g.nodes, g.links);
t = 0; while (sim.running() && t < 3000) { sim.tick(); t++; }
rows.push(['force + clustering', t, metrics(g.nodes, g.links)]);

// tidy tree
g = build();
I.tidyTree(g.nodes, g.links);
rows.push(['tidy tree', 0, metrics(g.nodes, g.links)]);

// tree with leaves hidden (the filter)
g = build();
const deg = new Map(g.nodes.map((_, i) => [i, 0]));
for (const [a, b] of g.links) { deg.set(a, deg.get(a) + 1); deg.set(b, deg.get(b) + 1); }
const keep = [...g.nodes.keys()].filter(i => deg.get(i) > 1 || g.nodes[i].index);
const rm = new Map(keep.map((v, i) => [v, i]));
const n2 = keep.map(i => ({ ...g.nodes[i] }));
const l2 = g.links.filter(([a, b]) => rm.has(a) && rm.has(b)).map(([a, b]) => [rm.get(a), rm.get(b)]);
I.tidyTree(n2, l2);
rows.push([`tidy tree, leaves hidden (${n2.length}n)`, 0, metrics(n2, l2)]);

console.log('  layout                              ticks  minGap  avgGap  overlapping  crossings');
for (const [name, ticks, m] of rows) {
  console.log(`  ${name.padEnd(34)} ${String(ticks).padStart(5)}  ${m.minGap.toFixed(1).padStart(6)}  ${m.avgGap.toFixed(1).padStart(6)}  ${String(m.overlaps).padStart(11)}  ${String(m.cross).padStart(9)}`);
}
const [, , base] = rows[0], [, , clustered] = rows[1], [, , tree] = rows[2], [, , pruned] = rows[3];
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };
console.log('');
ck('clustering reduces edge crossings', clustered.cross < base.cross, `${base.cross} -> ${clustered.cross}`);
ck('tidy tree has no crossings at all', tree.cross === 0, String(tree.cross));
ck('tidy tree needs no settling', rows[2][1] === 0);
ck('no node overlaps in any layout', rows.every(r => r[2].overlaps === 0));
ck('tree keeps siblings apart', tree.minGap > 30, tree.minGap.toFixed(1));
ck('hiding leaves opens it up further', pruned.minGap > tree.minGap,
   `${tree.minGap.toFixed(1)} -> ${pruned.minGap.toFixed(1)}`);
ck('force layout still settles quickly', rows[1][1] <= 180, `${rows[1][1]} ticks`);
console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
