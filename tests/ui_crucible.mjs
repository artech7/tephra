import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const css = fs.readFileSync(`${ROOT}/style.css`, 'utf8');

console.log('── the mark matches Tephra\u2019s ──');
const btn = doc.querySelector('#crucibleBtn');
ck('reuses the .mark class', btn.classList.contains('mark'));
ck('uses a gradient square, not an svg', !!btn.querySelector('i') && !btn.querySelector('svg'));
ck('label is plain text beside it', btn.textContent.trim() === 'Crucible');
const markFont = /\.mark\{[^}]*font-size:16px[^}]*\}/.test(css.replace(/\s+/g, ''));
const btnFont  = /\.markbtn\{[^}]*font-size:16px[^}]*font-weight:600[^}]*letter-spacing:-\.02em/.test(css.replace(/\s+/g, ''));
ck('same font-size as the wordmark (16px)', markFont && btnFont);
ck('same square geometry (19px / radius 7 from .mark i)',
   /\.marki\{width:19px;height:19px;border-radius:7px/.test(css.replace(/\s+/g, '')));
// The palette is derived from the accent's complement at runtime now, not
// hardcoded — see ui_cascade.mjs for the rule that actually paints it.
ck('mark is painted from the derived palette',
   /#crucibleBtn i\{[^}]*var\(--cruc-a\)/.test(css.replace(/\s+/g, ' ')) &&
   !/#crucibleBtn i\{[^}]*var\(--accent\)/.test(css.replace(/\s+/g, ' ')));

console.log('\n── slide transition, not a pop-over ──');
const flat = css.replace(/\s+/g, '');
// Deck-relative now: the header sits outside the sliding area, so panes move
// by one deck width rather than one viewport width.
ck('Crucible parks one deck-width right', flat.includes('#studyview{position:absolute;z-index:5;top:0;bottom:0;left:100%;right:-100%'));
ck('slides flush when open', flat.includes('body.crucible#studyview{left:0;right:0'));
ck('notes side leaves to the left', flat.includes('body.crucible.side{left:-100%;right:100%}'));
ck('the shell itself never moves', !flat.includes('body.crucible.shell{'));
ck('animates offsets, never transform',
   /#studyview\{[^}]*transition:left/.test(flat) && !/#studyview\{[^}]*transform:translate/.test(flat));
ck('old fixed-overlay pop-in removed', !flat.includes('#studyview{position:fixed'));

console.log('\n── body class drives both sides ──');
window.tephraApi = async (p) => {
  if (p === '/study') return { items: [
      { slug: 'icmp', title: 'ICMP', category: 'Networking', source: 'import', questions: 2, question: 'q1?', needs_review: false },
      { slug: 'lun',  title: 'LUN masking', category: 'SAN', source: 'import', questions: 1, question: 'q2?', needs_review: false }],
    categories: [{ category: 'Networking', topics: 1, questions: 2 }, { category: 'SAN', topics: 1, questions: 1 }],
    known_categories: ['Networking', 'SAN'],
    progress: { answered: 0, correct: 0, flagged: 0 },
    totals: { topics: 2, questions: 3, needs_review: 0 } };
  if (p === '/vault/info') return { vault: '/v', files_on_disk: 2, indexed: 2, study_items: 2 };
  if (p.startsWith('/study/item/')) return { slug: p.split('/').pop(), title: 'ICMP', category: 'Networking',
    source: 'import', confidence: null, question: 'q1?', prose: '', html: '<p>body</p>', quiz: [], updated: '' };
  throw new Error(p);
};
window.tephraToast = () => {}; window.tephraOpenNote = () => {};
window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));

ck('body clean before opening', !doc.body.classList.contains('crucible'));
await window.tephraStudy.open();
ck('opening adds body.crucible', doc.body.classList.contains('crucible'));
ck('view marked on', doc.querySelector('#studyview').classList.contains('on'));
window.tephraStudy.close();
ck('closing removes it', !doc.body.classList.contains('crucible'));

console.log('\n── clicking a category loads its cards directly ──');
await window.tephraStudy.open();
let cards = [...doc.querySelectorAll('.sv-card')];
ck('starts on the grid', cards.length === 2, `${cards.length} cards`);

cards[0].onclick(); await new Promise(r => setTimeout(r, 30));
ck('clicking a card opens the topic', !!doc.querySelector('.sv-topic-head'));

const catNodes = [...doc.querySelectorAll('#svCatList .node')];
const sanNode = catNodes.find(n => n.textContent.includes('SAN'));
sanNode.onclick(); await new Promise(r => setTimeout(r, 30));
ck('clicking a category leaves the open topic', !doc.querySelector('.sv-topic-head'));
cards = [...doc.querySelectorAll('.sv-card')];
ck('shows that category\u2019s cards', cards.length === 1 && cards[0].textContent.includes('LUN'),
   cards.map(c => c.textContent.match(/[A-Z][\w ]+/)?.[0]).join(','));
// renderCats() rebuilds the list, so the node clicked above is detached —
// re-query rather than trusting the old reference.
const sanNow = [...doc.querySelectorAll('#svCatList .node')].find(n => n.textContent.includes('SAN'));
ck('category marked current', sanNow.getAttribute('aria-current') === 'page',
   `aria-current=${sanNow.getAttribute('aria-current')}`);
ck('only one category current at a time',
   [...doc.querySelectorAll('#svCatList .node[aria-current]')].length === 1);

cards[0].onclick(); await new Promise(r => setTimeout(r, 30));
ck('open a card from within a category', !!doc.querySelector('.sv-topic-head'));
catNodes.find(n => n.textContent.includes('All categories')).onclick();
await new Promise(r => setTimeout(r, 30));
ck('All categories also clears the topic', [...doc.querySelectorAll('.sv-card')].length === 2);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
