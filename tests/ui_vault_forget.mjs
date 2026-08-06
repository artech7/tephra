import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const vaultPath = '/Users/dylan/Documents/Tephra';
let recents = [vaultPath, '/Users/dylan/Documents/Tephra-Old', '/Users/dylan/Documents/Scratch'];
const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (p.includes('/api/vault/forget')) {
    const path = JSON.parse(o.body).path;
    if (path === vaultPath) {
      return { ok: false, status: 400, json: async () => ({ detail: 'switch to another vault before removing this one' }),
                text: async () => JSON.stringify({ detail: 'switch to another vault before removing this one' }) };
    }
    recents = recents.filter(r => r !== path);
    b = { path, forgotten: true };
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
  return { ok: !('detail' in b) && b.status !== 400, status: 200, json: async () => b, text: async () => JSON.stringify(b) };
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

const rowFor = (path) => [...doc.querySelectorAll('.vaultrow')].find(r => r.querySelector('.vaultpath').textContent === path);
const forgetBtnAfter = (row) => row.nextElementSibling?.classList.contains('vaultforget') ? row.nextElementSibling : null;

console.log('── the control ──');
ck('offered for a non-current vault', !!forgetBtnAfter(rowFor('/Users/dylan/Documents/Tephra-Old')));
ck('not offered for the open vault', !forgetBtnAfter(rowFor(vaultPath)));
ck('three rows to start', doc.querySelectorAll('.vaultrow').length === 3);

console.log('\n── forgetting one ──');
forgetBtnAfter(rowFor('/Users/dylan/Documents/Tephra-Old')).onclick({ stopPropagation() {} });
await new Promise(r => setTimeout(r, 60));
const sent = calls.filter(c => c.p.includes('/vault/forget')).pop();
ck('sent the right path', JSON.parse(sent.body).path === '/Users/dylan/Documents/Tephra-Old');
ck('row disappears once the list refreshes', !rowFor('/Users/dylan/Documents/Tephra-Old'));
ck('the other non-current vault is untouched', !!rowFor('/Users/dylan/Documents/Scratch'));
ck('open vault still listed', !!rowFor(vaultPath));
ck('toast confirms it', doc.querySelector('#toast').textContent.includes('Tephra-Old'),
   doc.querySelector('#toast').textContent);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
