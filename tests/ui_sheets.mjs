/* Sheets: the ```sheets fence's parser, serializer, and column widths.
 *
 * Widths are stored as the dash count in the table's delimiter row -- see
 * the note next to _sheet_widths in render.py, which owns the format. Most
 * of what's worth asserting here is that round-tripping is lossless and
 * that a resize touches exactly one line, because the failure mode that
 * matters isn't a wrong width, it's a rewrite that eats cell text.
 *
 * jsdom has no layout engine, so nothing here can prove a column actually
 * came out 30 characters wide on screen. What it does prove: the arithmetic
 * and text rewriting are right, and the DOM the resize needs is wired up.
 * The visual result is checked by ui_cascade.mjs's cascade resolution for
 * the CSS side and by eye for the rest.
 */
import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8405/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

window.eval(fs.readFileSync(`${ROOT}/sheets.js`, 'utf8'));
const S = window.tephraSheets;
const W = S.widths;

const d = (n) => '-'.repeat(n);

console.log('── a column width is its dash count; `---` means unset ──');
{
  ck('the canonical three-dash form is unset, not a width of 3', W.parse('---') === null);
  ck('one and two dashes are unset too', W.parse('-') === null && W.parse('--') === null);
  ck('a real width reads back as its dash count', W.parse(d(30)) === 30);
  ck('alignment colons are not counted as width', W.parse(':' + d(24) + ':') === 24);
  ck('a width below the floor clamps up', W.parse(d(4)) === W.MIN, W.MIN);
  ck('a width above the ceiling clamps down', W.parse(d(200)) === W.MAX, W.MAX);
  ck('the floor and ceiling are a sane pair', W.MIN > W.UNSET && W.MAX > W.MIN);
}

console.log('\n── writing a width back preserves alignment ──');
{
  ck('unset round-trips to three dashes', W.cell(null, '---') === '---');
  ck('a width becomes that many dashes', W.cell(20, '---') === d(20));
  ck('left alignment survives a resize', W.cell(12, ':---') === ':' + d(12));
  ck('right alignment survives a resize', W.cell(12, '---:') === d(12) + ':');
  ck('centre alignment survives a resize', W.cell(12, ':---:') === ':' + d(12) + ':');
  ck('an out-of-range width is clamped on the way out too', W.cell(9999, '---') === d(W.MAX));
}

console.log('\n── parse lifts widths off the delimiter row ──');
{
  const m = S.parse(`## Week 1\n| Day | Topic | Notes |\n| --- | ${d(30)} | :${d(12)}: |\n| Mon | Intro | x |`);
  ck('one sheet parsed', m.length === 1 && m[0].name === 'Week 1');
  ck('the delimiter row is not mistaken for a body row', m[0].body.length === 1, m[0].body);
  ck('widths line up with the columns', JSON.stringify(m[0].widths) === '[null,30,12]', m[0].widths);
  ck('alignment is kept alongside the width', m[0].align[2] === ':' + d(12) + ':');
  ck('there is one width slot per header', m[0].widths.length === m[0].headers.length);
}
{
  // The pre-widths form: every sheet written before this existed.
  const m = S.parse('## A\n| X | Y |\n| --- | --- |\n| 1 | 2 |');
  ck('an old sheet has no widths at all, not zeros', m[0].widths.every((w) => w === null), m[0].widths);
}
{
  const m = S.parse(`| A | B |\n| ${d(18)} | --- |\n| 1 | 2 |`);
  ck('a headingless lone table still gets its widths', JSON.stringify(m[0].widths) === '[18,null]', m[0].widths);
}

console.log('\n── serialize keeps widths, so a grid edit does not reset them ──');
{
  const src = `## Week 1\n| Day | Topic |\n| --- | ${d(30)} |\n| Mon | Intro |`;
  const out = S.serialize(S.parse(src));
  ck('the width survives a parse/serialize round-trip', /\| --- \| -{30} \|/.test(out), out.split('\n')[3]);
  ck('re-parsing the output gives the same widths back',
     JSON.stringify(S.parse(out)[0].widths) === '[null,30]');
  const cells = S.parse(out)[0];
  ck('cell text is unchanged by the round-trip', cells.body[0].join('|') === 'Mon|Intro');
}
{
  // A cell holding a pipe is the round-trip's sharp edge: the escape has to
  // survive, or a [[Note|shown]] link silently splits into two cells.
  const src = `## A\n| L |\n| ${d(20)} |\n| [[Note\\|shown]] |`;
  const m = S.parse(src);
  ck('a pipe-escaped wikilink parses as one cell', m[0].body[0].length === 1 && m[0].body[0][0] === '[[Note|shown]]');
  const out = S.serialize(m);
  ck('and is re-escaped on the way out', out.includes('[[Note\\|shown]]'), out.split('\n')[3]);
  ck('with its width intact', S.parse(out)[0].widths[0] === 20);
}

