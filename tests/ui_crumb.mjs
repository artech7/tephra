import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const notes = {
  icmp:   { slug: 'icmp', title: 'ICMP', tags: ['study', 'nf'], meta: { category: 'Networking Fundamentals', study: 'true' } },
  netfun: { slug: 'netfun', title: 'Networking Fundamentals', tags: ['study', 'index'], meta: {} },
  plain:  { slug: 'plain', title: 'Shopping', tags: ['todo', 'home'], meta: {} },
  bare:   { slug: 'bare', title: 'Bare', tags: [], meta: {} },
};
let theme = {};
window.fetch = async (u, o = {}) => {
  const p = String(u); let b = {};
  if (p.includes('/api/theme')) { if (o.method === 'PUT') theme = JSON.parse(o.body); b = theme; }
  else if (p.includes('/api/vault/info')) b = { vault: '/Users/dylan/Documents/Tephra-Storage', files_on_disk: 4, indexed: 4, study_items: 1 };
  else if (p.includes('/api/vault')) b = { vault: '/Users/dylan/Documents/Tephra-Storage', recent: [], suggested_parent: '/x' };
  else if (p.includes('/api/repair/last')) b = { changed: 0 };
  else if (/\/api\/notes\/[\w-]+$/.test(p)) {
    const n = notes[p.split('/').pop()] || notes.icmp;
    b = { ...n, body: '', html: '<p>x</p>', links_out: 0, media: [], backlinks: [],
          suggestions: [], words: 1, updated: '2026-07-30T00:00:00Z', flags: 0 };
  }
  else if (p.includes('/api/notes')) b = Object.values(notes).map(n => ({
    slug: n.slug, title: n.title, tags: n.tags, updated: '2026-07-30T00:00:00Z',
    backlinks: 0, links_out: 0, size: 1, kind: 'note', flags: 0 }));
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

const crumb = () => doc.querySelector('#crumbTitle').textContent;
const dc = () => doc.querySelector('#docCrumb');
const parts = () => [...dc().querySelectorAll('.dc-part')].map(n => n.textContent);

console.log('── the topbar names the vault, not the note ──');
ck('shows the vault folder name', crumb() === 'Tephra-Storage', crumb());
await window.tephraOpenNote('icmp');
await new Promise(r => setTimeout(r, 40));
ck('opening a note does not change it', crumb() === 'Tephra-Storage', crumb());
ck('no note title in the header',
   !doc.querySelector('.topbar').textContent.includes('ICMP'),
   doc.querySelector('.topbar').textContent.trim());
ck('full path in the tooltip',
   doc.querySelector('#vaultCrumb').title.includes('/Users/dylan/Documents/Tephra-Storage'));
ck('clicking it opens the vault drawer', typeof doc.querySelector('#vaultCrumb').onclick === 'function');
ck('window title still names the note', doc.title.startsWith('ICMP —'), doc.title);

console.log('\n── and an autosave must not steal it back ──');
// This is the regression: flush() wrote the note title into the header after
// every save, silently undoing the change on the first keystroke.
doc.querySelector('#noteSrc').value = 'edited';
doc.querySelector('#noteSrc').dispatchEvent(new window.Event('input'));
await new Promise(r => setTimeout(r, 900));
ck('header still names the vault after a save', crumb() === 'Tephra-Storage', crumb());
ck('save actually happened', doc.querySelector('#saveChip').textContent.includes('Saved'),
   doc.querySelector('#saveChip').textContent);
ck('window title still tracks the note', doc.title.includes('—'), doc.title);

console.log('\n── the vault pill is themed ──');
const pill = doc.querySelector('#vaultCrumb');
ck('is a button', pill.tagName === 'BUTTON');
ck('carries an icon', !!pill.querySelector('svg'));
const css = fs.readFileSync(`${ROOT}/style.css`, 'utf8').replace(/\s+/g, '');
ck('uses the accent colour, so it follows the theme',
   /\.vaultpill\{[^}]*rgba\(var\(--acc\)/.test(css));
ck('uses the app display font', /\.vaultpill\{[^}]*var\(--display\)/.test(css));

console.log('\n── the note carries its own context ──');
ck('crumb line is visible', !dc().hidden);
ck('shows the category', parts().join(',') === 'Networking Fundamentals', parts().join(','));
ck('sits above the heading',
   dc().compareDocumentPosition(doc.querySelector('#noteTitle')) & 4);
const catBtn = dc().querySelector('.dc-part');
ck('links to the category index note', !catBtn.disabled && catBtn.title.includes('Open Networking Fundamentals'),
   catBtn.title);
catBtn.onclick();
await new Promise(r => setTimeout(r, 40));
ck('clicking it navigates there', doc.querySelector('#noteTitle').value === 'Networking Fundamentals',
   doc.querySelector('#noteTitle').value);

console.log('\n── notes with no category fall back to tags ──');
await window.tephraOpenNote('plain');
await new Promise(r => setTimeout(r, 40));
ck('shows tags instead', parts().join(',') === '#todo,#home', parts().join(','));
dc().querySelector('.dc-part').onclick();
await new Promise(r => setTimeout(r, 30));
ck('clicking a tag filters the sidebar',
   [...doc.querySelectorAll('#noteList .node .t')].map(n => n.textContent).join(',') === 'Shopping',
   [...doc.querySelectorAll('#noteList .node .t')].map(n => n.textContent).join(','));
doc.querySelector('#tagClear').onclick();

console.log('\n── nothing to say means nothing shown ──');
await window.tephraOpenNote('bare');
await new Promise(r => setTimeout(r, 40));
ck('crumb line hidden entirely', dc().hidden, `hidden=${dc().hidden}`);

console.log('\n── and it lives in the editor, so Crucible never shows it ──');
ck('crumb is inside the notes side',
   doc.querySelector('#sideTephra').contains(dc()));
ck('not inside the Crucible pane',
   !doc.querySelector('#studyview') || !doc.querySelector('#studyview').contains(dc()));
ck('not in the topbar', !doc.querySelector('.topbar').contains(dc()));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
