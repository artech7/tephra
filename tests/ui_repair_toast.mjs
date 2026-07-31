import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = '/home/claude/tephra/app/static';
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

let lastRepair = { changed: 3, created: ['Answer Ping', 'A B C'],
  notes: [{ nested: 2, quiz_links: 4, frontmatter: 1, empty: 0 },
          { nested: 1, quiz_links: 0, frontmatter: 0, empty: 2 },
          { nested: 1, quiz_links: 0, frontmatter: 0, empty: 0 }] };
let served = 0;
window.fetch = async (u, o = {}) => {
  const p = String(u); let b = {};
  if (p.includes('/api/repair/last')) { served++; b = served === 1 ? lastRepair : { changed: 0 }; }
  else if (p.includes('/api/theme')) b = {};
  else if (/\/api\/notes\/[\w-]+$/.test(p)) b = { slug: 'n', title: 'N', body: '', tags: [], meta: {}, html: '<p></p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 0, updated: '2026-07-30T00:00:00Z' };
  else if (p.includes('/api/notes')) b = [{ slug: 'n', title: 'N', tags: [], updated: '2026-07-30T00:00:00Z', backlinks: 0, links_out: 0, size: 1, kind: 'note', flags: 0 }];
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
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
await new Promise(r => setTimeout(r, 120));

const toast = doc.querySelector('#toast');
console.log('── the startup toast ──');
ck('a toast is shown', toast.classList.contains('on'), toast.textContent);
const t = toast.textContent;
ck('says how many notes', t.includes('Cleaned up 3 notes'), t);
ck('names nested links', t.includes('4 nested links'), t);
ck('names quiz text', t.includes('4 links in quiz text'), t);
ck('names headings', t.includes('1 heading'), t);
ck('names empty links', t.includes('2 empty links'), t);
ck('mentions created notes', t.includes('created 2 missing notes'), t);
ck('no internal jargon', !/flatten|frontmatter|unlink/i.test(t), t);

console.log('\n── it is not repeated ──');
ck('asked the server once', served === 1, String(served));
const second = await window.tephraApi('/repair/last');
ck('a reload gets nothing to announce', second.changed === 0);

console.log('\n── singulars read correctly ──');
lastRepair = { changed: 1, created: ['One'], notes: [{ nested: 1, quiz_links: 1, frontmatter: 1, empty: 1 }] };
served = 0;
const msg = window.eval('describeRepair')(lastRepair);
ck('singular note', msg.includes('Cleaned up 1 note —'), msg);
ck('singular link', msg.includes('1 nested link,'), msg);
ck('singular heading', msg.includes('1 heading'), msg);
ck('singular created', msg.includes('created 1 missing note'), msg);

console.log('\n── nothing to report means no toast ──');
const quiet = window.eval('describeRepair')({ changed: 0, created: [], notes: [] });
ck('degrades sanely', typeof quiet === 'string' && quiet.includes('0 notes'), quiet);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
