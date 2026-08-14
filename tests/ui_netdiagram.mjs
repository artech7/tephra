import { JSDOM } from 'jsdom'; import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8404/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };

/* ── pure parser/layout/serialize checks need no note open at all ── */
window.eval(fs.readFileSync(`${ROOT}/netdiagram.js`, 'utf8'));
const ndg = window.tephraNetDiagram;

console.log('── parser: nesting, range expansion/pairing, graceful errors ──');
{
  const m = ndg.parse('device a "A"\ndevice a.sub "Sub" at 5,5\nlink a.ETH1-4 -> a.sub.ETH1-4 "x" #A\n');
  ck('top-level + nested device both parsed', m.devices.size === 2 && m.devices.has('a.sub'));
  ck('nested device carries its parentId', m.devices.get('a.sub').parentId === 'a');
  ck('a dotted port path resolves against the longest declared device id', m.links[0].fromDevice === 'a' && m.links[0].toDevice === 'a.sub');
  ck('a numeric range expands to N individual ports', m.links[0].fromPorts.join(',') === 'ETH1,ETH2,ETH3,ETH4');
  ck('no errors on well-formed input', m.errors.length === 0, m.errors);
}
{
  const m = ndg.parse('device a "A"\nlink a.P1 -> a.P1 "loop"\n');
  ck('a non-numeric port name is a single port, not a range', ndg.expandPortSpec('Console').join(',') === 'Console');
}
{
  const bad = ndg.parse([
    'device a "A"', 'device b "B"', 'device c.d "nested before parent"',
    'link a.ETH1-4 -> b.ETH1-2 "mismatch"', 'link a.P1 -> nope.P1 "unknown"', 'garbage line',
  ].join('\n'));
  ck('a device nested under an undeclared parent is rejected, not silently dropped elsewhere',
     !bad.devices.has('c.d') && bad.errors.some((e) => e.message.includes('not declared yet')));
  ck('a mismatched port-range pairing is an error, not a crash',
     bad.errors.some((e) => e.message.includes('Port count mismatch')));
  ck('an unknown device in a link is an error', bad.errors.some((e) => e.message.includes('Unknown device')));
  ck('a genuinely unrecognized line is an error too', bad.errors.some((e) => e.message === 'Unrecognized line'));
  ck('the two good devices still parsed despite the bad lines around them',
     bad.devices.has('a') && bad.devices.has('b'), [...bad.devices.keys()]);
}

console.log('\n── layout: auto-placement, nesting wraps children, bundled links share one anchor ──');
{
  const m = ndg.parse('device a "Alpha"\ndevice b "Beta"\nlink a.P1 -> b.P1 "x"\n');
  const pos = ndg.layout(m);
  ck('two auto-placed top-level devices do not overlap',
     pos.get('b').x >= pos.get('a').x + pos.get('a').w, [pos.get('a'), pos.get('b')]);
}
{
  const m = ndg.parse('device p "Parent"\ndevice p.k1 "Kid 1"\ndevice p.k2 "Kid 2"\n');
  const pos = ndg.layout(m);
  const parent = pos.get('p'), k1 = pos.get('p.k1'), k2 = pos.get('p.k2');
  ck('both children sit inside the parent box horizontally',
     k1.x >= parent.x && k1.x + k1.w <= parent.x + parent.w, [parent, k1]);
  ck('children are stacked, not overlapping each other', k2.y >= k1.y + k1.h, [k1, k2]);
  ck('the parent box is tall enough to actually contain both children',
     parent.y + parent.h >= k2.y + k2.h, [parent, k2]);
}

