import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8402/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// Real mermaid.js needs SVGElement.getBBox(), which jsdom doesn't implement,
// and index.html's own <script src="/static/vendor/mermaid.min.js"> tag is
// never executed here anyway (runScripts:'outside-only' -- same reason
// app.js/graph.js below are loaded via window.eval, not the tag). So this
// stubs window.mermaid *before* app.js runs and checks Tephra's own
// integration glue (who calls initialize/run, with what, and when
// enhanceCodeBlocks leaves a diagram alone) rather than mermaid's internals.
const calls = { initialize: [], run: [] };
window.mermaid = {
  initialize: (opts) => calls.initialize.push(opts),
  run: async (opts) => {
    calls.run.push(opts);
    for (const n of opts.nodes) {
      n.setAttribute('data-processed', 'true');
      // Shaped like mermaid's real output (confirmed by actually running it
      // against a real diagram): a viewBox carrying the true natural size,
      // plus its own responsive width="100%" + inline max-width style that
      // enhanceMermaid() is supposed to strip back out again.
      n.innerHTML = '<svg viewBox="0 0 940 300" width="100%" style="max-width: 350px;"></svg>';
    }
  },
};

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
await new Promise((r) => setTimeout(r, 50));

console.log('── mermaid.initialize runs once at load, driven manually rather than on load ──');
ck('initialize called exactly once', calls.initialize.length === 1, calls.initialize.length);
ck('startOnLoad disabled -- rendering happens per note-render, not an automatic document scan',
   calls.initialize[0]?.startOnLoad === false, calls.initialize[0]);

console.log('\n── enhanceMermaid() hands only .mermaid blocks to mermaid.run(), not plain code ──');
const noteHtml = '<p>before</p>'
  + '<pre class="mermaid" id="dia">graph TD\nA --> B</pre>'
  + '<pre id="code"><code>plain code, untouched</code></pre>'
  + '<p>after</p>';
doc.querySelector('#noteBody').innerHTML = noteHtml;
const dia = doc.querySelector('#dia'), code = doc.querySelector('#code');
await window.eval('enhanceMermaid()');
ck('mermaid.run was called once', calls.run.length === 1, calls.run.length);
ck('run was handed exactly the .mermaid node, not the plain code block',
   calls.run[0]?.nodes.length === 1 && calls.run[0].nodes[0] === dia,
   calls.run[0]?.nodes.map((n) => n.id));
ck('the stubbed run marked it processed', dia.getAttribute('data-processed') === 'true', dia.outerHTML);

console.log('\n── mermaid\'s own responsive sizing is stripped, natural size restored from viewBox ──');
const svg = dia.querySelector('svg');
ck('the svg exists', !!svg);
ck('mermaid\'s own inline max-width style is gone -- it always beat our CSS regardless of container width',
   svg.getAttribute('style') === null, svg.getAttribute('style'));
ck('width is set from the viewBox, not left at mermaid\'s responsive 100%',
   svg.getAttribute('width') === '940', svg.getAttribute('width'));
ck('height likewise', svg.getAttribute('height') === '300', svg.getAttribute('height'));

console.log('\n── click-and-drag pans a diagram too big to show at once ──');
const fire = (el, type, opts = {}) => el.dispatchEvent(new window.MouseEvent(type, { bubbles: true, button: 0, ...opts }));
ck('starts unscrolled', dia.scrollLeft === 0 && dia.scrollTop === 0);
fire(dia, 'mousedown', { clientX: 200, clientY: 200 });
fire(doc, 'mousemove', { clientX: 202, clientY: 201 });
ck('a couple px of jitter is not mistaken for a pan (avoids hijacking a plain click)',
   dia.scrollLeft === 0 && dia.scrollTop === 0, [dia.scrollLeft, dia.scrollTop]);
fire(doc, 'mousemove', { clientX: 140, clientY: 170 });
ck('panning engages once the drag clears a small threshold, and marks the diagram',
   dia.classList.contains('panning'), dia.className);
ck('dragging left/up scrolls the view right/down (grabbing the canvas, not the content)',
   dia.scrollLeft === 60 && dia.scrollTop === 30, [dia.scrollLeft, dia.scrollTop]);
fire(doc, 'mouseup', { clientX: 140, clientY: 170 });
ck('stops marking panning once released', !dia.classList.contains('panning'));
ck('the scroll position from the drag sticks', dia.scrollLeft === 60 && dia.scrollTop === 30,
   [dia.scrollLeft, dia.scrollTop]);

console.log('\n── a drag that starts on a resize handle never engages panning ──');
dia.scrollLeft = 0; dia.scrollTop = 0;
const handle = dia.querySelector('.embed-handle.se');
ck('diagram has its resize handles too', !!handle);
fire(handle, 'mousedown', { clientX: 100, clientY: 100 });
fire(doc, 'mousemove', { clientX: 300, clientY: 300 });
ck('scroll position untouched -- the handle drag is a resize, not a pan',
   dia.scrollLeft === 0 && dia.scrollTop === 0, [dia.scrollLeft, dia.scrollTop]);
fire(doc, 'mouseup', { clientX: 300, clientY: 300 });

console.log('\n── enhanceCodeBlocks() skips .mermaid blocks entirely ──');
Object.defineProperty(code, 'scrollHeight', { value: 4000, configurable: true });
Object.defineProperty(dia, 'scrollHeight', { value: 9000, configurable: true });
window.eval('enhanceCodeBlocks()');
ck('the plain code block got the default height cap', code.style.height === '200px', code.style.height);
ck('the mermaid block was never touched by the code-block cap', dia.style.height === '', JSON.stringify(dia.style.height));

console.log('\n── a note with no diagrams never touches mermaid.run again ──');
calls.run.length = 0;
doc.querySelector('#noteBody').innerHTML = '<p>plain prose, no diagrams</p>';
await window.eval('enhanceMermaid()');
ck('run was not called', calls.run.length === 0, calls.run.length);

console.log('\n── an already-processed diagram is not re-handed to run() on a second pass ──');
doc.querySelector('#noteBody').innerHTML = noteHtml;
const dia2 = doc.querySelector('#dia');
dia2.setAttribute('data-processed', 'true');
await window.eval('enhanceMermaid()');
ck('run was not called for a node already marked processed', calls.run.length === 0, calls.run.length);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
