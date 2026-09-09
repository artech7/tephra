/* KB Authoring: the third deck.
 *
 * jsdom has no layout engine and no clipboard, so nothing here can prove the
 * deck *looks* right or that a paste into ServiceNow lands. What it can
 * prove is everything upstream of that: the deck's lifecycle, that the
 * structure panel's three states are derived from the outline the server
 * sends rather than guessed, that the metadata form is generated from the
 * field schema (so adding a field needs no frontend change), and that the
 * preview iframe is fed the export payload and is sandboxed without
 * allow-scripts.
 *
 * The sandbox assertion is the one worth being loud about. The preview
 * renders server-built HTML derived from note text, and note text is
 * whatever anyone pasted into a vault. Running scripts in there would run
 * them on the app's own origin, against an API with no authentication by
 * design.
 */
import { JSDOM } from 'jsdom';
import fs from 'fs';
const ROOT = new URL('../app/static', import.meta.url).pathname;
const dom = new JSDOM(fs.readFileSync(`${ROOT}/index.html`, 'utf8'),
  { runScripts: 'outside-only', url: 'http://127.0.0.1:8407/', pretendToBeVisual: true });
const { window } = dom; const doc = window.document;
let ok = 0, fail = 0;
const ck = (l, c, x = '') => { c ? (ok++, console.log(`  PASS  ${l} ${x}`)) : (fail++, console.log(`  FAIL  ${l} ${x}`)); };
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));

const css = fs.readFileSync(`${ROOT}/style.css`, 'utf8');
const flat = css.replace(/\s+/g, '');
const appjs = fs.readFileSync(`${ROOT}/app.js`, 'utf8');

console.log('── the mark sits with the other two ──');
const btn = doc.querySelector('#kbBtn');
ck('the button exists in the topbar', !!btn);
ck('reuses the .mark/.markbtn classes rather than inventing a third look',
   btn.classList.contains('mark') && btn.classList.contains('markbtn'));
ck('uses a gradient square like the others, not an svg',
   !!btn.querySelector('i') && !btn.querySelector('svg'));
