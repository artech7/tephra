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
  if (failNext && path === '/study/import/upload')
    throw new Error('{"detail":"that file is not valid Python: bad"}');
  if (path === '/study') return JSON.parse(JSON.stringify(study));
  if (path === '/vault/info') return { vault: '/Users/dylan/Documents/Tephra', files_on_disk: 3, indexed: 3, study_items: 0 };
  if (path === '/study/formats') {
    return { accepted: ['.json', '.py'], formats: [
      { id: 'json', label: 'JSON', extensions: ['.json'], summary: 'Portable.', example: '{"topics":[]}' },
    ] };
  }
  if (path === '/study/import/upload') {
    study.totals = { topics: 62, questions: 135, needs_review: 0 };
    study.categories = [{ category: 'SAN & Fibre Channel', topics: 5, questions: 14 }];
    study.items = [{ slug: 'icmp', title: 'ICMP', category: 'SAN & Fibre Channel', source: 'import', questions: 3, question: 'q?', needs_review: false }];
    return { topics: 62, questions: 135, categories: 13, vault: '/Users/dylan/Documents/Tephra',
             reindexed: 79, images_embedded: 4 };
  }
  throw new Error('unexpected ' + path);
};
window.tephraToast = (m) => console.log(`        toast: ${m}`);
window.tephraOpenNote = () => {};
window.tephraReloadList = async () => { calls.push({ path: 'RELOAD_SIDEBAR' }); };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });

window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));

console.log('── one import control: a folder picker, not three separate buttons ──');
const allFile = [...document.querySelectorAll('input[type=file]')];
const folderInputs = allFile.filter((i) => i.webkitdirectory);
console.log(`        (page has ${allFile.length} file input(s) total: wallpaper picker + the study importer)`);
ck('exactly one study import input', folderInputs.length === 1, `found ${folderInputs.length}`);
ck('it is a folder picker, so one dialog covers guide-only or guide+images',
   folderInputs[0].webkitdirectory === true);
ck('accepts every file the OS hands back', folderInputs[0].multiple === true);
ck('NOT nested inside a label', folderInputs[0].closest('label') === null);
ck('lives directly on body', folderInputs[0].parentElement === document.body);

console.log('\n── open the study view with an empty guide ──');
await window.tephraStudy.open();
ck('fetched study data', calls.some((c) => c.path === '/study'));
ck('fetched vault path', calls.some((c) => c.path === '/vault/info'));
const dz = document.querySelector('.sv-drop');
ck('empty state shows the dropzone', !!dz);
ck('dropzone is a div, not a label', dz && dz.tagName === 'DIV');
ck('vault path shown to the user', document.querySelector('.sv-vaultinfo')?.textContent.includes('Documents/Tephra'));
ck('exactly one import button in the header', document.querySelectorAll('.sv-head .sv-import').length === 1);
ck('it sits in its own section, not lumped in with the mode toggle',
   !!document.querySelector('.sv-importbox > #svImport'));
ck('the old server-path panel is gone', !document.querySelector('#svPathImport'));

console.log('\n── the format reference is reachable before any import ──');
ck('reference button exists in the header', !!document.querySelector('#svFormatsBtn'));
document.querySelector('#svFormatsBtn').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
await new Promise((r) => setTimeout(r, 20));
ck('drawer opens on click', document.querySelector('#svFormats').classList.contains('on'));
ck('fetched the format list', calls.some((c) => c.path === '/study/formats'));
ck('renders the fetched format', document.querySelector('#svFormatsBody .sv-fmt-h')?.textContent.includes('JSON'));
document.querySelector('#svFormatsClose').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ck('close button closes it', !document.querySelector('#svFormats').classList.contains('on'));

console.log('\n── clicking opens the (one) dialog exactly once ──');
let clicks = 0;
folderInputs[0].click = () => { clicks++; };
dz.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ck('dropzone click opens it once', clicks === 1, `${clicks}x`);

clicks = 0;
document.querySelector('#svImport').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ck('header button opens it once', clicks === 1, `${clicks}x`);

console.log('\n── picking a folder uploads every file it contains ──');
const gFile = new window.File(['{"topics":[]}'], 'guide.json', { type: 'application/json' });
const iFile = new window.File(['x'], 'slide1.png', { type: 'image/png' });
Object.defineProperty(folderInputs[0], 'files', { value: [gFile, iFile], writable: true, configurable: true });
folderInputs[0].dispatchEvent(new window.Event('change'));
await new Promise((r) => setTimeout(r, 60));

