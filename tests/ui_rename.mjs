import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = '/home/claude/tephra/app/static';
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

let vaultPath = '/Users/dylan/Documents/Tephra';
let recents = [vaultPath, '/Users/dylan/Documents/Tephra-Old'];
let failNext = null;
const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (p.includes('/api/vault/rename')) {
    const name = JSON.parse(o.body).name;
    if (failNext) return { ok: false, status: 409, json: async () => ({ detail: failNext }), text: async () => JSON.stringify({ detail: failNext }) };
    const parent = vaultPath.split('/').slice(0, -1).join('/');
    recents = recents.map(r => (r === vaultPath ? `${parent}/${name}` : r));
    vaultPath = `${parent}/${name}`;
    b = { vault: vaultPath, name, notes: 79, renamed: true };
  }
  else if (p.includes('/api/vault/info')) b = { vault: vaultPath, files_on_disk: 79, indexed: 79, study_items: 62 };
  else if (p.includes('/api/vault/list')) b = { current: vaultPath, suggested_parent: '/Users/dylan/Documents',
    recent: recents.map(r => ({ path: r, exists: true, current: r === vaultPath })) };
  else if (p.includes('/api/theme')) b = {};
  else if (p.includes('/api/repair/last')) b = { changed: 0 };
  else if (/\/api\/notes\/[\w-]+$/.test(p)) b = { slug: 'n', title: 'N', body: '', tags: [], meta: {}, html: '<p></p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 0, updated: '2026-07-30T00:00:00Z', flags: 0 };
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
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
await new Promise(r => setTimeout(r, 120));

doc.querySelector('#vaultBtn').onclick();
await new Promise(r => setTimeout(r, 60));

const renameBtns = () => [...doc.querySelectorAll('.vaultrename')];
console.log('── the control ──');
ck('offered exactly once', renameBtns().length === 1, String(renameBtns().length));
ck('only for the open vault',
   renameBtns()[0].previousElementSibling.classList.contains('current'));
ck('form starts hidden', doc.querySelector('#renameRow').hidden);
renameBtns()[0].onclick({ stopPropagation() {} });
ck('opens the form', !doc.querySelector('#renameRow').hidden);
ck('prefilled with the current name', doc.querySelector('#renameInput').value === 'Tephra',
   doc.querySelector('#renameInput').value);

console.log('\n── renaming ──');
doc.querySelector('#renameInput').value = 'Tephra-Storage';
await doc.querySelector('#renameSave').onclick();
await new Promise(r => setTimeout(r, 60));
const sent = calls.filter(c => c.p.includes('/vault/rename')).pop();
ck('sent just the folder name', JSON.parse(sent.body).name === 'Tephra-Storage');
ck('header updates', doc.querySelector('#crumbTitle').textContent === 'Tephra-Storage',
   doc.querySelector('#crumbTitle').textContent);
ck('form closes', doc.querySelector('#renameRow').hidden);
ck('drawer list refreshed', [...doc.querySelectorAll('.vaultname')].some(n => n.textContent.includes('Tephra-Storage')),
   [...doc.querySelectorAll('.vaultname')].map(n => n.textContent).join(' | '));
ck('old path no longer listed as current',
   ![...doc.querySelectorAll('.vaultpath')].some(n => n.textContent === '/Users/dylan/Documents/Tephra'),
   [...doc.querySelectorAll('.vaultpath')].map(n => n.textContent).join(' | '));
ck('confirmation shown', doc.querySelector('#vaultMsg').textContent.includes('Tephra-Storage'),
   doc.querySelector('#vaultMsg').textContent);

console.log('\n── a rejected rename explains itself ──');
renameBtns()[0].onclick({ stopPropagation() {} });
doc.querySelector('#renameInput').value = 'Taken';
failNext = 'Taken already exists alongside this vault';
await doc.querySelector('#renameSave').onclick();
await new Promise(r => setTimeout(r, 60));
ck('server reason surfaced', doc.querySelector('#vaultMsg').textContent.includes('already exists'),
   doc.querySelector('#vaultMsg').textContent);
ck('form stays open to correct it', !doc.querySelector('#renameRow').hidden);
ck('header unchanged', doc.querySelector('#crumbTitle').textContent === 'Tephra-Storage');
failNext = null;

console.log('\n── empty name is caught before hitting the server ──');
const before = calls.filter(c => c.p.includes('/vault/rename')).length;
doc.querySelector('#renameInput').value = '   ';
await doc.querySelector('#renameSave').onclick();
ck('no request sent', calls.filter(c => c.p.includes('/vault/rename')).length === before);
ck('told to type a name', doc.querySelector('#vaultMsg').textContent.includes('Type a folder name'));

console.log('\n── cancel and escape ──');
doc.querySelector('#renameCancel').onclick();
ck('cancel closes it', doc.querySelector('#renameRow').hidden);
renameBtns()[0].onclick({ stopPropagation() {} });
doc.querySelector('#renameInput').onkeydown({ key: 'Escape', stopPropagation() {} });
ck('escape closes it', doc.querySelector('#renameRow').hidden);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
