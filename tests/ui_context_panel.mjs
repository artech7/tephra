import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const HTML = fs.readFileSync(`${ROOT}/index.html`, 'utf8');
const APP_JS = fs.readFileSync(`${ROOT}/app.js`, 'utf8');

let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// Boots app.js far enough to wire the context-panel toggle -- same stub
// bundle ui_topbar.mjs uses, since app.js's top-level setup touches all of
// these regardless of what a given test actually exercises.
function boot(presetStorage) {
  const dom = new JSDOM(HTML, { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
  const { window } = dom;
  const doc = window.document;
  if (presetStorage) for (const [k, v] of Object.entries(presetStorage)) window.localStorage.setItem(k, v);
  window.tephraStudy = { open: async () => {}, close: () => {}, isOpen: () => false, refresh: async () => {} };
  window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false, select: () => {} };
  window.tephraStats = { open: async () => {}, close: () => {}, isOpen: () => false };
  window.__tephraGraphInternals = { createSim: () => ({ running: () => false, tick() {}, nodes: [] }), W: 1000, H: 700 };
  const notes = [{ slug: 'a', title: 'A', tags: [], updated: new Date().toISOString(), backlinks: 0 }];
  window.fetch = async (u) => {
    const p = String(u);
    const body = p.includes('/api/theme') ? {} :
      p.includes('/api/notes/a') ? { slug: 'a', title: 'A', body: '', tags: [], meta: {}, html: '<p></p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 0, updated: new Date().toISOString() } :
      p.includes('/api/notes') ? notes :
      p.includes('/api/graph') ? { nodes: [], links: [] } :
      p.includes('/api/media') ? [] :
      p.includes('/api/study') ? { known_categories: [] } : {};
    return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
  };
  for (const el of [doc.querySelector('#mini'), doc.querySelector('#graph')]) {
    if (el) { el.getContext = () => null; el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 200 }); }
  }
  doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){ return { addColorStop(){} }; }, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
  window.requestAnimationFrame = () => 0;
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  window.devicePixelRatio = 1;
  window.eval(APP_JS);
  return { window, doc };
}

console.log('── the handle exists on the context panel, not buried in a menu ──');
{
  const { doc } = boot();
  const panel = doc.querySelector('#contextPanel');
  const btn = doc.querySelector('#ctxToggle');
  ck('toggle button exists', !!btn);
  ck('lives inside the context panel, a sibling of the scrolling content',
     btn.parentElement === panel && btn.nextElementSibling.classList.contains('ctx-scroll'));
  ck('starts visible (not collapsed)', !panel.classList.contains('collapsed'));
  ck('starts at full width', doc.documentElement.style.getPropertyValue('--context-w') === '320px');
  ck('tooltip offers to hide it', btn.title.toLowerCase().includes('hide'));
}

console.log('\n── clicking it hides the panel and remembers that ──');
{
  const { window, doc } = boot();
  const panel = doc.querySelector('#contextPanel');
  const btn = doc.querySelector('#ctxToggle');
  btn.onclick();
  ck('panel is marked collapsed', panel.classList.contains('collapsed'));
  ck('grid track collapses to 0', doc.documentElement.style.getPropertyValue('--context-w') === '0px');
  ck('tooltip flips to offer showing it again', btn.title.toLowerCase().includes('show'));
  ck('persisted to localStorage', window.localStorage.getItem('tephra:contextHidden') === '1');

  console.log('\n── clicking it again brings the panel back ──');
  btn.onclick();
  ck('no longer collapsed', !panel.classList.contains('collapsed'));
  ck('grid track restored', doc.documentElement.style.getPropertyValue('--context-w') === '320px');
  ck('tooltip back to offering to hide it', btn.title.toLowerCase().includes('hide'));
  ck('persisted the un-hide too', window.localStorage.getItem('tephra:contextHidden') === '0');
}

console.log('\n── reopening the app with it hidden keeps it hidden ──');
{
  const { doc } = boot({ 'tephra:contextHidden': '1' });
  const panel = doc.querySelector('#contextPanel');
  ck('boots collapsed', panel.classList.contains('collapsed'));
  ck('grid track boots at 0', doc.documentElement.style.getPropertyValue('--context-w') === '0px');
  ck('tooltip boots offering to show it', doc.querySelector('#ctxToggle').title.toLowerCase().includes('show'));
}

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
