import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

let notes = [
  { slug: 'zeta',  title: 'Zeta note',  tags: ['note'],           updated: '2026-07-01T00:00:00Z', backlinks: 0, links_out: 5, size: 4000, kind: 'note',  favorite: false },
  { slug: 'alpha', title: 'Alpha note', tags: ['study', 'nf'],    updated: '2026-07-29T00:00:00Z', backlinks: 9, links_out: 1, size: 100,  kind: 'study', favorite: false },
  { slug: 'mid',   title: 'Middle',     tags: ['study', 'index'], updated: '2026-07-15T00:00:00Z', backlinks: 3, links_out: 12, size: 900, kind: 'index', favorite: false },
];
let theme = {}, deleted = [];
const dupPairs = [
  { a_slug: 'zeta', a_title: 'Zeta note', a_updated: '2026-07-01T00:00:00Z',
    b_slug: 'alpha', b_title: 'Alpha note', b_updated: '2026-07-29T00:00:00Z', similarity: 0.962 },
  // Deliberately not in `notes` -- exists only so the delete test below can
  // exercise a real DELETE round trip without touching the zeta/alpha/mid
  // fixture the rest of this file's narrative (favorites, tag editing, the
  // final "delete everything" pass) depends on staying intact.
  { a_slug: 'dup-x', a_title: 'Scratch dup X', a_updated: '2026-06-01T00:00:00Z',
    b_slug: 'dup-y', b_title: 'Scratch dup Y', b_updated: '2026-06-02T00:00:00Z', similarity: 0.911 },
];
const reconcileReport = {
  scanned: 3,
  changed: [{ title: 'Networking Index', slug: 'networking-index', dead: ['Old Topic'] }],
  removed: [{ title: 'Empty Cat Index', slug: 'empty-cat-index', dead: ['Sole Topic'] }],
  dry_run: false,
};
const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, m: o.method || 'GET', body: o.body });
  let b = {};
  if (p.includes('/api/theme')) { if (o.method === 'PUT') theme = JSON.parse(o.body); b = theme; }
  else if (o.method === 'DELETE') { const sl = p.split('/').pop(); deleted.push(sl); notes = notes.filter(n => n.slug !== sl); b = { ok: true }; }
  else if (/\/api\/notes\/[\w-]+\/favorite$/.test(p)) { const sl = p.split('/').slice(-2)[0];
    const n = notes.find(x => x.slug === sl); n.favorite = !n.favorite; b = { slug: sl, favorite: n.favorite }; }
  else if (/\/api\/notes\/[\w-]+$/.test(p)) { const sl = p.split('/').pop();
    const n = notes.find(x => x.slug === sl) || notes[0];
    if (o.method === 'PUT') { const payload = o.body ? JSON.parse(o.body) : {};
      if (payload.tags) n.tags = payload.tags; }
    b = { slug: n.slug, title: n.title, body: '', tags: n.tags, favorite: n.favorite, meta: {}, html: '<p>x</p>', links_out: n.links_out, media: [], backlinks: [], suggestions: [], words: 1, updated: n.updated }; }
  else if (p.includes('/api/notes')) b = notes;
  else if (p.includes('/api/duplicates')) b = { pairs: dupPairs };
  else if (p.includes('/api/study/import/reconcile')) b = reconcileReport;
  else if (p.includes('/api/audit')) b = { clean: true };
  else if (p.includes('/api/repair')) b = { changed: 0, notes: [] };
  else if (p.includes('/api/reindex')) b = { notes: notes.length };
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
  else if (p.includes('/api/study')) b = { known_categories: [] };
  // Cloned, not returned live: a real fetch response is never the same
  // object the "server" holds, and `b` here can alias straight into `notes`
  // (the /api/notes list branch just assigns it). Without the clone, the
  // client's optimistic update on a note and the mock's own read-then-flip
  // for /favorite touch the identical object and the toggle cancels itself.
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
await new Promise(r => setTimeout(r, 90));

const titles = () => [...doc.querySelectorAll('#noteList .node .t')].map(n => n.textContent);
const sortSel = doc.querySelector('#noteSort');
const setSort = (v) => { sortSel.value = v; sortSel.onchange({ target: sortSel }); };

console.log('── every control app.js wires exists in the markup ──');
// Four separate bugs in this project were a silent string-replace leaving the
// markup without an element the code then wired, throwing on null.
const WIRED = ['#noteSort', '#tagClear', '#tephraBtn', '#crucibleBtn', '#vaultBtn',
               '#vaultClose', '#vaultGoOpen', '#vaultGoCreate', '#vaultOpenBack', '#vaultWizBack',
               '#wizNext1', '#wizNext2', '#wizCreateBtn', '#healthScan', '#repairRun',
               '#themeBtn', '#newNote',
               '#openPalette', '#favBtn', '#dupFilter'];
