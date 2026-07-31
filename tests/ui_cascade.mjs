import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = '/home/claude/tephra/app/static';
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const rawCss = fs.readFileSync(`${ROOT}/style.css`, 'utf8');
// Strip comments first: a naive rule regex otherwise treats commas inside a
// comment as selector separators and silently drops the rule that follows.
const css = rawCss.replace(/\/\*[\s\S]*?\*\//g, '');

/* Resolve the cascade by hand: find every rule whose selector matches the
   element, order by (specificity, source order), and report the winner for a
   property. Asserting the *variables* differ was not enough — the previous bug
   set them correctly and then lost the cascade. */
function specificity(sel) {
  const s = sel.trim();
  const ids = (s.match(/#[\w-]+/g) || []).length;
  const cls = (s.match(/\.[\w-]+|\[[^\]]+\]|:[\w-]+/g) || []).length;
  const types = (s.replace(/#[\w-]+|\.[\w-]+|\[[^\]]+\]|::?[\w-]+/g, ' ')
                  .match(/[a-zA-Z][\w-]*/g) || []).length;
  return ids * 10000 + cls * 100 + types;
}
function rulesFor(el, prop) {
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m, order = 0;
  while ((m = re.exec(css))) {
    const body = m[2];
    order++;
    for (const sel of m[1].split(',')) {
      const s = sel.trim();
      if (!s || s.startsWith('@') || s.includes('%')) continue;
      let matches = false;
      try { matches = el.matches(s); } catch { continue; }
      if (!matches) continue;
      const pm = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`).exec(body);
      if (pm) out.push({ sel: s, value: pm[1].trim(), spec: specificity(s), order });
    }
  }
  return out.sort((a, b) => a.spec - b.spec || a.order - b.order);
}

console.log('── which rule actually paints the Crucible square? ──');
const cIcon = doc.querySelector('#crucibleBtn i');
const tIcon = doc.querySelector('#tephraBtn i');
ck('Crucible has an icon element', !!cIcon);

const cRules = rulesFor(cIcon, 'background');
const winner = cRules[cRules.length - 1];
console.log('        candidates: ' + cRules.map(r => `${r.sel}(${r.spec})`).join(' < '));
ck('the winning background is Crucible\u2019s, not .mark i\u2019s',
   winner && winner.sel.includes('#crucibleBtn'), `winner: ${winner?.sel}`);
ck('it uses the derived palette', winner && winner.value.includes('--cruc-a'), winner?.value.slice(0, 46));
ck('it does NOT use --accent', winner && !winner.value.includes('--accent'));

const tWinner = rulesFor(tIcon, 'background').pop();
ck('Tephra\u2019s square still uses --accent', tWinner && tWinner.value.includes('--accent'), tWinner?.sel);
ck('the two squares resolve to different rules', winner.sel !== tWinner.sel);

console.log('\n── the same trap, checked for the box-shadow glow ──');
const gw = rulesFor(cIcon, 'box-shadow').pop();
ck('glow comes from the Crucible rule', gw && gw.value.includes('--cruc-a'), gw?.sel);

console.log('\n── the body mark is gone, not blank ──');
ck('no .sv-mark element in the Crucible header', !doc.querySelector('.sv-mark'));
ck('no orphaned .sv-mark CSS', !rawCss.includes('.sv-mark'));
ck('no background:none rule can strip a gradient any more',
   !/\.sv-mark\{[^}]*background:none/.test(rawCss.replace(/\s+/g, '')));

// mount study.js and confirm the rendered header
window.tephraApi = async (p) => {
  if (p === '/study') return { items: [], categories: [], known_categories: [],
    progress: { answered: 0, correct: 0, flagged: 0 }, totals: { topics: 0, questions: 0, needs_review: 0 } };
  if (p === '/vault/info') return { vault: '/v', files_on_disk: 0, indexed: 0, study_items: 0 };
  throw new Error(p);
};
window.tephraToast = () => {}; window.tephraOpenNote = () => {};
window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));
await window.tephraStudy.open();
ck('Crucible header renders with no icon slot',
   !!doc.querySelector('#studyview h3') && !doc.querySelector('#studyview .sv-mark'));
ck('title still reads Crucible', doc.querySelector('#studyview h3').textContent === 'Crucible');

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
