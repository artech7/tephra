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
      { name: 'Existing', path: '/Users/dylan/Documents/Existing', is_vault: false },
    ],
  },
};
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (p.includes('/api/vault/browse')) {
    const m = /path=([^&]+)/.exec(p);
    const path = m ? decodeURIComponent(m[1]) : '/Users/dylan/Documents';
    b = dirs[path];
  }
  else if (p.includes('/api/vault/create')) {
    const path = JSON.parse(o.body).path;
    vaultPath = path;
    recents.unshift(path);
    b = { vault: path, notes: 0, created: true };
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

const step = (n) => doc.querySelector(`.wiz-pane[data-n="${n}"]`);
const rows = () => [...doc.querySelectorAll('#wizBrowseList .vaultrow')];

console.log('── opening the wizard ──');
doc.querySelector('#vaultGoCreate').onclick();
await new Promise(r => setTimeout(r, 60));
ck('home hides, wizard shows',
   doc.querySelector('#vaultHome').hidden && !doc.querySelector('#vaultWizard').hidden);
ck('starts on step 1 (location)', !step(1).hidden && step(2).hidden && step(3).hidden);
ck('browses the suggested parent by default',
   doc.querySelector('#wizBrowsePath').textContent === '/Users/dylan/Documents',
   doc.querySelector('#wizBrowsePath').textContent);
ck('lists both entries', rows().length === 2, rows().length);

console.log('\n── step 1 -> 2: picking a location does not open anything ──');
doc.querySelector('#wizNext1').onclick();
await new Promise(r => setTimeout(r, 60));
ck('advances to step 2', step(1).hidden && !step(2).hidden && step(3).hidden);
ck('nothing was opened or created',
   !calls.some(c => c.p.includes('/vault/open') || c.p.includes('/vault/create')));

console.log('\n── step 2: live path preview and collision warning ──');
doc.querySelector('#wizName').value = 'New Vault';
doc.querySelector('#wizName').oninput({ target: doc.querySelector('#wizName') });
ck('preview shows the full path',
   doc.querySelector('#wizPathPreview').textContent === '/Users/dylan/Documents/New Vault',
   doc.querySelector('#wizPathPreview').textContent);
ck('no warning for a name that does not collide',
   !doc.querySelector('#wizPathPreview').classList.contains('warn'));

doc.querySelector('#wizName').value = 'Existing';
doc.querySelector('#wizName').oninput({ target: doc.querySelector('#wizName') });
ck('warns when a folder by that name is already here',
   doc.querySelector('#wizPathPreview').classList.contains('warn') &&
   doc.querySelector('#wizPathPreview').textContent.includes('already exists'),
   doc.querySelector('#wizPathPreview').textContent);

console.log('\n── empty name is caught before advancing ──');
doc.querySelector('#wizName').value = '   ';
doc.querySelector('#wizNext2').onclick();
await new Promise(r => setTimeout(r, 30));
ck('still on step 2', !step(2).hidden && step(3).hidden);
ck('told to type a name', doc.querySelector('#vaultWizMsg').textContent.includes('Type a vault name'));

console.log('\n── step 2 -> 3: confirm ──');
doc.querySelector('#wizName').value = 'New Vault';
doc.querySelector('#wizName').oninput({ target: doc.querySelector('#wizName') });
doc.querySelector('#wizNext2').onclick();
await new Promise(r => setTimeout(r, 30));
ck('advances to step 3', step(1).hidden && step(2).hidden && !step(3).hidden);
ck('shows the full path to confirm',
   doc.querySelector('#wizConfirmPath').textContent === '/Users/dylan/Documents/New Vault',
   doc.querySelector('#wizConfirmPath').textContent);

console.log('\n── back navigation ──');
doc.querySelector('#wizBack3').onclick();
ck('back to step 2', !step(2).hidden);
doc.querySelector('#wizBack2').onclick();
ck('back to step 1', !step(1).hidden);
doc.querySelector('#wizNext1').onclick();
doc.querySelector('#wizName').value = 'New Vault';
doc.querySelector('#wizName').oninput({ target: doc.querySelector('#wizName') });
doc.querySelector('#wizNext2').onclick();
await new Promise(r => setTimeout(r, 30));

console.log('\n── creating ──');
await doc.querySelector('#wizCreateBtn').onclick();
await new Promise(r => setTimeout(r, 60));
const created = calls.filter(c => c.p.includes('/vault/create')).pop();
ck('posted the assembled path', JSON.parse(created.body).path === '/Users/dylan/Documents/New Vault',
   created && JSON.parse(created.body).path);
ck('returns to the Recent Vaults home on success',
   !doc.querySelector('#vaultHome').hidden && doc.querySelector('#vaultWizard').hidden);
ck('toast confirms creation', doc.querySelector('#toast').textContent.includes('Created vault'),
   doc.querySelector('#toast').textContent);

console.log('\n── reopening the drawer always lands on Recent Vaults ──');
doc.querySelector('#vaultGoCreate').onclick();          // leave it mid-wizard
await new Promise(r => setTimeout(r, 30));
ck('wizard is showing, not home', doc.querySelector('#vaultWizard').hidden === false);
doc.querySelector('#vaultBtn').onclick();                // close
doc.querySelector('#vaultBtn').onclick();                // reopen
await new Promise(r => setTimeout(r, 60));
ck('home pane shown, not the abandoned wizard',
   !doc.querySelector('#vaultHome').hidden && doc.querySelector('#vaultWizard').hidden);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
