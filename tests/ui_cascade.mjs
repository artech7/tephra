import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
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

console.log('\n── code blocks scroll both axes and resize instead of growing forever ──');
const bodyEl = doc.createElement('div');
bodyEl.className = 'body';
const preEl = doc.createElement('pre');
bodyEl.appendChild(preEl);
doc.body.appendChild(bodyEl);

const rz = rulesFor(preEl, 'resize').pop();
ck('gets a vertical drag handle', rz && rz.value === 'vertical', rz?.value);
const ov = rulesFor(preEl, 'overflow').pop();
ck('scrolls both axes, not just horizontally', ov && ov.value === 'auto', ov?.value);
ck('has a default min size (the resize drag floor too)',
   !!rulesFor(preEl, 'min-height').pop(), rulesFor(preEl, 'min-height').pop()?.value);
// The default cap is applied client-side (enhanceCodeBlocks() in app.js) as
// an inline height, deliberately not here: max-height would also be the
// resize drag's own ceiling, capping how far a block can be pulled open.
ck('does NOT set max-height -- that would cap the resize drag too',
   !rulesFor(preEl, 'max-height').pop(), rulesFor(preEl, 'max-height').pop()?.value);
doc.body.removeChild(bodyEl);

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
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));
await window.tephraStudy.open();
ck('Crucible header renders with no icon slot',
   !!doc.querySelector('#studyview h3') && !doc.querySelector('#studyview .sv-mark'));
ck('title still reads Crucible', doc.querySelector('#studyview h3').textContent === 'Crucible');

/* The sheets fullscreen viewer *moves* the real card out of #noteBody and
   into #shtViewBody. Every rule that styles a sheet is scoped under `.body`,
   because that's where a rendered note lives -- so if the viewer's host
   isn't a `.body` context, the relocated card matches none of them. It
   shipped that way: unstyled tables, and `.sheet-pane{display:none}` not
   applying, so every pane showed at once and the tabs looked broken while
   working perfectly. This is a cascade question, which is why it's checked
   here rather than by asserting a class name somewhere. */
console.log('\n── a sheet moved into the fullscreen viewer keeps its styling ──');
{
  const host = doc.querySelector('#shtViewBody');
  ck('the viewer host exists', !!host);
  ck('the viewer host is a .body context, or every sheet rule stops matching',
     !!host && host.matches('.body'), host && host.className);

  // Build the same card shape render.py emits, once in the note and once in
  // the viewer, and resolve the properties that actually broke.
  const mk = (parent) => {
    parent.innerHTML = `
      <div class="sheets g2" data-sheets-index="0">
        <div class="sheet-tabs"><button class="sheet-tab on" data-sheet="0">A</button></div>
        <div class="sheet-body">
          <div class="sheet-pane on" data-sheet="0"><table><thead><tr><th>H</th></tr></thead>
            <tbody><tr><td>c</td></tr></tbody></table></div>
          <div class="sheet-pane" data-sheet="1"><table><tbody><tr><td>d</td></tr></tbody></table></div>
        </div>
      </div>`;
    return parent.querySelector('.sheets');
  };
  const inNote = mk(doc.querySelector('#noteBody'));
  const inView = mk(host);

  const winner = (el, prop) => rulesFor(el, prop).pop();
  const off = (card) => card.querySelectorAll('.sheet-pane')[1];
  const cell = (card) => card.querySelector('td');

  ck('an inactive pane resolves display:none inside the note',
     winner(off(inNote), 'display')?.value === 'none', winner(off(inNote), 'display')?.sel);
  ck('...and still does inside the viewer -- the tab-switching bug',
     winner(off(inView), 'display')?.value === 'none', winner(off(inView), 'display')?.sel);

  ck('a cell resolves a border inside the note', !!winner(cell(inNote), 'border'));
  ck('...and the viewer resolves the same border rule -- the theming bug',
     winner(cell(inView), 'border')?.sel === winner(cell(inNote), 'border')?.sel,
     winner(cell(inView), 'border')?.sel);

  ck('cells wrap in the viewer too, not just in the note',
     winner(cell(inView), 'white-space')?.value === 'normal',
     winner(cell(inView), 'white-space')?.sel);

  ck('the tab is styled in the viewer, not a bare button',
     !!winner(inView.querySelector('.sheet-tab'), 'border-radius'));

  // The viewer's own overrides must still beat the .body rules they exist to
  // override -- an id selector outranks a class chain, but only if it's
  // actually there.
  const expand = doc.createElement('button');
  expand.className = 'sheet-expand';
  inView.appendChild(expand);
  ck('the card\u2019s own Expand button is hidden in the viewer',
     winner(expand, 'display')?.value === 'none', winner(expand, 'display')?.sel);

  doc.querySelector('#noteBody').innerHTML = '';
  host.innerHTML = '';
}