console.log('\n── a resize rewrites the delimiter row and nothing else ──');
{
  const body = [
    'Intro paragraph.', '', '```sheets', '## Week 1', '',
    '| Day | Topic |', '| --- | --- |', '| Mon | [[Intro]] |', '',
    '```', '', 'Trailing text.',
  ].join('\n');
  const out = W.set(body, 0, 0, [null, 30]);
  const a = body.split('\n'), b = out.split('\n');
  ck('the delimiter row changed', b[6] === `| --- | ${d(30)} |`, b[6]);
  ck('every other line is byte-identical',
     a.every((l, i) => i === 6 || l === b[i]), b.filter((l, i) => i !== 6 && l !== a[i]));
  ck('prose outside the fence is untouched', out.startsWith('Intro paragraph.') && out.endsWith('Trailing text.'));
  ck('the wikilink in the cell is untouched', out.includes('| Mon | [[Intro]] |'));
  ck('the fence still opens and closes', (out.match(/```/g) || []).length === 2);
}
{
  // Widths are per-sheet: the second sheet's delimiter row must be the one
  // that moves, and the first must not.
  const body = ['```sheets',
    '## One', '| A |', '| --- |', '| 1 |', '',
    '## Two', '| B |', '| --- |', '| 2 |',
    '```'].join('\n');
  const out = W.set(body, 0, 1, [24]).split('\n');
  ck("sheet 0's delimiter row is left alone", out[3] === '| --- |', out[3]);
  ck("sheet 1's delimiter row is the one resized", out[8] === `| ${d(24)} |`, out[8]);
}
{
  // Two fences in one note: only the addressed one may change.
  const body = ['```sheets', '| A |', '| --- |', '| 1 |', '```', '',
                '```sheets', '| B |', '| --- |', '| 2 |', '```'].join('\n');
  const out = W.set(body, 1, 0, [16]).split('\n');
  ck('the first fence is untouched', out[2] === '| --- |', out[2]);
  ck('the second fence is the one resized', out[8] === `| ${d(16)} |`, out[8]);
}
{
  const body = ['```sheets', '| A | B |', '| --- | :---: |', '| 1 | 2 |', '```'].join('\n');
  const out = W.set(body, 0, 0, [null, 20]).split('\n');
  ck('resizing a centred column keeps it centred', out[2] === `| --- | :${d(20)}: |`, out[2]);
}
{
  const body = ['```sheets', '| A |', '| ' + d(30) + ' |', '| 1 |', '```'].join('\n');
  const out = W.set(body, 0, 0, [null]).split('\n');
  ck('resetting a width writes the plain three-dash form back', out[2] === '| --- |', out[2]);
}
{
  const body = ['```sheets', '| A |', '| --- |', '| 1 |', '```'].join('\n');
  ck('an out-of-range fence index is a no-op, not a corruption',
     W.set(body, 7, 0, [20]) === body);
  ck('an out-of-range sheet index is a no-op too',
     W.set(body, 0, 7, [20]) === body);
}

console.log('\n── adding and deleting columns keeps the width slots aligned ──');
{
  // The bug this guards: splicing headers but not widths slides every
  // width one column to the left of the column it belongs to.
  const m = S.parse(`## A\n| P | Q | R |\n| ${d(10)} | ${d(20)} | ${d(30)} |\n| 1 | 2 | 3 |`);
  m[0].headers.splice(1, 1); m[0].widths.splice(1, 1); m[0].align.splice(1, 1);
  for (const row of m[0].body) row.splice(1, 1);
  const out = S.serialize(m);
  ck('deleting the middle column leaves the outer two widths in place',
     JSON.stringify(S.parse(out)[0].widths) === '[10,30]', S.parse(out)[0].widths);
  ck('and the right cells with them', S.parse(out)[0].body[0].join('|') === '1|3');
}

console.log('\n── the DOM a resize needs is wired up on enhance ──');
{
  const noteBody = doc.querySelector('#noteBody') || doc.body.appendChild(doc.createElement('div'));
  noteBody.id = 'noteBody';
  noteBody.innerHTML = `
    <div class="sheets g2" data-sheets-index="0">
      <div class="sheet-tabs"><button class="sheet-tab on" data-sheet="0">A</button></div>
      <div class="sheet-body">
        <div class="sheet-pane on" data-sheet="0">
          <table><thead><tr><th>Day</th><th>Topic</th></tr></thead>
          <tbody><tr><td>Mon</td><td>Intro</td></tr></tbody></table>
        </div>
      </div>
    </div>`;
  S.enhance();
  const card = noteBody.querySelector('.sheets');
  const grips = card.querySelectorAll('.sheet-grip');
  ck('one grip per header cell', grips.length === 2, grips.length);
  ck('the grip lives inside the th, so it rides the sticky header',
     grips[0].parentElement.tagName === 'TH');
  ck('enhance is idempotent -- a second pass adds no duplicate grips',
     (S.enhance(), card.querySelectorAll('.sheet-grip').length) === 2);
  ck('the card is marked processed', card.dataset.processed === 'true');
  ck('the Edit and Expand buttons still get attached alongside',
     !!card.querySelector('.sheet-edit') && !!card.querySelector('.sheet-expand'));

  // Drag: jsdom reports every element as 0x0, so the measured char width
  // falls back to 8px and an unset column starts at 0 -- which makes the
  // arithmetic deterministic rather than unverifiable. 80px right of a
  // 0-width start is 10 characters.
  let saved = null;
  window.tephraCurrentSlug = () => 'a-note';
  window.tephraSaveNoteBody = (slug, compute) => { saved = { slug, body: compute(
    ['```sheets', '| Day | Topic |', '| --- | --- |', '| Mon | Intro |', '```'].join('\n')) }; };

  const grip = grips[1];
  const pd = new window.MouseEvent('pointerdown', { bubbles: true, clientX: 0 });
  grip.dispatchEvent(pd);
  ck('the pane switches to fixed layout while dragging, or the drag looks dead',
     grip.closest('.sheet-pane').classList.contains('sheet-fixed'));
  ck('a colgroup is created to hold the width',
     !!grip.closest('table').querySelector('colgroup'));
  ck('the colgroup has one col per column',
     grip.closest('table').querySelectorAll('colgroup col').length === 2);
  grip.dispatchEvent(new window.MouseEvent('pointermove', { bubbles: true, clientX: 80 }));
  const col = grip.closest('table').querySelectorAll('colgroup col')[1];
  ck('dragging right widens the dragged column', col.style.width === '10ch', col.style.width);
  grip.dispatchEvent(new window.MouseEvent('pointerup', { bubbles: true, clientX: 80 }));
  ck('releasing saves through the note-body bridge', saved && saved.slug === 'a-note');
  ck('the saved markdown carries the new width',
     saved && saved.body.includes(`| --- | ${d(10)} |`), saved && saved.body.split('\n')[2]);
  ck('the drag is over -- body no longer in resizing mode',
     !doc.body.classList.contains('sheet-resizing'));

  // A drag can only ever set a width inside the clamp, so the stored file
  // can never ask for a column wider than the ceiling.
  grip.dispatchEvent(new window.MouseEvent('pointerdown', { bubbles: true, clientX: 0 }));
  grip.dispatchEvent(new window.MouseEvent('pointermove', { bubbles: true, clientX: 99999 }));
  ck('dragging past the ceiling clamps rather than running away',
     col.style.width === `${W.MAX}ch`, col.style.width);
  grip.dispatchEvent(new window.MouseEvent('pointermove', { bubbles: true, clientX: -99999 }));
  ck('dragging past the floor clamps too', col.style.width === `${W.MIN}ch`, col.style.width);
  grip.dispatchEvent(new window.MouseEvent('pointerup', { bubbles: true, clientX: 0 }));

  // Double-click resets: without it there'd be no way back to auto sizing,
  // since no draggable width means "auto".
  grip.dispatchEvent(new window.MouseEvent('dblclick', { bubbles: true }));
  ck('double-clicking a grip clears the explicit width', col.style.width === '');
  ck('and writes the unset form back to the file',
     saved && saved.body.includes('| --- | --- |'), saved && saved.body.split('\n')[2]);
  ck('with no explicit widths left, the pane drops back to auto layout',
     !grip.closest('.sheet-pane').classList.contains('sheet-fixed'));
}

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
