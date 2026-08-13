import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
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
    { slug: 'icmp', label: 'ICMP', kind: 'note', deg: 3, category: 'Networking' },
    { slug: 'networking-fundamentals', label: 'Networking Fundamentals', kind: 'note', deg: 10, category: 'Networking' },
    { slug: 'dns', label: 'DNS', kind: 'note', deg: 2, category: 'DNS' },
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

console.log('\n── stats layout: a vault-shape + Crucible summary, not a drawing ──');
const byCatCalls = [];
const studyCategoryCalls = [];
const bulkCategoryCalls = [];
const BY_CATEGORY = {
  Networking: [
    { slug: 'icmp', title: 'ICMP', tags: [], updated: '2026-01-01T00:00:00+00:00',
      category: 'Networking', category_source: 'manual', study: false },
    { slug: 'networking-fundamentals', title: 'Networking Fundamentals', tags: [],
      updated: '2026-01-02T00:00:00+00:00', category: 'Networking', category_source: '', study: true },
  ],
  '': [
    { slug: 'fb-study-guide', title: 'FB Study Guide', tags: [], updated: '2026-01-03T00:00:00+00:00',
      category: '', category_source: '', study: true },
  ],
  DNS: [
    { slug: 'dns-extra', title: 'DNS Extra', tags: [], updated: '2026-01-04T00:00:00+00:00',
      category: 'DNS', category_source: 'manual', study: false },
  ],
};
window.tephraApi = async (p, opts) => {
  if (p === '/graph') return JSON.parse(JSON.stringify(graph));
  if (p === '/study') return {
    totals: { topics: 7, questions: 20, needs_review: 2 },
    progress: { answered: 10, correct: 8, flagged: 1 },
  };
  if (p.startsWith('/notes/by-category')) {
    const cat = decodeURIComponent(p.split('category=')[1] || '');
    byCatCalls.push(cat);
    return { category: cat, notes: JSON.parse(JSON.stringify(BY_CATEGORY[cat] || [])) };
  }
  if (/^\/study\/[^/]+\/category$/.test(p)) {
    const slug = p.split('/')[2];
    const body = JSON.parse(opts.body);
    studyCategoryCalls.push({ slug, category: body.category });
    for (const k of Object.keys(BY_CATEGORY)) BY_CATEGORY[k] = BY_CATEGORY[k].filter((n) => n.slug !== slug);
    return { slug, category: body.category, changed: true };
  }
  if (p === '/notes/category/bulk') {
    const body = JSON.parse(opts.body);
    bulkCategoryCalls.push(body);
    for (const k of Object.keys(BY_CATEGORY)) BY_CATEGORY[k] = BY_CATEGORY[k].filter((n) => !body.slugs.includes(n.slug));
    return { updated: body.slugs, category: body.category };
  }
  throw new Error('unexpected ' + p);
};
layout.value = 'stats'; layout.onchange({ target: layout });
await new Promise(r => setTimeout(r, 20));
ck('graphview marked in stats mode',
   window.document.querySelector('#graphview').classList.contains('gv-statsmode'));
const statsPanel = () => window.document.querySelector('#gvStatsPanel');
ck('vault tile counts real notes, stubs excluded',
   statsPanel().textContent.includes('Notes') &&
   statsPanel().querySelector('.gv-stat-tile b').textContent === '4');
ck('crucible totals came from /study, not /graph',
   statsPanel().textContent.includes('7') && statsPanel().textContent.includes('Topics'));
ck('quiz accuracy computed from progress (8/10)', statsPanel().textContent.includes('80%'));
const mostLinkedRow = [...statsPanel().querySelectorAll('.gv-p-row')]
  .find((r) => r.textContent.includes('FB Study Guide'));
ck('most-linked list surfaces the highest-degree note', !!mostLinkedRow);

layout.value = 'cluster'; layout.onchange({ target: layout });
await new Promise(r => setTimeout(r, 20));
ck('leaving stats clears the mode class',
   !window.document.querySelector('#graphview').classList.contains('gv-statsmode'));

opened = null;
layout.value = 'stats'; layout.onchange({ target: layout });
await new Promise(r => setTimeout(r, 20));
[...statsPanel().querySelectorAll('.gv-p-row')]
  .find((r) => r.textContent.includes('FB Study Guide')).onclick();
ck('clicking a most-linked row opens the note', opened === 'fb-study-guide');

console.log('\n── clicking a category bar drills into a note list, in place ──');
const catBar = () => [...statsPanel().querySelectorAll('.gv-stat-bar-row')]
  .find((r) => r.textContent.includes('Networking'));
ck('category bars are clickable', typeof catBar().onclick === 'function');
catBar().onclick();
await new Promise((r) => setTimeout(r, 30));
ck('fetched notes for that category', byCatCalls.includes('Networking'), byCatCalls);
ck('back link replaces the overview', !!statsPanel().querySelector('.sv-back'));
rows = [...statsPanel().querySelectorAll('.gv-cat-row')];
ck('lists every note in the category', rows.length === 2, rows.map((r) => r.textContent));
ck('a Crucible-enabled note is chipped', [...statsPanel().querySelectorAll('.gv-cat-chip')].length === 1);
ck('a plain (non-Crucible) note is not chipped',
   rows.find((r) => r.textContent.includes('ICMP')).querySelector('.gv-cat-chip') === null);