/* The four tab windows -- Overview, Links, Crucible, and Crucible's
   Formatting & Uploads reference -- are full-bleed panels that sit on top of
   a note rather than beside it. What's behind them is text you're trying to
   stop reading, not wallpaper you're trying to see, so neither their blur nor
   their tint may come from the theme sliders: both bottom out at values that
   leave the note underneath legible straight through the panel.

   This is checked rather than trusted because it has now regressed twice --
   once when a stale style.css was copied over the fix, and once when a
   restore picked the commit immediately before it. Both times the symptom
   was the same and neither was caught by anything. */
console.log('\n── panels that sit on top of notes never take blur from the slider ──');
{
  const veiled = ['#svFormats', '#studyview', '#statsview', '#linksview'];
  const chrome = ['.topbar', '.sidebar', '.editor', '.context'];

  // Read the declarations straight out of the stylesheet: these are the
  // values that matter and they're set on the rule, not resolved per-element.
  const declFor = (sel, prop) => {
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m, found = null;
    while ((m = re.exec(css))) {
      const sels = m[1].split(',').map((x) => x.trim());
      if (!sels.includes(sel)) continue;
      const pm = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`).exec(m[2]);
      if (pm) found = pm[1].trim();
    }
    return found;
  };

  for (const sel of veiled) {
    const bf = declFor(sel, 'backdrop-filter');
    ck(`${sel} declares a backdrop blur`, !!bf, bf);
    ck(`${sel} does not take its blur from the --blur slider`,
       !!bf && !/blur\(var\(--blur\)\)/.test(bf), bf);
    ck(`${sel} pins it to --blur-fixed instead`,
       !!bf && bf.includes('--blur-fixed'), bf);
    const bg = declFor(sel, 'background');
    ck(`${sel} floors its tint with --veil-ink rather than raw --ink`,
       !!bg && bg.includes('--veil-ink') && !bg.includes('calc(var(--ink)'),
       bg && bg.slice(0, 54));
  }

  // The counterpart: the frosted chrome beside a note is exactly what the
  // slider is for, so pinning it too would be the opposite bug.
  const chromeBf = declFor('.topbar', 'backdrop-filter');
  ck('the chrome beside a note still follows the slider',
     !!chromeBf && chromeBf.includes('var(--blur)') && !chromeBf.includes('--blur-fixed'),
     chromeBf);

  // Both floors have to actually be floors, not aliases of the slider.
  const root = /:root\{([\s\S]*?)\}/.exec(css);
  const fixed = /--blur-fixed\s*:\s*([^;]+)/.exec(root[1]);
  const veil = /--veil-ink\s*:\s*([^;]+)/.exec(root[1]);
  ck('--blur-fixed is a constant, not derived from --blur',
     !!fixed && !fixed[1].includes('var(--blur)'), fixed && fixed[1].trim());
  ck('--veil-ink is a max() floor over --ink, so the theme can raise but not lower it',
     !!veil && veil[1].includes('max(') && veil[1].includes('var(--ink)'),
     veil && veil[1].trim());
}

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
