import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// Flashcards draw from the same pool /study/quiz feeds multiple-choice mode --
// one card per Q: entry, not one per topic. Two questions in Storage, one in
// Networking, so category switching has something to actually prove.
const allQuestions = [
  { id: 'q1', question: 'Which RAID level has no redundancy?', options: ['RAID 0', 'RAID 1', 'RAID 5'],
    answers: [0], why: 'RAID 0 stripes data with no parity or mirroring.',
    slug: 'raid', title: 'RAID levels', category: 'Storage', stats: { seen: 0, right: 0 }, flagged: false },
  { id: 'q2', question: 'Which RAID level mirrors data?', options: ['RAID 0', 'RAID 1', 'RAID 5'],
    answers: [1], why: 'RAID 1 duplicates every write to a second disk.',
    slug: 'raid', title: 'RAID levels', category: 'Storage', stats: { seen: 0, right: 0 }, flagged: false },
  { id: 'q3', question: 'What does ICMP do?', options: ['Routes packets', 'Reports network errors', 'Encrypts traffic'],
    answers: [1], why: '',
    slug: 'icmp', title: 'ICMP', category: 'Networking', stats: { seen: 0, right: 0 }, flagged: false },
];
const data = {
  items: [
    { slug: 'raid', title: 'RAID levels', category: 'Storage', question: 'About RAID', questions: 2, source: 'manual', confidence: null, needs_review: false, flags: 0 },
    { slug: 'icmp', title: 'ICMP', category: 'Networking', question: 'About ICMP', questions: 1, source: 'manual', confidence: null, needs_review: false, flags: 0 },
  ],
  categories: [{ category: 'Storage', topics: 1, questions: 2 }, { category: 'Networking', topics: 1, questions: 1 },
               { category: 'Empty Cat', topics: 0, questions: 0 }],
  known_categories: ['Storage', 'Networking'],
  progress: { answered: 0, correct: 0, flagged: 0 },
  settings: { quiz_count: 12 }, max_quiz: 200,
  totals: { topics: 2, questions: 3, needs_review: 0 },
};
const calls = [];
window.tephraApi = async (p) => {
  calls.push(p);
  if (p === '/study') return JSON.parse(JSON.stringify(data));
  if (p === '/vault/info') return { vault: '/v', files_on_disk: 2, indexed: 2, study_items: 2 };
  if (p.startsWith('/study/quiz')) {
    const params = new URLSearchParams(p.split('?')[1]);
    const cat = params.get('category');
    const pool = allQuestions.filter((q) => !cat || q.category === cat);
    return { questions: JSON.parse(JSON.stringify(pool)), pool: pool.length };
  }
  if (p === '/study/item/raid') {
    return { slug: 'raid', title: 'RAID levels', category: 'Storage', question: 'About RAID',
             html: '<p>whole note prose</p>', quiz: [], tags: [], updated: '2026-08-12T00:00:00Z' };
  }
  throw new Error(p);
};
window.tephraToast = () => {}; window.tephraOpenNote = () => {};
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
// Real layout doesn't run in jsdom (getBoundingClientRect/scrollHeight stay
// 0), so resize()'s numbers aren't worth asserting on here -- this just
// needs requestAnimationFrame to actually invoke its callback so resize()
// runs at all. Safe to do synchronously in this file specifically because,
// unlike app.js, study.js has no requestAnimationFrame-driven redraw loop
// that would recurse on an immediate callback.
window.requestAnimationFrame = (cb) => cb();
window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));
await new Promise((r) => setTimeout(r, 20));

await window.tephraStudy.open();
doc.querySelector('.sv-modes button[data-mode="cards"]').onclick();
await new Promise((r) => setTimeout(r, 20));

const tilt = () => doc.querySelector('.sv-flash-tilt');
const flip = () => doc.querySelector('.sv-flash-flip');

console.log('── cards come from the quiz pool, not the topic list ──');
ck('fetched /study/quiz for the deck', calls.some((c) => c.startsWith('/study/quiz')), calls);
ck('front shows a QUESTION\'S text, not a topic-level one-liner',
   doc.querySelector('.sv-flash-q')?.textContent === allQuestions[0].question,
   doc.querySelector('.sv-flash-q')?.textContent);
