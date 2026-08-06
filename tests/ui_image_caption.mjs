import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// HTML shaped exactly like app/render.py would emit for an unsized,
// uncaptioned embed: the caption text falls back to the filename, same as
// the server does, with data-caption empty marking it as a fallback rather
// than a real caption.
const noteHtml = '<p>before</p>'
  + '<figure class="embed g2" data-kind="image" data-embed-index="0">'
  + '<div class="embed-media"><img src="/media/a.png" alt="a.png" loading="lazy"></div>'
  + '<figcaption class="embed-cap"><span class="kind">IMAGE</span>'
  + '<span class="embed-cap-text" data-caption="" data-fallback="a.png">a.png</span></figcaption></figure>'
  + '<p>after</p>';
const noteBody = '![[a.png]]';

let serverBody = noteBody;
const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (/\/api\/notes\/n$/.test(p) && (!o.method || o.method === 'GET')) {
    b = { slug: 'n', title: 'N', body: serverBody, tags: [], meta: {}, html: noteHtml,
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

console.log('── pure helper mirrors render.py\'s own parsing ──');
const cases = [
  ["body(): unsized+uncaptioned -> adds a caption", "![[a.png]]", 0, "Example A", "![[a.png|Example A]]"],
  ["body(): caption added alongside an existing size", "![[a.png|400]]", 0, "Example A", "![[a.png|Example A|400]]"],
  ["body(): existing caption replaced, size kept", "![[a.png|Old|400]]", 0, "New", "![[a.png|New|400]]"],
  ["body(): clearing the caption drops the field but keeps the size", "![[a.png|Old|400]]", 0, "", "![[a.png|400]]"],
  ["body(): clearing the only field leaves a bare embed", "![[a.png|Old]]", 0, "", "![[a.png]]"],
  ["body(): targets the right index among several", "![[a.png]]\n![[b.png]]", 1, "Caption B", "![[a.png]]\n![[b.png|Caption B]]"],
];
for (const [label, body, idx, cap, expected] of cases) {
  const got = window.eval(`setEmbedCaption(${JSON.stringify(body)}, ${idx}, ${JSON.stringify(cap)})`);
  ck(label, got === expected, got);
}

console.log('\n── clicking the caption bar starts an inline edit ──');
const fig = doc.querySelector('.embed[data-kind="image"]');
ck('note opened with the embed rendered', !!fig);
const capText = fig.querySelector('.embed-cap-text');
ck('caption span present, showing the filename fallback', capText.textContent === 'a.png');
ck('starts in preview', !doc.querySelector('#noteBody').hidden && doc.querySelector('#noteSrc').hidden);

capText.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await new Promise(r => setTimeout(r, 20));
ck('click swapped in an input, not entering whole-note edit mode',
   !!fig.querySelector('.embed-cap-input') && !doc.querySelector('#noteBody').hidden && doc.querySelector('#noteSrc').hidden);
const input = fig.querySelector('.embed-cap-input');
ck('input starts empty, not pre-filled with the filename fallback', input.value === '', input.value);

console.log('\n── typing a caption and committing it rewrites the source and the DOM ──');
input.value = 'Example A: this is a diagram';
input.dispatchEvent(new window.Event('blur', { bubbles: true }));
await new Promise(r => setTimeout(r, 20));
ck('input swapped back out for the span', !fig.querySelector('.embed-cap-input') && !!fig.querySelector('.embed-cap-text'));
ck('caption span shows the new text immediately',
   fig.querySelector('.embed-cap-text').textContent === 'Example A: this is a diagram');
ck('source textarea rewritten with the caption',
   doc.querySelector('#noteSrc').value === '![[a.png|Example A: this is a diagram]]',
   doc.querySelector('#noteSrc').value);

console.log('\n── the caption autosaves like any other edit ──');
await new Promise(r => setTimeout(r, 800));
const put = calls.filter(c => c.p.endsWith('/api/notes/n') && c.body).pop();
ck('a save went out with the captioned body',
   !!put && JSON.parse(put.body).body === '![[a.png|Example A: this is a diagram]]', put && put.body);

console.log('\n── Escape cancels without saving ──');
const capText2 = fig.querySelector('.embed-cap-text');
capText2.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await new Promise(r => setTimeout(r, 20));
const input2 = fig.querySelector('.embed-cap-input');
input2.value = 'Thrown away';
input2.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
await new Promise(r => setTimeout(r, 20));
ck('reverted to the pre-edit caption, not the typed text',
   fig.querySelector('.embed-cap-text').textContent === 'Example A: this is a diagram');
ck('source untouched by the cancelled edit',
   doc.querySelector('#noteSrc').value === '![[a.png|Example A: this is a diagram]]',
   doc.querySelector('#noteSrc').value);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
