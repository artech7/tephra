import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };
const $ = (s) => doc.querySelector(s);
const wait = (ms = 20) => new Promise((r) => setTimeout(r, ms));

console.log('── the elements this feature needs actually exist ──');
ck('lock button in the topbar', !!$('#lockBtn'));
ck('admin drawer', !!$('#admin'));
for (const id of ['newNote', 'favBtn', 'quizAdd', 'repairRun', 'reconcileRun', 'renameSave', 'wizCreateBtn'])
  ck(`#${id} is tagged admin-only`, $(`#${id}`)?.classList.contains('admin-only'), id);

// ── a fake backend, stateful enough to test setup -> lock -> unlock ->
// change-password as one continuous session, the same way a real browser
// would experience it against main.py's /api/admin/* routes ──
const backend = { configured: false, password: null };
let sessionValid = false;
const jres = (body, status = 200) => ({ ok: status < 300, status, json: async () => body, text: async () => JSON.stringify(body) });
const notes = [{ slug: 'a', title: 'A', tags: [], updated: new Date().toISOString(), backlinks: 0 }];

window.fetch = async (u, o = {}) => {
  const p = String(u);
  const method = o.method || 'GET';
  if (p.includes('/api/admin/status'))
    return jres({ configured: backend.configured, unlocked: backend.configured && sessionValid });
  if (p.includes('/api/admin/login') && method === 'POST') {
    if (!backend.configured) return jres({ detail: 'no admin password has been set yet' }, 400);
    const { password } = JSON.parse(o.body);
    if (password !== backend.password) return jres({ detail: 'wrong password' }, 401);
    sessionValid = true;
    return jres({ ok: true });
  }
  if (p.includes('/api/admin/logout') && method === 'POST') { sessionValid = false; return jres({ ok: true }); }
  if (p.includes('/api/admin/password') && method === 'POST') {
    const { password, current_password } = JSON.parse(o.body);
    if (password.length < 8) return jres({ detail: 'password must be at least 8 characters' }, 400);
    if (backend.configured && current_password !== backend.password)
      return jres({ detail: 'current password required to change it' }, 401);
    backend.configured = true; backend.password = password; sessionValid = true;
    return jres({ ok: true });
  }
  // Every other mutating call behaves like a real gated route once a
  // password is set and this "browser" hasn't unlocked.
  if (['POST', 'PUT', 'DELETE'].includes(method) && backend.configured && !sessionValid)
    return jres({ detail: 'locked -- unlock with the admin password to edit' }, 401);
  const body = p.includes('/api/theme') ? {} :
    p.includes('/api/notes/a') ? { slug: 'a', title: 'A', body: '', tags: [], meta: {}, html: '<p></p>', links_out: 0, media: [], backlinks: [], suggestions: [], words: 0, updated: new Date().toISOString() } :
    p.includes('/api/notes') ? notes :
    p.includes('/api/graph') ? { nodes: [], links: [] } :
    p.includes('/api/media') ? [] :
    p.includes('/api/repair/last') ? { changed: 0 } :
    p.includes('/api/study') ? { known_categories: [] } : {};
  return jres(body);
};

