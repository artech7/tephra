import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const notes = [
  { slug: 'alpha', title: 'Alpha note', tags: ['study'], updated: '2026-07-29T00:00:00Z',
    backlinks: 0, links_out: 0, size: 100, kind: 'study', favorite: false },
];
// The note's own quiz, as GET /api/notes/alpha would return it -- one
// existing single-answer question, mirroring what parse_quiz would hand
// back for a hand-written `## Quiz` block already on disk.
let quiz = [
  { id: 'alpha:existing', question: 'Existing question?', options: ['Right', 'Wrong'], answers: [0], why: 'Because.' },
];
let quizPuts = [];
const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); const m = o.method || 'GET';
  calls.push({ p, m, body: o.body });
  let b = {};
  if (p.includes('/api/theme')) b = {};
  else if (/\/api\/notes\/[\w-]+\/quiz$/.test(p) && m === 'PUT') {
    const payload = JSON.parse(o.body);
    // Same acceptance rule as the real save_quiz: drop anything unanswerable
    // rather than persist it broken.
    quiz = payload.items.filter((it) => it.options.length >= 2 && it.answers.length > 0)
      .map((it, i) => ({ id: `alpha:${i}`, ...it }));
    quizPuts.push(payload);
    b = { slug: 'alpha', title: 'Alpha note', body: '(regenerated body)', tags: ['study'],
      favorite: false, meta: {}, quiz };
  } else if (/\/api\/notes\/[\w-]+$/.test(p)) {
    const n = notes.find((x) => x.slug === p.split('/').pop()) || notes[0];
    b = { slug: n.slug, title: n.title, body: '', tags: n.tags, favorite: n.favorite, meta: {},
      html: '<p>prose only</p>', links_out: 0, media: [], backlinks: [], suggestions: [],
      words: 1, updated: n.updated, quiz };
  } else if (p.includes('/api/notes')) b = notes;
  else if (p.includes('/api/duplicates')) b = { pairs: [] };
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
  else if (p.includes('/api/study')) b = { known_categories: [] };
  const clone = JSON.parse(JSON.stringify(b));
  return { ok: true, status: 200, json: async () => clone, text: async () => JSON.stringify(clone) };
};
window.tephraStudy = { open: async () => {}, close: () => {}, isOpen: () => false, refresh: async () => {} };
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false };
window.__tephraGraphInternals = { createSim: () => ({ running: () => false, tick() {}, nodes: [] }), W: 1000, H: 700 };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1; window.requestAnimationFrame = () => 0;
for (const id of ['#mini', '#graph']) { const e = doc.querySelector(id); if (e) { e.getContext = () => null; e.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 200 }); } }
doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){return{addColorStop(){}}}, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/quiz-editor.js`, 'utf8'));
await new Promise((r) => setTimeout(r, 90));

const cards = () => [...doc.querySelectorAll('#quizList .quizitem')];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

console.log('── existing quiz loads into the form ──');
ck('one card for the one existing question', cards().length === 1, cards().length);
ck('question text populated', cards()[0].querySelector('.quizitem-q').value === 'Existing question?');
const firstOpts = () => cards()[0].querySelectorAll('.quizopt-text');
ck('both options populated', firstOpts()[0].value === 'Right' && firstOpts()[1].value === 'Wrong');
const firstChecks = () => cards()[0].querySelectorAll('.quizopt-check');
ck('the marked answer is checked', firstChecks()[0].checked === true && firstChecks()[1].checked === false);
ck('why text populated', cards()[0].querySelector('.quizitem-why').value === 'Because.');

console.log('\n── adding a new question ──');
doc.querySelector('#quizAdd').click();
ck('a second, blank card appears', cards().length === 2);
ck('starts with two empty options', cards()[1].querySelectorAll('.quizopt-text').length === 2);
ck('nothing saved yet -- an empty question is not persisted', quizPuts.length === 0);

const q2 = cards()[1].querySelector('.quizitem-q');
q2.value = 'New question?'; q2.dispatchEvent(new window.Event('input'));
const opts2 = () => cards()[1].querySelectorAll('.quizopt-text');
opts2()[0].value = 'First choice'; opts2()[0].dispatchEvent(new window.Event('input'));
opts2()[1].value = 'Second choice'; opts2()[1].dispatchEvent(new window.Event('input'));
const checks2 = () => cards()[1].querySelectorAll('.quizopt-check');
checks2()[0].checked = true; checks2()[0].onchange();
await wait(750);
ck('saved after the debounce', quizPuts.length === 1, quizPuts.length);
const sent = quizPuts[0].items[1];
ck('question text sent', sent.question === 'New question?', sent.question);
ck('both option texts sent', sent.options.join(',') === 'First choice,Second choice', sent.options);
ck('single answer sent as a one-element list', JSON.stringify(sent.answers) === '[0]', sent.answers);
ck('save chip shows Saved', doc.querySelector('#quizSaveChip').textContent === 'Saved');

console.log('\n── multi-select: checking a second box ──');
checks2()[1].checked = true; checks2()[1].onchange();
await wait(750);
const sent2 = quizPuts[quizPuts.length - 1].items[1];
ck('both boxes are now marked correct', JSON.stringify(sent2.answers.slice().sort()) === '[0,1]', sent2.answers);

console.log('\n── adding and removing options ──');
cards()[1].querySelector('.quizitem-addopt').click();
ck('a third option row appears', cards()[1].querySelectorAll('.quizopt-row').length === 3);
const thirdDel = () => cards()[1].querySelectorAll('.quizopt-del')[2];
ck('removable while above the 2-option floor', !thirdDel().disabled);
thirdDel().click();
ck('back to two options', cards()[1].querySelectorAll('.quizopt-row').length === 2);
const twoOptDel = () => cards()[1].querySelectorAll('.quizopt-del')[0];
ck('removing is disabled at exactly 2 options', twoOptDel().disabled);

console.log('\n── deleting a question needs two clicks ──');
const delBtn = () => cards()[0].querySelector('.quizitem-del');
delBtn().click();
ck('first click only arms it', cards().length === 2 && delBtn().classList.contains('armed'));
ck('nothing sent for an arm click alone', quizPuts.length === 2);
delBtn().click();
await wait(750);
ck('second click removes the card', cards().length === 1);
ck('the remaining card is the one that was second', cards()[0].querySelector('.quizitem-q').value === 'New question?');
ck('deleting triggered a save', quizPuts.length === 3);
ck('the deleted question is not in the payload',
   !quizPuts[quizPuts.length - 1].items.some((it) => it.question === 'Existing question?'));

console.log('\n── a hand-edited markdown quiz re-syncs the form ──');
quiz = [{ id: 'alpha:handwritten', question: 'Hand-written in source mode', options: ['A', 'B'], answers: [1], why: '' }];
window.tephraQuizEdit.render(quiz, 'alpha');
ck('form now shows exactly the hand-written question',
   cards().length === 1 && cards()[0].querySelector('.quizitem-q').value === 'Hand-written in source mode');

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
