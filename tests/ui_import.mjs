import { JSDOM } from 'jsdom';
import fs from 'fs';

const ROOT = new URL('../app/static', import.meta.url).pathname;
const html = fs.readFileSync(`${ROOT}/index.html`, 'utf8');

const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://127.0.0.1:8400/' });
const { window } = dom;
global.window = window; global.document = window.document;

let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };
const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));

// ── record every request the app makes ──
const calls = [];
const study = { items: [], categories: [], known_categories: ['SAN & Fibre Channel'],
                progress: { answered: 0, correct: 0, flagged: 0 },
                totals: { topics: 0, questions: 0, needs_review: 0 } };
let vaultInfo = { vault: '/Users/dylan/Documents/Tephra', files_on_disk: 3, indexed: 3, study_items: 0 };
let failCreate = false;
let afterVaultSwitchCalls = 0;
window.tephraAfterVaultSwitch = async () => { afterVaultSwitchCalls++; };
window.tephraApi = async (path, opts = {}) => {
  calls.push({ path, method: opts.method || 'GET', body: opts.body });
  if (path === '/study') return JSON.parse(JSON.stringify(study));
  if (path === '/vault/info') return vaultInfo;
  if (path === '/vault/list') return { current: vaultInfo.vault, recent: [], suggested_parent: '/Users/dylan/Documents' };
  if (path === '/study/formats') {
    return { accepted: ['.json', '.py'], formats: [
      { id: 'json', label: 'JSON', extensions: ['.json'], summary: 'Portable.', example: '{"topics":[]}' },
    ] };
  }
  if (path === '/vault/create') {
    if (failCreate) throw new Error('{"detail":"a vault already exists at that path"}');
    const p = JSON.parse(opts.body).path;
    vaultInfo = { vault: p, files_on_disk: 3, indexed: 3, study_items: 0 };
    return { vault: p, notes: 3, created: true, seeded: true };
  }
  if (path.startsWith('/study/import/upload')) {
    const dry = path.includes('dry_run=true');
    if (!dry) {
      study.totals = { topics: 62, questions: 135, needs_review: 0 };
      study.categories = [{ category: 'SAN & Fibre Channel', topics: 5, questions: 14 }];
      study.items = [{ slug: 'icmp', title: 'ICMP', category: 'SAN & Fibre Channel', source: 'import', questions: 3, question: 'q?', needs_review: false }];
    }
    return { topics: 62, questions: 135, categories: 13, created: 60, updated: 2,
             vault: vaultInfo.vault, reindexed: dry ? undefined : 79, images_embedded: 4,
             collisions: [], skipped_duplicates: 0, duplicates: [], missing_images: [], duplicate_image_names: [],
             dry_run: dry };
  }
  throw new Error('unexpected ' + path);
};
window.tephraToast = (m) => console.log(`        toast: ${m}`);
window.tephraOpenNote = () => {};
window.tephraReloadList = async () => { calls.push({ path: 'RELOAD_SIDEBAR' }); };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });

window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));

const modal = () => document.querySelector('#svImportModal');
const folderInput = () => [...document.querySelectorAll('input[type=file]')].find((i) => i.webkitdirectory);

console.log('── one import control: a folder picker, not three separate buttons ──');
const allFile = [...document.querySelectorAll('input[type=file]')];
console.log(`        (page has ${allFile.length} file input(s) total: wallpaper picker + the study importer)`);
ck('exactly one study import input', allFile.filter((i) => i.webkitdirectory).length === 1);
ck('accepts every file the OS hands back', folderInput().multiple === true);
ck('NOT nested inside a label', folderInput().closest('label') === null);
ck('lives directly on body', folderInput().parentElement === document.body);

console.log('\n── open the study view with an empty guide ──');
await window.tephraStudy.open();
ck('fetched study data', calls.some((c) => c.path === '/study'));
ck('fetched vault path', calls.some((c) => c.path === '/vault/info'));
const dz = () => document.querySelector('.sv-drop:not(.sv-importdrop)');
ck('empty state shows the dropzone', !!dz());
ck('exactly one import button in the header', document.querySelectorAll('.sv-head .sv-import').length === 1);
ck('it sits in its own section, not lumped in with the mode toggle',
   !!document.querySelector('.sv-importbox > #svImport'));
ck('the confirmation modal exists but starts hidden', modal() && modal().hidden === true);

