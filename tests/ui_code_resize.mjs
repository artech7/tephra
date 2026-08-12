import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8401/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// jsdom has no real layout, so an unpatched <pre> reports scrollHeight 0
// regardless of content -- this stands in for "a 1000-line terminal paste"
// and "a normal 3-line snippet" without needing an actual layout engine.
const noteHtml = '<p>before</p>'
  + '<pre id="tall"><code>lots of output</code></pre>'
  + '<pre id="short"><code>three lines</code></pre>'
  + '<p>after</p>';

window.fetch = async (u) => {
  const p = String(u); let b = {};
  if (p.includes('/api/notes')) b = [];
  else if (p.includes('/api/vault/list')) b = { current: '/v', suggested_parent: '/', recent: [{ path: '/v', exists: true, current: true }] };
  else if (p.includes('/api/vault/info')) b = { vault: '/v', files_on_disk: 1, indexed: 1, study_items: 0 };
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
await new Promise(r => setTimeout(r, 50));

console.log('── a rendered block past the cap gets an inline height, a short one is left alone ──');
doc.querySelector('#noteBody').innerHTML = noteHtml;
const tall = doc.querySelector('#tall'), short = doc.querySelector('#short');
Object.defineProperty(tall, 'scrollHeight', { value: 4000, configurable: true });
Object.defineProperty(short, 'scrollHeight', { value: 120, configurable: true });
window.eval('enhanceCodeBlocks()');
ck('tall block capped to the default height', tall.style.height === '200px', tall.style.height);
ck('short block gets no inline height at all', short.style.height === '', JSON.stringify(short.style.height));

console.log('\n── the cap does not fight a size the user dragged past it ──');
// A real drag sets an inline height directly (that's how CSS resize works).
// Re-running the same enhancement pass -- as happens on any other re-render
// -- must not clamp a deliberately-oversized block back down.
tall.style.height = '3000px';
Object.defineProperty(tall, 'scrollHeight', { value: 3000, configurable: true });
window.eval('enhanceCodeBlocks()');
ck('still at the dragged height, not reset to the cap', tall.style.height === '3000px', tall.style.height);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