window.tephraStudy = { open: async () => {}, close: () => {}, isOpen: () => false, refresh: async () => {} };
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false, select: () => {} };
window.tephraStats = { open: async () => {}, close: () => {}, isOpen: () => false };
window.__tephraGraphInternals = { createSim: () => ({ running: () => false, tick() {}, nodes: [] }), W: 1000, H: 700 };
for (const el of [$('#mini'), $('#graph')]) { if (el) { el.getContext = () => null; el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 200 }); } }
$('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){ return { addColorStop(){} }; }, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
window.requestAnimationFrame = () => 0;
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1;
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
await wait(80);

console.log('\n── boots open: no password ever set ──');
ck('lock button shows the neutral "open" state', $('#lockBtn').dataset.state === 'open');
ck('html is not in locked mode', !doc.documentElement.classList.contains('locked'));
ck('note title is editable', $('#noteTitle').readOnly === false);

console.log('\n── first-time setup ──');
$('#lockBtn').onclick();
ck('admin drawer opens', $('#admin').classList.contains('on'));
ck('the setup pane is the one showing', $('#adminSetup').hidden === false);
ck('locked/unlocked panes are hidden', $('#adminLocked').hidden && $('#adminUnlocked').hidden);

$('#adminNewPw').value = 'wonderwall';
$('#adminNewPw2').value = 'different';
await $('#adminSetupBtn').onclick();
ck('mismatched confirmation is caught client-side, before any request',
   $('#adminSetupMsg').textContent.includes('match'));
ck('still not configured', backend.configured === false);

$('#adminNewPw2').value = 'wonderwall';
await $('#adminSetupBtn').onclick();
ck('password accepted', backend.configured === true, backend.configured);
ck('this browser is unlocked immediately after setting it', sessionValid === true);
ck('drawer closes on success', $('#admin').classList.contains('on') === false);
ck('lock button now shows unlocked', $('#lockBtn').dataset.state === 'unlocked');
ck('html is still not in locked mode (this browser is unlocked)',
   !doc.documentElement.classList.contains('locked'));

console.log('\n── locking, from the unlocked state ──');
$('#lockBtn').onclick();
ck('reopening while unlocked shows the "unlocked" pane', $('#adminUnlocked').hidden === false);
await $('#adminLockNowBtn').onclick();
ck('logged out server-side', sessionValid === false);
ck('lock button reflects locked', $('#lockBtn').dataset.state === 'locked');
ck('html gains .locked', doc.documentElement.classList.contains('locked'));
ck('note title becomes read-only', $('#noteTitle').readOnly === true);

console.log('\n── locked: the editor refuses to open, even via double-click ──');
$('#adminClose').onclick();
$('#noteBody').dispatchEvent(new window.Event('dblclick', { bubbles: true }));
await wait(20);
ck('source editor did not open', $('#noteSrc').hidden === true);

console.log('\n── unlocking with the wrong then right password ──');
$('#lockBtn').onclick();
ck('the locked pane is the one showing', $('#adminLocked').hidden === false);
$('#adminUnlockPw').value = 'not it';
await $('#adminUnlockBtn').onclick();
ck('wrong password reports an error inline', $('#adminUnlockMsg').textContent.includes('wrong password'));
ck('still locked', doc.documentElement.classList.contains('locked'));

$('#adminUnlockPw').value = 'wonderwall';
await $('#adminUnlockBtn').onclick();
ck('correct password unlocks', sessionValid === true);
ck('html loses .locked', !doc.documentElement.classList.contains('locked'));
ck('note title editable again', $('#noteTitle').readOnly === false);
ck('drawer closes on success', $('#admin').classList.contains('on') === false);

console.log('\n── changing the password always needs current_password, even while unlocked ──');
$('#lockBtn').onclick();
$('#adminChgPw').value = 'new wonderwall';
await $('#adminChangeBtn').onclick();
ck('caught client-side with no current password entered, before any request',
   $('#adminChangeMsg').textContent.includes('current password'));
ck('backend never called', backend.password === 'wonderwall');

$('#adminChgCurPw').value = 'wrong';
await $('#adminChangeBtn').onclick();
ck('server refuses a wrong current password', backend.password === 'wonderwall');
ck('reports the server error inline', $('#adminChangeMsg').textContent.includes('current password'));

$('#adminChgCurPw').value = 'wonderwall';
await $('#adminChangeBtn').onclick();
ck('rotation accepted with the right current password', backend.password === 'new wonderwall');
ck('still unlocked in this browser after rotating', sessionValid === true);
$('#adminClose').onclick();

console.log('\n── a 401 from anywhere else in the app opens the drawer too ──');
sessionValid = false;
ck('drawer starts closed for this check', $('#admin').classList.contains('on') === false);
try { await window.tephraApi('/notes', { method: 'POST', body: JSON.stringify({ title: 'x' }) }); } catch {}
await wait(20);
ck('a locked write opens the admin drawer on its own', $('#admin').classList.contains('on') === true);
ck('and explains why', $('#toast').textContent.toLowerCase().includes('locked'));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
