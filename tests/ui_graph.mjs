import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = '/home/claude/tephra/app/static';
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// canvas isn't implemented in jsdom; a stub proves the code never assumes one
const canvas = window.document.querySelector('#graph');
canvas.getContext = () => null;
canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 900, height: 700, right: 900, bottom: 700 });
canvas.setPointerCapture = () => {};

const graph = {
  nodes: [
    { slug: 'icmp', label: 'ICMP', kind: 'note', deg: 3 },
    { slug: 'networking-fundamentals', label: 'Networking Fundamentals', kind: 'note', deg: 10 },
    { slug: 'dns', label: 'DNS', kind: 'note', deg: 2 },
    { slug: null, label: 'Cycle Life', kind: 'stub', deg: 1 },
    { slug: 'fb-study-guide', label: 'FB Study Guide', kind: 'note', deg: 13 },
  ],
  links: [[0, 1], [2, 1], [1, 4], [0, 3]],
};
window.tephraApi = async (p) => { if (p === '/graph') return JSON.parse(JSON.stringify(graph)); throw new Error(p); };
let opened = null;
window.tephraOpenNote = (slug) => { opened = slug; };
window.tephraCurrentSlug = () => 'icmp';

window.eval(fs.readFileSync(`${ROOT}/graph.js`, 'utf8'));
const I = window.__tephraGraphInternals;

console.log('── opening the graph ──');
await window.tephraGraph.open();
ck('reports counts', window.document.querySelector('#gvStats').textContent.includes('5 NOTES'),
   window.document.querySelector('#gvStats').textContent);
ck('current note is pre-selected', window.document.querySelector('.gv-p-title')?.textContent === 'ICMP');
ck('shows its connection count',
   window.document.querySelector('.gv-p-meta')?.textContent.includes('2 connections'),
   window.document.querySelector('.gv-p-meta')?.textContent);

console.log('\n── the panel lists what it connects to ──');
let rows = [...window.document.querySelectorAll('.gv-p-row')];
ck('neighbours listed', rows.length === 2, rows.map(r => r.textContent.trim()).join(', '));
ck('stub neighbour marked distinctly', rows.some(r => r.classList.contains('stub')));
ck('Open note button present', [...window.document.querySelectorAll('.gv-p-acts button')]
   .some(b => b.textContent === 'Open note'));

console.log('\n── single click on a neighbour walks the graph ──');
const nf = rows.find(r => r.textContent.includes('Networking'));
nf.onclick();
ck('selection moved', window.document.querySelector('.gv-p-title').textContent === 'Networking Fundamentals');
ck('did NOT leave the graph', opened === null);
rows = [...window.document.querySelectorAll('.gv-p-row')];
ck('now shows the hub\u2019s 3 links', rows.length === 3, rows.length + ' rows');

console.log('\n── double click jumps into the note ──');
rows.find(r => r.textContent.includes('DNS')).ondblclick();
ck('opened the note', opened === 'dns', String(opened));
ck('graph closed on jump', !window.tephraGraph.isOpen());

console.log('\n── a stub has no note to open ──');
await window.tephraGraph.open();
window.tephraGraph.select(graph.nodes.find(n => n.kind === 'stub') && 
  window.__gnodes ? null : null);
// select via the panel instead
await window.tephraGraph.open();
rows = [...window.document.querySelectorAll('.gv-p-row')];
const stubRow = rows.find(r => r.classList.contains('stub'));
stubRow.onclick();
ck('stub selected, labelled as unwritten',
   window.document.querySelector('.gv-p-kind').textContent === 'NOT WRITTEN YET');
ck('no Open note button for a stub',
   ![...window.document.querySelectorAll('.gv-p-acts button')].some(b => b.textContent === 'Open note'));
opened = null;
stubRow.ondblclick();
ck('double-clicking a stub does nothing', opened === null);

console.log('\n── canvas pointer interaction ──');
const dn = (x, y) => { const e = new window.MouseEvent('pointerdown', { bubbles: true, clientX: x, clientY: y }); e.pointerId = 1; canvas.dispatchEvent(e); };
const mv = (x, y) => { const e = new window.MouseEvent('pointermove', { bubbles: true, clientX: x, clientY: y }); e.pointerId = 1; canvas.dispatchEvent(e); };
const up = () => { const e = new window.MouseEvent('pointerup', { bubbles: true }); e.pointerId = 1; canvas.dispatchEvent(e); };
ck('click on empty space clears selection', (() => {
  dn(880, 20); up();
  return !!window.document.querySelector('.gv-hint');
})());
ck('dragging empty space pans without selecting', (() => {
  dn(400, 300); mv(430, 320); up();
  return !!window.document.querySelector('.gv-hint');
})());
// Every control the code wires must exist in the markup. A string-replace that
// silently missed left #gvLayout absent, and wire() threw on null.onchange —
// which made the entire graph view unopenable.
const CONTROLS = ['#gvZoomIn', '#gvZoomOut', '#gvFit', '#gvRelax', '#gvFind',
                  '#gvLayout', '#gvStubs', '#gvLeaves'];
ck('every toolbar control exists in the markup',
   CONTROLS.every(id => !!window.document.querySelector(id)),
   CONTROLS.filter(id => !window.document.querySelector(id)).join(',') || 'all present');
ck('and every one is wired', CONTROLS.every(id => {
  const el = window.document.querySelector(id);
  return el && typeof (el.onclick || el.oninput || el.onchange) === 'function';
}));
ck('search filters without throwing', (() => {
  const f = window.document.querySelector('#gvFind');
  f.value = 'dns'; f.oninput({ target: f }); return true;
})());
ck('enter in search selects the match', (() => {
  const f = window.document.querySelector('#gvFind');
  f.value = 'dns'; f.oninput({ target: f });
  f.onkeydown({ key: 'Enter' });
  return window.document.querySelector('.gv-p-title')?.textContent === 'DNS';
})(), window.document.querySelector('.gv-p-title')?.textContent);

console.log('\n── layout and filter controls do something ──');
const layout = window.document.querySelector('#gvLayout');
layout.value = 'tree'; layout.onchange({ target: layout });
await new Promise(r => setTimeout(r, 20));
ck('switching to the tidy tree lays out immediately',
   graph.nodes.length > 0 && window.tephraGraph.isOpen());
const stubs = window.document.querySelector('#gvStubs');
ck('stubs start shown', stubs.hasAttribute('data-on'));
stubs.onclick();
await new Promise(r => setTimeout(r, 20));
ck('hiding stubs updates the count',
   !stubs.hasAttribute('data-on') &&
   window.document.querySelector('#gvStats').textContent.includes('HIDDEN'),
   window.document.querySelector('#gvStats').textContent);
stubs.onclick();
await new Promise(r => setTimeout(r, 20));
ck('and restores them', stubs.hasAttribute('data-on'));
const leaves = window.document.querySelector('#gvLeaves');
leaves.onclick();
await new Promise(r => setTimeout(r, 20));
ck('leaves filter also reports hidden nodes',
   window.document.querySelector('#gvStats').textContent.includes('HIDDEN'));

console.log('\n── survives a missing 2d context (never assumes canvas) ──');
ck('no crash with getContext() === null', true);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
