import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const notes = [
  { slug: 'alpha', title: 'Alpha note', tags: [], updated: '2026-07-29T00:00:00Z',
    backlinks: 0, links_out: 0, size: 100, kind: 'note', favorite: false },
];
// Sources for whichever note GET /api/notes/alpha returns -- mutated between
// phases below the same way ui_quiz_editor.mjs swaps its `quiz` variable.
let sources = [
  { text: 'Wikipedia', url: 'https://en.wikipedia.org/wiki/Example' },
  { text: 'A plain-text citation', url: null },
];
window.fetch = async (u, o = {}) => {
  const p = String(u); const m = o.method || 'GET';
  let b = {};
  if (p.includes('/api/theme')) b = {};
  else if (/\/api\/notes\/[\w-]+$/.test(p)) {
    const n = notes.find((x) => x.slug === p.split('/').pop()) || notes[0];
    b = { slug: n.slug, title: n.title, body: '', tags: n.tags, favorite: n.favorite, meta: {},
      html: '<p>prose only</p>', links_out: 0, media: [], backlinks: [], suggestions: [],
      words: 1, updated: n.updated, quiz: [], sources };
  } else if (p.includes('/api/notes')) b = notes;
  else if (p.includes('/api/duplicates')) b = { pairs: [] };
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
  else if (p.includes('/api/study')) b = { known_categories: [] };
  const clone = JSON.parse(JSON.stringify(b));
  return { ok: true, status: 200, json: async () => clone, text: async () => JSON.stringify(clone) };
};
window.tephraStudy = { open: async () => {}, close: () => {}, isOpen: () => false, refresh: async () => {} };
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false };
window.__tephraGraphInternals = { createSim: () => ({ running: () => false, tick() {}, nodes: [] }), W: 1000, H: 700 };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1; window.requestAnimationFrame = () => 0;
for (const id of ['#mini', '#graph']) { const e = doc.querySelector(id); if (e) { e.getContext = () => null; e.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 200 }); } }
doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){return{addColorStop(){}}}, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/quiz-editor.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/sources-panel.js`, 'utf8'));
await new Promise((r) => setTimeout(r, 90));

const items = () => [...doc.querySelectorAll('#sourcesList .sources-item')];

console.log('── existing sources load into the panel ──');
ck('section is visible when there are sources', doc.querySelector('#sourcesEdit').hidden === false);
ck('two source rows', items().length === 2, items().length);
ck('count badge', doc.querySelector('#sourcesCount').textContent === '2 sources');
const link = items()[0].querySelector('a.sources-link');
ck('linked source renders as an <a>', !!link);
ck('href matches', link?.href === 'https://en.wikipedia.org/wiki/Example');
ck('opens in a new tab, safely', link?.target === '_blank' && (link?.rel || '').includes('noopener'));
ck('link text is the title, not the url', link?.textContent === 'Wikipedia');
ck('plain source has no link, just text',
   !items()[1].querySelector('a') && items()[1].textContent === 'A plain-text citation');

console.log('\n── collapsed by default, with a toggle ──');
const toggle = doc.querySelector('#sourcesToggle');
const body = doc.querySelector('#sourcesBody');
ck('collapsed on load', body.hidden === true && toggle.getAttribute('aria-expanded') === 'false');
toggle.click();
ck('expands on click', body.hidden === false && toggle.getAttribute('aria-expanded') === 'true');
toggle.click();
ck('collapses again on a second click', body.hidden === true);
toggle.click();   // leave it open -- a re-render below should not re-collapse it

console.log('\n── a note with no sources hides the whole section ──');
window.tephraSourcesPanel.render([]);
ck('section is hidden with an empty list', doc.querySelector('#sourcesEdit').hidden === true);

console.log('\n── a hand-edited markdown Sources block re-syncs the panel ──');
window.tephraSourcesPanel.render([{ text: 'Only One', url: null }]);
ck('section reappears', doc.querySelector('#sourcesEdit').hidden === false);
ck('shows the new content', items().length === 1 && items()[0].textContent === 'Only One');
ck('re-rendering does not re-collapse an opened section', body.hidden === false);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