const absent = WIRED.filter(id => !doc.querySelector(id));
ck('no wired control is missing', absent.length === 0, absent.join(',') || 'all present');

console.log('\n── sorting ──');
ck('sort control exists', !!sortSel);
// Asserting the exact set rather than a count, so adding a sort doesn't
// produce a failure that says nothing about whether sorting works.
ck('all sorts offered', [...sortSel.options].map(o => o.value).join(',') ===
   'updated,title,backlinks,links_out,flags,kind,size',
   [...sortSel.options].map(o => o.value).join(','));
ck('defaults to recently edited', sortSel.value === 'updated');
ck('recent first', titles()[0] === 'Alpha note', titles().join(' | '));
setSort('title');
ck('alphabetical', titles().join(',') === 'Alpha note,Middle,Zeta note', titles().join(','));
setSort('backlinks');
ck('most linked to first', titles()[0] === 'Alpha note' && titles()[2] === 'Zeta note', titles().join(','));
setSort('links_out');
ck('most links out first', titles()[0] === 'Middle', titles().join(','));
setSort('size');
ck('longest first', titles()[0] === 'Zeta note', titles().join(','));
setSort('kind');
ck('grouped by type: index, study, note',
   titles().join(',') === 'Middle,Alpha note,Zeta note', titles().join(','));
ck('trailing number relabels with sort',
   doc.querySelector('#noteList .node').title.includes('sorted by') === false ||
   doc.querySelector('#noteList .node').title.includes('backlinks'));
ck('type shown via dot class', !!doc.querySelector('.node.kind-index') && !!doc.querySelector('.node.kind-study'));

console.log('\n── vault health: scan runs all four checks from one button ──');
doc.querySelector('#healthScan').onclick();
await new Promise((r) => setTimeout(r, 20));
ck('hit the duplicates endpoint', calls.some((c) => c.p.endsWith('/api/duplicates')));
ck('checked with dry_run', calls.some((c) => c.p.includes('/api/study/import/reconcile') && c.p.includes('dry_run=true')));
ck('rebuilt the index', calls.some((c) => c.p.endsWith('/api/reindex') && c.m === 'POST'));
const dupResult = doc.querySelector('#dupResult');
ck('reports the pair count', dupResult.textContent.includes('2'), dupResult.textContent);
const dupList = doc.querySelector('#dupList');
const dupCard = dupList.querySelector('.dup-pair');
ck('renders a card with both titles and the score',
   !!dupCard && dupCard.textContent.includes('Zeta note') && dupCard.textContent.includes('Alpha note')
   && dupCard.textContent.includes('96%'), dupCard && dupCard.textContent);
ck('the more recently edited note of the pair is marked NEWER',
   !!dupCard.querySelector('.dup-note[data-slug="alpha"] .dup-badge')
   && !dupCard.querySelector('.dup-note[data-slug="zeta"] .dup-badge'), dupCard.innerHTML);
const dupLink = [...dupList.querySelectorAll('.dup-title')].find((b) => b.textContent === 'Alpha note');
dupLink.onclick();
await new Promise((r) => setTimeout(r, 20));
ck('clicking a title in the report opens that note', doc.querySelector('#noteTitle').value === 'Alpha note');

console.log('\n── vault health: delete straight from the duplicate list ──');
const scratchDel = dupList.querySelector('.dup-note[data-slug="dup-x"] .dup-del');
scratchDel.onclick({ stopPropagation() {} });
ck('first click only arms it, nothing sent yet', !calls.some((c) => c.m === 'DELETE'));
scratchDel.onclick({ stopPropagation() {} });
await new Promise((r) => setTimeout(r, 20));
ck('second click actually deletes', calls.some((c) => c.m === 'DELETE' && c.p.endsWith('/dup-x')));
ck('the whole pair card is gone, not just the deleted note\'s row',
   dupList.querySelectorAll('.dup-pair').length === 1);
ck('the unrelated zeta/alpha pair is untouched',
   !!dupList.querySelector('.dup-note[data-slug="zeta"]'), dupList.innerHTML);
ck('result count updates to reflect one pair left', dupResult.textContent.includes('1'), dupResult.textContent);
// Reset shared fixture state this test borrowed -- deleted/calls are
// asserted by count (not just presence) further down, for the *next*
// deletion this file does (via the note editor's own Delete chip).
deleted.length = 0;

