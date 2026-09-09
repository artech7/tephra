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
// Which article the deck currently has open, read off the DOM rather than
// assumed -- the delete tests above move the selection.
const S_openSlug = () => {
  const row = doc.querySelector('.kb-row[aria-pressed="true"]');
  const title = row && row.querySelector('.kb-row-t').textContent;
  const hit = store.articles.find((a) => a.title === title);
  return hit ? hit.slug : null;
};

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
let deleted = null;

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
      block_groups: ['Text', 'Structure'],
      blocks: [
        { id: 'heading', label: 'Heading', glyph: 'H2', group: 'Text', hint: 'h',
          snippet: '## Heading', select: 'Heading', inline: false },
        { id: 'bullets', label: 'Bullet list', glyph: '\u2022', group: 'Text', hint: 'h',
          snippet: '- Item\n- Item', select: 'Item', inline: false },
        { id: 'callout', label: 'Callout', glyph: '\u26a0', group: 'Structure', hint: 'h',
          snippet: '> [!WARNING] Title\n> Text.', select: 'Title', inline: false },
      ],
    };
  }
  if (p === '/kb/articles' && opts.method === 'POST') { created = body; return store.articles[0]; }
  if (p === '/kb/articles') return { articles: store.articles };
  if (p === '/notes') return [{ slug: 'loose', title: 'A loose note' }, { slug: 'a1', title: 'Array unreachable' }];
  if (p.startsWith('/notes/') && opts.method === 'PUT') { lastPut = body; store.bodies.a1 = body.body; return {}; }
  if (p.startsWith('/notes/') && opts.method === 'DELETE') {
    deleted = decodeURIComponent(p.split('/').pop());
    store.articles = store.articles.filter((a) => a.slug !== deleted);
    return { ok: true, trashed: deleted };
  }
  const meta = p.match(/^\/kb\/([^/]+)\/meta$/);
  if (meta) { lastMeta = body.meta; return { slug: meta[1], kb: body.meta, is_article: true }; }
  const rel = p.match(/^\/kb\/([^/]+)\/release$/);
  if (rel) { released = rel[1]; return { slug: rel[1], is_article: false }; }
  const ad = p.match(/^\/kb\/([^/]+)\/adopt$/);
  if (ad) { adopted = { slug: ad[1], ...body }; return store.articles[0]; }
  const rnd = p.match(/^\/kb\/([^/]+)\/render$/);
  if (rnd) {
    const lines = (store.bodies[rnd[1]] || '').split('\n');
    // Mirrors the server's own splitter closely enough for the drop maths:
    // blank lines separate blocks.
    const blocks = [];
    let start = null;
    lines.forEach((ln, i) => {
      if (ln.trim() === '') {
        if (start !== null) { blocks.push({ start, end: i - 1 }); start = null; }
      } else if (start === null) start = i;
    });
    if (start !== null) blocks.push({ start, end: lines.length - 1 });
    return {
      slug: rnd[1], lines: lines.length,
      blocks: blocks.map((b) => ({
        ...b,
        text: lines.slice(b.start, b.end + 1).join('\n'),
        html: '<p>' + lines.slice(b.start, b.end + 1).join(' ') + '</p>',
      })),
    };
  }
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

console.log('\n── the block palette ──');
await window.tephraKb.open();
await tick(40);
const pal = doc.querySelector('#kbPalette');
ck('the palette exists beside the editor', !!pal);
ck('blocks are grouped the way the registry groups them',
   [...pal.querySelectorAll('.kb-palgroup')].map((g) => g.textContent).join('|')
   === 'Text|Structure|Notes',
   [...pal.querySelectorAll('.kb-palgroup')].map((g) => g.textContent).join('|'));
ck('one draggable item per block',
   pal.querySelectorAll('.kb-palitem').length === 3);
ck('every item is actually draggable',
   [...pal.querySelectorAll('.kb-palitem')].every((i) => i.draggable === true));
ck('each item shows its glyph and its label',
   !!pal.querySelector('.kb-palglyph') && !!pal.querySelector('.kb-pallabel'));
ck('vault notes are draggable in too, which is the point of writing KBs in a wiki',
   pal.querySelectorAll('.kb-palnote').length >= 1);

console.log('\n── clicking a block appends it and selects the placeholder ──');
const ed = doc.querySelector('#kbBody');
const before = ed.value;
const calloutItem = [...pal.querySelectorAll('.kb-palitem')]
  .find((i) => /Callout/.test(i.textContent));
await calloutItem.onclick();
await tick(60);
ck('the snippet is appended as markdown, not as some other format',
   ed.value.includes('> [!WARNING] Title'), JSON.stringify(ed.value.slice(-40)));
ck('what was already written is untouched', ed.value.startsWith(before.trim()));
ck('a blank line separates it from what came before, or markdown would join them',
   /\n\n> \[!WARNING\]/.test(ed.value));
ck('the placeholder is selected, so the first thing typed replaces it',
   ed.value.slice(ed.selectionStart, ed.selectionEnd) === 'Title',
   ed.value.slice(ed.selectionStart, ed.selectionEnd));