console.log('\n── bulk-move several selected notes at once ──');
const allBox = () => statsPanel().querySelector('.gv-cat-bulk input[type=checkbox]');
allBox().checked = true;
allBox().onchange();
ck('selecting all checks every row', [...statsPanel().querySelectorAll('.gv-cat-row input[type=checkbox]')]
   .every((b) => b.checked));
const bulkSel = () => statsPanel().querySelector('.gv-cat-bulk select');
bulkSel().value = '__new__';
bulkSel().onchange();
const bulkInput = statsPanel().querySelector('.gv-cat-bulk input.sv-select');
ck('offers "+ New category…" the same way Crucible does', !!bulkInput);
bulkInput.value = 'Archived';
bulkInput.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter' }));
const applyBtn = statsPanel().querySelector('.gv-cat-bulk .sv-btn.primary');
ck('apply is enabled once a target and a selection exist', !applyBtn.disabled);
applyBtn.onclick();
await new Promise((r) => setTimeout(r, 30));
ck('bulk endpoint got both slugs and the typed category',
   bulkCategoryCalls.length === 1 &&
   new Set(bulkCategoryCalls[0].slugs).size === 2 &&
   bulkCategoryCalls[0].category === 'Archived', bulkCategoryCalls);
ck('moved notes disappear from this category’s list',
   statsPanel().textContent.includes('No notes left in this category'), statsPanel().textContent);

console.log('\n── back returns to the overview ──');
statsPanel().querySelector('.sv-back').onclick();
await new Promise((r) => setTimeout(r, 30));
ck('bars are back', statsPanel().querySelectorAll('.gv-stat-bar-row').length > 0);
ck('detail list is gone', !statsPanel().querySelector('.gv-cat-list'));

console.log('\n── per-row recategorize, from the Uncategorised bucket ──');
const uncatBar = () => [...statsPanel().querySelectorAll('.gv-stat-bar-row')]
  .find((r) => r.textContent.includes('Uncategorised'));
uncatBar().onclick();
await new Promise((r) => setTimeout(r, 30));
ck('fetched the empty-category bucket', byCatCalls.includes(''), byCatCalls);
rows = [...statsPanel().querySelectorAll('.gv-cat-row')];
ck('shows the one uncategorised note', rows.length === 1, rows.map((r) => r.textContent));
const rowSel = rows[0].querySelector('select');
const hasDns = [...rowSel.options].some((o) => o.value === 'DNS');
ck('per-row picker offers the vault’s known categories', hasDns, [...rowSel.options].map((o) => o.value));
rowSel.value = 'DNS';
rowSel.onchange();
await new Promise((r) => setTimeout(r, 30));
ck('recategorize call went to the per-note endpoint',
   studyCategoryCalls.some((c) => c.slug === 'fb-study-guide' && c.category === 'DNS'), studyCategoryCalls);
ck('the note drops out of the list it was just moved from',
   statsPanel().textContent.includes('No notes left in this category'), statsPanel().textContent);

console.log('\n── "Clear category" is a real, unambiguous choice ──');
statsPanel().querySelector('.sv-back').onclick();
await new Promise((r) => setTimeout(r, 30));
const dnsBar = () => [...statsPanel().querySelectorAll('.gv-stat-bar-row')]
  .find((r) => r.textContent.includes('DNS'));
dnsBar().onclick();
await new Promise((r) => setTimeout(r, 30));
rows = [...statsPanel().querySelectorAll('.gv-cat-row')];
ck('shows the DNS note', rows.length === 1, rows.map((r) => r.textContent));
const dnsRowSel = rows[0].querySelector('select');
const rowOptVals = [...dnsRowSel.options].map((o) => o.value);
ck('offers a real "Clear category" option', rowOptVals.includes(''), rowOptVals);
ck('but never the literal string "Uncategorised" as a settable value',
   ![...dnsRowSel.options].some((o) => o.textContent === 'Uncategorised'), rowOptVals);
const dnsBulkSel = () => statsPanel().querySelector('.gv-cat-bulk select');
const bulkOptVals = [...dnsBulkSel().options].map((o) => o.value);
ck('bulk toolbar offers "Clear category" too, distinct from its placeholder',
   bulkOptVals.includes('__clear__') && bulkOptVals.includes('__unset__'), bulkOptVals);
ck('and not the literal "Uncategorised" there either',
   ![...dnsBulkSel().options].some((o) => o.textContent === 'Uncategorised'), bulkOptVals);

statsPanel().querySelector('.gv-cat-row input[type=checkbox]').click();
dnsBulkSel().value = '__clear__';
dnsBulkSel().onchange();
const dnsApplyBtn = statsPanel().querySelector('.gv-cat-bulk .sv-btn.primary');
ck('apply enables on a Clear-category choice, same as a real target', !dnsApplyBtn.disabled);
dnsApplyBtn.onclick();
await new Promise((r) => setTimeout(r, 30));
ck('bulk endpoint got an empty category, meaning clear',
   bulkCategoryCalls.some((c) => c.slugs.includes('dns-extra') && c.category === ''), bulkCategoryCalls);
ck('the cleared note leaves the DNS list',
   statsPanel().textContent.includes('No notes left in this category'), statsPanel().textContent);

console.log('\n── survives a missing 2d context (never assumes canvas) ──');
ck('no crash with getContext() === null', true);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