console.log('\n── vault health: dead references, as a reviewable card list ──');
const reconList = doc.querySelector('#reconcileList');
ck('one card per affected index page, not a bare count', reconList.querySelectorAll('.recon-card').length === 2);
const changedCard = [...reconList.querySelectorAll('.recon-card')].find((c) => c.textContent.includes('Networking Index'));
const removedCard = [...reconList.querySelectorAll('.recon-card')].find((c) => c.textContent.includes('Empty Cat Index'));
ck('a changed page lists the specific dead title', changedCard.textContent.includes('Old Topic'), changedCard.textContent);
ck('...without a REMOVED badge', !changedCard.querySelector('.recon-badge'));
ck('a page dropped entirely is badged REMOVED', !!removedCard.querySelector('.recon-badge'), removedCard.innerHTML);
ck('...and still names what left it empty', removedCard.textContent.includes('Sole Topic'), removedCard.textContent);
ck('Clean-up is enabled now that something was found', !doc.querySelector('#reconcileRun').disabled);
const reconTitle = changedCard.querySelector('.recon-title');
reconTitle.onclick();
await new Promise((r) => setTimeout(r, 20));
ck('clicking a card\'s title opens that page', calls.some((c) => c.p.endsWith('/networking-index')));

doc.querySelector('#reconcileRun').onclick();
await new Promise((r) => setTimeout(r, 20));
ck('clean-up ran for real, no dry_run', calls.some((c) => c.p.endsWith('/api/study/import/reconcile') && c.m === 'POST'));
ck('Clean-up disables again until the next check', doc.querySelector('#reconcileRun').disabled);

console.log('\n── favorites float to the top, under any sort ──');
setSort('updated');
const starBtn = (slug) => doc.querySelector(`#noteList .node[data-slug="${slug}"] .star`);
ck('unfavorited notes show no lit star', ![...doc.querySelectorAll('#noteList .star')].some(s => s.classList.contains('on')));
starBtn('zeta').onclick({ stopPropagation() {} });
await new Promise(r => setTimeout(r, 10));
ck('starring calls the toggle endpoint', calls.some(c => c.p.endsWith('/api/notes/zeta/favorite') && c.m === 'POST'));
ck('zeta jumps to the top despite sorting by recently-edited (it is the oldest)',
   titles()[0] === 'Zeta note', titles().join(','));
ck('its star lights up', starBtn('zeta').classList.contains('on'));
setSort('backlinks');
ck('still pinned first under most-linked-to, where zeta (0 backlinks) would otherwise rank last',
   titles()[0] === 'Zeta note', titles().join(','));
setSort('title');
ck('and under alphabetical, where zeta would otherwise sort last too',
   titles()[0] === 'Zeta note', titles().join(','));
starBtn('zeta').onclick({ stopPropagation() {} });
await new Promise(r => setTimeout(r, 10));
ck('unstarring drops it back into normal order', titles()[0] === 'Alpha note', titles().join(','));
setSort('updated');

console.log('\n── the doc header star mirrors and drives the same state ──');
const favBtn = doc.querySelector('#favBtn');
doc.querySelector('#noteList .node[data-slug="alpha"]').onclick();
await new Promise(r => setTimeout(r, 20));
ck('opening an unfavorited note shows an unlit header star', !favBtn.classList.contains('on'));
favBtn.onclick();
await new Promise(r => setTimeout(r, 10));
ck('clicking it favorites the open note', favBtn.classList.contains('on'));
ck('the sidebar row for the open note lights up too', starBtn('alpha').classList.contains('on'));
ck('alpha is now pinned first', titles()[0] === 'Alpha note', titles().join(','));
starBtn('alpha').onclick({ stopPropagation() {} });
await new Promise(r => setTimeout(r, 10));
ck('unstarring from the sidebar updates the open header star too', !favBtn.classList.contains('on'));

// Back to the note and sort boot left in place, so the assertions further
// down (persisted sort, tag editor's "boot opens zeta" check, etc.) still
// see the state they expect.
doc.querySelector('#noteList .node[data-slug="zeta"]').onclick();
setSort('kind');
await new Promise(r => setTimeout(r, 20));

console.log('\n── the sort choice is remembered ──');
await new Promise(r => setTimeout(r, 450));
ck('written to theme.json', theme.note_sort === 'kind', theme.note_sort);

console.log('\n── tags now filter ──');
const tags = () => [...doc.querySelectorAll('#tagCloud .tag')];
ck('tag chips rendered', tags().length === 4, tags().map(t => t.textContent).join(' '));
const study = tags().find(t => t.textContent === '#study');
study.onclick();
ck('filters to that tag', titles().join(',') === 'Middle,Alpha note', titles().join(','));
ck('count shows the subset', doc.querySelector('#noteCount').textContent === '2 of 3',
   doc.querySelector('#noteCount').textContent);
