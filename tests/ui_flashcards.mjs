import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const items = [
  { slug: 'raid', title: 'RAID levels', category: 'Storage', question: 'Which RAID level has no redundancy?' },
  { slug: 'icmp', title: 'ICMP', category: 'Networking', question: 'What does ICMP do?' },
];
const data = {
  items, categories: [{ category: 'Storage', topics: 1, questions: 0 }, { category: 'Networking', topics: 1, questions: 0 }],
  known_categories: ['Storage', 'Networking'],
  progress: { answered: 0, correct: 0, flagged: 0 },
  settings: { quiz_count: 12 }, max_quiz: 200,
  totals: { topics: 2, questions: 2, needs_review: 0 },
};
const calls = [];
window.tephraApi = async (p) => {
  calls.push(p);
  if (p === '/study') return JSON.parse(JSON.stringify(data));
  if (p === '/vault/info') return { vault: '/v', files_on_disk: 2, indexed: 2, study_items: 2 };
  if (p === '/study/item/raid') return { html: '<p>RAID 0 stripes data with no redundancy.</p>' };
  if (p === '/study/item/icmp') return { html: '<p>ICMP handles diagnostics like ping.</p>' };
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

console.log('── front face on open ──');
ck('shows the first card\'s question', doc.querySelector('.sv-flash-q')?.textContent === items[0].question,
   doc.querySelector('.sv-flash-q')?.textContent);
ck('hints to click', doc.querySelector('.front .sv-flash-hint')?.textContent === 'click to reveal');
ck('not flipped yet', !flip().classList.contains('flipped'));
ck('answer not fetched yet', !calls.includes('/study/item/raid'), calls);

console.log('\n── flipping reveals the answer, fetched once ──');
tilt().onclick();
await new Promise((r) => setTimeout(r, 20));
ck('flipped class applied', flip().classList.contains('flipped'));
ck('back shows the title', doc.querySelector('.sv-flash-title')?.textContent === 'RAID levels');
ck('answer html loaded into the back face',
   doc.querySelector('.sv-flash-answer')?.innerHTML.includes('stripes data with no redundancy'));
ck('fetched exactly once', calls.filter((c) => c === '/study/item/raid').length === 1, calls);

console.log('\n── flip back and forth again: no re-fetch ──');
tilt().onclick();
await new Promise((r) => setTimeout(r, 10));
ck('back to the front', !flip().classList.contains('flipped'));
ck('question still intact', doc.querySelector('.sv-flash-q')?.textContent === items[0].question);
tilt().onclick();
await new Promise((r) => setTimeout(r, 10));
ck('flipped again', flip().classList.contains('flipped'));
ck('still exactly one fetch for this card -- cached, not re-requested',
   calls.filter((c) => c === '/study/item/raid').length === 1, calls);

console.log('\n── Next moves to the next card, unflipped ──');
doc.querySelector('.sv-nav .sv-btn.primary').onclick();
await new Promise((r) => setTimeout(r, 20));
ck('shows the second card\'s question', doc.querySelector('.sv-flash-q')?.textContent === items[1].question,
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

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
