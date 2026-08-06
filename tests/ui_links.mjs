import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

let pending = [
  { kind: 'unlinked', term: 'Kerberos', target: 'kerberos', notes: 3, mentions: 5,
    where: [{ slug: 'ldap', title: 'LDAP' }, { slug: 'ad', title: 'Active Directory' }, { slug: 'spn', title: 'SPN' }] },
  { kind: 'emerging', term: 'access control', target: null, notes: 3, mentions: 3,
    where: [{ slug: 'acl', title: 'ACLs' }, { slug: 'perm', title: 'Permissions' }, { slug: 'nfs', title: 'NFS' }] },
];
let dismissed = [];
const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (p.includes('/suggestions/dismissed')) b = dismissed;
  else if (p.includes('/suggestions/dismiss')) {
    const t = JSON.parse(o.body).term;
    pending = pending.filter(x => x.term !== t);
    dismissed = [{ term: t, at: new Date().toISOString(), note: '' }, ...dismissed];
    b = { ok: true };
  }
  else if (p.includes('/suggestions/restore')) {
    const t = JSON.parse(o.body).term;
    dismissed = dismissed.filter(d => d.term !== t);
    pending = [...pending, { kind: 'emerging', term: t, target: null, notes: 3, mentions: 3, where: [] }];
    b = { ok: true };
  }
  else if (p.includes('/suggestions/apply')) {
    const t = JSON.parse(o.body).term;
    pending = pending.filter(x => x.term !== t);
    dismissed = [{ term: t, at: new Date().toISOString(), note: 'applied' }, ...dismissed];
    b = { slug: 's', title: t, notes_updated: 3 };
  }
  else if (p.includes('/api/suggestions')) b = pending;
  else if (p.includes('/api/theme')) b = {};
  else if (p.includes('/api/repair/last')) b = { changed: 0 };
  else if (p.includes('/api/vault')) b = { vault: '/v/Tephra', recent: [], suggested_parent: '/v' };
  else if (/\/api\/notes\/[\w-]+$/.test(p)) b = { slug: 'n', title: 'N', body: '', tags: [], meta: {}, html: '<p></p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 0, updated: '2026-07-30T00:00:00Z', flags: 0, category_history: [] };
  else if (p.includes('/api/notes')) b = [{ slug: 'n', title: 'N', tags: [], updated: '2026-07-30T00:00:00Z', backlinks: 0, links_out: 0, size: 1, kind: 'note', flags: 0 }];
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
window.eval(fs.readFileSync(`${ROOT}/links.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
await new Promise(r => setTimeout(r, 130));

const lastToast = () => doc.querySelector('#toast').textContent;
const cards = () => [...doc.querySelectorAll('#lvList .lv-card')];
const terms = () => cards().map(c => c.querySelector('.lv-term').textContent);

console.log('── the old inline panel is gone ──');
ck('no suggestion box in the note panel', !doc.querySelector('#suggestSect'));
ck('no leftover list element', !doc.querySelector('#suggestList'));

console.log('\n── a tab, with the queue size on it ──');
ck('Links tab exists', !!doc.querySelector('[data-view="links"]'));
ck('badge shows how many wait', doc.querySelector('#linksBadge').textContent === '2',
   doc.querySelector('#linksBadge').textContent);
doc.querySelector('[data-view="links"]').onclick();
await new Promise(r => setTimeout(r, 60));
ck('opens', window.tephraLinks.isOpen() && doc.querySelector('#linksview').classList.contains('on'));
ck('lists everything, not three at a time', terms().length === 2, terms().join(','));
ck('counts both lists', doc.querySelector('#lvStats').textContent.includes('2 TO REVIEW'),
   doc.querySelector('#lvStats').textContent);

console.log('\n── each row says what it would do, and to which notes ──');
const first = cards()[0];
ck('labels an existing page', first.querySelector('.lv-kind').textContent === 'page exists',
   first.querySelector('.lv-kind').textContent);
ck('explains the effect', first.querySelector('.lv-what').textContent.includes('5 plain mentions'),
   first.querySelector('.lv-what').textContent);
const refs = [...first.querySelectorAll('.lv-ref')].map(r => r.textContent);
ck('names the notes involved', refs.join(',') === 'LDAP,Active Directory,SPN', refs.join(','));
ck('a new-page suggestion reads differently',
   cards()[1].querySelector('.lv-what').textContent.includes('no page of its own'),
   cards()[1].querySelector('.lv-what').textContent);
ck('and is labelled differently', cards()[1].querySelector('.lv-kind').textContent === 'no page yet');
first.querySelector('.lv-ref').onclick();
await new Promise(r => setTimeout(r, 30));
ck('clicking a note opens it and leaves the view', !window.tephraLinks.isOpen());

console.log('\n── dismissing sticks ──');
doc.querySelector('[data-view="links"]').onclick();
await new Promise(r => setTimeout(r, 60));
await cards()[1].querySelector('.lv-btn.no').onclick();
await new Promise(r => setTimeout(r, 60));
ck('removed from the queue', terms().join(',') === 'Kerberos', terms().join(','));
ck('confirmed', lastToast().includes("won't be suggested again"), lastToast());
ck('badge drops', doc.querySelector('#linksBadge').textContent === '1');
// the real bug: it came back on the next fetch
window.tephraLinks.close();
doc.querySelector('[data-view="links"]').onclick();
await new Promise(r => setTimeout(r, 60));
ck('STAYS gone after leaving and returning', terms().join(',') === 'Kerberos', terms().join(','));

console.log('\n── dismissed things are reviewable, not lost ──');
doc.querySelector('.lv-tabs button[data-tab="dismissed"]').onclick();
await new Promise(r => setTimeout(r, 30));
ck('listed', terms().join(',') === 'access control', terms().join(','));
ck('labelled as your decision', cards()[0].querySelector('.lv-what').textContent.includes('not a link'));
await cards()[0].querySelector('.lv-btn').onclick();
await new Promise(r => setTimeout(r, 60));
ck('can be brought back', lastToast().includes('back in the review list'), lastToast());
doc.querySelector('.lv-tabs button[data-tab="pending"]').onclick();
await new Promise(r => setTimeout(r, 30));
ck('and returns to the queue', terms().includes('access control'), terms().join(','));

console.log('\n── approving ──');
const kerb = cards().find(c => c.querySelector('.lv-term').textContent === 'Kerberos');
await kerb.querySelector('.lv-btn.yes').onclick();
await new Promise(r => setTimeout(r, 70));
ck('applied and reported', lastToast().includes('Linked “Kerberos” across 3 notes'), lastToast());
ck('gone from the queue', !terms().includes('Kerberos'), terms().join(','));
doc.querySelector('.lv-tabs button[data-tab="dismissed"]').onclick();
await new Promise(r => setTimeout(r, 30));
ck('shows as linked, not dismissed',
   cards()[0].querySelector('.lv-kind').textContent === 'linked',
   cards()[0].querySelector('.lv-kind').textContent);

console.log('\n── a saved edit refreshes the badge without waiting for something else to ──');
// The actual bug report: typing a phrase into notes and saving never updated
// the Links badge until an unrelated action (a vault switch, a full reload)
// happened to also call poll(). Autosave itself has to trigger it.
pending = [];
window.tephraLinks.close();
doc.querySelector('[data-view="links"]').onclick();
await new Promise(r => setTimeout(r, 60));
ck('starts with nothing pending', doc.querySelector('#linksBadge').hidden);
window.tephraLinks.close();

const ta = doc.querySelector('#noteSrc');
ta.value = 'Some newly typed text.';
ta.dispatchEvent(new window.Event('input', { bubbles: true }));
// The save is debounced ~700ms after the last keystroke; the mock's list
// changes *after* the edit, simulating a suggestion that only exists once
// this text is on disk -- so the badge can only be right if flush() itself
// re-polls, not because it happened to poll earlier and this was stale luck.
pending = [{ kind: 'emerging', term: 'newly typed', target: null, notes: 3, mentions: 3, where: [] }];
await new Promise(r => setTimeout(r, 850));
ck('autosave fired', calls.some(c => c.body && JSON.parse(c.body).body === ta.value));
ck('badge updated without any other action in between',
   doc.querySelector('#linksBadge').textContent === '1' && !doc.querySelector('#linksBadge').hidden,
   doc.querySelector('#linksBadge').textContent);

console.log('\n── empty states ──');
pending = []; dismissed = [];
window.tephraLinks.close();
doc.querySelector('[data-view="links"]').onclick();
await new Promise(r => setTimeout(r, 60));
ck('explains when there is nothing', doc.querySelector('.lv-empty').textContent.includes('three or more notes'),
   doc.querySelector('.lv-empty').textContent.slice(0, 40));
ck('badge hidden', doc.querySelector('#linksBadge').hidden);

console.log('\n── opening always lands on the review list ──');
doc.querySelector('.lv-tabs button[data-tab="dismissed"]').onclick();
window.tephraLinks.close();
doc.querySelector('[data-view="links"]').onclick();
await new Promise(r => setTimeout(r, 60));
ck('review tab selected on open',
   doc.querySelector('.lv-tabs button[data-tab="pending"]').getAttribute('aria-pressed') === 'true');

console.log('\n── it lives on the Tephra side ──');
ck('inside the notes pane', doc.querySelector('#sideTephra').contains(doc.querySelector('#linksview')));
ck('not in the topbar', !doc.querySelector('.topbar').contains(doc.querySelector('#linksview')));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
