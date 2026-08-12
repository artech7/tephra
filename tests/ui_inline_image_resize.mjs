import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// HTML shaped exactly like app/render.py's _inline_image_rule emits: a plain
// markdown image inline in running text (not an ![[embed]] attachment
// figure), sized via the |400 suffix on its alt text.
const noteHtml = '<p>before '
  + '<span class="inline-img sized" data-img-index="0" style="width:400px">'
  + '<img src="pic.png" alt="a photo" loading="lazy"></span>'
  + ' after</p>';
const noteBody = 'before ![a photo|400](pic.png) after';

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
await new Promise(r => setTimeout(r, 150));

console.log('── pure helpers mirror render.py\'s own alt|size parsing ──');
const cases = [
  ["body(): unsized -> adds width", "![a photo](pic.png)", 0, 400, "![a photo|400](pic.png)"],
  ["body(): existing size replaced", "![a photo|300](pic.png)", 0, 500, "![a photo|500](pic.png)"],
  ["body(): no alt text at all", "![](pic.png)", 0, 250, "![|250](pic.png)"],
  ["body(): a title after the url survives", '![x](pic.png "a title")', 0, 200, '![x|200](pic.png "a title")'],
  ["body(): targets the right index among several", "![a](a.png) ![b](b.png)", 1, 150, "![a](a.png) ![b|150](b.png)"],
];
for (const [label, body, idx, w, expected] of cases) {
  const got = window.eval(`setInlineImgWidth(${JSON.stringify(body)}, ${idx}, ${w})`);
  ck(label, got === expected, got);
}

console.log('\n── handles ──');
const fig = doc.querySelector('.inline-img');
ck('note opened with the inline image rendered', !!fig);
const handles = () => [...fig.querySelectorAll('.embed-handle')];
ck('four corner handles injected', handles().length === 4, handles().map(h => h.className).join(' '));
ck('one of each corner', ['nw', 'ne', 'sw', 'se'].every(c => fig.querySelector(`.embed-handle.${c}`)));

console.log('\n── a handle click does not enter edit mode ──');
ck('starts in preview', !doc.querySelector('#noteBody').hidden && doc.querySelector('#noteSrc').hidden);
const seHandle = fig.querySelector('.embed-handle.se');
seHandle.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true, clientX: 100, clientY: 100 }));
doc.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true, clientX: 100, clientY: 100 }));
seHandle.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await new Promise(r => setTimeout(r, 30));
ck('still in preview, not switched to source', !doc.querySelector('#noteBody').hidden && doc.querySelector('#noteSrc').hidden);

console.log('\n── dragging the se handle resizes and persists into the alt|size suffix ──');
fig.getBoundingClientRect = () => ({ width: 400, height: 200, left: 0, top: 0, right: 400, bottom: 200 });
Object.defineProperty(fig.parentElement, 'clientWidth', { value: 800, configurable: true });
seHandle.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true, clientX: 100, clientY: 100 }));
ck('marks the image sized while dragging', fig.classList.contains('resizing') && fig.classList.contains('sized'));
doc.dispatchEvent(new window.MouseEvent('mousemove', { bubbles: true, clientX: 180, clientY: 100 }));
ck('width grows live while dragging (se = drag right to grow)', fig.style.width === '480px', fig.style.width);
doc.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true, clientX: 180, clientY: 100 }));
await new Promise(r => setTimeout(r, 30));
ck('stops marking resizing once released', !fig.classList.contains('resizing'));
ck('source textarea rewritten with the new width, alt text kept',
   doc.querySelector('#noteSrc').value === 'before ![a photo|480](pic.png) after',
   doc.querySelector('#noteSrc').value);

console.log('\n── the resize autosaves like any other edit ──');
await new Promise(r => setTimeout(r, 800));
const put = calls.filter(c => c.p.endsWith('/api/notes/n') && c.body).pop();
ck('a save went out with the resized body',
   !!put && JSON.parse(put.body).body === 'before ![a photo|480](pic.png) after',
   put && put.body);

console.log('\n── a real drag\'s trailing click lands on the image, not the handle -- must still not open edit mode ──');
fig.style.width = '';
fig.getBoundingClientRect = () => ({ width: 400, height: 200, left: 0, top: 0, right: 400, bottom: 200 });
const seHandle2 = fig.querySelector('.embed-handle.se');
const img = fig.querySelector('img');
seHandle2.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true, clientX: 100, clientY: 100 }));
doc.dispatchEvent(new window.MouseEvent('mousemove', { bubbles: true, clientX: 160, clientY: 100 }));
doc.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true, clientX: 160, clientY: 100 }));
img.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));   // the browser's synthesized click, on the image
await new Promise(r => setTimeout(r, 30));
ck('the resize was applied', fig.style.width === '460px', fig.style.width);
ck('edit mode was NOT entered despite the click landing on the image',
   !doc.querySelector('#noteBody').hidden && doc.querySelector('#noteSrc').hidden);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
