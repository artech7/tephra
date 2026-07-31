import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const calls = [];
let saved = 12;
const data = {
  items: [], categories: [
    { category: 'Networking', topics: 4, questions: 26 },
    { category: 'Tiny', topics: 1, questions: 3 }],
  known_categories: ['Networking', 'Tiny'],
  progress: { answered: 0, correct: 0, flagged: 2 },
  settings: { get quiz_count() { return saved; } },
  max_quiz: 200,
  totals: { topics: 5, questions: 29, needs_review: 0 },
};
window.tephraApi = async (p, o = {}) => {
  calls.push({ p, body: o.body });
  if (p === '/study') return JSON.parse(JSON.stringify({ ...data, settings: { quiz_count: saved } }));
  if (p === '/vault/info') return { vault: '/v', files_on_disk: 5, indexed: 5, study_items: 5 };
  if (p === '/study/prefs') { saved = JSON.parse(o.body).quiz_count; return { quiz_count: saved }; }
  if (p.startsWith('/study/quiz')) {
    const n = +new URLSearchParams(p.split('?')[1]).get('n');
    return { pool: 29, questions: Array.from({ length: Math.min(n, 29) }, (_, i) =>
      ({ id: 'q' + i, question: 'Q' + i, options: ['a', 'b'], answer: 0, why: '', slug: 's', title: 'T', category: 'Networking', stats: { seen: 0, right: 0 }, flagged: false })) };
  }
  throw new Error(p);
};
window.tephraToast = () => {}; window.tephraOpenNote = () => {};
window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));

const S = () => doc.querySelector('#studyview');
await window.tephraStudy.open();
doc.querySelector('.sv-modes button[data-mode="quiz"]').onclick();
await new Promise(r => setTimeout(r, 30));

console.log('── the slider ──');
const slider = () => S().querySelector('.sv-slider input[type=range]');
ck('a range slider is present', !!slider());
ck('minimum is 1', slider().min === '1');
ck('maximum is the whole bank', slider().max === '29', `max=${slider().max}`);
ck('starts at the saved value', slider().value === '12', slider().value);
ck('shows what is available', S().querySelector('.sv-slider-avail').textContent.includes('of 29'));
ck('start button reflects the count',
   S().querySelector('.sv-btn.primary').textContent === 'Start · 12',
   S().querySelector('.sv-btn.primary').textContent);

console.log('\n── dragging it ──');
const set = (v) => { const i = slider(); i.value = String(v); i.oninput(); };
set(5);
ck('label updates', S().querySelector('.sv-slider-n').textContent === '5 questions');
ck('buttons update', S().querySelector('.sv-btn.primary').textContent === 'Start · 5');
set(1);
ck('singular at 1', S().querySelector('.sv-slider-n').textContent === '1 question');
set(29);
ck('reads "All" at the ceiling', S().querySelector('.sv-slider-n').textContent === 'All 29 questions');
ck('start says all too', S().querySelector('.sv-btn.primary').textContent === 'Start · all 29');

console.log('\n── it is remembered ──');
await new Promise(r => setTimeout(r, 450));
ck('persisted to the server', calls.some(c => c.p === '/study/prefs'), `saved=${saved}`);
ck('saved the last value', saved === 29, String(saved));
window.tephraStudy.close();
await window.tephraStudy.open();
doc.querySelector('.sv-modes button[data-mode="quiz"]').onclick();
await new Promise(r => setTimeout(r, 30));
ck('reopens at the remembered value', slider().value === '29', slider().value);

console.log('\n── the ceiling follows the category ──');
const cat = (name) => [...doc.querySelectorAll('#svCatList .node')].find(n => n.textContent.includes(name));
cat('Tiny').onclick(); await new Promise(r => setTimeout(r, 20));
doc.querySelector('.sv-modes button[data-mode="quiz"]').onclick();
await new Promise(r => setTimeout(r, 20));
ck('max drops to that category\u2019s pool', slider().max === '3', `max=${slider().max}`);
ck('saved 29 is clamped down, not lost', slider().value === '3', slider().value);
ck('availability text follows', S().querySelector('.sv-slider-avail').textContent.includes('of 3'));

console.log('\n── presets ──');
const chips = [...S().querySelectorAll('.sv-chip')].map(c => c.textContent);
ck('preset chips offered', chips.length > 0, chips.join(','));
ck('no preset exceeds the pool', chips.every(t => t === 'All' || +t <= 3), chips.join(','));
cat('Networking').onclick(); await new Promise(r => setTimeout(r, 20));
doc.querySelector('.sv-modes button[data-mode="quiz"]').onclick();
await new Promise(r => setTimeout(r, 20));
const chips2 = [...S().querySelectorAll('.sv-chip')].map(c => c.textContent);
ck('bigger pool offers more presets', chips2.includes('5') && chips2.includes('20') && chips2.includes('All'), chips2.join(','));
S().querySelectorAll('.sv-chip')[0].onclick();
ck('clicking a preset moves the slider', slider().value === '5', slider().value);

console.log('\n── starting actually uses the value ──');
set(7);
S().querySelector('.sv-btn.primary').onclick();
await new Promise(r => setTimeout(r, 40));
const asked = calls.filter(c => c.p.startsWith('/study/quiz')).pop();
ck('requested 7 questions', asked.p.includes('n=7'), asked.p);
ck('quiz shows 1 of 7', S().querySelector('.sv-quiz-meta')?.textContent.includes('1 of 7'),
   S().querySelector('.sv-quiz-meta')?.textContent.trim().slice(0, 20));

console.log('\n── reopening mid-quiz resumes it (intended) ──');
window.tephraStudy.close(); await window.tephraStudy.open();
await new Promise(r => setTimeout(r, 30));
ck('still on question 1 of 7', S().querySelector('.sv-quiz-meta')?.textContent.includes('1 of 7'));

console.log('\n── changing category abandons it and re-offers the slider ──');
cat('Tiny').onclick(); await new Promise(r => setTimeout(r, 20));
doc.querySelector('.sv-modes button[data-mode="quiz"]').onclick();
await new Promise(r => setTimeout(r, 20));
ck('back to the intro, not the old round', !!S().querySelector('.sv-slider input'));
ck('no stale question showing', !S().querySelector('.sv-quiz-q'));

console.log('\n── empty pool shows a message, not a slider ──');
data.totals.questions = 0; data.categories = [];
window.tephraStudy.close(); await window.tephraStudy.open();
cat('All categories').onclick(); await new Promise(r => setTimeout(r, 20));
doc.querySelector('.sv-modes button[data-mode="quiz"]').onclick();
await new Promise(r => setTimeout(r, 30));
ck('no slider, a message instead',
   !S().querySelector('.sv-slider input') && !!S().querySelector('.sv-warn'),
   S().querySelector('.sv-warn')?.textContent);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
