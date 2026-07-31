import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8400/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };
const css = fs.readFileSync(`${ROOT}/style.css`, 'utf8'), flat = css.replace(/\s+/g, '');

console.log('── the header is outside the sliding area ──');
const shell = doc.querySelector('.shell'), deck = doc.querySelector('.deck');
ck('topbar is a direct child of .shell', doc.querySelector('.topbar').parentElement === shell);
ck('topbar is NOT inside the deck', !deck.contains(doc.querySelector('.topbar')));
ck('notes side is inside the deck', deck.contains(doc.querySelector('.row')));
ck('graph is inside the deck too', deck.contains(doc.querySelector('#graphview')));
ck('deck clips its panes', /\.deck\{position:relative;flex:1;min-height:0;overflow:hidden\}/.test(flat));
ck('only .side and #studyview slide',
   flat.includes('body.crucible.side{left:-100%;right:100%}') &&
   flat.includes('body.crucible#studyview{left:0;right:0'));
ck('nothing shifts the whole shell any more', !flat.includes('body.crucible.shell{'));
ck('graph no longer covers the header', /#graphview\{position:absolute;inset:0/.test(flat));

console.log('\n── two wordmarks, no close button ──');
ck('Tephra is a button', doc.querySelector('#tephraBtn')?.tagName === 'BUTTON');
ck('Crucible is a button', doc.querySelector('#crucibleBtn')?.tagName === 'BUTTON');
ck('both styled as marks',
   doc.querySelector('#tephraBtn').classList.contains('mark') &&
   doc.querySelector('#crucibleBtn').classList.contains('mark'));
ck('Tephra starts pressed', doc.querySelector('#tephraBtn').getAttribute('aria-pressed') === 'true');
ck('Crucible has no data-view (not a canvas mode)', !doc.querySelector('#crucibleBtn').dataset.view);

// boot with stubs
const st = { open: false };
window.tephraStudy = { open: async () => { st.open = true; doc.body.classList.add('crucible'); },
  close: () => { st.open = false; doc.body.classList.remove('crucible'); },
  isOpen: () => st.open, refresh: async () => {} };
window.tephraGraph = { open: async () => {}, close: () => {}, isOpen: () => false, select: () => {} };
window.__tephraGraphInternals = { createSim: () => ({ running: () => false, tick() {}, nodes: [] }), W: 1000, H: 700 };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.devicePixelRatio = 1; window.requestAnimationFrame = () => 0;
window.fetch = async (u) => {
  const p = String(u);
  const b = p.includes('/api/theme') ? {} :
    p.includes('/api/notes/a') ? { slug:'a',title:'A',body:'',tags:[],meta:{},html:'<p></p>',links_out:0,media:[],backlinks:[],suggestions:[],words:0,updated:new Date().toISOString() } :
    p.includes('/api/notes') ? [{ slug:'a',title:'A',tags:[],updated:new Date().toISOString(),backlinks:0 }] :
    p.includes('/api/graph') ? { nodes:[],links:[] } : p.includes('/api/media') ? [] :
    p.includes('/api/study') ? { known_categories: [] } : {};
  return { ok:true, status:200, json: async () => b, text: async () => JSON.stringify(b) };
};
for (const id of ['#mini','#graph']) { const e = doc.querySelector(id); if (e) { e.getContext = () => null; e.getBoundingClientRect = () => ({left:0,top:0,width:300,height:200}); } }
doc.querySelector('#aurora').getContext = () => ({ fillRect(){}, createRadialGradient(){return{addColorStop(){}}}, beginPath(){}, arc(){}, fill(){}, clearRect(){}, setTransform(){} });
window.eval(fs.readFileSync(`${ROOT}/app.js`, 'utf8'));
await new Promise(r => setTimeout(r, 80));

console.log('\n── cycling with the header marks ──');
const pressed = (id) => doc.querySelector(id).getAttribute('aria-pressed');
doc.querySelector('#crucibleBtn').onclick();
await new Promise(r => setTimeout(r, 20));
ck('Crucible in', st.open && doc.body.classList.contains('crucible'));
ck('Crucible pressed, Tephra not', pressed('#crucibleBtn') === 'true' && pressed('#tephraBtn') === 'false');
doc.querySelector('#tephraBtn').onclick();
await new Promise(r => setTimeout(r, 20));
ck('Tephra brings the notes back', !st.open && !doc.body.classList.contains('crucible'));
ck('Tephra pressed again', pressed('#tephraBtn') === 'true' && pressed('#crucibleBtn') === 'false');

console.log('\n── leaving Crucible keeps the canvas mode you were in ──');
doc.querySelector('[data-view="graph"]').onclick(); await new Promise(r => setTimeout(r, 20));
ck('Graph active', pressed('[data-view="graph"]') === 'true');
doc.querySelector('#crucibleBtn').onclick(); await new Promise(r => setTimeout(r, 20));
ck('Graph stays selected while in Crucible', pressed('[data-view="graph"]') === 'true');
doc.querySelector('#tephraBtn').onclick(); await new Promise(r => setTimeout(r, 20));
ck('back to Graph, not Write', pressed('[data-view="graph"]') === 'true' && pressed('[data-view="write"]') === 'false');

console.log('\n── Crucible colours are derived, never equal to the accent ──');
const R = doc.documentElement;
const read = (v) => R.style.getPropertyValue(v).trim();
const hueOf = (h) => {
  const n = parseInt(h.slice(1), 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  if (!d) return -1;
  let x = mx === r ? ((g - b) / d + (g < b ? 6 : 0)) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return x * 60;
};
function check(name) {
  const acc = read('--accent').toLowerCase(), ca = read('--cruc-a').toLowerCase();
  const ha = hueOf(acc), hc = hueOf(ca);
  let diff = Math.abs(ha - hc); if (diff > 180) diff = 360 - diff;
  ck(`${name}: mark hue differs`, !!ca && acc !== ca && (ha < 0 || diff > 80),
     `accent ${acc} -> crucible ${ca}, ${ha < 0 ? 'grey accent' : diff.toFixed(0) + '\u00b0 apart'}`);
}
// drive it the way a user does: click the accent swatches
for (const [rgb, name] of [['63,224,173','jade'], ['255,157,110','peach (the wallpaper case)'],
                           ['183,156,255','violet'], ['198,242,78','lime']]) {
  doc.querySelector(`.sw[data-acc="${rgb}"]`).onclick();
  await new Promise(r => setTimeout(r, 10));
  check(name);
}
// and a fully desaturated accent via the colour picker
const pick = doc.querySelector('#accPick');
pick.value = '#808080'; pick.oninput({ target: pick });
await new Promise(r => setTimeout(r, 10));
ck('grey accent still yields a coloured Crucible mark',
   read('--cruc-a').toLowerCase() !== read('--accent').toLowerCase() && hueOf(read('--cruc-a')) >= 0,
   `accent ${read('--accent')} -> crucible ${read('--cruc-a')}`);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
