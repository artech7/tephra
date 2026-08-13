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

// ── background import job mock (postImport now posts, then polls status) ──
let jobSeq = 0;
const jobs = new Map();
// How many /study/import/status polls a job takes to report finished:true.
// 1 (the default) finishes on the very first poll, so most tests don't pay
// postImport's inter-poll delay; bumped to 2+ by the one test that actually
// exercises the progress bar mid-import, then reset back to 1 after.
let jobPollsUntilDone = 1;
const JOB_TOTAL = 62;
function jobResult(dry) {
  return { topics: 62, questions: 135, categories: 13, created: 60, updated: 2,
           vault: vaultInfo.vault, reindexed: dry ? undefined : 79, images_embedded: 4,
           collisions: [], skipped_duplicates: 0, duplicates: [], missing_images: [], duplicate_image_names: [],
           dry_run: dry };
}

window.tephraApi = async (path, opts = {}) => {
  calls.push({ path, method: opts.method || 'GET', body: opts.body });
  if (path === '/study') return JSON.parse(JSON.stringify(study));
  if (path === '/vault/info') return vaultInfo;
  if (path === '/vault/list') return { current: vaultInfo.vault, recent: [], suggested_parent: '/Users/dylan/Documents' };
  if (path === '/study/formats') {
    return { accepted: ['.json', '.py'], formats: [
      { id: 'json', label: 'JSON', extensions: ['.json'], summary: 'Portable.', example: '{"topics":[]}' },
    ], media: { kinds: { image: ['.png', '.jpg'], video: ['.mp4'], audio: ['.mp3'] }, max_mb: 200 } };
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
    const job_id = `job${++jobSeq}`;
    jobs.set(job_id, { polls: 0, result: jobResult(dry) });
    return { job_id };
  }
  if (path.startsWith('/study/import/status/')) {
    const job_id = path.slice('/study/import/status/'.length);
    const job = jobs.get(job_id);
    if (!job) throw new Error('{"detail":"unknown import job"}');
    job.polls += 1;
    if (job.polls < jobPollsUntilDone) {
      const done = Math.round(JOB_TOTAL * job.polls / jobPollsUntilDone);
      return { done, total: JOB_TOTAL, finished: false, result: null, error: null };
    }
    jobs.delete(job_id);
    return { done: JOB_TOTAL, total: JOB_TOTAL, finished: true, result: job.result, error: null };
  }
  throw new Error('unexpected ' + path);
};
window.tephraToast = (m) => console.log(`        toast: ${m}`);
window.tephraOpenNote = () => {};
window.tephraReloadList = async () => { calls.push({ path: 'RELOAD_SIDEBAR' }); };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });

window.eval(fs.readFileSync(`${ROOT}/study.js`, 'utf8'));

const modal = () => document.querySelector('#svImportModal');
// The study importer owns two inputs -- a plain multi-file picker (default:
// works on a lone guide file with no folder requirement) and a folder picker
// (for images nested in subfolders). Both accept every file the OS hands
// back; only `multiple` (not webkitdirectory) tells them apart from the
// wallpaper picker, which is single-file and lives in the static markup.
const studyInputs = () => [...document.querySelectorAll('input[type=file]')].filter((i) => i.multiple);
const folderInput = () => studyInputs().find((i) => i.webkitdirectory);
const filePicker = () => studyInputs().find((i) => !i.webkitdirectory);

console.log('── two import controls: a plain file picker and a folder picker ──');
const allFile = [...document.querySelectorAll('input[type=file]')];
console.log(`        (page has ${allFile.length} file input(s) total: wallpaper picker + the two study importer inputs)`);
ck('exactly two study import inputs', studyInputs().length === 2);
ck('exactly one is a folder picker', studyInputs().filter((i) => i.webkitdirectory).length === 1);
ck('exactly one is a plain (non-directory) file picker', studyInputs().filter((i) => !i.webkitdirectory).length === 1);
ck('folder picker accepts every file the OS hands back', folderInput().multiple === true);
ck('file picker accepts every file the OS hands back', filePicker().multiple === true);
ck('neither is nested inside a label', folderInput().closest('label') === null && filePicker().closest('label') === null);
ck('both live directly on body', folderInput().parentElement === document.body && filePicker().parentElement === document.body);

console.log('\n── open the study view with an empty guide ──');
await window.tephraStudy.open();
ck('fetched study data', calls.some((c) => c.path === '/study'));
ck('fetched vault path', calls.some((c) => c.path === '/vault/info'));
const dz = () => document.querySelector('.sv-drop:not(.sv-importdrop)');
ck('empty state shows the dropzone', !!dz());
ck('exactly one import button in the topbar', document.querySelectorAll('header.topbar .sv-import').length === 1);
ck('it lives in the app topbar, reachable without opening Crucible at all',
   !!document.querySelector('header.topbar > #svImport') && !document.querySelector('.sv-modes .sv-import'));
ck('the confirmation modal exists but starts hidden', modal() && modal().hidden === true);

console.log('\n── the format reference is reachable before any import ──');
ck('reference button exists in the header', !!document.querySelector('#svFormatsBtn'));
document.querySelector('#svFormatsBtn').click();
await tick(20);
ck('whole-screen view opens on click', document.querySelector('#svFormats').classList.contains('on'));
ck('fetched the format list', calls.some((c) => c.path === '/study/formats'));

const fmtTabs = () => [...document.querySelectorAll('#svFormats .lv-tabs button')];
const fmtHeadings = () => [...document.querySelectorAll('#svFormatsBody .sv-fmt-h')].map((n) => n.textContent);
ck('sectioned into three tabs by topic', fmtTabs().map((b) => b.textContent).join('|')
   === 'Media attachments|Study guide import|Markdown syntax', fmtTabs().map((b) => b.textContent));
