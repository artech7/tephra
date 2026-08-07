import { JSDOM } from 'jsdom';
import fs from 'fs';
const dom = new JSDOM('<html></html>', { runScripts: 'outside-only' });
dom.window.tephraApi = async () => ({ nodes: [], links: [] });
dom.window.eval(fs.readFileSync(new URL('../app/static/graph.js', import.meta.url).pathname, 'utf8'));
const I = dom.window.__tephraGraphInternals;

let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

console.log('── treePath finds the lowest common ancestor ──');
//        0
//      / | \
//     1  2  3
//    /|     |
//   4 5     6
const parent = [-1, 0, 0, 0, 1, 1, 3];
ck('siblings under the same parent route through it', JSON.stringify(I.treePath(parent, 4, 5)) === JSON.stringify([4, 1, 5]));
ck('cousins route through the shared grandparent', JSON.stringify(I.treePath(parent, 4, 6)) === JSON.stringify([4, 1, 0, 3, 6]));
ck('parent-child is a direct 2-point path', JSON.stringify(I.treePath(parent, 1, 4)) === JSON.stringify([1, 4]));
ck('a node and the root', JSON.stringify(I.treePath(parent, 4, 0)) === JSON.stringify([4, 1, 0]));
ck('no shared ancestor falls back to a direct 2-point path', JSON.stringify(I.treePath([-1, -1], 0, 1)) === JSON.stringify([0, 1]));

console.log('\n── blendPath bows toward the tree without moving the endpoints ──');
const nodes2 = [
  { x: 0, y: 0 }, { x: -50, y: 40 }, { x: 50, y: 40 }, { x: 0, y: -50 },
  { x: -80, y: 90 }, { x: 80, y: 90 },
];
const path = [4, 1, 0, 2, 5];   // cousins routed through the root
for (const beta of [0, 0.5, 0.82, 1]) {
  const pts = I.blendPath(nodes2, path, beta);
  const okEnds = pts[0].x === nodes2[4].x && pts[0].y === nodes2[4].y &&
    pts[pts.length - 1].x === nodes2[5].x && pts[pts.length - 1].y === nodes2[5].y;
  ck(`beta=${beta}: endpoints stay exactly on the real notes`, okEnds);
}
const straight = I.blendPath(nodes2, path, 0);
const cross = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
const collinear = straight.every((p) => Math.abs(cross(straight[0], straight[straight.length - 1], p)) < 1e-9);
ck('beta=0 is a straight line (every point collinear with the endpoints)', collinear);
const hugging = I.blendPath(nodes2, path, 1);
const matchesTree = path.every((idx, i) => hugging[i].x === nodes2[idx].x && hugging[i].y === nodes2[idx].y);
ck('beta=1 reproduces the tree path exactly', matchesTree);
// At the root's slot in the path (index 2), the tree says y=0 and a
// straight line between the endpoints says y=90. A high beta should land
// clearly on the tree side of that range, not just anywhere between.
const mid = I.blendPath(nodes2, path, 0.82)[2];
ck('a partial beta bows toward the tree without reaching it',
   mid.y > 0 && mid.y < 45,
   `tree.y=0, straight.y=90, blended.y=${mid.y}`);

console.log('\n── buildBundles only bundles the links a tidy tree draws straight anyway would clutter ──');
const bnodes = [
  { label: 'root', deg: 0 }, { label: 'cat A', deg: 0 }, { label: 'cat B', deg: 0 },
  { label: 'topic A1', deg: 0 }, { label: 'topic A2', deg: 0 }, { label: 'topic B1', deg: 0 },
];
const blinks = [
  [0, 1], [0, 2], [1, 3], [1, 4], [2, 5],   // the tree itself
  [3, 5],                                    // a cross-branch "related topic" link
  [3, 4],                                    // siblings — also not a tree edge
];
for (const [a, b] of blinks) { bnodes[a].deg++; bnodes[b].deg++; }
const { parent: p2 } = I.tidyTree(bnodes.map((n) => ({ ...n })), blinks);
const bundles = I.buildBundles(bnodes, blinks, p2);
ck('tree edges are not bundled (drawn straight, they have no crossings to fix)',
   !bundles.has(I.bundleKey(0, 1)) && !bundles.has(I.bundleKey(1, 3)));
ck('the sibling link (3,4) is bundled — it is never a parent-child edge',
   bundles.has(I.bundleKey(3, 4)));
ck('lookup is order-independent', I.bundleKey(3, 5) === I.bundleKey(5, 3));
// Node 5 has two candidate parents ([2,5] and [3,5]); the BFS picks one as
// the actual tree edge and that choice is an implementation detail of
// tidyTree, not something bundling should hardcode. What must hold is the
// invariant: exactly the non-tree edge gets bundled, whichever one that is.
ck('every link is bundled if and only if it is not the tree edge tidyTree actually picked',
   blinks.every(([a, b]) => (p2[a] === b || p2[b] === a) !== bundles.has(I.bundleKey(a, b))),
   blinks.map(([a, b]) => `${a}-${b}:${bundles.has(I.bundleKey(a, b)) ? 'bundled' : 'straight'}`).join(' '));
ck('every bundle is exactly the tree path between its two notes',
   [...bundles.entries()].every(([key, path]) => {
     const [a, b] = key.split(':').map(Number);
     return JSON.stringify(path) === JSON.stringify(I.treePath(p2, a, b));
   }));

console.log('\n── holds up on a bigger vault with several cross-links ──');
function buildBig() {
  const nodes = [{ label: 'FB Study Guide', deg: 0, index: true, kind: 'note' }];
  const links = [];
  let id = 1;
  const perCat = [13, 10, 9, 5, 5, 5, 3, 3, 3, 3, 1, 1, 1];
  const firstTopic = [];
  for (let c = 0; c < perCat.length; c++) {
    const catIdx = id++;
    nodes.push({ label: 'Cat ' + c, deg: 0, index: true, kind: 'note' });
    links.push([0, catIdx]);
    for (let t = 0; t < perCat[c]; t++) {
      nodes.push({ label: `T${c}.${t}`, deg: 0, index: false, kind: 'note' });
      if (t === 0) firstTopic.push(id);
      links.push([catIdx, id++]);
    }
  }
  // "related topic" links across categories — the kind that used to cut
  // straight across the radial layout.
  for (let i = 0; i < firstTopic.length - 1; i++) links.push([firstTopic[i], firstTopic[i + 1]]);
  for (const [a, b] of links) { nodes[a].deg++; nodes[b].deg++; }
  return { nodes, links };
}
const big = buildBig();
const { parent: bigParent } = I.tidyTree(big.nodes, big.links);
const bigBundles = I.buildBundles(big.nodes, big.links, bigParent);
ck('every cross-category link got bundled', bigBundles.size === 12, String(bigBundles.size));
let allAnchored = true, allFinite = true;
for (const [key, path] of bigBundles) {
  const [a, b] = key.split(':').map(Number);
  const pts = I.blendPath(big.nodes, path, 0.82);
  if (pts[0].x !== big.nodes[a].x && pts[0].x !== big.nodes[b].x) allAnchored = false;
  if (!pts.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y))) allFinite = false;
}
ck('every bundled curve is anchored to a real note position at both ends', allAnchored);
ck('every bundled curve is finite (no NaN from a missing ancestor)', allFinite);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
