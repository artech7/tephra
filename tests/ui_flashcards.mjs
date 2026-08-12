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
// Not set inline yet -- the CSS default (--mx:50% in style.css) is what
// applies until wireTilt's first mousemove writes an inline value over it,
// same as real browsers; jsdom has no layout engine to compute cx/cy
// against (getBoundingClientRect stays 0x0), so the exact percentage isn't
// worth asserting on, only that wireTilt actually writes *something*.
ck('--mx/--my not set inline before any pointer movement',
   tilt().style.getPropertyValue('--mx') === '' && tilt().style.getPropertyValue('--my') === '');
const rect = tilt().getBoundingClientRect();
tilt().dispatchEvent(new window.MouseEvent('mousemove', {
  clientX: rect.left + rect.width * 0.8, clientY: rect.top + rect.height * 0.2, bubbles: true,
}));
ck('transform set while tracking the pointer', tilt().style.transform.includes('rotate3d'), tilt().style.transform);
ck('glow follows too', tilt().querySelector('.sv-flash-glow').style.background.includes('radial-gradient'));
// --mx/--my drive .sv-flash-face's own spotlight-border pseudo-element (see
// style.css) -- the same holo-border effect .sv-card and #lens use. Set on
// .sv-flash-tilt, not each face, so they inherit down to whichever face is
// currently showing without wireTilt needing to know or care which one that is.
ck('--mx written by the mousemove handler', tilt().style.getPropertyValue('--mx') !== '', tilt().style.getPropertyValue('--mx'));
ck('--my written by the mousemove handler', tilt().style.getPropertyValue('--my') !== '', tilt().style.getPropertyValue('--my'));
tilt().dispatchEvent(new window.MouseEvent('mouseleave', { bubbles: true }));
ck('resets on mouseleave', tilt().style.transform === '');
ck('--mx/--my reset to centered on mouseleave',
   tilt().style.getPropertyValue('--mx') === '50%' && tilt().style.getPropertyValue('--my') === '50%');

console.log('\n── flipping does not compound with a lingering hover tilt (the "ghost double card") ──');
// The flip (rotateY on .sv-flash-flip) and the tilt (rotate3d on
// .sv-flash-tilt itself) are two independent 3D rotations. Leaving the
// last hover tilt applied while a flip is also mid-transition composes
// them into a lopsided rotation that renders as two overlapping card-
// shaped planes through perspective -- this is the actual bug report.
const rect2 = tilt().getBoundingClientRect();
tilt().dispatchEvent(new window.MouseEvent('mousemove', {
  clientX: rect2.left + rect2.width * 0.8, clientY: rect2.top + rect2.height * 0.2, bubbles: true,
}));
ck('a tilt is applied from hovering', tilt().style.transform.includes('rotate3d'), tilt().style.transform);
tilt().onclick();
ck('the lingering tilt is cleared the instant a flip starts', tilt().style.transform === '', tilt().style.transform);
tilt().dispatchEvent(new window.MouseEvent('mousemove', {
  clientX: rect2.left + rect2.width * 0.3, clientY: rect2.top + rect2.height * 0.7, bubbles: true,
}));
ck('tilt stays suppressed for further hover movement while the flip is still transitioning',
   tilt().style.transform === '', tilt().style.transform);
const transformEvt = new window.Event('transitionend', { bubbles: true });
transformEvt.propertyName = 'transform';
flip().dispatchEvent(transformEvt);
tilt().dispatchEvent(new window.MouseEvent('mousemove', {
  clientX: rect2.left + rect2.width * 0.8, clientY: rect2.top + rect2.height * 0.2, bubbles: true,
}));
ck('tilt resumes once the flip\'s own transitionend fires', tilt().style.transform.includes('rotate3d'), tilt().style.transform);
tilt().dispatchEvent(new window.MouseEvent('mouseleave', { bubbles: true }));
tilt().onclick();   // back to front, for the sections below

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