ck('all 3 questions loaded (no category filter yet)', doc.querySelector('.sv-count')?.textContent === '1 / 3',
   doc.querySelector('.sv-count')?.textContent);
ck('hints to click', doc.querySelector('.front .sv-flash-hint')?.textContent === 'click to reveal');
ck('not flipped yet', !flip().classList.contains('flipped'));

console.log('\n── flipping reveals the marked-correct answer and Why -- no extra fetch needed ──');
const callsBeforeFlip = calls.length;
tilt().onclick();
await new Promise((r) => setTimeout(r, 20));
ck('flipped class applied', flip().classList.contains('flipped'));
ck('back shows the CORRECT option, not the topic title',
   doc.querySelector('.sv-flash-title')?.textContent === 'RAID 0',
   doc.querySelector('.sv-flash-title')?.textContent);
ck('the Why explanation is shown',
   doc.querySelector('.sv-why')?.textContent === allQuestions[0].why,
   doc.querySelector('.sv-why')?.textContent);
ck('a link back to the source topic is offered',
   doc.querySelector('.sv-back')?.textContent === 'Read the full topic: RAID levels →');
ck('flipping did not fetch anything -- the answer was already in the card data',
   calls.length === callsBeforeFlip, calls.slice(callsBeforeFlip));

console.log('\n── the "read the full topic" link opens the note in Browse mode ──');
doc.querySelector('.sv-back').onclick({ stopPropagation() {} });
await new Promise((r) => setTimeout(r, 20));
ck('fetched the full topic', calls.includes('/study/item/raid'), calls);
ck('switched to Browse mode', doc.querySelector('.sv-modes button[data-mode="browse"]').getAttribute('aria-pressed') === 'true');
doc.querySelector('.sv-modes button[data-mode="cards"]').onclick();
await new Promise((r) => setTimeout(r, 20));

console.log('\n── Next moves to the next question, unflipped ──');
doc.querySelector('.sv-nav .sv-btn.primary').onclick();
await new Promise((r) => setTimeout(r, 20));
ck('shows the second question', doc.querySelector('.sv-flash-q')?.textContent === allQuestions[1].question,
   doc.querySelector('.sv-flash-q')?.textContent);
ck('starts unflipped again', !flip().classList.contains('flipped'));

console.log('\n── tilt tracks the cursor while hovering ──');
ck('no transform at rest', tilt().style.transform === '');
const rect = tilt().getBoundingClientRect();
tilt().dispatchEvent(new window.MouseEvent('mousemove', {
  clientX: rect.left + rect.width * 0.8, clientY: rect.top + rect.height * 0.2, bubbles: true,
}));
ck('transform set while tracking the pointer', tilt().style.transform.includes('rotate3d'), tilt().style.transform);
ck('glow follows too', tilt().querySelector('.sv-flash-glow').style.background.includes('radial-gradient'));
tilt().dispatchEvent(new window.MouseEvent('mouseleave', { bubbles: true }));
ck('resets on mouseleave', tilt().style.transform === '');

console.log('\n── switching category reloads the deck scoped to it ──');
const callsBeforeCat = calls.length;
doc.querySelectorAll('#svCatList .node').forEach((n) => {
  if (n.querySelector('.t')?.textContent === 'Networking') n.onclick();
});
await new Promise((r) => setTimeout(r, 20));
ck('re-fetched /study/quiz with the new category', calls.slice(callsBeforeCat).some((c) => c.startsWith('/study/quiz') && c.includes('category=Networking')),
   calls.slice(callsBeforeCat));
ck('only the Networking question is in the deck now', doc.querySelector('.sv-count')?.textContent === '1 / 1',
   doc.querySelector('.sv-count')?.textContent);
ck('shows the Networking question', doc.querySelector('.sv-flash-q')?.textContent === allQuestions[2].question);

console.log('\n── a category with no quiz questions shows an empty state, not a crash ──');
doc.querySelectorAll('#svCatList .node').forEach((n) => {
  if (n.querySelector('.t')?.textContent === 'Empty Cat') n.onclick();
});
await new Promise((r) => setTimeout(r, 20));
ck('empty message shown', doc.querySelector('.empty')?.textContent.includes('No flashcards'),
   doc.querySelector('.empty')?.textContent);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
