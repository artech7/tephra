import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };
const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));

// jsdom has no layout engine, so scrollIntoView is left unimplemented --
// stub it so a click can be asserted on rather than just not crashing.
window.Element.prototype.scrollIntoView = function () { this.__scrolledIntoView = true; };

const CITE_HTML =
  '<p>Claim one' +
  '<sup class="cite-ref"><a class="cite-link" href="#src-1" data-idx="1" ' +
  'data-text="Wikipedia" data-url="https://en.wikipedia.org/wiki/Example">1</a></sup>' +
  ' and a shaky claim' +
  '<sup class="cite-ref"><a class="cite-link missing" data-idx="5">5</a></sup>.</p>';

const notes = [
  { slug: 'alpha', title: 'Alpha note', tags: [], updated: '2026-07-29T00:00:00Z',
    backlinks: 0, links_out: 0, size: 100, kind: 'note', favorite: false },
];
const sources = [
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
      html: CITE_HTML, links_out: 0, media: [], backlinks: [], suggestions: [],
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
window.eval(fs.readFileSync(`${ROOT}/citations.js`, 'utf8'));
await tick(90);

const fire = (el, type) => el.dispatchEvent(new window.MouseEvent(type, { bubbles: true }));
const lens = () => doc.querySelector('#lens');

console.log('── hovering a resolved citation opens the same #lens a wikilink does ──');
const good = doc.querySelector('.cite-link:not(.missing)');
ck('citation marker rendered in note body', !!good);
fire(good, 'mouseover');
await tick(200);   // app.js debounces the lens open by 160ms
ck('lens opens on hover', lens().classList.contains('on'));
ck('kind label says SOURCE', doc.querySelector('#lensKind').textContent === 'SOURCE');
ck('title is the source text', doc.querySelector('#lensTitle').textContent === 'Wikipedia');
ck('body is the source url', doc.querySelector('#lensBody').textContent === 'https://en.wikipedia.org/wiki/Example');
ck('meta names the citation number', doc.querySelector('#lensMeta').textContent.includes('Source #1'));
fire(good, 'mouseout');
ck('lens closes on mouseout', lens().classList.contains('on') === false);

console.log('\n── hovering a missing citation explains why, in the same lens ──');
const missing = doc.querySelector('.cite-link.missing');
ck('an out-of-range marker is flagged', !!missing);
fire(missing, 'mouseover');
await tick(200);
ck('kind label flags it', doc.querySelector('#lensKind').textContent === 'MISSING SOURCE');
ck('title names the citation number', doc.querySelector('#lensTitle').textContent === 'Citation #5');
ck('body explains it was not found',
   doc.querySelector('#lensBody').textContent.includes('Not found') &&
   doc.querySelector('#lensBody').textContent.includes('Sources list'));
fire(missing, 'mouseout');
ck('lens closes on mouseout', lens().classList.contains('on') === false);

console.log('\n── clicking a resolved citation closes the lens, opens Sources, and jumps to it ──');
fire(good, 'mouseover');
await tick(200);
ck('lens open before the click', lens().classList.contains('on'));
const sourcesBody = doc.querySelector('#sourcesBody');
ck('sources panel starts collapsed', sourcesBody.hidden === true);
fire(good, 'click');
ck('lens closes on click', lens().classList.contains('on') === false);
ck('sources panel opens on click', sourcesBody.hidden === false);
const target = doc.getElementById('src-1');
ck('the matching source entry is highlighted', !!target && target.classList.contains('cite-highlight'));
ck('the matching source entry is scrolled into view', target?.__scrolledIntoView === true);

console.log('\n── clicking a missing citation is a no-op beyond closing the lens ──');
[...doc.querySelectorAll('.sources-item')].forEach((li) => li.classList.remove('cite-highlight'));
fire(missing, 'click');
ck('no source entry gets highlighted for an unresolved citation',
   ![...doc.querySelectorAll('.sources-item')].some((li) => li.classList.contains('cite-highlight')));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
