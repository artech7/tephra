import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

let vaultPath = '/Users/dylan/Documents/Tephra';
const recents = [vaultPath];
const calls = [];
const dirs = {
  '/Users/dylan/Documents': {
    path: '/Users/dylan/Documents', parent: '/Users/dylan',
    entries: [
      { name: 'Tephra', path: '/Users/dylan/Documents/Tephra', is_vault: true },
      { name: 'Photos', path: '/Users/dylan/Documents/Photos', is_vault: false },
    ],
  },
  '/Users/dylan/Documents/Photos': {
    path: '/Users/dylan/Documents/Photos', parent: '/Users/dylan/Documents',
    entries: [
      { name: '2026', path: '/Users/dylan/Documents/Photos/2026', is_vault: false },
    ],
  },
};
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (p.includes('/api/vault/browse')) {
    const m = /path=([^&]+)/.exec(p);
    const path = m ? decodeURIComponent(m[1]) : '/Users/dylan/Documents';
    if (path === '/Users/dylan/Documents/Locked') {
      return { ok: false, status: 403, json: async () => ({ detail: 'outside the browse root' }),
                text: async () => JSON.stringify({ detail: 'outside the browse root' }) };
    }
    b = dirs[path];
  }
  else if (p.includes('/api/vault/open')) {
    const path = JSON.parse(o.body).path;
    vaultPath = path;
    b = { vault: path, notes: 3, created: false };
  }
  else if (p.includes('/api/vault/info')) b = { vault: vaultPath, files_on_disk: 3, indexed: 3, study_items: 0 };
  else if (p.includes('/api/vault/list')) b = { current: vaultPath, suggested_parent: '/Users/dylan/Documents',
    recent: recents.map(r => ({ path: r, exists: true, current: r === vaultPath })) };
  else if (p.includes('/api/theme')) b = {};
  else if (p.includes('/api/repair/last')) b = { changed: 0 };
  else if (/\/api\/notes\/[\w-]+$/.test(p)) b = { slug: 'n', title: 'N', body: '', tags: [], meta: {}, html: '<p></p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 0, updated: '2026-07-30T00:00:00Z', flags: 0 };
  else if (p.includes('/api/notes')) b = [{ slug: 'n', title: 'N', tags: [], updated: '2026-07-30T00:00:00Z', backlinks: 0, links_out: 0, size: 1, kind: 'note', flags: 0 }];
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
  else if (p.includes('/api/study')) b = { known_categories: [] };
  return { ok: !!b, status: b ? 200 : 404, json: async () => b, text: async () => JSON.stringify(b) };
};
window.tephraStudy = { open: async () => {}, close: () => {}, isOpen: () => false, refresh: async () => {} };
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1; window.requestAnimationFrame = () => 0;
for (const id of ['#mini', '#graph']) { const e = doc.querySelector(id); if (e) { e.getContext = () => null; e.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 200 }); } }
doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){return{addColorStop(){}}}, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
window.eval(fs.readFileSync(`${ROOT}/graph.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
await new Promise(r => setTimeout(r, 120));

doc.querySelector('#vaultBtn').onclick();
await new Promise(r => setTimeout(r, 60));

console.log('── opening the browse panel ──');
ck('starts hidden', doc.querySelector('#vaultBrowse').hidden);
doc.querySelector('#vaultBrowseToggle').onclick();
await new Promise(r => setTimeout(r, 60));
ck('toggled open', !doc.querySelector('#vaultBrowse').hidden);
ck('defaults to suggested_parent (no path param)',
   calls.some(c => c.p === '/api/vault/browse'), calls.map(c => c.p).join(' | '));
ck('shows the listed path', doc.querySelector('#vaultBrowsePath').textContent === '/Users/dylan/Documents',
   doc.querySelector('#vaultBrowsePath').textContent);

const rows = () => [...doc.querySelectorAll('#vaultBrowseList .vaultrow')];
console.log('\n── listing ──');
ck('lists both entries', rows().length === 2, rows().length);
ck('flags the vault entry', rows().some(r => r.querySelector('.vaultname').textContent.includes('vault')));
ck('does not flag the plain folder',
   rows().find(r => r.querySelector('.vaultpath').textContent.endsWith('/Photos'))
     .querySelector('.vaultname').textContent === 'Photos');

console.log('\n── descending ──');
rows().find(r => r.querySelector('.vaultpath').textContent.endsWith('/Photos')).onclick();
await new Promise(r => setTimeout(r, 60));
ck('path advances into the subfolder',
   doc.querySelector('#vaultBrowsePath').textContent === '/Users/dylan/Documents/Photos',
   doc.querySelector('#vaultBrowsePath').textContent);
ck('lists the subfolder\'s own entries', rows().length === 1 && rows()[0].querySelector('.vaultname').textContent === '2026');

console.log('\n── going back up ──');
doc.querySelector('#vaultBrowseUp').onclick();
await new Promise(r => setTimeout(r, 60));
ck('back at the parent', doc.querySelector('#vaultBrowsePath').textContent === '/Users/dylan/Documents',
   doc.querySelector('#vaultBrowsePath').textContent);

console.log('\n── opening a vault from the listing ──');
await rows().find(r => r.querySelector('.vaultpath').textContent.endsWith('/Tephra')).onclick();
await new Promise(r => setTimeout(r, 60));
const opened = calls.filter(c => c.p.includes('/vault/open')).pop();
ck('opened via /vault/open', !!opened);
ck('opened the clicked entry\'s path', JSON.parse(opened.body).path === '/Users/dylan/Documents/Tephra');
ck('closes the browse panel on success', doc.querySelector('#vaultBrowse').hidden);

console.log('\n── a containment failure explains itself instead of crashing ──');
doc.querySelector('#vaultBrowseToggle').onclick();       // reopen
await new Promise(r => setTimeout(r, 60));
window.eval("browseAt = { path: '/Users/dylan/Documents/Locked', parent: '/Users/dylan/Documents' };");
await window.eval("renderBrowse('/Users/dylan/Documents/Locked')");
await new Promise(r => setTimeout(r, 60));
ck('shows the server detail rather than throwing',
   doc.querySelector('#vaultBrowseList').textContent.includes('outside the browse root'),
   doc.querySelector('#vaultBrowseList').textContent);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