console.log('\n── grid devices: ports are derived from links, never separately declared ──');
{
  const m = ndg.parse('device sw "Switch" grid\ndevice a "A"\nlink sw.ETH1-4 -> a.P1-4 "x"\n');
  ck('the grid flag parses', m.devices.get('sw').grid === true);
  ck('a plain device defaults to grid:false', m.devices.get('a').grid === false);
  ck('grid survives a serialize round-trip', ndg.serialize(m).includes('device sw "Switch" grid'), ndg.serialize(m));

  const pos = ndg.layout(m);
  const sw = pos.get('sw');
  // Not instanceof Map -- netdiagram.js runs inside the jsdom window's own
  // realm (window.eval), so its Map constructor isn't reference-equal to
  // this script's own global Map even for a genuine Map instance.
  ck('a grid device gets a portCells map', typeof sw.portCells?.get === 'function' && sw.portCells.size === 4, sw);
  ck('exactly the 4 referenced ports appear, in natural numeric order',
     [...sw.portCells.keys()].join(',') === 'ETH1,ETH2,ETH3,ETH4', [...sw.portCells.keys()]);
  ck('a port never mentioned in a link never appears',
     !sw.portCells.has('ETH5'));

  const anchors = ndg.anchors(m, pos);
  const anchor = anchors.get('0:from');
  const eth1 = sw.portCells.get('ETH1'), eth4 = sw.portCells.get('ETH4');
  ck('the bundled link\'s anchor sits at the centroid of the ports it actually spans, not a generic edge point',
     anchor.x === (eth1.x + eth4.x) / 2 && anchor.y === (eth1.y + eth4.y) / 2, [anchor, eth1, eth4]);
}
{
  const many = ['device sw "Switch" grid', 'device a "A"'];
  for (let i = 1; i <= 20; i++) many.push(`device a.p${i} "p${i}"`);
  // 20 ports referenced across 5 bundled links -- exercises the wrap-to-
  // multiple-rows path (MAX_COLS is 8), matching the real XFM's port count.
  const linkLines = [];
  for (let i = 1; i <= 20; i += 4) linkLines.push(`link sw.ETH${i}-${i + 3} -> a.p${i}-${i + 3} "x"`);
  const m2 = ndg.parse(many.slice(0, 2).concat(linkLines).join('\n'));
  ck('no errors on a 20-port grid device', m2.errors.length === 0, m2.errors);
  const pos2 = ndg.layout(m2);
  ck('all 20 ports laid out', pos2.get('sw').portCells.size === 20);
  ck('wraps into multiple rows rather than one absurdly wide box',
     pos2.get('sw').h > 50 && pos2.get('sw').w < 500, pos2.get('sw'));
}

console.log('\n── serializer round-trips the user\'s actual XFM cabling example ──');
{
  const xfm = [
    'device xfmA "XFM-8400 A" at 40,40',
    'device xfmB "XFM-8400 B" at 40,260',
    'device c1 "Chassis 1" at 420,40',
    'device c1.fiom0 "FIOM 0" at 10,10',
    'device c1.fiom1 "FIOM 1" at 10,90',
    '',
    'link xfmA.ETH1-4 -> c1.fiom0.ETH1-4 "100G QSFP28" #A',
    'link xfmB.ETH1-4 -> c1.fiom1.ETH1-4 "100G QSFP28" #B',
  ].join('\n');
  const m1 = ndg.parse(xfm);
  const again = ndg.parse(ndg.serialize(m1));
  ck('no parse errors on the real example', m1.errors.length === 0, m1.errors);
  ck('same device count after a round-trip', again.devices.size === m1.devices.size);
  ck('same link count after a round-trip', again.links.length === m1.links.length);
  ck('nesting survives the round-trip', again.devices.get('c1.fiom0').parentId === 'c1');
  ck('explicit positions survive the round-trip', again.devices.get('xfmA').x === 40 && again.devices.get('xfmA').y === 40);
  ck('range fan-out still pairs correctly after the round-trip',
     again.links[0].fromPorts.length === 4 && again.links[0].toPorts.length === 4);
}