ck('active chip marked', tags().find(t => t.textContent === '#study').hasAttribute('data-on'));
ck('clear affordance appears', !doc.querySelector('#tagClear').hidden);
tags().find(t => t.textContent === '#study').onclick();
ck('clicking again clears it', titles().length === 3);
tags().find(t => t.textContent === '#nf').onclick();
ck('a different tag filters too', titles().join(',') === 'Alpha note', titles().join(','));
doc.querySelector('#tagClear').onclick();
ck('clear button works', titles().length === 3);
await new Promise(r => setTimeout(r, 450));
ck('tag choice persisted too', 'note_tag' in theme);

console.log('\n── tag editor on a note ──');
const tagChips = () => [...doc.querySelectorAll('#tagRow .tag')];
const chipText = (c) => c.querySelector('span').textContent;
// Boot opens state.notes[0], i.e. zeta (the raw /api/notes order), tagged ['note'].
ck('shows the note\'s current tags on boot',
   tagChips().map(chipText).join(',') === '#note', tagChips().map(chipText).join(','));

doc.querySelector('#noteList .node[data-slug="alpha"]').onclick();
await new Promise((r) => setTimeout(r, 20));
ck('switching notes reloads the tag row',
   tagChips().map(chipText).sort().join(',') === '#nf,#study', tagChips().map(chipText).join(','));
const studyChipEl = tagChips().find((c) => chipText(c) === '#study');
ck('the study tag is locked', studyChipEl.classList.contains('locked') && !studyChipEl.querySelector('.tagx'));
const nfChipEl = tagChips().find((c) => chipText(c) === '#nf');
ck('an ordinary tag is removable', !!nfChipEl.querySelector('.tagx'));

const tagInput = () => doc.querySelector('#tagRow .taginput');
const enter = () => tagInput().dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter' }));
tagInput().value = 'Solar Gear';
enter();
await new Promise((r) => setTimeout(r, 20));
ck('typed tag is normalised (lowercased, spaces to -)',
   tagChips().map(chipText).sort().join(',') === '#nf,#solar-gear,#study',
   tagChips().map(chipText).join(','));
ck('written through to the note', notes.find((n) => n.slug === 'alpha').tags.includes('solar-gear'));

tagInput().value = 'study';
enter();
await new Promise((r) => setTimeout(r, 20));
ck('typing "study" directly is refused',
   tagChips().filter((c) => chipText(c) === '#study').length === 1, tagChips().map(chipText).join(','));

const removeBtn = tagChips().find((c) => chipText(c) === '#solar-gear').querySelector('.tagx');
removeBtn.onclick();
await new Promise((r) => setTimeout(r, 20));
ck('removing a tag drops its chip',
   tagChips().map(chipText).sort().join(',') === '#nf,#study', tagChips().map(chipText).join(','));
ck('and drops from the note on disk', !notes.find((n) => n.slug === 'alpha').tags.includes('solar-gear'));

tagInput().value = 'n';
tagInput().dispatchEvent(new window.Event('input'));
ck('autocomplete suggests existing tags sharing the prefix, minus ones already on the note',
   [...doc.querySelectorAll('.tagsuggest-item')].map((o) => o.textContent).join(',') === '#note',
   [...doc.querySelectorAll('.tagsuggest-item')].map((o) => o.textContent).join(','));

console.log('\n── deleting a note ──');
const delBtn = () => doc.querySelector('#deleteChip button');
ck('delete button present', !!delBtn());
ck('starts unarmed', delBtn().textContent === 'Delete');
delBtn().onclick();
await new Promise(r => setTimeout(r, 10));
ck('first click only arms it', delBtn().textContent.includes('click again') && deleted.length === 0);
ck('armed state styled', delBtn().classList.contains('armed'));
delBtn().onclick();
await new Promise(r => setTimeout(r, 60));
ck('second click deletes', deleted.length === 1, deleted.join(','));
ck('used DELETE', calls.some(c => c.m === 'DELETE'));
ck('list refreshed', titles().length === 2, titles().join(','));
ck('moved to another note', doc.querySelector('#noteTitle').value !== '');

console.log('\n── arming times out rather than staying hot ──');
delBtn().onclick();
ck('armed', delBtn().textContent.includes('click again'));
await new Promise(r => setTimeout(r, 4200));
ck('disarms itself', delBtn().textContent === 'Delete', delBtn().textContent);
ck('nothing extra deleted', deleted.length === 1);

console.log('\n── deleting the last note ──');
delBtn().onclick(); delBtn().onclick();
await new Promise(r => setTimeout(r, 60));
delBtn().onclick(); delBtn().onclick();
await new Promise(r => setTimeout(r, 60));
ck('handles an empty vault', notes.length === 0 && doc.querySelector('#noteBody').textContent.includes('No notes left'),
   doc.querySelector('#noteBody').textContent.slice(0, 30));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
