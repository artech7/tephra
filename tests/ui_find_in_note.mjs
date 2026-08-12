import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

const noteBody = 'first widget\nsecond widget\nthird thing';
const noteHtml = '<p>first widget</p><p>second widget</p><p>third thing</p>';

const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (/\/api\/notes\/n$/.test(p) && (!o.method || o.method === 'GET')) {
    b = { slug: 'n', title: 'N', body: noteBody, tags: [], meta: {}, html: noteHtml,
          links_out: 0, media: [], backlinks: [], suggestions: [], words: 5,
          updated: '2026-07-30T00:00:00Z', flags: 0 };
  }
  else if (/\/api\/notes\/n$/.test(p) && o.method === 'PUT') {
    b = { slug: 'n', title: 'N', renamed_to: null };
  }
  else if (p.includes('/api/notes')) b = [{ slug: 'n', title: 'N', tags: [], updated: '2026-07-30T00:00:00Z', backlinks: 0, links_out: 0, size: 1, kind: 'note', flags: 0 }];
  else if (p.includes('/api/vault/list')) b = { current: '/v', suggested_parent: '/', recent: [{ path: '/v', exists: true, current: true }] };
  else if (p.includes('/api/vault/info')) b = { vault: '/v', files_on_disk: 1, indexed: 1, study_items: 0 };
  else if (p.includes('/api/theme')) b = {};
  else if (p.includes('/api/repair/last')) b = { changed: 0 };
  else if (p.includes('/api/graph')) b = { nodes: [], links: [] };
  else if (p.includes('/api/media')) b = [];
  else if (p.includes('/api/study')) b = { known_categories: [] };
  return { ok: true, status: 200, json: async () => b, text: async () => JSON.stringify(b) };
};
window.tephraStudy = { open: async () => {}, close: () => {}, isOpen: () => false, refresh: async () => {} };
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1; window.requestAnimationFrame = () => 0;
for (const id of ['#mini', '#graph']) { const e = doc.querySelector(id); if (e) { e.getContext = () => null; e.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 200 }); } }
doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){return{addColorStop(){}}}, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
window.eval(fs.readFileSync(`${ROOT}/graph.js`, 'utf8'));
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
await new Promise(r => setTimeout(r, 150));

console.log('── entering edit mode ──');
window.eval('setEditing(true)');
await new Promise(r => setTimeout(r, 20));
ck('source textarea shown, rendered body hidden',
   !doc.querySelector('#noteSrc').hidden && doc.querySelector('#noteBody').hidden);

console.log('\n── the find shortcut opens the bar WITHOUT kicking the editor back to preview ──');
// This is the actual regression: opening find moves focus from #noteSrc to
// #findInput, which used to unconditionally blur-trigger setEditing(false) --
// hiding #findBar right back out the instant it opened, and the textarea with
// it. The fix must let focus move into the find bar without treating that as
// "left the editor."
window.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true, cancelable: true }));
await new Promise(r => setTimeout(r, 20));
ck('find bar is visible', doc.querySelector('#findBar').hidden === false);
ck('still editing -- source textarea still shown', !doc.querySelector('#noteSrc').hidden);
ck('still editing -- rendered body still hidden', doc.querySelector('#noteBody').hidden === true);
ck('focus landed in the find input', doc.activeElement === doc.querySelector('#findInput'));

console.log('\n── typing a whole word keeps focus in the find box the entire time ──');
// Each keystroke used to call showMatch(), which called #noteSrc.focus() to
// paint the match -- yanking focus out of #findInput after the very first
// letter, so every character after it landed nowhere near the search box.
// Typed one character at a time, like a real keypress, not set in one shot.
const findInput = doc.querySelector('#findInput');
for (const partial of ['w', 'wi', 'wid', 'widg', 'widge', 'widget']) {
  findInput.value = partial;
  findInput.dispatchEvent(new window.Event('input', { bubbles: true }));
  await new Promise(r => setTimeout(r, 5));
  ck(`focus still in the find box after typing "${partial}"`, doc.activeElement === findInput);
}
ck('the full word made it into the input, not just the first letter', findInput.value === 'widget', findInput.value);

console.log('\n── it counts matches live, but does not jump to one yet (that would steal focus back) ──');
findInput.dispatchEvent(new window.Event('input', { bubbles: true }));
await new Promise(r => setTimeout(r, 20));
ck('both occurrences of "widget" counted, none current yet', doc.querySelector('#findCount').textContent === '0/2',
   doc.querySelector('#findCount').textContent);
ck('focus is still in the find box (typing was not interrupted)', doc.activeElement === findInput);
ck('no selection made in the textarea yet',
   doc.querySelector('#noteSrc').selectionStart === doc.querySelector('#noteSrc').selectionEnd);

console.log('\n── Enter jumps to and actually highlights the first match ──');
const ta = doc.querySelector('#noteSrc');
findInput.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
await new Promise(r => setTimeout(r, 20));
ck('now on match 1 of 2', doc.querySelector('#findCount').textContent === '1/2', doc.querySelector('#findCount').textContent);
ck('the word is actually selected in the textarea', ta.value.slice(ta.selectionStart, ta.selectionEnd) === 'widget');
ck('the selection is the FIRST occurrence', ta.selectionStart === noteBody.indexOf('widget'));
ck('focus moved to the textarea so the highlight is visible (browsers only paint a focused textarea\'s selection)',
   doc.activeElement === ta);

console.log('\n── Enter again advances to the next match ──');
findInput.focus();   // as if the user tabbed/clicked back to keep searching
findInput.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
await new Promise(r => setTimeout(r, 20));
ck('now on match 2 of 2', doc.querySelector('#findCount').textContent === '2/2', doc.querySelector('#findCount').textContent);
ck('the selection is the SECOND occurrence', ta.selectionStart === noteBody.indexOf('widget', noteBody.indexOf('widget') + 1));

console.log('\n── Shift+Enter steps backward ──');
findInput.focus();
findInput.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true }));
await new Promise(r => setTimeout(r, 20));
ck('back on match 1 of 2', doc.querySelector('#findCount').textContent === '1/2', doc.querySelector('#findCount').textContent);

console.log('\n── the Next/Prev buttons do the same jump ──');
doc.querySelector('#findNext').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await new Promise(r => setTimeout(r, 20));
ck('Next moved to match 2 of 2', doc.querySelector('#findCount').textContent === '2/2', doc.querySelector('#findCount').textContent);
doc.querySelector('#findPrev').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await new Promise(r => setTimeout(r, 20));
ck('Prev moved back to match 1 of 2', doc.querySelector('#findCount').textContent === '1/2', doc.querySelector('#findCount').textContent);

console.log('\n── Escape closes the bar and returns focus to the textarea, still editing ──');
doc.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
await new Promise(r => setTimeout(r, 20));
ck('find bar hidden again', doc.querySelector('#findBar').hidden === true);
ck('focus back on the textarea', doc.activeElement === doc.querySelector('#noteSrc'));
ck('still editing, not kicked to preview', !doc.querySelector('#noteSrc').hidden && doc.querySelector('#noteBody').hidden);

console.log('\n── genuinely clicking away still exits edit mode (the fix must not break this) ──');
doc.querySelector('#noteTitle').focus();
doc.querySelector('#noteSrc').dispatchEvent(new window.FocusEvent('blur', { relatedTarget: doc.querySelector('#noteTitle') }));
await new Promise(r => setTimeout(r, 20));
ck('left edit mode', doc.querySelector('#noteSrc').hidden === true);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
