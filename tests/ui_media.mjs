import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = '/home/claude/tephra/app/static';
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

let media = [
  { name: 'a.png', url: '/media/a.png', kind: 'image', size: 2048, used_by: ['n1'] },
  { name: 'b.png', url: '/media/b.png', kind: 'image', size: 1024, used_by: [] },
  { name: 'c.mp4', url: '/media/c.mp4', kind: 'video', size: 9999, used_by: [] },
  { name: 'd.pdf', url: '/media/d.pdf', kind: 'file',  size: 512,  used_by: [] },
];
let theme = {}; const deleted = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); let b = {};
  if (p.includes('/api/theme')) { if (o.method === 'PUT') theme = JSON.parse(o.body); b = theme; }
  else if (p.includes('/api/media/') && o.method === 'DELETE') {
    const n = decodeURIComponent(p.split('/').pop()); deleted.push(n);
    media = media.filter(m => m.name !== n); b = { ok: true, trashed: n, was_used_by: [] };
  }
  else if (p.includes('/api/media')) b = media;
  else if (/\/api\/notes\/[\w-]+$/.test(p)) b = { slug: 'n1', title: 'N', body: '', tags: [], meta: {}, html: '<p></p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 0, updated: '2026-07-29T00:00:00Z' };
  else if (p.includes('/api/notes')) b = [{ slug: 'n1', title: 'N', tags: [], updated: '2026-07-29T00:00:00Z', backlinks: 0, links_out: 0, size: 1, kind: 'note', flags: 0 }];
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/vault')) b = { vault: '/v', recent: [], suggested_parent: '/v' };
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
await new Promise(r => setTimeout(r, 90));

const groups = () => [...doc.querySelectorAll('.mgroup')];
const heads = () => [...doc.querySelectorAll('.mgroup-h .mlabel')].map(n => n.textContent);
const cells = () => [...doc.querySelectorAll('.mcell')];

console.log('── grouped by type ──');
ck('one section per present type', groups().length === 3, heads().join(','));
ck('ordered images, video, files', heads().join(',') === 'Images,Video,Files', heads().join(','));
ck('counts shown', [...doc.querySelectorAll('.mcount')].map(n => n.textContent).join(',') === '2,1,1');
ck('total still reported', doc.querySelector('#mediaCount').textContent === '4');
ck('all tiles visible while open', cells().length === 4, String(cells().length));

console.log('\n── the dropdown toggles a section ──');
const imgHead = doc.querySelectorAll('.mgroup-h')[0];
ck('starts open', imgHead.classList.contains('open'));
imgHead.onclick();
await new Promise(r => setTimeout(r, 20));
ck('collapses', !doc.querySelectorAll('.mgroup-h')[0].classList.contains('open'));
ck('its tiles are hidden', cells().length === 2, String(cells().length));
ck('other sections unaffected', heads().length === 3);
await new Promise(r => setTimeout(r, 450));
ck('collapse state persisted', theme.media_open && theme.media_open.image === false,
   JSON.stringify(theme.media_open));
doc.querySelectorAll('.mgroup-h')[0].onclick();
await new Promise(r => setTimeout(r, 20));
ck('reopens', cells().length === 4);

console.log('\n── usage badge ──');
const badges = [...doc.querySelectorAll('.mused')];
ck('only the embedded file is badged', badges.length === 1, String(badges.length));
ck('badge names the note', badges[0].title.includes('n1'));

console.log('\n── hover remove is two-step ──');
const rmOf = (name) => cells().find(c => c.querySelector('a').href.includes(name)).querySelector('.mremove');
ck('every tile has a remove control', cells().every(c => !!c.querySelector('.mremove')));
const rm = rmOf('c.mp4');
await rm.onclick({ preventDefault(){}, stopPropagation(){} });
ck('first click only arms', deleted.length === 0 && rm.classList.contains('armed'));
await rm.onclick({ preventDefault(){}, stopPropagation(){} });
await new Promise(r => setTimeout(r, 50));
ck('second click removes', deleted.join(',') === 'c.mp4', deleted.join(','));
ck('tile gone', cells().length === 3);
ck('empty section removed', !heads().includes('Video'), heads().join(','));

console.log('\n── removing a file still in use warns first ──');
const rm2 = rmOf('a.png');
await rm2.onclick({ preventDefault(){}, stopPropagation(){} });
ck('arm message mentions the embed', rm2.title.includes('Still embedded'), rm2.title.slice(0, 40));
ck('not deleted yet', !deleted.includes('a.png'));

console.log('\n── arming times out ──');
await new Promise(r => setTimeout(r, 4200));
ck('disarms itself', !rm2.classList.contains('armed'));

console.log('\n── empty vault ──');
media = [];
await window.tephraReloadList();     // the real refresh path
await new Promise(r => setTimeout(r, 60));
ck('shows a hint, not a blank box',
   doc.querySelector('#mediaGroups').textContent.includes('Nothing attached'),
   doc.querySelector('#mediaGroups').textContent.trim().slice(0, 28));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