console.log('\n── the format reference is reachable before any import ──');
ck('reference button exists in the header', !!document.querySelector('#svFormatsBtn'));
document.querySelector('#svFormatsBtn').click();
await tick(20);
ck('drawer opens on click', document.querySelector('#svFormats').classList.contains('on'));
ck('fetched the format list', calls.some((c) => c.path === '/study/formats'));
document.querySelector('#svFormatsClose').click();

console.log('\n── clicking the header button opens the CONFIRM MODAL, not a file dialog ──');
let dialogClicks = 0;
folderInput().click = () => { dialogClicks++; };
document.querySelector('#svImport').click();
ck('modal opens', modal().hidden === false);
ck('the OS dialog was NOT opened yet', dialogClicks === 0);
ck('defaults to "Import → new vault"',
   document.querySelector('.sv-modebtn[data-mode="new"]').getAttribute('aria-pressed') === 'true');
ck('merge pane starts hidden', document.querySelector('#svMergePane').hidden === true);
ck('confirm is disabled with nothing picked yet', document.querySelector('#svImportModalConfirm').disabled === true);

document.querySelector('#svImportModalCancel').click();
ck('cancel closes it without calling anything', modal().hidden === true);
ck('no API calls were made just from opening/cancelling',
   !calls.some((c) => c.path.startsWith('/study/import') || c.path === '/vault/create'));

console.log('\n── the empty-state dropzone also opens the modal, not the OS dialog ──');
dz().click();
ck('dropzone click opens the modal', modal().hidden === false);
ck('still no OS dialog', dialogClicks === 0);
ck('choosing a folder inside the modal DOES open the OS dialog', (() => {
  document.querySelector('#svImportDrop').click();
  return dialogClicks === 1;
})());

console.log('\n── new-vault mode: picking files prefills the name and previews the path ──');
const gFile = new window.File(['{"topics":[]}'], 'ldap_overview_guide.json', { type: 'application/json' });
const iFile = new window.File(['x'], 'slide1.png', { type: 'image/png' });
Object.defineProperty(folderInput(), 'files', { value: [gFile, iFile], writable: true, configurable: true });
folderInput().dispatchEvent(new window.Event('change'));
await tick();
ck('drop summary names the guide file',
   document.querySelector('#svImportDropS').textContent.includes('ldap_overview_guide.json'));
ck('vault name guessed from the guide filename',
   document.querySelector('#svNewVaultName').value === 'Ldap Overview Guide', document.querySelector('#svNewVaultName').value);
ck('path preview uses the suggested parent + typed name',
   document.querySelector('#svNewVaultPath').textContent === 'Will create: /Users/dylan/Documents/Ldap Overview Guide',
   document.querySelector('#svNewVaultPath').textContent);
ck('confirm now enabled', document.querySelector('#svImportModalConfirm').disabled === false);
ck('confirm labelled for vault creation', document.querySelector('#svImportModalConfirm').textContent.includes('Create Vault'));

console.log('\n── confirming creates the vault, THEN imports into it ──');
calls.length = 0; afterVaultSwitchCalls = 0;
document.querySelector('#svImportModalConfirm').click();
await tick(80);
const createCall = calls.find((c) => c.path === '/vault/create');
ck('vault created first', !!createCall, calls.map((c) => c.path));
ck('at suggested-parent + typed name', JSON.parse(createCall.body).path === '/Users/dylan/Documents/Ldap Overview Guide');
const importIdx = calls.findIndex((c) => c.path === '/study/import/upload');
ck('then a real (non-dry) import follows it', importIdx > calls.indexOf(createCall));
ck('the import carried both files', calls[importIdx].body.getAll('files').length === 2);
ck('app shell refreshed after the vault switch', afterVaultSwitchCalls === 1);
ck('sidebar reload also fired', calls.some((c) => c.path === 'RELOAD_SIDEBAR'));
ck('modal closed on success', modal().hidden === true);

console.log('\n── vault creation failing keeps the modal open with the reason shown ──');
document.querySelector('#svImport').click();
Object.defineProperty(folderInput(), 'files', { value: [gFile], writable: true, configurable: true });
folderInput().dispatchEvent(new window.Event('change'));
await tick();
failCreate = true;
document.querySelector('#svImportModalConfirm').click();
await tick(80);
ck('modal stayed open', modal().hidden === false);
ck('error shown inline', !document.querySelector('#svImportModalError').hidden
   && document.querySelector('#svImportModalError').textContent.includes('already exists'));
ck('cancel button usable again (not stuck busy)', document.querySelector('#svImportModalCancel').disabled === false);
failCreate = false;
document.querySelector('#svImportModalCancel').click();

