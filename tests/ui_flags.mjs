import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = '/home/claude/tephra/app/static';
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// shared fake server so both halves see the same flag state
const flagged = new Set();
const QS = { icmp: ['icmp:aa', 'icmp:bb', 'icmp:cc'], dns: ['dns:aa'] };
const noteMeta = { icmp: { title: 'ICMP', tags: ['study'] }, dns: { title: 'DNS', tags: ['study'] } };
const flagsFor = (slug) => [...flagged].filter((q) => q.rsplit === undefined && q.split(':')[0] === slug).length;
const opened = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); let b = {};
  if (p.includes('/api/theme')) b = {};
  else if (p.includes('/api/study/flag')) { const { qid, flagged: f } = JSON.parse(o.body); f ? flagged.add(qid) : flagged.delete(qid); b = { flagged: [...flagged] }; }
  else if (p.includes('/api/study/quiz')) {
    const sp = new URLSearchParams(p.split('?')[1] || '');
    let pool = Object.entries(QS).flatMap(([s, ids]) => ids.map((id) => ({ id, slug: s })));
    if (sp.get('slug')) pool = pool.filter((q) => q.slug === sp.get('slug'));
    if (sp.get('only_flagged') === 'true') pool = pool.filter((q) => flagged.has(q.id));
    b = { pool: pool.length, questions: pool.slice(0, +sp.get('n') || 12).map((q) => ({
      id: q.id, slug: q.slug, title: noteMeta[q.slug].title, category: 'Net',
      question: 'Q ' + q.id, options: ['a', 'b'], answer: 0, why: '',
      stats: { seen: 0, right: 0 }, flagged: flagged.has(q.id) })) };
  }
  else if (p.includes('/api/study')) b = {
    items: Object.keys(QS).map((s) => ({ slug: s, title: noteMeta[s].title, category: 'Net',
      source: 'import', questions: QS[s].length, question: 'q?', needs_review: false,
      flags: QS[s].filter((id) => flagged.has(id)).length })),
    categories: [{ category: 'Net', topics: 2, questions: 4 }], known_categories: ['Net'],
    progress: { answered: 0, correct: 0, flagged: flagged.size },
    settings: { quiz_count: 12 }, max_quiz: 200,
    totals: { topics: 2, questions: 4, needs_review: 0 } };
  else if (p.includes('/api/vault/info')) b = { vault: '/v', files_on_disk: 2, indexed: 2, study_items: 2 };
  else if (/\/api\/notes\/[\w-]+$/.test(p)) { const sl = p.split('/').pop();
    const fq = QS[sl].filter((id) => flagged.has(id));
    b = { slug: sl, title: noteMeta[sl].title, body: '', tags: noteMeta[sl].tags, meta: {},
      html: '<p>x</p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 1,
      updated: '2026-07-29T00:00:00Z', flags: fq.length,
      flagged_questions: fq.map((id) => ({ id, question: 'Q ' + id })) }; }
  else if (p.includes('/api/notes')) b = Object.keys(QS).map((s) => ({
    slug: s, title: noteMeta[s].title, tags: noteMeta[s].tags, updated: '2026-07-29T00:00:00Z',
    backlinks: 0, links_out: 0, size: 10, kind: 'study',
    flags: QS[s].filter((id) => flagged.has(id)).length }));
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
  return { ok: true, status: 200, json: async () => b, text: async () => JSON.stringify(b) };
};
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false };
window.__tephraGraphInternals = { createSim: () => ({ running: () => false, tick() {}, nodes: [] }), W: 1000, H: 700 };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1; window.requestAnimationFrame = () => 0;
for (const id of ['#mini', '#graph']) { const e = doc.querySelector(id); if (e) { e.getContext = () => null; e.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 200 }); } }
doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){return{addColorStop(){}}}, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });

window.eval(fs.readFileSync(`${ROOT}/graph.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));
await new Promise(r => setTimeout(r, 100));

const marks = () => [...doc.querySelectorAll('#noteList .flagmark')].length;
const S = () => doc.querySelector('#studyview');

console.log('── nothing flagged yet ──');
ck('no marks in the sidebar', marks() === 0);
ck('no flag chip on the note', !doc.querySelector('#flagChip button'));

console.log('\n── flag a question inside Crucible ──');
doc.querySelector('#crucibleBtn').onclick();
await new Promise(r => setTimeout(r, 40));
doc.querySelector('.sv-modes button[data-mode="quiz"]').onclick();
await new Promise(r => setTimeout(r, 30));
S().querySelector('.sv-btn.primary').onclick();
await new Promise(r => setTimeout(r, 40));
const flagBtn = () => [...S().querySelectorAll('.sv-flagbtn')].find(b => /Flag/i.test(b.textContent));
ck('quiz running with a flag control', !!flagBtn(), flagBtn()?.textContent);
await flagBtn().onclick();
await new Promise(r => setTimeout(r, 60));
ck('question is flagged server-side', flagged.size === 1, [...flagged].join(','));
ck('button reflects it', flagBtn().textContent.includes('Flagged'));
ck('an "open note" link appears next to it',
   [...S().querySelectorAll('.sv-flagbtn')].some(b => b.textContent.includes('open note')));

console.log('\n── it propagates to Tephra without a manual refresh ──');
ck('sidebar now shows a flag mark', marks() === 1, `${marks()} marks`);
const marked = [...doc.querySelectorAll('#noteList .node')].find(n => n.querySelector('.flagmark'));
ck('on the right note', marked.dataset.slug === 'icmp', marked.dataset.slug);
ck('tooltip explains it', marked.title.includes('1 flagged question'), marked.title.split('\n').pop());

console.log('\n── the flag chip on the note links back ──');
doc.querySelector('#tephraBtn').onclick();
await new Promise(r => setTimeout(r, 30));
await window.tephraOpenNote('icmp');
await new Promise(r => setTimeout(r, 40));
const chip = doc.querySelector('#flagChip button');
ck('chip present on the flagged note', !!chip, chip?.textContent.trim());
ck('shows the count', chip.textContent.includes('1 flagged'));
ck('lists the questions in its tooltip', chip.title.includes('Q icmp:'), chip.title.split('\n')[0]);
chip.onclick();
await new Promise(r => setTimeout(r, 80));
ck('drills straight into that note\u2019s flagged questions',
   window.tephraStudy.isOpen() && !!S().querySelector('.sv-quiz-q'));
ck('exactly the one flagged question', S().querySelector('.sv-quiz-meta').textContent.includes('1 of 1'),
   S().querySelector('.sv-quiz-meta').textContent.trim().slice(0, 12));

console.log('\n── crucible cards carry the mark too ──');
doc.querySelector('.sv-modes button[data-mode="browse"]').onclick();
await new Promise(r => setTimeout(r, 40));
const cardFlags = [...S().querySelectorAll('.sv-card .sv-flagged')];
ck('flagged topic marked on its card', cardFlags.length === 1, cardFlags.map(c => c.textContent.trim()).join(','));

console.log('\n── sorting by flags ──');
doc.querySelector('#tephraBtn').onclick();
await new Promise(r => setTimeout(r, 20));
const sel = doc.querySelector('#noteSort');
ck('"Flagged first" offered', [...sel.options].some(o => o.value === 'flags'));
QS.dns.forEach(id => flagged.add(id));
await window.tephraRefreshFlags();
sel.value = 'flags'; sel.onchange({ target: sel });
await new Promise(r => setTimeout(r, 20));
const order = [...doc.querySelectorAll('#noteList .node')].map(n => n.dataset.slug);
ck('flagged notes rise to the top', order[0] === 'icmp' || order[0] === 'dns', order.join(','));
ck('both notes marked now', marks() === 2, `${marks()} marks`);

console.log('\n── unflagging clears the indicator ──');
[...flagged].forEach(q => flagged.delete(q));
await window.tephraRefreshFlags();
await new Promise(r => setTimeout(r, 20));
ck('marks gone', marks() === 0);
ck('chip gone', !doc.querySelector('#flagChip button'));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