/* ── everything below needs a real open note: enhance() reads live DOM,
   and the editor's save path goes through app.js's state/touched bridge
   (window.tephraSaveNoteBody), the same arm's-length relationship
   ui_mermaid_resize.mjs already exercises for setMermaidWidth. ──────── */

// The DSL text itself (what enhance() reads from the rendered card's own
// textContent) vs. the *note's* raw markdown body (what setNetDiagramBody
// has to find and rewrite a ```netdiagram fence inside of) are two
// different strings -- easy to conflate, since render.py strips the fence
// markers when it emits the <div>.
const ndgText = [
  'device a "Device A"',
  'device b "Device B"',
  '',
  'link a.P1 -> b.P1 "link" #A',
].join('\n');
const noteBody = '```netdiagram\n' + ndgText + '\n```\n';
const noteHtml = `<div class="netdiagram" data-netdiagram-index="0">${ndgText}</div>`;

const calls = [];
window.fetch = async (u, o = {}) => {
  const p = String(u); calls.push({ p, body: o.body }); let b = {};
  if (/\/api\/notes\/n$/.test(p) && (!o.method || o.method === 'GET')) {
    b = { slug: 'n', title: 'N', body: noteBody, tags: [], meta: {}, html: noteHtml,
          links_out: 0, media: [], backlinks: [], suggestions: [], words: 1,
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
await new Promise((r) => setTimeout(r, 150));

const fire = (el, type, opts = {}) => el.dispatchEvent(new window.MouseEvent(type, { bubbles: true, button: 0, ...opts }));

console.log('\n── enhance() renders the fence into a real SVG in the note body ──');
const card = doc.querySelector('#noteBody .netdiagram');
ck('the card was rendered', !!card);
ck('two device boxes drawn', card.querySelectorAll('.ndg-device').length === 2);
ck('one link drawn', card.querySelectorAll('.ndg-link').length === 1);
ck('an Edit button is present', !!card.querySelector('.ndg-edit-btn'));

console.log('\n── opening the editor ──');
card.querySelector('.ndg-edit-btn').click();
ck('overlay is shown', doc.querySelector('#ndgEditor').classList.contains('on'));
ck('canvas has the same two devices', doc.querySelectorAll('#ndgCanvas .ndg-device').length === 2);

console.log('\n── dragging a device moves it and persists an explicit position ──');
const devA = doc.querySelector('#ndgCanvas .ndg-device[data-id="a"]');
fire(devA, 'mousedown', { clientX: 100, clientY: 100 });
fire(doc, 'mousemove', { clientX: 160, clientY: 130 });
fire(doc, 'mouseup', { clientX: 160, clientY: 130 });
await new Promise((r) => setTimeout(r, 600));
ck('#noteSrc now carries an explicit position for device a',
   /device a "Device A" at \d+,\d+/.test(doc.querySelector('#noteSrc').value), doc.querySelector('#noteSrc').value);

console.log('\n── editing a device\'s label via the inspector ──');
const labelInput = doc.querySelector('#ndgInspector .ndg-field input');
ck('inspector shows the selected device\'s label field', labelInput?.value === 'Device A', labelInput?.value);
labelInput.value = 'Renamed A';
labelInput.dispatchEvent(new window.Event('change', { bubbles: true }));
await new Promise((r) => setTimeout(r, 600));
ck('the rename is reflected in the note body', doc.querySelector('#noteSrc').value.includes('"Renamed A"'), doc.querySelector('#noteSrc').value);

console.log('\n── adding a device from the toolbar ──');
doc.querySelector('#ndgAddDevice').click();
ck('a third device appears on the canvas', doc.querySelectorAll('#ndgCanvas .ndg-device').length === 3);

console.log('\n── drawing a new link by clicking two devices in link mode ──');
doc.querySelector('#ndgAddLink').click();
ck('hint asks for the source device first', doc.querySelector('#ndgInspector').textContent.includes('source device'));
fire(doc.querySelector('#ndgCanvas .ndg-device[data-id="a"]'), 'mousedown', { clientX: 50, clientY: 50 });
ck('hint now asks for the destination', doc.querySelector('#ndgInspector').textContent.includes('destination'));
fire(doc.querySelector('#ndgCanvas .ndg-device[data-id="b"]'), 'mousedown', { clientX: 200, clientY: 50 });
ck('a second link now exists', doc.querySelectorAll('#ndgCanvas .ndg-link').length === 2);
ck('the new link is auto-selected, showing its port fields for editing',
   [...doc.querySelectorAll('#ndgInspector .ndg-field span')].some((s) => s.textContent === 'From ports'));

console.log('\n── editing the new link\'s ports, with a bad edit rejected gracefully ──');
const fromInput = [...doc.querySelectorAll('#ndgInspector .ndg-field')]
  .find((f) => f.querySelector('span').textContent === 'From ports').querySelector('input');
fromInput.value = 'ETH1-4';
fromInput.dispatchEvent(new window.Event('change', { bubbles: true }));
await new Promise((r) => setTimeout(r, 600));
ck('a mismatched range is rejected -- still the original single port, not corrupted',
   doc.querySelector('#noteSrc').value.includes('link a.PORT1 -> b.PORT1'), doc.querySelector('#noteSrc').value);

console.log('\n── deleting a link (double-click-armed, like Quiz\'s delete buttons) ──');
const deleteBtn = [...doc.querySelectorAll('#ndgInspector .ndg-btn-danger')].find((b) => b.textContent === 'Delete');
deleteBtn.click();
ck('first click only arms it, does not delete yet', doc.querySelectorAll('#ndgCanvas .ndg-link').length === 2);
deleteBtn.click();
ck('second click confirms the delete', doc.querySelectorAll('#ndgCanvas .ndg-link').length === 1);

console.log('\n── toggling grid layout on a device from the inspector ──');
fire(doc.querySelector('#ndgCanvas .ndg-device[data-id="a"]'), 'mousedown', { clientX: 50, clientY: 50 });
fire(doc, 'mouseup', { clientX: 50, clientY: 50 });
const gridCheckbox = doc.querySelector('#ndgInspector .ndg-checkrow input');
ck('inspector offers a grid-layout checkbox for the selected device', !!gridCheckbox);
ck('starts unchecked', gridCheckbox.checked === false);
gridCheckbox.checked = true;
gridCheckbox.dispatchEvent(new window.Event('change', { bubbles: true }));
ck('device a\'s box now shows its one referenced port ("P1") as a cell',
   doc.querySelectorAll('#ndgCanvas .ndg-device[data-id="a"] .ndg-port-cell').length === 1,
   [...doc.querySelectorAll('#ndgCanvas .ndg-device[data-id="a"] .ndg-port-label')].map((t) => t.textContent));
await new Promise((r) => setTimeout(r, 600));
ck('the grid keyword persists into the note body', doc.querySelector('#noteSrc').value.includes('device a "Renamed A" at'), doc.querySelector('#noteSrc').value);
ck('...specifically with grid appended', /device a "Renamed A" at \d+,\d+ grid/.test(doc.querySelector('#noteSrc').value), doc.querySelector('#noteSrc').value);

console.log('\n── closing the editor re-renders the inline card from the edited model ──');
doc.querySelector('#ndgClose').click();
ck('overlay hides', !doc.querySelector('#ndgEditor').classList.contains('on'));
ck('the inline card now shows three devices too', doc.querySelectorAll('#noteBody .ndg-device').length === 3);

console.log('\n── the edits autosaved along the way ──');
await new Promise((r) => setTimeout(r, 800));  // touched()'s own 700ms debounce
const put = calls.filter((c) => c.p.endsWith('/api/notes/n') && c.body).pop();
ck('a save went out carrying the edited diagram', !!put && JSON.parse(put.body).body.includes('Renamed A'), put && put.body);

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