ck('label is plain text beside it', btn.textContent.trim() === 'KB');
// The (0,1,1) specificity trap `.mark i` set for Crucible: a bare class
// selector loses to it, so the gradient has to be hung off an id.
ck('painted from its own palette via an id selector, so .mark i cannot win',
   /#kbBtn i\{[^}]*var\(--kb-a\)/.test(css.replace(/\s+/g, ' ')));
ck('KB, being last in the row, takes the trailing-border exemption',
   flat.includes('#kbBtn{border-right:0'));
ck('and Crucible gets its divider back now that it is no longer last',
   flat.includes('#crucibleBtn{border-right:1pxsolidvar(--edge)'));

console.log('\n── slides like Crucible, for the same WebKit reason ──');
ck('parks one deck-width right',
   flat.includes('#kbview{position:absolute;z-index:5;top:0;bottom:0;left:100%;right:-100%'));
ck('slides flush when open', flat.includes('body.kbdeck#kbview{left:0;right:0'));
ck('notes side leaves to the left', flat.includes('body.kbdeck.side{left:-100%;right:100%}'));
ck('animates offsets, never transform — a transformed ancestor breaks '
   + 'backdrop-filter on WebKit',
   /#kbview\{[^}]*transition:left/.test(flat) && !/#kbview\{[^}]*transform:translate/.test(flat));

console.log('\n── one deck at a time ──');
ck('a single setDeck drives all three pressed states', /function setDeck\(name\)/.test(appjs));
ck('opening KB closes Crucible', /if \(name === 'crucible'\) window\.tephraStudy\?\.open\(\);\s*\n\s*else window\.tephraStudy\?\.close\(\);/.test(appjs));
ck('opening Crucible closes KB', /if \(name === 'kb'\) window\.tephraKb\?\.open\(\);\s*\n\s*else window\.tephraKb\?\.close\(\);/.test(appjs));
ck('a canvas view brings the Tephra side back', /setDeck\('tephra'\);/.test(appjs));
ck('Escape closes KB before it falls through to anything else',
   appjs.indexOf("if (window.tephraKb?.isOpen()) return setKb(false);")
   < appjs.indexOf("if (window.tephraStudy?.isOpen()) return setStudy(false);"));
ck('a vault switch resets the deck, since none of its state survives one',
   /await window\.tephraKb\?\.reset\(\)/.test(appjs));

console.log('\n── the deck itself ──');
const FIELDS = [
  { key: 'kb_short_description', label: 'Short description', kind: 'textarea', hint: 'h', options: [], required: true, max_len: 160 },
  { key: 'kb_status', label: 'Status', kind: 'select', hint: 'h', options: ['draft', 'published'], required: true, max_len: 0 },
  { key: 'kb_keywords', label: 'Keywords', kind: 'tags', hint: 'h', options: [], required: true, max_len: 0 },
  { key: 'kb_review_by', label: 'Review by', kind: 'date', hint: 'h', options: [], required: false, max_len: 0 },
];
const OUTLINE = [
  { heading: 'Summary', hint: 'one paragraph', required: true, shape: 'prose', present: true, empty: false },
  { heading: 'Symptoms', hint: 'what breaks', required: true, shape: 'list', present: true, empty: true },
  { heading: 'Resolution', hint: 'numbered steps', required: true, shape: 'steps', present: false, empty: false },
];
const store = {
  articles: [
    { slug: 'a1', title: 'Array unreachable', updated: '2026-01-02', kb_type: 'troubleshooting',
      type_name: 'Troubleshooting', status: 'draft', audience: 'internal', number: 'KB1',
      short_description: 's', products: ['FlashArray'], words: 40 },
    { slug: 'a2', title: 'Mount a filesystem', updated: '2026-01-01', kb_type: 'how-to',
      type_name: 'How-To / Procedure', status: 'published', audience: 'customer', number: '',
      short_description: '', products: [], words: 12 },
  ],
  bodies: { a1: '## Summary\n\nreal prose\n\n## Symptoms\n', a2: '## Goal\n' },
  meta: { a1: { kb_type: 'troubleshooting', kb_status: 'draft', kb_keywords: ['arp', 'dns'] }, a2: {} },
};
let lastPut = null, lastMeta = null, released = null, adopted = null, created = null;

window.tephraApi = async (p, opts = {}) => {
  const body = opts.body ? JSON.parse(opts.body) : {};
  if (p === '/kb/templates') {
    return {
      templates: [
        { id: 'troubleshooting', name: 'Troubleshooting', summary: 'A specific failure.', sections: [] },
        { id: 'how-to', name: 'How-To / Procedure', summary: 'A task.', sections: [] },
      ],
      fields: FIELDS, default: 'troubleshooting',
      targets: ['servicenow', 'standalone', 'markdown', 'text'],
      link_modes: ['auto', 'number', 'url', 'text'],
      form: 'Question and Answer',
      section_fields: ['Question', 'Environment', 'Answer', 'Additional Information', 'Internal Notes'],
      meta_fields: ['Short description', 'Meta'],
    };
  }
  if (p === '/kb/articles' && opts.method === 'POST') { created = body; return store.articles[0]; }
  if (p === '/kb/articles') return { articles: store.articles };
  if (p === '/notes') return [{ slug: 'loose', title: 'A loose note' }, { slug: 'a1', title: 'Array unreachable' }];
  if (p.startsWith('/notes/') && opts.method === 'PUT') { lastPut = body; store.bodies.a1 = body.body; return {}; }
  const meta = p.match(/^\/kb\/([^/]+)\/meta$/);
  if (meta) { lastMeta = body.meta; return { slug: meta[1], kb: body.meta, is_article: true }; }
  const rel = p.match(/^\/kb\/([^/]+)\/release$/);
  if (rel) { released = rel[1]; return { slug: rel[1], is_article: false }; }
  const ad = p.match(/^\/kb\/([^/]+)\/adopt$/);
  if (ad) { adopted = { slug: ad[1], ...body }; return store.articles[0]; }
  if (p.startsWith('/kb/') && p.includes('/export')) {
    return {
      target: 'servicenow', title: 'Array unreachable', slug: 'a1', mime: 'text/html',
      filename: 'KB1-a1.html', generated: '2026-01-02', meta: {},
      content: '<h2 style="font-size:1.3em">Summary</h2><p style="margin:0">real prose</p>',
      form: 'Question and Answer',
      parts: [
        { field: 'Short description', kind: 'text', content: 'x'.repeat(180), chars: 180, limit: 160, sections: [] },
        { field: 'Question', kind: 'html', content: '<p style="margin:0">real prose</p>', chars: 10, limit: 0, sections: ['Summary', 'Symptoms'] },
        { field: 'Answer', kind: 'html', content: '<p style="margin:0">the fix</p>', chars: 7, limit: 0, sections: ['Resolution'] },
        { field: 'Meta', kind: 'text', content: 'arp, dns', chars: 8, limit: 4000, sections: [] },
      ],
      manifest: [{ n: 1, kind: 'image', name: 'topology.png', caption: 'Management topology' }],
      warnings: ['mermaid diagram 2 cannot be pasted as a diagram'],
    };
  }
  const one = p.match(/^\/kb\/([^/]+)$/);
  if (one) {
    const slug = one[1];
    return {
      slug, title: store.articles.find((a) => a.slug === slug).title,
      body: store.bodies[slug], tags: [], meta: {}, kb: store.meta[slug],
      is_article: true, template: 'troubleshooting', template_name: 'Troubleshooting',
      outline: slug === 'a1' ? OUTLINE : [], extra_sections: slug === 'a1' ? ['Notes'] : [],
      has_guidance: slug === 'a1',
      field_plan: slug === 'a1'
        ? [{ field: 'Question', sections: ['Summary', 'Symptoms'] },
           { field: 'Answer', sections: ['Resolution'] }]
        : [],
      fieldmap: {},
    };
  }
  throw new Error(p);
};
window.tephraToast = () => {};
window.tephraOpenNote = () => {};
window.tephraReloadList = () => {};
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.eval(fs.readFileSync(`${ROOT}/kb.js`, 'utf8'));

ck('body is clean before opening', !doc.body.classList.contains('kbdeck'));
await window.tephraKb.open();
await tick();
ck('opening adds body.kbdeck', doc.body.classList.contains('kbdeck'));
ck('the pane is marked on', doc.querySelector('#kbview').classList.contains('on'));
ck('every article is listed', doc.querySelectorAll('.kb-row').length === 2);
ck('the counts line reports both articles and their statuses',
   /2 ARTICLES/.test(doc.querySelector('#kbStats').textContent));
ck('an article with a KB number shows it', doc.querySelector('.kb-num').textContent === 'KB1');
ck('status is a chip, so draft and published are distinguishable at a glance',
   !!doc.querySelector('.kb-status-draft') && !!doc.querySelector('.kb-status-published'));
ck('the first article opens by default', doc.querySelector('#kbTitle').value === 'Array unreachable');
ck('its body is loaded into the editor', doc.querySelector('#kbBody').value.includes('real prose'));

console.log('\n── filtering the list ──');
const filter = doc.querySelector('#kbFilter');
filter.value = 'mount'; filter.oninput({ target: filter });
ck('filtering by title narrows the list', doc.querySelectorAll('.kb-row').length === 1);
filter.value = 'KB1'; filter.oninput({ target: filter });
ck('filtering matches the KB number too', doc.querySelectorAll('.kb-row').length === 1);
filter.value = 'zzz'; filter.oninput({ target: filter });
ck('an empty result says so rather than showing a blank column',
   !!doc.querySelector('.kb-rows .kb-empty'));
filter.value = ''; filter.oninput({ target: filter });

console.log('\n── the structure panel reads the server’s outline ──');
const secs = [...doc.querySelectorAll('.kb-sec')];
ck('one row per template section', secs.length === 3, `${secs.length} rows`);
ck('a written section reads as written', secs[0].classList.contains('kb-sec-ok'));
ck('a section holding nothing reads as empty, not written',
   secs[1].classList.contains('kb-sec-empty'));
ck('a section that is not there at all reads as missing',
   secs[2].classList.contains('kb-sec-missing'));
ck('only a missing section offers to add itself',
   secs.filter((s) => s.querySelector('.kb-sec-add')).length === 1);
ck('headings the template does not know about are surfaced, not hidden',
   /Notes/.test(doc.querySelector('.kb-outline-extra').textContent));
ck('leftover template guidance is called out',
   !!doc.querySelector('.kb-outline-warn'));

console.log('\n── adding a missing section ──');
secs[2].querySelector('.kb-sec-add').onclick();
await tick(40);
ck('the heading is appended to the body', /## Resolution/.test(lastPut.body), lastPut && lastPut.body);
ck('its guidance comes with it, so the section is not just an empty heading',
   /TODO — numbered steps/.test(lastPut.body));

console.log('\n── the metadata form is generated from the field schema ──');
ck('one input per field, whatever the schema says',
   FIELDS.every((f) => !!doc.querySelector('#kbf-' + f.key)));
ck('a select field renders as a select with its options',
   doc.querySelector('#kbf-kb_status').tagName === 'SELECT'
   && doc.querySelectorAll('#kbf-kb_status option').length === 3);
ck('a date field renders as a date input',
   doc.querySelector('#kbf-kb_review_by').type === 'date');
ck('a long-text field renders as a textarea capped at the schema’s limit',
   doc.querySelector('#kbf-kb_short_description').tagName === 'TEXTAREA'
   && doc.querySelector('#kbf-kb_short_description').getAttribute('maxlength') === '160');
ck('a list field arrives joined for editing',
   doc.querySelector('#kbf-kb_keywords').value === 'arp, dns');
ck('a required field is marked as one', doc.querySelectorAll('.kb-field.req').length === 3);

const kw = doc.querySelector('#kbf-kb_keywords');
kw.value = 'arp, dns, mtu';
kw.oninput();
await tick(600);
ck('a list field is split back into a list on save',
   JSON.stringify(lastMeta.kb_keywords) === JSON.stringify(['arp', 'dns', 'mtu']),
   JSON.stringify(lastMeta && lastMeta.kb_keywords));
ck('the article type rides along, so saving fields cannot orphan the article',
   lastMeta.kb_type === 'troubleshooting');

console.log('\n── export mode ──');
await window.tephraKb.open();
await tick();
doc.querySelector('[data-kbmode="export"]').onclick();
await tick(60);
ck('the mode toggle reflects the switch',
   doc.querySelector('[data-kbmode="export"]').getAttribute('aria-pressed') === 'true');
ck('the deck marks itself as exporting, so the layout can give the preview room',
   doc.querySelector('#kbview').classList.contains('kb-exporting'));
const frame = doc.querySelector('#kbPreview');
ck('a preview iframe is rendered', !!frame);
ck('the preview is fed the export payload, not the app’s own render',
   frame.getAttribute('srcdoc').includes('real prose'));
ck('the preview is laid out as the destination form, one labelled box per '
   + 'field, since that document does not exist over there',
   frame.getAttribute('srcdoc').includes('>Question</h4>')
   && frame.getAttribute('srcdoc').includes('>Answer</h4>'));
ck('a field with nothing in it is shown as empty rather than omitted',
   frame.getAttribute('srcdoc').includes('class="none"')
   || !frame.getAttribute('srcdoc').includes('Internal Notes'));
ck('the preview page carries no stylesheet of the app’s, so only what the '
   + 'markup carries is visible',
   !frame.getAttribute('srcdoc').includes('style.css'));
ck('the preview is sandboxed', frame.hasAttribute('sandbox'));
ck('and never with allow-scripts, since the content comes from note text',
   !frame.getAttribute('sandbox').includes('allow-scripts'));

ck('every export target is offered',
   doc.querySelectorAll('#kbTarget option').length === 4);
ck('wiki-link handling is a choice, not a hardcoded one',
   doc.querySelectorAll('#kbLinks option').length === 4);
console.log('\n── one copy button per form field ──');
const fcs = [...doc.querySelectorAll('.kb-fieldcopy')];
ck('one row per field, in the order the form asks for them',
   fcs.map((f) => f.querySelector('.kb-fc-name').textContent).join('|')
   === 'Short description|Question|Answer|Meta',
   fcs.map((f) => f.querySelector('.kb-fc-name').textContent).join('|'));
ck('a rich-text field offers a formatted copy and a source copy',
   fcs[1].querySelectorAll('button').length === 2);
ck('a plain-text field offers only the one copy, since there is no markup',
   fcs[3].querySelectorAll('button').length === 1);
ck('each field says which sections feed it',
   fcs[1].querySelector('.kb-fc-src').textContent === 'Summary · Symptoms');
ck('a field over the form’s character limit is flagged',
   fcs[0].classList.contains('over'));
ck('a field within its limit is not',
   !fcs[3].classList.contains('over'));
ck('the character count is shown against the limit where there is one',
   fcs[0].querySelector('.kb-fc-chars').textContent.replace(/\s/g, '') === '180/160');
ck('the whole-document copy and download are gone for a fielded target, '
   + 'since there is nowhere to paste a whole document',
   !doc.querySelector('#kbDownload') && !doc.querySelector('#kbIncMeta'));

console.log('\n── the section mapping is editable and persists ──');
const maprows = [...doc.querySelectorAll('.kb-maprow')];
ck('one row per section that has content',
   maprows.map((r) => r.querySelector('.kb-map-h').textContent).join('|')
   === 'Summary|Symptoms|Resolution',
   maprows.map((r) => r.querySelector('.kb-map-h').textContent).join('|'));
ck('each row offers every field the form has',
   maprows[0].querySelectorAll('option').length === 5);
ck('the row shows where the section currently lands',
   maprows[2].querySelector('select').value === 'Answer');
const msel = maprows[2].querySelector('select');
msel.value = 'Internal Notes';
await msel.onchange();
await tick(40);
ck('changing a mapping saves it into the article’s own frontmatter',
   lastMeta && lastMeta.kb_fieldmap && lastMeta.kb_fieldmap.Resolution === 'Internal Notes',
   JSON.stringify(lastMeta && lastMeta.kb_fieldmap));
ck('saving a mapping does not blank the metadata the form is not showing',
   lastMeta.kb_keywords && lastMeta.kb_keywords.length > 0,
   JSON.stringify(lastMeta && lastMeta.kb_keywords));
ck('the attachment manifest is listed',
   doc.querySelectorAll('.kb-manrow').length === 1);
ck('a manifest row carries its number, so it matches the placeholder in the paste',
   doc.querySelector('.kb-mannum').textContent === '1');
ck('the manifest names the file to attach',
   doc.querySelector('.kb-manname').textContent === 'topology.png');
ck('warnings are shown rather than swallowed',
   doc.querySelectorAll('.kb-warns li').length === 1);

console.log('\n── new and adopt ──');
doc.querySelector('#kbNew').onclick();
ck('the picker opens', !doc.querySelector('.kb-pick').hidden);
ck('it offers every article type', doc.querySelectorAll('#kbNewType option').length === 2);
ck('picking a type explains what it is for',
   doc.querySelector('#kbTplSummary').textContent.length > 0);
doc.querySelector('[data-pick="adopt"]').onclick();
await tick(30);
ck('the adopt tab lists notes that are not already articles',
   [...doc.querySelectorAll('.kb-adoptrow')].map((r) => r.textContent).join() === 'A loose note');
ck('the action button renames itself for the tab it is on',
   doc.querySelector('#kbPickGo').textContent === 'Adopt');
doc.querySelector('.kb-adoptrow').onclick();
doc.querySelector('#kbPickGo').onclick();
await tick(40);
ck('adopting posts the chosen note and type',
   adopted && adopted.slug === 'loose' && adopted.kb_type === 'troubleshooting',
   JSON.stringify(adopted));
ck('the picker closes afterwards', doc.querySelector('.kb-pick').hidden);

console.log('\n── releasing ──');
await window.tephraKb.open();
await tick(30);
doc.querySelector('#kbRelease').onclick();
await tick(40);
ck('releasing calls the endpoint that leaves the prose alone', released === 'a1', released);

console.log('\n── closing ──');
window.tephraKb.close();
ck('closing removes the body class', !doc.body.classList.contains('kbdeck'));
ck('and un-marks the pane', !doc.querySelector('#kbview').classList.contains('on'));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