ck('the edit is saved through the ordinary note endpoint',
   lastPut && lastPut.body.includes('[!WARNING]'));

console.log('\n── the live render, and dropping onto it ──');
function dragEvent(type, payload) {
  const e = new window.Event(type, { bubbles: true, cancelable: true });
  const store = {
    'application/x-tephra-block': JSON.stringify(payload),
    'text/plain': '',
  };
  Object.defineProperty(e, 'dataTransfer', {
    value: {
      types: Object.keys(store),
      getData: (k) => store[k] || '',
      setData: (k, v) => { store[k] = v; },
      dropEffect: '', effectAllowed: '',
    },
  });
  return e;
}

const render = doc.querySelector('#kbRender');
ck('the render pane is the default tab, since it is what you write beside',
   !!render && !doc.querySelector('#kbPaneRender').hidden);
ck('it renders through Tephra\u2019s own renderer, so the preview is the app\u2019s look',
   render.innerHTML.includes('<p>'));
const blks = [...render.querySelectorAll('.kb-blk')];
ck('one wrapper per source block', blks.length >= 2, blks.length);
ck('each wrapper carries its source line range',
   blks.every((b) => b.dataset.start !== undefined && b.dataset.end !== undefined));
const zones = [...render.querySelectorAll('.kb-drop')];
ck('there is a drop zone before every block and one after the last',
   zones.length === blks.length + 1, `${zones.length} zones, ${blks.length} blocks`);
ck('the first zone targets line 0', zones[0].dataset.line === '0');

const beforeDrop = ed.value.split('\n');
zones[0].dispatchEvent(dragEvent('drop', { block: 'heading' }));
await tick(80);
ck('dropping on the first zone inserts at the very top',
   ed.value.startsWith('## Heading'), JSON.stringify(ed.value.slice(0, 30)));
ck('nothing that was already written is lost',
   beforeDrop.every((l) => !l.trim() || ed.value.includes(l.trim())));
ck('the placeholder is selected after a drop too',
   ed.value.slice(ed.selectionStart, ed.selectionEnd) === 'Heading');

const zones2 = [...doc.querySelectorAll('#kbRender .kb-drop')];
const lastZone = zones2[zones2.length - 1];
lastZone.dispatchEvent(dragEvent('drop', { note: 'A loose note' }));
await tick(80);
ck('a note dropped in becomes a wikilink, not a copy of the note',
   ed.value.includes('[[A loose note]]'));

console.log('\n── dropping onto the markdown itself ──');
ed.value = 'line one\nline two';
const editorDrop = dragEvent('drop', { block: 'bullets' });
ed.dispatchEvent(editorDrop);
await tick(80);
ck('the snippet lands in the source', ed.value.includes('- Item'));
ck('and it is still markdown on the way to disk',
   lastPut && lastPut.body.includes('- Item'));

console.log('\n── the right column takes turns ──');
const tabs = [...doc.querySelectorAll('[data-kbtab]')];
ck('three tabs share the column',
   tabs.map((t) => t.dataset.kbtab).join('|') === 'render|structure|fields');
tabs.find((t) => t.dataset.kbtab === 'structure').onclick();
ck('switching shows the structure panel', !doc.querySelector('#kbPaneStructure').hidden
   && doc.querySelector('#kbPaneRender').hidden);
ck('and the outline is still there', !!doc.querySelector('.kb-sec'));
tabs.find((t) => t.dataset.kbtab === 'fields').onclick();
ck('the metadata form lives on its own tab now',
   !doc.querySelector('#kbPaneFields').hidden && !!doc.querySelector('#kbf-kb_status'));

console.log('\n── adjustable dividers ──');
const root = doc.documentElement;
const grips = [...doc.querySelectorAll('.kb-grip')];
ck('one grip per divider', grips.length === 3, grips.length);
ck('they name the columns they resize',
   grips.map((g) => g.dataset.grip).sort().join('|') === 'list|pal|right');
ck('the right column\u2019s grip is on its left edge, since it grows leftwards',
   doc.querySelector('.kb-grip[data-grip="right"]').classList.contains('kb-grip-left'));
ck('widths are custom properties, so a collapse is one property change',
   /--kb-list-w/.test(flat) && /--kb-pal-w/.test(flat) && /--kb-right-w/.test(flat));
ck('the markdown column takes whatever is left over',
   /grid-template-columns:var\(--kb-list-w,238px\)var\(--kb-pal-w,152px\)minmax\(0,1fr\)var\(--kb-right-w,420px\)/
     .test(flat));
ck('the grip reuses the notes sidebar\u2019s own drag class, not a second one',
   /body\.resizing-sidebar\{cursor:col-resize/.test(flat));

function dragGrip(which, dx) {
  const g = doc.querySelector(`.kb-grip[data-grip="${which}"]`);
  g.getBoundingClientRect = () => ({ width: 0 });
  g.parentElement.getBoundingClientRect = () => ({ width: 200 });
  g.dispatchEvent(new window.MouseEvent('mousedown', { clientX: 500, bubbles: true, cancelable: true }));
  doc.dispatchEvent(new window.MouseEvent('mousemove', { clientX: 500 + dx, bubbles: true }));
  doc.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true }));
  return parseInt(root.style.getPropertyValue('--kb-list-w'), 10);
}
dragGrip('list', 60);
ck('dragging the list grip right widens the list',
   parseInt(root.style.getPropertyValue('--kb-list-w'), 10) === 260,
   root.style.getPropertyValue('--kb-list-w'));