const post = calls.find((c) => c.path === '/study/import/upload');
ck('POSTed to /study/import/upload', !!post, post && post.method);
ck('sent as multipart FormData', post && post.body instanceof window.FormData);
ck('both files attached under the same "files" field', post && post.body.getAll('files').length === 2,
   post && post.body.getAll('files').map((f) => f.name));
ck('sidebar + graph refreshed after import', calls.some((c) => c.path === 'RELOAD_SIDEBAR'));
ck('view re-rendered with content', !document.querySelector('.sv-drop'));
ck('topics now visible', !!document.querySelector('.sv-card'));

console.log('\n── ...and still reachable now that the vault is no longer empty ──');
// This is the actual bug: the reference used to live only inside the
// empty-state screen and vanished the moment a single item existed.
ck('the dropzone (and the old inline reference) are gone', !document.querySelector('.sv-drop'));
ck('the header button is still there', !!document.querySelector('#svFormatsBtn'));
document.querySelector('#svFormatsBtn').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
ck('still opens with real study items on screen', document.querySelector('#svFormats').classList.contains('on'));
document.querySelector('#svFormatsClose').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

console.log('\n── dropping a single file also goes through the same endpoint ──');
calls.length = 0;
const dt = { files: [gFile] };
const ev = new window.Event('drop', { bubbles: true, cancelable: true });
Object.defineProperty(ev, 'dataTransfer', { value: dt });
document.querySelector('.sv-body').dispatchEvent(ev);
await new Promise((r) => setTimeout(r, 60));
ck('a single dropped file imports it', calls.some((c) => c.path === '/study/import/upload'));

console.log('\n── dropping a whole folder walks it recursively (FileSystem Entry API) ──');
// A minimal fake of the browser's drag-drop directory-entry shape: each
// directory answers readEntries() once with its children, then empty (the
// real API is batch-based and study.js has to keep calling until it's told
// there's nothing left).
const fileEntry = (file) => ({ isFile: true, isDirectory: false, file: (resolve) => resolve(file) });
const dirEntry = (children) => {
  let served = false;
  return {
    isFile: false, isDirectory: true,
    createReader: () => ({
      readEntries: (resolve) => { const batch = served ? [] : children; served = true; resolve(batch); },
    }),
  };
};
const deepFile = new window.File(['x'], 'deep.png', { type: 'image/png' });
const topImg = new window.File(['x'], 'top.png', { type: 'image/png' });
const folderGuide = new window.File(['{"topics":[]}'], 'guide2.json', { type: 'application/json' });
const rootDir = dirEntry([fileEntry(folderGuide), fileEntry(topImg), dirEntry([fileEntry(deepFile)])]);

calls.length = 0;
const dropDt = { items: [{ webkitGetAsEntry: () => rootDir }], files: [] };
const dropEv = new window.Event('drop', { bubbles: true, cancelable: true });
Object.defineProperty(dropEv, 'dataTransfer', { value: dropDt });
document.querySelector('.sv-body').dispatchEvent(dropEv);
await new Promise((r) => setTimeout(r, 80));
const upPost2 = calls.find((c) => c.path === '/study/import/upload');
ck('a dropped folder posts to the same upload endpoint', !!upPost2, upPost2 && upPost2.method);
const droppedNames = (upPost2 && upPost2.body.getAll('files').map((f) => f.name).sort()) || [];
ck('the nested file was found too -- not just the top level',
   JSON.stringify(droppedNames) === JSON.stringify(['deep.png', 'guide2.json', 'top.png']), droppedNames);

console.log('\n── a server error is shown, not swallowed ──');
failNext = true;
folderInputs[0].dispatchEvent(new window.Event('change'));
await new Promise((r) => setTimeout(r, 60));
const warn = [...document.querySelectorAll('.sv-warn')].map((n) => n.textContent).join(' ');
ck('failure reason rendered in the view', warn.includes('not valid Python'), warn.slice(0, 60));
ck('dropzone label restored after failure',
   !document.querySelector('.sv-drop') || document.querySelector('.sv-drop-t')?.textContent === 'Import/Merge study guide');

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
