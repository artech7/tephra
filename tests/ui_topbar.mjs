import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = '/home/claude/tephra/app/static';
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

console.log('── placement in the topbar ──');
const bar = [...doc.querySelector('.topbar').children];
const iMark = bar.findIndex(n => n.classList.contains('mark'));
const iCruc = bar.findIndex(n => n.id === 'crucibleBtn');
const iCrumb = bar.findIndex(n => n.classList.contains('crumbs'));
const iSeg = bar.findIndex(n => n.classList.contains('segmented'));
ck('Crucible sits immediately after the Tephra mark', iCruc === iMark + 1, `mark@${iMark} crucible@${iCruc}`);
ck('it is left of the breadcrumb', iCruc < iCrumb);
ck('it is left of the Write/Graph control', iCruc < iSeg);
ck('it has its own icon', !!doc.querySelector('#crucibleBtn i.cruc-mark'));
ck('it has its own name', doc.querySelector('#crucibleBtn').textContent.trim() === 'Crucible');
ck('styled as a sibling wordmark', doc.querySelector('#crucibleBtn').classList.contains('mark'));
// The segmented control holds the canvas modes. Crucible is an overlay with
// its own wordmark; Links is a canvas mode and belongs here.
ck('segmented holds the canvas modes',
   [...doc.querySelectorAll('.segmented button')].map(b => b.dataset.view).join('/') === 'write/graph/links',
   [...doc.querySelectorAll('.segmented button')].map(b => b.dataset.view).join('/'));
ck('no stray Study button left behind',
   ![...doc.querySelectorAll('.segmented button')].some(b => b.dataset.view === 'study'));

// ── boot app.js with stubs so setView is live ──
const studyState = { open: false };
window.tephraStudy = { open: async () => { studyState.open = true; }, close: () => { studyState.open = false; }, isOpen: () => studyState.open, refresh: async () => {} };
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false, select: () => {} };
window.__tephraGraphInternals = { createSim: () => ({ running: () => false, tick() {}, nodes: [] }), W: 1000, H: 700 };
const notes = [{ slug: 'a', title: 'A', tags: [], updated: new Date().toISOString(), backlinks: 0 }];
window.fetch = async (u, o = {}) => {
  const p = String(u);
  const body = p.includes('/api/theme') ? {} :
    p.includes('/api/notes/a') ? { slug: 'a', title: 'A', body: '', tags: [], meta: {}, html: '<p></p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 0, updated: new Date().toISOString() } :
    p.includes('/api/notes') ? notes :
    p.includes('/api/graph') ? { nodes: [], links: [] } :
    p.includes('/api/media') ? [] :
    p.includes('/api/study') ? { known_categories: [] } : {};
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
};
for (const el of [doc.querySelector('#mini'), doc.querySelector('#graph')]) { if (el) { el.getContext = () => null; el.getBoundingClientRect = () => ({ left:0, top:0, width:300, height:200 }); } }
doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){ return { addColorStop(){} }; }, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
window.requestAnimationFrame = () => 0;
// jsdom implements neither of these; real browsers do
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1;
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
await new Promise(r => setTimeout(r, 80));

console.log('\n── it behaves as an overlay, not a third canvas mode ──');
const cruc = doc.querySelector('#crucibleBtn');
const pressed = (sel) => doc.querySelector(sel)?.getAttribute('aria-pressed');
ck('Write starts pressed', pressed('[data-view="write"]') === 'true');
ck('no close button inside Crucible', !doc.querySelector('#svClose'));
cruc.onclick();
await new Promise(r => setTimeout(r, 20));
ck('Crucible opens', studyState.open === true);
ck('Crucible button shows pressed', pressed('#crucibleBtn') === 'true');
ck('Write stays pressed underneath', pressed('[data-view="write"]') === 'true',
   `write=${pressed('[data-view="write"]')}`);
// Tab semantics, not a toggle: clicking Crucible again keeps you there, and
// Tephra is how you come back. The X was removed for exactly this reason.
cruc.onclick();
await new Promise(r => setTimeout(r, 20));
ck('clicking Crucible again keeps it open', studyState.open === true);
doc.querySelector('#tephraBtn').onclick();
await new Promise(r => setTimeout(r, 20));
ck('Tephra returns to the notes', studyState.open === false && pressed('#tephraBtn') === 'true');

console.log('\n── switching canvas mode closes Crucible ──');
cruc.onclick(); await new Promise(r => setTimeout(r, 20));
doc.querySelector('[data-view="graph"]').onclick();
await new Promise(r => setTimeout(r, 20));
ck('Graph closes Crucible', studyState.open === false);
ck('Graph now pressed', pressed('[data-view="graph"]') === 'true');

console.log('\n── Escape closes only the topmost layer ──');
cruc.onclick(); await new Promise(r => setTimeout(r, 20));
const esc = () => window.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'Escape', metaKey: false, ctrlKey: false, altKey: false }));
esc(); await new Promise(r => setTimeout(r, 20));
ck('first Escape closes Crucible', studyState.open === false);
ck('and leaves Graph alone', pressed('[data-view="graph"]') === 'true',
   `graph=${pressed('[data-view="graph"]')}`);
esc(); await new Promise(r => setTimeout(r, 20));
ck('second Escape returns to Write', pressed('[data-view="write"]') === 'true');

console.log('\n── the ⌥D shortcut still works ──');
window.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'd', altKey: true, metaKey: false, ctrlKey: false, preventDefault(){} }));
await new Promise(r => setTimeout(r, 20));
ck('⌥D toggles Crucible', studyState.open === true);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
