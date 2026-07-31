import { JSDOM } from 'jsdom';
import fs from 'fs';

const ROOT = new URL('../app/static', import.meta.url).pathname;
const html = fs.readFileSync(`${ROOT}/index.html`, 'utf8');

const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://127.0.0.1:8400/' });
const { window } = dom;
global.window = window; global.document = window.document;

let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

// ── record every request the app makes ──
const calls = [];
const study = { items: [], categories: [], known_categories: ['SAN & Fibre Channel'],
                progress: { answered: 0, correct: 0, flagged: 0 },
                totals: { topics: 0, questions: 0, needs_review: 0 } };
let failNext = false;
window.tephraApi = async (path, opts = {}) => {
  calls.push({ path, method: opts.method || 'GET', body: opts.body });
  if (failNext && path === '/study/import')
    throw new Error('{"detail":"that file is not valid Python: bad"}');
  if (path === '/study') return JSON.parse(JSON.stringify(study));
  if (path === '/vault/info') return { vault: '/Users/dylan/Documents/Tephra', files_on_disk: 3, indexed: 3, study_items: 0 };
  if (path === '/study/import') {
    study.totals = { topics: 62, questions: 135, needs_review: 0 };
    study.categories = [{ category: 'SAN & Fibre Channel', topics: 5, questions: 14 }];
    study.items = [{ slug: 'icmp', title: 'ICMP', category: 'SAN & Fibre Channel', source: 'import', questions: 3, question: 'q?', needs_review: false }];
    return { topics: 62, questions: 135, categories: 13, vault: '/Users/dylan/Documents/Tephra', reindexed: 79 };
  }
  throw new Error('unexpected ' + path);
};
window.tephraToast = (m) => console.log(`        toast: ${m}`);
window.tephraOpenNote = () => {};
window.tephraReloadList = async () => { calls.push({ path: 'RELOAD_SIDEBAR' }); };

window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));

console.log('── the file input ──');
const allFile = [...document.querySelectorAll('input[type=file]')];
const inputs = allFile.filter(i => (i.accept || '').includes('.py'));
console.log(`        (page has ${allFile.length} file inputs total: wallpaper picker + study importer)`);
ck('exactly one study file input', inputs.length === 1, `found ${inputs.length}`);
ck('NOT nested inside a label', inputs[0].closest('label') === null);
ck('lives directly on body', inputs[0].parentElement === document.body);

console.log('\n── open the study view with an empty guide ──');
await window.tephraStudy.open();
ck('fetched study data', calls.some(c => c.path === '/study'));
ck('fetched vault path', calls.some(c => c.path === '/vault/info'));
const dz = document.querySelector('.sv-drop');
ck('empty state shows the dropzone', !!dz);
ck('dropzone is a div, not a label', dz && dz.tagName === 'DIV');
ck('vault path shown to the user', document.querySelector('.sv-vaultinfo')?.textContent.includes('Documents/Tephra'));
ck('header import button exists', !!document.querySelector('#svImport'));

console.log('\n── clicking the dropzone opens the dialog exactly once ──');
let clicks = 0;
inputs[0].click = () => { clicks++; };
dz.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ck('one dialog open, no double-fire', clicks === 1, `input.click() fired ${clicks}x`);

clicks = 0;
document.querySelector('#svImport').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ck('header button also opens it once', clicks === 1, `${clicks}x`);

console.log('\n── selecting a file actually posts it ──');
const file = new window.File(['TOPICS = []\nQUIZ = []\n'], 'fb_study_guide.py', { type: 'text/x-python' });
Object.defineProperty(inputs[0], 'files', { value: [file], writable: true, configurable: true });
inputs[0].dispatchEvent(new window.Event('change'));
await new Promise(r => setTimeout(r, 60));

const post = calls.find(c => c.path === '/study/import');
ck('POSTed to /study/import', !!post, post && post.method);
ck('sent as multipart FormData', post && post.body instanceof window.FormData);
ck('the file is attached', post && post.body.get('file')?.name === 'fb_study_guide.py');
ck('sidebar + graph refreshed after import', calls.some(c => c.path === 'RELOAD_SIDEBAR'));
ck('view re-rendered with content', !document.querySelector('.sv-drop'));
ck('topics now visible', !!document.querySelector('.sv-card'));

console.log('\n── drag and drop onto the body ──');
calls.length = 0;
const dt = { files: [file] };
const ev = new window.Event('drop', { bubbles: true, cancelable: true });
Object.defineProperty(ev, 'dataTransfer', { value: dt });
document.querySelector('.sv-body').dispatchEvent(ev);
await new Promise(r => setTimeout(r, 60));
ck('dropping a file imports it', calls.some(c => c.path === '/study/import'));

console.log('\n── a server error is shown, not swallowed ──');
failNext = true;
inputs[0].dispatchEvent(new window.Event('change'));
await new Promise(r => setTimeout(r, 60));
const warn = [...document.querySelectorAll('.sv-warn')].map(n => n.textContent).join(' ');
ck('failure reason rendered in the view', warn.includes('not valid Python'), warn.slice(0, 60));
ck('dropzone label restored after failure',
   !document.querySelector('.sv-drop') || document.querySelector('.sv-drop-t')?.textContent === 'Import study guide');

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
