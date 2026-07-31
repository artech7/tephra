import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const ago = (m) => new Date(Date.now() - m * 60000).toISOString();
let note = {
  slug: 'icmp', title: 'ICMP', body: '', tags: ['study'], html: '<p>x</p>',
  links_out: 0, media: [], backlinks: [], suggestions: [], words: 1,
  updated: new Date().toISOString(), flags: 0,
  meta: { study: 'true', category: 'OSI Model', category_source: 'manual' },
  category_history: [
    { category: 'Log Analysis', at: ago(5), source: 'manual' },
    { category: 'Linux Commands', at: ago(90), source: 'auto' },
    { category: 'Networking Fundamentals', at: ago(3000), source: 'import' },
  ],
};
const toasts = []; const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (p.includes('/study/icmp/category')) {
    const to = JSON.parse(o.body).category, from = note.meta.category;
    note.category_history = [{ category: from, at: new Date().toISOString(), source: note.meta.category_source }, ...note.category_history];
    note.meta = { ...note.meta, category: to, category_source: 'manual' };
    b = { slug: 'icmp', category: to, from, changed: true, history: note.category_history };
  } else if (p.includes('/study/icmp/revert')) {
    const want = JSON.parse(o.body).category;
    const e = note.category_history.find(x => x.category === want) || note.category_history[0];
    const from = note.meta.category;
    note.category_history = [{ category: from, at: new Date().toISOString(), source: note.meta.category_source }, ...note.category_history];
    note.meta = { ...note.meta, category: e.category, category_source: e.source };
    b = { slug: 'icmp', category: e.category, from, restored_source: e.source, history: note.category_history };
  }
  else if (p.includes('/api/theme')) b = {};
  else if (p.includes('/api/repair/last')) b = { changed: 0 };
  else if (p.includes('/api/vault')) b = { vault: '/v/Tephra', recent: [], suggested_parent: '/v' };
  else if (/\/api\/notes\/icmp$/.test(p)) b = JSON.parse(JSON.stringify(note));
  else if (p.includes('/api/notes')) b = [{ slug: 'icmp', title: 'ICMP', tags: ['study'], updated: note.updated, backlinks: 0, links_out: 0, size: 1, kind: 'study', flags: 0 }];
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
  else if (p.includes('/api/study')) b = { known_categories: ['OSI Model', 'Log Analysis', 'Linux Commands', 'Networking Fundamentals', 'DNS & Name Resolution'] };
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
// app.js owns its toast function, so intercepting the global does nothing.
// Read the element instead — that is what actually reaches the user.
const lastToast = () => doc.querySelector('#toast').textContent;
await new Promise(r => setTimeout(r, 130));
await window.tephraOpenNote('icmp');
await new Promise(r => setTimeout(r, 80));

const chip = () => doc.querySelector('#studyChip');
const trail = () => doc.querySelector('#trailChip');
const items = () => [...trail().querySelectorAll('.trail-item .trail-cat')].map(n => n.textContent);

console.log('── the control says what it is ──');
ck('labelled "study group"', chip().textContent.includes('study group'), chip().textContent.trim());
ck('shows who set it', chip().textContent.includes('set by you'), chip().textContent.trim());
ck('current value selected', chip().querySelector('select').value === 'OSI Model');

console.log('\n── the trail ──');
ck('trail visible', !trail().hidden);
ck('newest first', items().join(' | ') === 'Log Analysis | Linux Commands | Networking Fundamentals', items().join(' | '));
ck('counts the entries', trail().textContent.includes('previously (3)'), trail().querySelector('.trail-h').textContent);
ck('shows when', trail().querySelector('.trail-when').textContent.includes('m ago'),
   trail().querySelector('.trail-when').textContent);
ck('says what clicking does',
   trail().querySelector('.trail-item').title.includes('Move it back to Log Analysis'));
ck('warns when the old value was a guess',
   [...trail().querySelectorAll('.trail-item')][1].title.includes('was a guess'),
   [...trail().querySelectorAll('.trail-item')][1].title);

console.log('\n── changing it is announced ──');
const sel = chip().querySelector('select');
sel.value = 'DNS & Name Resolution';
await sel.onchange();
await new Promise(r => setTimeout(r, 80));
ck('names both ends of the move',
   lastToast().includes('Moved from OSI Model to DNS & Name Resolution'), lastToast());
ck('explains the consequence', lastToast().includes('classifier learns'), lastToast());
ck('the departed value joins the trail', items()[0] === 'OSI Model', items().join(' | '));

console.log('\n── reverting ──');
const back = [...trail().querySelectorAll('.trail-item')].find(b => b.textContent.includes('OSI Model'));
await back.onclick();
await new Promise(r => setTimeout(r, 80));
ck('moved back', chip().querySelector('select').value === 'OSI Model',
   chip().querySelector('select').value);
ck('confirmed by name', lastToast().includes('Moved back to OSI Model'), lastToast());

console.log('\n── reverting to a guessed value restores it as a guess ──');
const guessed = [...trail().querySelectorAll('.trail-item')].find(b => b.textContent.includes('Linux Commands'));
await guessed.onclick();
await new Promise(r => setTimeout(r, 80));
ck('toast says the signal was withdrawn',
   lastToast().includes('restored as a guess'), lastToast());
ck('chip shows it as guessed again', chip().textContent.includes('guessed'), chip().textContent.trim());

console.log('\n── the group also shows above the local graph ──');
const gc = doc.querySelector('#graphCrumb');
ck('crumb visible', !gc.hidden);
ck('names the current group', gc.querySelector('.gc-now').textContent === 'Linux Commands',
   gc.querySelector('.gc-now').textContent);
ck('and where it came from', gc.querySelector('.gc-was').textContent.startsWith('was '),
   gc.querySelector('.gc-was').textContent);

console.log('\n── a note with no history shows no trail ──');
note = { ...note, category_history: [], meta: { study: 'true', category: 'OSI Model', category_source: 'import' } };
await window.tephraOpenNote('icmp');
await new Promise(r => setTimeout(r, 80));
ck('trail hidden', trail().hidden);
ck('imported notes are labelled as such', chip().textContent.includes('from the guide'), chip().textContent.trim());

console.log('\n── a non-study note has neither ──');
note = { ...note, meta: {}, category_history: [] };
await window.tephraOpenNote('icmp');
await new Promise(r => setTimeout(r, 80));
ck('offers to make it one', chip().textContent.includes('Make study item'));
ck('no trail', trail().hidden);
ck('no graph crumb', doc.querySelector('#graphCrumb').hidden);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