console.log('\n── merge mode: explicit banner, gated review, gated confirm ──');
document.querySelector('#svImport').click();
document.querySelector('.sv-modebtn[data-mode="merge"]').click();
ck('new-vault pane hidden', document.querySelector('#svNewVaultPane').hidden === true);
ck('merge pane shown', document.querySelector('#svMergePane').hidden === false);
ck('banner names the currently open vault explicitly',
   document.querySelector('#svMergeBanner').textContent.includes('Ldap Overview Guide'),
   document.querySelector('#svMergeBanner').textContent);
ck('review button starts disabled (nothing picked yet)',
   document.querySelector('#svMergeReviewBtn').disabled === true);
ck('confirm starts disabled (nothing reviewed yet)',
   document.querySelector('#svImportModalConfirm').disabled === true);

Object.defineProperty(folderInput(), 'files', { value: [gFile, iFile], writable: true, configurable: true });
folderInput().dispatchEvent(new window.Event('change'));
await tick();
ck('review button enabled once a guide is picked',
   document.querySelector('#svMergeReviewBtn').disabled === false);
ck('confirm still disabled -- picking files alone does not count as review',
   document.querySelector('#svImportModalConfirm').disabled === true);

calls.length = 0;
document.querySelector('#svMergeReviewBtn').click();
await tick(60);
const reviewCall = calls.find((c) => c.path.startsWith('/study/import/upload'));
ck('review runs a DRY RUN', !!reviewCall && reviewCall.path.includes('dry_run=true'), reviewCall && reviewCall.path);
ck('review renders a summary', document.querySelectorAll('#svMergeReviewOut .sv-reviewlist li').length > 0);
ck('confirm enabled only now, after review', document.querySelector('#svImportModalConfirm').disabled === false);
ck('confirm labelled with the target vault by name',
   document.querySelector('#svImportModalConfirm').textContent.includes('Ldap Overview Guide'));

calls.length = 0;
document.querySelector('#svImportModalConfirm').click();
await tick(80);
const mergeCall = calls.find((c) => c.path.startsWith('/study/import/upload'));
ck('the real merge is NOT a dry run', !!mergeCall && !mergeCall.path.includes('dry_run'));
ck('no vault was created for a merge', !calls.some((c) => c.path === '/vault/create'));
ck('modal closed after merging', modal().hidden === true);

console.log('\n── picking new files after a review resets the gate ──');
document.querySelector('#svImport').click();
document.querySelector('.sv-modebtn[data-mode="merge"]').click();
Object.defineProperty(folderInput(), 'files', { value: [gFile], writable: true, configurable: true });
folderInput().dispatchEvent(new window.Event('change'));
await tick();
document.querySelector('#svMergeReviewBtn').click();
await tick(60);
ck('confirm enabled right after review', document.querySelector('#svImportModalConfirm').disabled === false);
Object.defineProperty(folderInput(), 'files', { value: [gFile, iFile], writable: true, configurable: true });
folderInput().dispatchEvent(new window.Event('change'));
await tick();
ck('re-picking files revokes the gate until reviewed again',
   document.querySelector('#svImportModalConfirm').disabled === true);
document.querySelector('#svImportModalCancel').click();

console.log('\n── dropping a file/folder anywhere opens the modal instead of importing immediately ──');
calls.length = 0;
const dt = { files: [gFile] };
const ev = new window.Event('drop', { bubbles: true, cancelable: true });
Object.defineProperty(ev, 'dataTransfer', { value: dt });
document.querySelector('.sv-body').dispatchEvent(ev);
await tick(60);
ck('the modal opened', modal().hidden === false);
ck('pre-populated with the dropped file', document.querySelector('#svImportDropS').textContent.includes('ldap_overview_guide.json'));
ck('nothing was imported yet -- confirmation is still required',
   !calls.some((c) => c.path.startsWith('/study/import') || c.path === '/vault/create'));
document.querySelector('#svImportModalCancel').click();

console.log('\n── dropping a whole folder still walks it recursively before the modal shows it ──');
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

const dropDt = { items: [{ webkitGetAsEntry: () => rootDir }], files: [] };
const dropEv = new window.Event('drop', { bubbles: true, cancelable: true });
Object.defineProperty(dropEv, 'dataTransfer', { value: dropDt });
document.querySelector('.sv-body').dispatchEvent(dropEv);
await tick(80);
ck('modal opened with all three files (including the nested one) picked up',
   document.querySelector('#svImportDropS').textContent.includes('guide2.json'));
ck('vault name guessed from the folder-dropped guide',
   document.querySelector('#svNewVaultName').value === 'Guide2');
document.querySelector('#svImportModalCancel').click();

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
