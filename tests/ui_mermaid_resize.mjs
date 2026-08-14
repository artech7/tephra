import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8403/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// A manual resize (drag handles, same as .embed/.inline-img) persists as
// ```mermaid|500 on the fence tag itself -- see app/render.py's _fence_rule
// and app.js's setMermaidWidth. This file follows tests/ui_image_resize.mjs's
// own pattern exactly: pure-helper cases first, then a real simulated drag
// through the actual openNote()/autosave flow, so state.note.body is
// genuinely populated (unlike tests/ui_mermaid.mjs's lighter harness, which
// only needs #noteBody's markup, not a real open note, for what it checks).
window.mermaid = {
  initialize() {},
  run: async (opts) => { for (const n of opts.nodes) n.setAttribute('data-processed', 'true'); },
};

// HTML shaped exactly like app/render.py's _fence_rule emits for an unsized
// ```mermaid fence at index 0.
const noteHtml = '<p>before</p>'
  + '<pre class="mermaid" data-mermaid-index="0">graph TD\nA --&gt; B</pre>'
  + '<p>after</p>';
const noteBody = '```mermaid\ngraph TD\nA --> B\n```';

const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (/\/api\/notes\/n$/.test(p) && (!o.method || o.method === 'GET')) {
    b = { slug: 'n', title: 'N', body: noteBody, tags: [], meta: {}, html: noteHtml,
          links_out: 0, media: [], backlinks: [], suggestions: [], words: 1,
          updated: '2026-07-30T00:00:00Z', flags: 0 };
  }
  else if (/\/api\/notes\/n$/.test(p) && o.method === 'PUT') {
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
await new Promise((r) => setTimeout(r, 150));

console.log('── setMermaidWidth mirrors render.py\'s own fence-tag parsing ──');
const cases = [
  ['unsized -> adds a size to the fence tag',
    '```mermaid\ngraph TD\nA --> B\n```', 0, 500,
    '```mermaid|500\ngraph TD\nA --> B\n```'],
  ['existing size replaced',
    '```mermaid|300\ngraph TD\nA --> B\n```', 0, 700,
    '```mermaid|700\ngraph TD\nA --> B\n```'],
  ['targets the right diagram among several',
    '```mermaid\nA --> B\n```\n\nprose\n\n```mermaid\nC --> D\n```', 1, 250,
    '```mermaid\nA --> B\n```\n\nprose\n\n```mermaid|250\nC --> D\n```'],
  ['the diagram source itself is left untouched, only the fence tag changes',
    '```mermaid\ngraph TD\n    A[[Subroutine]] --> B\n```', 0, 400,
    '```mermaid|400\ngraph TD\n    A[[Subroutine]] --> B\n```'],
];
for (const [label, body, idx, w, expected] of cases) {
  const got = window.eval(`setMermaidWidth(${JSON.stringify(body)}, ${idx}, ${w})`);
  ck(label, got === expected, got);
}

console.log('\n── handles ──');
const fig = doc.querySelector('.mermaid');
ck('note opened with the diagram rendered', !!fig);
const handles = () => [...fig.querySelectorAll('.embed-handle')];
ck('four corner handles injected', handles().length === 4, handles().map((h) => h.className).join(' '));
ck('one of each corner', ['nw', 'ne', 'sw', 'se'].every((c) => fig.querySelector(`.embed-handle.${c}`)));

console.log('\n── dragging the se handle resizes and persists ──');
fig.getBoundingClientRect = () => ({ width: 300, height: 200, left: 0, top: 0, right: 300, bottom: 200 });
Object.defineProperty(fig.parentElement, 'clientWidth', { value: 800, configurable: true });
const seHandle = fig.querySelector('.embed-handle.se');
seHandle.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true, clientX: 100, clientY: 100 }));
ck('marks the diagram sized while dragging', fig.classList.contains('resizing') && fig.classList.contains('sized'));
doc.dispatchEvent(new window.MouseEvent('mousemove', { bubbles: true, clientX: 180, clientY: 100 }));
ck('width grows live while dragging (se = drag right to grow)', fig.style.width === '380px', fig.style.width);
doc.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true, clientX: 180, clientY: 100 }));
await new Promise((r) => setTimeout(r, 30));
ck('stops marking resizing once released', !fig.classList.contains('resizing'));
ck('source textarea rewritten with the new width, diagram body untouched',
   doc.querySelector('#noteSrc').value === '```mermaid|380\ngraph TD\nA --> B\n```',
   doc.querySelector('#noteSrc').value);

console.log('\n── the resize autosaves like any other edit ──');
await new Promise((r) => setTimeout(r, 800));
const put = calls.filter((c) => c.p.endsWith('/api/notes/n') && c.body).pop();
ck('a save went out with the resized body', !!put && JSON.parse(put.body).body === '```mermaid|380\ngraph TD\nA --> B\n```',
   put && put.body);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
