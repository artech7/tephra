import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// jsdom has no DataTransfer/DragEvent (confirmed absent as of this writing),
// so drags are simulated with plain Events carrying a hand-rolled
// dataTransfer -- the app code only ever calls setData/getData/clientX on
// it, never anything that needs a real DragEvent subclass.
function fakeDataTransfer() {
  const store = {};
  return { setData: (k, v) => { store[k] = v; }, getData: (k) => store[k] ?? '', effectAllowed: null };
}
function fire(el, type, props = {}) {
  const ev = new window.Event(type, { bubbles: true, cancelable: true });
  Object.assign(ev, props);
  el.dispatchEvent(ev);
  return ev;
}

const figHtml = (name, idx) =>
  `<figure class="embed g2" data-kind="image" data-embed-index="${idx}">`
  + `<div class="embed-media"><img src="/media/${name}" alt="${name}" loading="lazy"></div>`
  + `<figcaption class="embed-cap"><span class="kind">IMAGE</span>${name}</figcaption></figure>`;

// Before: a row of [a, b] (indices 0, 1) plus a standalone c (index 2).
const bodyBefore = '![[a.png]]\n![[b.png]]\n\n![[c.png]]';
const htmlBefore = `<div class="embed-row">${figHtml('a.png', 0)}${figHtml('b.png', 1)}</div>` + figHtml('c.png', 2);
// After dragging c onto b's right half: c joins the row, becoming [a, b, c].
const bodyAfter = '![[a.png]]\n![[b.png]]\n![[c.png]]';
const htmlAfter = `<div class="embed-row">${figHtml('a.png', 0)}${figHtml('b.png', 1)}${figHtml('c.png', 2)}</div>`;

let serverBody = bodyBefore;
const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (/\/api\/notes\/n$/.test(p) && (!o.method || o.method === 'GET')) {
    b = { slug: 'n', title: 'N', body: serverBody, tags: [], meta: {},
          html: serverBody === bodyAfter ? htmlAfter : htmlBefore,
          links_out: 0, media: [], backlinks: [], suggestions: [], words: 1,
          updated: '2026-07-30T00:00:00Z', flags: 0 };
  }
  else if (/\/api\/notes\/n$/.test(p) && o.method === 'PUT') {
    serverBody = JSON.parse(o.body).body;
    b = { slug: 'n', title: 'N', renamed_to: null };
  }
  else if (p.includes('/api/notes')) b = [{ slug: 'n', title: 'N', tags: [], updated: '2026-07-30T00:00:00Z', backlinks: 0, links_out: 0, size: 1, kind: 'note', flags: 0 }];
  else if (p.includes('/api/vault/list')) b = { current: '/v', suggested_parent: '/', recent: [{ path: '/v', exists: true, current: true }] };
  else if (p.includes('/api/vault/info')) b = { vault: '/v', files_on_disk: 1, indexed: 1, study_items: 0 };
  else if (p.includes('/api/theme')) b = {};
  else if (p.includes('/api/repair/last')) b = { changed: 0 };
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
  else if (p.includes('/api/study')) b = { known_categories: [] };
  return { ok: true, status: 200, json: async () => b, text: async () => JSON.stringify(b) };
};
window.tephraStudy = { open: async () => {}, close: () => {}, isOpen: () => false, refresh: async () => {} };
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1; window.requestAnimationFrame = () => 0;
for (const id of ['#mini', '#graph']) { const e = doc.querySelector(id); if (e) { e.getContext = () => null; e.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 200 }); } }
doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){return{addColorStop(){}}}, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
window.eval(fs.readFileSync(`${ROOT}/graph.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
await new Promise(r => setTimeout(r, 150));

console.log('── the reorder helpers, mirroring app/render.py\'s own grouping ──');
const cases = [
  ["single row: move last to front",
    "![[a.png]]\n![[b.png]]\n![[c.png]]", 2, 0, 'before', "![[c.png]]\n![[a.png]]\n![[b.png]]"],
  ["standalone joins an existing row",
    "![[a.png]]\n![[b.png]]\n\n![[c.png]]", 2, 1, 'after', "![[a.png]]\n![[b.png]]\n![[c.png]]"],
  ["moving the only member out collapses the empty row cleanly",
    "Intro\n\n![[a.png]]\n\nMiddle\n\n![[b.png]]\n![[c.png]]\n\nEnd", 0, 2, 'after',
    "Intro\n\nMiddle\n\n![[b.png]]\n![[c.png]]\n![[a.png]]\n\nEnd"],
  ["dropping on itself is a no-op",
    "![[a.png]]\n![[b.png]]", 0, 0, 'after', "![[a.png]]\n![[b.png]]"],
];
for (const [label, body, from, to, side, expected] of cases) {
  const got = window.eval(`moveEmbed(${JSON.stringify(body)}, ${from}, ${to}, ${JSON.stringify(side)})`);
  ck(label, got === expected, got);
}

console.log('\n── figures are draggable, in document order ──');
const figs = () => [...doc.querySelectorAll('.embed[data-kind="image"]')];
ck('three image figures rendered', figs().length === 3, figs().length);
ck('all draggable', figs().every((f) => f.draggable === true));
ck('indices in document order', figs().map((f) => f.dataset.embedIndex).join(',') === '0,1,2');

console.log('\n── dragging c onto b\'s right half joins it into the row ──');
const [figA, figB, figC] = figs();
figB.getBoundingClientRect = () => ({ left: 100, top: 0, width: 100, height: 80, right: 200, bottom: 80 });

const dt = fakeDataTransfer();
fire(figC, 'dragstart', { dataTransfer: dt });
ck('drop data carries the source index', dt.getData('text/plain') === '2', dt.getData('text/plain'));
ck('dragging class applied to the source', figC.classList.contains('dragging'));

fire(figB, 'dragover', { dataTransfer: dt, clientX: 180 });   // right half of [100,200)
ck('right-half hover marks drop-after', figB.classList.contains('drop-after') && !figB.classList.contains('drop-before'));

fire(figB, 'drop', { dataTransfer: dt, clientX: 180 });
fire(figC, 'dragend', {});
ck('drop indicator cleared', !figB.classList.contains('drop-after') && !figB.classList.contains('drop-before'));
ck('dragging class cleared from the source', !figC.classList.contains('dragging'));

await new Promise(r => setTimeout(r, 30));
console.log('\n── the move is saved immediately, not debounced like a text edit ──');
const put = calls.filter((c) => c.p.endsWith('/api/notes/n') && c.body).pop();
ck('saved without waiting on the usual 700ms debounce',
   !!put && JSON.parse(put.body).body === bodyAfter, put && put.body);

console.log('\n── the preview re-renders from the server\'s own layout ──');
const newFigs = () => [...doc.querySelectorAll('.embed[data-kind="image"]')];
ck('now one row of three, in the new order',
   doc.querySelectorAll('.embed-row').length === 1 && newFigs().length === 3
   && newFigs().every((f) => f.closest('.embed-row')), doc.querySelector('#noteBody').innerHTML);
ck('re-rendered figures got their handles and drag wiring too (enhanceEmbeds reran)',
   newFigs().every((f) => f.querySelectorAll('.embed-handle').length === 4 && f.draggable === true));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