ck('lands on Media attachments by default',
   fmtTabs().find((b) => b.dataset.tab === 'media').getAttribute('aria-pressed') === 'true');
ck('media limits block is present', fmtHeadings().some((h) => h.includes('image button')), fmtHeadings());
ck('the other two tabs are not rendered until picked',
   !fmtHeadings().some((h) => h.startsWith('JSON —')) && !fmtHeadings().includes('Wikilinks'), fmtHeadings());

fmtTabs().find((b) => b.dataset.tab === 'import').click();
ck('switches to the import tab', fmtTabs().find((b) => b.dataset.tab === 'import').getAttribute('aria-pressed') === 'true');
ck('the mocked JSON import format renders there', fmtHeadings().some((h) => h.startsWith('JSON —')), fmtHeadings());
ck('media content is gone now that a different tab is active', !fmtHeadings().some((h) => h.includes('image button')));

fmtTabs().find((b) => b.dataset.tab === 'syntax').click();
ck('markdown syntax reference is included, e.g. wikilinks', fmtHeadings().includes('Wikilinks'), fmtHeadings());
ck('...and the new Sources section syntax', fmtHeadings().includes('Sources section'), fmtHeadings());

document.querySelector('#svFormatsClose').click();
ck('closes on the close button', document.querySelector('#svFormats').classList.contains('on') === false);

console.log('\n── clicking the header button opens the CONFIRM MODAL, not a file dialog ──');
let folderDialogClicks = 0, fileDialogClicks = 0;
folderInput().click = () => { folderDialogClicks++; };
filePicker().click = () => { fileDialogClicks++; };
document.querySelector('#svImport').click();
ck('modal opens', modal().hidden === false);
ck('the OS dialog was NOT opened yet', folderDialogClicks === 0 && fileDialogClicks === 0);
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
ck('still no OS dialog', folderDialogClicks === 0 && fileDialogClicks === 0);
ck('choosing files inside the modal opens the plain file dialog by default', (() => {
  document.querySelector('#svImportDrop').click();
  return fileDialogClicks === 1 && folderDialogClicks === 0;
})());
ck('the "...or choose a folder instead" control opens the folder dialog, not the file one', (() => {
  document.querySelector('#svImportPickFolder').click();
  return folderDialogClicks === 1 && fileDialogClicks === 1;
})());

console.log('\n── a lone guide file with no images imports fine through the plain file picker ──');
const loneFile = new window.File(['{"topics":[]}'], 'lone_guide.json', { type: 'application/json' });
document.querySelector('#svImport').click();
Object.defineProperty(filePicker(), 'files', { value: [loneFile], writable: true, configurable: true });
filePicker().dispatchEvent(new window.Event('change'));
await tick();
ck('drop summary names the lone guide, no folder required',
   document.querySelector('#svImportDropS').textContent.includes('lone_guide.json'));
ck('confirm enabled off a single file', document.querySelector('#svImportModalConfirm').disabled === false);
document.querySelector('#svImportModalCancel').click();

console.log('\n── the progress bar tracks a multi-poll import and hides again after ──');
document.querySelector('#svImport').click();
document.querySelector('.sv-modebtn[data-mode="merge"]').click();
jobPollsUntilDone = 3;
Object.defineProperty(filePicker(), 'files', { value: [loneFile], writable: true, configurable: true });
filePicker().dispatchEvent(new window.Event('change'));
await tick();
ck('progress bar hidden before review starts', document.querySelector('#svImportProgress').hidden === true);
document.querySelector('#svMergeReviewBtn').click();
await tick(50);   // let the first (immediate) status poll land
ck('progress bar visible with a partial fill mid-import', (() => {
  const p = document.querySelector('#svImportProgress');
  const w = document.querySelector('#svImportProgressFill').style.width;
  return p.hidden === false && w !== '0%' && w !== '100%';
})(), document.querySelector('#svImportProgressFill').style.width);
await tick(700);   // let the remaining 300ms-apart polls resolve
ck('progress bar hidden again once the review completes',
   document.querySelector('#svImportProgress').hidden === true);
ck('review still completed successfully despite the extra polling',
   document.querySelectorAll('#svMergeReviewOut .sv-reviewlist li').length > 0);
jobPollsUntilDone = 1;
document.querySelector('#svImportModalCancel').click();

console.log('\n── new-vault mode: picking files prefills the name and previews the path ──');
const gFile = new window.File(['{"topics":[]}'], 'ldap_overview_guide.json', { type: 'application/json' });
const iFile = new window.File(['x'], 'slide1.png', { type: 'image/png' });
document.querySelector('#svImport').click();   // fresh modal -- reset the name field the previous section typed into
Object.defineProperty(filePicker(), 'files', { value: [gFile, iFile], writable: true, configurable: true });
filePicker().dispatchEvent(new window.Event('change'));
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
Object.defineProperty(filePicker(), 'files', { value: [gFile], writable: true, configurable: true });
filePicker().dispatchEvent(new window.Event('change'));
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

Object.defineProperty(filePicker(), 'files', { value: [gFile, iFile], writable: true, configurable: true });
filePicker().dispatchEvent(new window.Event('change'));
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
Object.defineProperty(filePicker(), 'files', { value: [gFile], writable: true, configurable: true });
filePicker().dispatchEvent(new window.Event('change'));
await tick();
document.querySelector('#svMergeReviewBtn').click();
await tick(60);
ck('confirm enabled right after review', document.querySelector('#svImportModalConfirm').disabled === false);
Object.defineProperty(filePicker(), 'files', { value: [gFile, iFile], writable: true, configurable: true });
filePicker().dispatchEvent(new window.Event('change'));
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