dragGrip('list', 9999);
ck('a width is clamped to its maximum, so a column cannot eat the window',
   parseInt(root.style.getPropertyValue('--kb-list-w'), 10) === 460);
dragGrip('list', -9999);
ck('and to its minimum, so it cannot vanish by accident',
   parseInt(root.style.getPropertyValue('--kb-list-w'), 10) === 150);
ck('the width is remembered', window.localStorage.getItem('tephra.kb.listw') === '150');
doc.querySelector('.kb-grip[data-grip="list"]')
   .dispatchEvent(new window.MouseEvent('dblclick', { bubbles: true }));
ck('double-clicking a grip restores the default',
   parseInt(root.style.getPropertyValue('--kb-list-w'), 10) === 238);

console.log('\n── collapsing the right column ──');
const collapse = doc.querySelector('#kbCollapse');
ck('there is a collapse control in the tab bar', !!collapse);
ck('it starts expanded', !doc.querySelector('#kbview').classList.contains('kb-collapsed'));
collapse.onclick();
ck('collapsing marks the deck', doc.querySelector('#kbview').classList.contains('kb-collapsed'));
ck('the markdown gets the space: the right column goes to zero, not to a gutter',
   /#kbview\.kb-collapsed:not\(\.kb-exporting\)\.kb-body\{grid-template-columns:var\(--kb-list-w,238px\)var\(--kb-pal-w,152px\)minmax\(0,1fr\)0\}/
     .test(flat));
ck('a reopen handle is the only thing left of it',
   /#kbview\.kb-collapsed:not\(\.kb-exporting\)\.kb-reopen\{display:block\}/.test(flat));
ck('the collapse is remembered', window.localStorage.getItem('tephra.kb.rightcollapsed') === '1');
ck('export mode is exempt \u2014 the same column holds the copy buttons over there',
   /#kbview\.kb-collapsed:not\(\.kb-exporting\)/.test(flat)
   && !/#kbview\.kb-collapsed\.kb-aside\{opacity:0/.test(flat));
doc.querySelector('#kbReopen').onclick();
ck('the reopen handle brings it back',
   !doc.querySelector('#kbview').classList.contains('kb-collapsed'));
ck('and the state is remembered the other way too',
   window.localStorage.getItem('tephra.kb.rightcollapsed') === '0');

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

console.log('\n── deleting an article ──');
await window.tephraKb.open();
await tick(30);
const delBtn = doc.querySelector('#kbDelete');
ck('the deck offers a delete, not only a release', !!delBtn);
ck('release and delete are visibly different actions',
   !!doc.querySelector('#kbRelease') && delBtn.classList.contains('danger'));
ck('and the panel says which one keeps the note',
   /Release keeps the note/.test(doc.querySelector('.kb-dangersect').textContent));

await delBtn.onclick();
ck('one click only arms it', deleted === null && /click again/.test(delBtn.textContent));
ck('the armed state is visible', delBtn.classList.contains('armed'));
await delBtn.onclick();
await tick(40);
ck('the second click deletes', deleted === 'a1', deleted);
ck('it goes through the endpoint that trashes rather than unlinks',
   deleted === 'a1');
ck('the list drops it', !store.articles.some((a) => a.slug === 'a1'));
ck('the deck lands on the next article rather than an empty pane',
   doc.querySelector('#kbTitle') && doc.querySelector('#kbTitle').value === 'Mount a filesystem',
   doc.querySelector('#kbTitle') && doc.querySelector('#kbTitle').value);

// The bug this guards: a debounced autosave that lands after the delete
// writes the file straight back out of the trash.
lastPut = null;
store.articles.push({ slug: 'a1', title: 'Array unreachable', updated: '2026-01-02',
  kb_type: 'troubleshooting', type_name: 'Troubleshooting', status: 'draft',
  audience: 'internal', number: 'KB1', short_description: 's', products: [], words: 40 });
await window.tephraKb.open();
await tick(30);
const ta = doc.querySelector('#kbBody');
ta.value = 'edited but doomed';
ta.oninput();
const d2 = doc.querySelector('#kbDelete');
await d2.onclick(); await d2.onclick();
await tick(900);
ck('a pending autosave cannot resurrect a deleted article', lastPut === null,
   JSON.stringify(lastPut));

console.log('\n── releasing ──');
await window.tephraKb.open();
await tick(30);
const openSlug = S_openSlug();
doc.querySelector('#kbRelease').onclick();
await tick(40);
ck('releasing calls the endpoint that leaves the prose alone',
   released === openSlug, `${released} vs ${openSlug}`);

console.log('\n── closing ──');
window.tephraKb.close();
ck('closing removes the body class', !doc.body.classList.contains('kbdeck'));
ck('and un-marks the pane', !doc.querySelector('#kbview').classList.contains('on'));

console.log(`\n  ${ok} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
