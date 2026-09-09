/* KB Authoring — the third deck.
 *
 * Tephra and Crucible are two sides of one deck; this is the third. It is a
 * lens over ordinary notes, not a separate store: everything it edits goes
 * back through the same /api/notes autosave the Write view uses, and the
 * only thing that makes a note an article is a `kb_type` in its frontmatter.
 *
 * Two modes, because authoring and exporting want opposite layouts:
 *
 *   Write    list · body · metadata and structure
 *   Export   list · preview of what the other system will actually show ·
 *            export controls, attachment manifest, and warnings
 *
 * The preview is the point of the whole deck. It renders the *export* HTML
 * in a sandboxed iframe carrying only the target's own inline styles, so
 * what you look at is what ServiceNow will render -- not what Tephra
 * renders. A preview that used the app's stylesheet would be a lie, and a
 * comfortable one, which is worse.
 */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const api = window.tephraApi;
  const toast = window.tephraToast;
  const esc = (s) => String(s == null ? '' : s)
    .replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  const S = {
    open: false,
    mode: 'write',
    ready: false,
    templates: [],
    fields: [],
    targets: [],
    articles: [],
    slug: null,
    article: null,
    target: 'servicenow',
    links: 'auto',
    includeMeta: true,
    houseStyle: true,
    exportData: null,
    filter: '',
    picking: false,
    fieldmap: {},
    blocks: [],
    blockGroups: [],
    rightTab: 'render',
    previewBlocks: [],
    notes: [],
    renderCollapsed: false,
    sectionFields: [],
    form: '',
  };

  const tplById = (id) => S.templates.find((t) => t.id === id) || null;

  /* ── shell ── */
  const view = el('div');
  view.id = 'kbview';
  view.className = 'deckpane';
  view.innerHTML = `
    <div class="sv-head kb-head">
      <div class="sv-brand">
        <div>
          <h3>KB Authoring</h3>
          <p id="kbStats">—</p>
        </div>
      </div>
      <div class="sv-modes kb-modes">
        <button data-kbmode="write" aria-pressed="true">Write</button>
        <button data-kbmode="export" aria-pressed="false">Export</button>
      </div>
    </div>
    <div class="kb-body">
      <aside class="kb-list">
        <div class="kb-grip" data-grip="list" title="Drag to resize"></div>
        <div class="eyebrow"><span>Articles</span><span id="kbCount">—</span></div>
        <input type="search" id="kbFilter" placeholder="Filter articles…" autocomplete="off">
        <div id="kbRows" class="kb-rows"></div>
        <button class="newnote admin-only" id="kbNew">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.4"><path d="M12 5v14M5 12h14"/></svg>
          New article
        </button>
      </aside>
      <aside class="kb-palette">
        <div class="kb-palinner" id="kbPalette"></div>
        <div class="kb-grip" data-grip="pal" title="Drag to resize"></div>
      </aside>
      <section class="kb-main" id="kbMain"></section>
      <aside class="kb-aside">
        <div class="kb-grip kb-grip-left" data-grip="right" title="Drag to resize"></div>
        <div class="kb-asideinner" id="kbAside"></div>
      </aside>
      <button class="kb-reopen" id="kbReopen" type="button"
              title="Show the render again">\u00ab</button>
    </div>`;
  (document.querySelector('.deck') || document.body).appendChild(view);

  /* ── new / adopt ─────────────────────────────────────────────────────
     One panel with two doors. "New" is the obvious one; "Adopt" matters
     more in practice, because almost no article starts life as an article
     -- it starts as the note somebody took while working the case, and the
     alternative to adopting it is copy-paste, which loses the history and
     the links both. */
  const pick = el('div', 'kb-pick');
  pick.hidden = true;
  pick.innerHTML = `
    <div class="kb-pick-card">
      <div class="sv-modetoggle">
        <button class="sv-modebtn" data-pick="new" aria-pressed="true">New article</button>
        <button class="sv-modebtn" data-pick="adopt" aria-pressed="false">Adopt a note</button>
      </div>
      <div id="kbPickNew">
        <label class="sv-fieldlabel" for="kbNewTitle">Title</label>
        <input type="text" id="kbNewTitle" placeholder="What the reader is trying to fix">
        <label class="sv-fieldlabel" for="kbNewType" style="margin-top:14px">Article type</label>
        <select id="kbNewType"></select>
        <p class="kb-tplsummary" id="kbTplSummary"></p>
      </div>
      <div id="kbPickAdopt" hidden>
        <label class="sv-fieldlabel" for="kbAdoptFind">Note to adopt</label>
        <input type="search" id="kbAdoptFind" placeholder="Search your notes…" autocomplete="off">
        <div class="kb-adoptlist" id="kbAdoptList"></div>
        <label class="sv-fieldlabel" for="kbAdoptType" style="margin-top:12px">Article type</label>
        <select id="kbAdoptType"></select>
      </div>
      <div class="th-row kb-pick-actions">
        <button class="sv-btn" id="kbPickCancel">Cancel</button>
        <button class="sv-btn primary admin-only" id="kbPickGo">Create</button>
      </div>
    </div>`;
  view.appendChild(pick);

  let adoptSlug = null;

  function showPick(on) {
    S.picking = on;
    pick.hidden = !on;
    if (on) {
      $('#kbNewTitle').value = '';
      adoptSlug = null;
      setPickTab('new');
      $('#kbNewTitle').focus();
    }
  }

  function setPickTab(which) {
    pick.querySelectorAll('[data-pick]').forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset.pick === which)));
    $('#kbPickNew').hidden = which !== 'new';
    $('#kbPickAdopt').hidden = which !== 'adopt';
    $('#kbPickGo').textContent = which === 'adopt' ? 'Adopt' : 'Create';
    if (which === 'adopt') renderAdoptList('');
  }

  function fillTypeSelects() {
    const opts = S.templates.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
    $('#kbNewType').innerHTML = opts;
    $('#kbAdoptType').innerHTML = opts;
    showTplSummary();
  }

  function showTplSummary() {
    const t = tplById($('#kbNewType').value);
    $('#kbTplSummary').textContent = t ? t.summary : '';
  }

  async function renderAdoptList(q) {
    const box = $('#kbAdoptList');
    let notes = [];
    try { notes = await api('/notes'); } catch { notes = []; }
    const taken = new Set(S.articles.map((a) => a.slug));
    const needle = q.trim().toLowerCase();
    const rows = notes
      .filter((n) => !taken.has(n.slug))
      .filter((n) => !needle || n.title.toLowerCase().includes(needle))
      .slice(0, 40);
    box.innerHTML = '';
    if (!rows.length) {
      box.appendChild(el('p', 'kb-empty', needle
        ? 'No notes match, and every article already adopted is hidden here.'
        : 'Every note in this vault is already a KB article.'));
      return;
    }
    rows.forEach((n) => {
      const row = el('button', 'kb-adoptrow');
      row.type = 'button';
      row.textContent = n.title;
      row.setAttribute('aria-pressed', String(adoptSlug === n.slug));
      row.onclick = () => {
        adoptSlug = n.slug;
        box.querySelectorAll('.kb-adoptrow').forEach((r) =>
          r.setAttribute('aria-pressed', String(r === row)));
      };
      box.appendChild(row);
    });
  }

  /* ── list ── */
  function renderList() {
    const box = $('#kbRows');
    const needle = S.filter.trim().toLowerCase();
    const rows = S.articles.filter((a) =>
      !needle
      || a.title.toLowerCase().includes(needle)
      || (a.number || '').toLowerCase().includes(needle)
      || (a.products || []).join(' ').toLowerCase().includes(needle));
    $('#kbCount').textContent = String(S.articles.length);
    box.innerHTML = '';
    if (!rows.length) {
      box.appendChild(el('p', 'kb-empty', S.articles.length
        ? 'Nothing matches that filter.'
        : 'No KB articles yet. Start one, or adopt a note you have already written.'));
      return;
    }
    rows.forEach((a) => {
      const row = el('button', 'kb-row node');
      row.type = 'button';
      row.setAttribute('aria-pressed', String(a.slug === S.slug));
      row.innerHTML = `
        <span class="kb-row-t">${esc(a.title)}</span>
        <span class="kb-row-m">
          <span class="kb-chip kb-status-${esc(a.status || 'draft')}">${esc(a.status || 'draft')}</span>
          <span class="kb-chip">${esc(a.type_name || 'Article')}</span>
          ${a.number ? `<span class="kb-num">${esc(a.number)}</span>` : ''}
        </span>`;
      row.onclick = () => openArticle(a.slug);
      box.appendChild(row);
    });
  }

  function renderStats() {
    const by = {};
    S.articles.forEach((a) => { by[a.status || 'draft'] = (by[a.status || 'draft'] || 0) + 1; });
    const parts = Object.keys(by).sort().map((k) => `${by[k]} ${k.toUpperCase()}`);
    $('#kbStats').textContent = S.articles.length
      ? `${S.articles.length} ARTICLE${S.articles.length === 1 ? '' : 'S'} · ${parts.join(' · ')}`
      : 'NO ARTICLES YET';
  }

  /* ── autosave ────────────────────────────────────────────────────────
     The same contract the Write view has: there is no save button in this
     app and there is not going to be one here either. Body and title go to
     /api/notes; kb_* fields go to /api/kb/{slug}/meta, which leaves every
     other frontmatter key alone. */
  let saveT = null;
  let metaT = null;

  function queueSave() {
    clearTimeout(saveT);
    saveT = setTimeout(flushBody, 700);
  }

  async function flushBody() {
    clearTimeout(saveT);
    if (!S.slug) return;
    const body = $('#kbBody');
    const title = $('#kbTitle');
    if (!body || !title) return;
    try {
      const res = await api('/notes/' + S.slug, {
        method: 'PUT',
        body: JSON.stringify({ title: title.value, body: body.value }),
      });
      if (res && res.renamed_to && res.renamed_to !== S.slug) S.slug = res.renamed_to;
      await refreshArticle();
      await loadArticles();
    } catch (e) {
      toast('Could not save: ' + String((e && e.message) || e).slice(0, 120), 4000);
    }
  }

  function queueMeta() {
    clearTimeout(metaT);
    metaT = setTimeout(flushMeta, 500);
  }

  async function flushMeta() {
    clearTimeout(metaT);
    if (!S.slug) return;
    // Built on top of what the article already has, not rebuilt from the
    // inputs. The metadata form only exists in Write mode, so rebuilding
    // from inputs would blank every field the moment something saved while
    // Export mode was showing -- which is exactly when the field mapping
    // saves.
    const meta = { ...(S.article ? S.article.kb : {}) };
    meta.kb_type = S.article ? S.article.template : '';
    meta.kb_fieldmap = S.fieldmap;
    S.fields.forEach((f) => {
      const input = $('#kbf-' + f.key);
      if (!input) return;
      meta[f.key] = f.kind === 'tags'
        ? input.value.split(',').map((x) => x.trim()).filter(Boolean)
        : input.value;
    });
    try {
      const res = await api('/kb/' + S.slug + '/meta', {
        method: 'PUT', body: JSON.stringify({ meta }),
      });
      if (S.article) S.article.kb = res.kb;
      await loadArticles();
    } catch (e) {
      toast('Could not save fields: ' + String((e && e.message) || e).slice(0, 120), 4000);
    }
  }

  /* ── write mode ────────────────────────────────────────────────────────
     Markdown on the left, the same markdown rendered on the right, and a
     palette of blocks you can drag into either. The file on disk stays
     plain markdown throughout: a block is a way of writing the syntax
     without typing it, never a second format. */
  function renderWrite() {
    const main = $('#kbMain');
    if (!S.article) {
      main.innerHTML = '';
      main.appendChild(el('p', 'kb-empty kb-empty-lg',
        'Pick an article on the left, or start a new one.'));
      $('#kbAside').innerHTML = '';
      $('#kbPalette').innerHTML = '';
      return;
    }
    const a = S.article;
    main.innerHTML = `
      <input type="text" id="kbTitle" class="kb-title" value="${esc(a.title)}"
             placeholder="Article title">
      <textarea id="kbBody" class="kb-editor" spellcheck="true"
                placeholder="Write the article in markdown, or drag a block in."></textarea>`;
    $('#kbBody').value = a.body || '';
    $('#kbTitle').oninput = queueSave;
    $('#kbBody').oninput = () => { queueSave(); queuePreview(); };
    wireEditorDrop($('#kbBody'));
    renderPalette();
    renderAside();
    loadPreview();
  }

  /* ── the palette ── */
  function renderPalette() {
    const box = $('#kbPalette');
    box.innerHTML = '<div class="eyebrow"><span>Blocks</span></div>';
    S.blockGroups.forEach((group) => {
      const items = S.blocks.filter((b) => b.group === group);
      if (!items.length) return;
      box.appendChild(el('p', 'kb-palgroup', group));
      items.forEach((b) => box.appendChild(paletteItem(b)));
    });
    // Every note in the vault, draggable straight in as a [[wikilink]] --
    // the point of writing KBs in a wiki rather than in the KB system.
    box.appendChild(el('p', 'kb-palgroup', 'Notes'));
    const search = el('input', 'kb-palsearch');
    search.type = 'search';
    search.placeholder = 'Find a note…';
    search.oninput = () => renderNoteChips(search.value);
    box.appendChild(search);
    box.appendChild(el('div', 'kb-palnotes'));
    renderNoteChips('');
  }

  function paletteItem(b) {
    const item = el('button', 'kb-palitem');
    item.type = 'button';
    item.draggable = true;
    item.title = b.hint;
    item.innerHTML = `<span class="kb-palglyph">${esc(b.glyph)}</span>`
      + `<span class="kb-pallabel">${esc(b.label)}</span>`;
    item.addEventListener('dragstart', (e) => startDrag(e, { block: b.id }));
    // Clicking appends, for anyone who would rather not drag -- and for a
    // keyboard, where dragging is not available at all.
    item.onclick = () => insertAtLine(lineCount(), b.snippet, b.select);
    return item;
  }

  async function renderNoteChips(q) {
    const box = $('.kb-palnotes');
    if (!box) return;
    if (!S.notes.length) {
      try { S.notes = await api('/notes'); } catch { S.notes = []; }
    }
    const needle = q.trim().toLowerCase();
    box.innerHTML = '';
    S.notes
      .filter((n) => n.slug !== S.slug)
      .filter((n) => !needle || n.title.toLowerCase().includes(needle))
      .slice(0, 24)
      .forEach((n) => {
        const chip = el('button', 'kb-palnote', n.title);
        chip.type = 'button';
        chip.draggable = true;
        chip.title = 'Drag in as a [[link]] to this note';
        chip.addEventListener('dragstart', (e) => startDrag(e, { note: n.title }));
        chip.onclick = () => insertAtLine(lineCount(), `[[${n.title}]]`, n.title);
        box.appendChild(chip);
      });
  }

  function startDrag(e, payload) {
    // text/plain as well as the private type: dropping onto the textarea
    // uses the browser's own text insertion as a fallback when our handler
    // cannot work out a caret position.
    const snippet = payload.note
      ? `[[${payload.note}]]`
      : (S.blocks.find((b) => b.id === payload.block) || {}).snippet || '';
    e.dataTransfer.setData('text/plain', snippet);
    e.dataTransfer.setData('application/x-tephra-block', JSON.stringify(payload));
    e.dataTransfer.effectAllowed = 'copy';
    document.body.classList.add('kb-dragging');
    e.target.addEventListener('dragend', () => {
      document.body.classList.remove('kb-dragging');
      clearDropMarks();
    }, { once: true });
  }

  function payloadOf(e) {
    const raw = e.dataTransfer.getData('application/x-tephra-block');
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return null; }
  }

  function snippetOf(payload) {
    if (!payload) return null;
    if (payload.note) return { snippet: `[[${payload.note}]]`, select: payload.note };
    const b = S.blocks.find((x) => x.id === payload.block);
    return b ? { snippet: b.snippet, select: b.select } : null;
  }

  /* ── splicing ── */
  const lineCount = () => (($('#kbBody') || {}).value || '').split('\n').length;

  /* Insert `snippet` so that it starts at source line `line`, keeping the
     blank lines markdown needs on either side, then select `select` so the
     first thing typed replaces the placeholder. */
  async function insertAtLine(line, snippet, select) {
    const ta = $('#kbBody');
    if (!ta) return;
    const lines = ta.value.split('\n');
    const before = lines.slice(0, Math.max(0, Math.min(line, lines.length)));
    const after = lines.slice(Math.max(0, Math.min(line, lines.length)));
    while (before.length && before[before.length - 1].trim() === '') before.pop();
    while (after.length && after[0].trim() === '') after.shift();
    const head = before.length ? before.join('\n') + '\n\n' : '';
    const tail = after.length ? '\n\n' + after.join('\n') : '\n';
    ta.value = head + snippet + tail;
    ta.focus();
    const at = head.length;
    const rel = select ? snippet.indexOf(select) : -1;
    if (rel >= 0) ta.setSelectionRange(at + rel, at + rel + select.length);
    else ta.setSelectionRange(at + snippet.length, at + snippet.length);
    scrollToOffset(ta, at);
    await flushBody();
    await loadPreview();
  }

  function scrollToOffset(ta, at) {
    const line = ta.value.slice(0, at).split('\n').length;
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 20;
    ta.scrollTop = Math.max(0, (line - 4) * lh);
  }

  /* Dropping onto the markdown itself inserts at the caret under the
     pointer. caretRangeFromPoint and caretPositionFromPoint are the same
     idea under two names -- neither is universal, so a plain append is the
     floor rather than losing the drop. */
  function wireEditorDrop(ta) {
    if (!ta) return;
    ta.addEventListener('dragover', (e) => {
      if (!payloadOf(e) && !e.dataTransfer.types.includes('application/x-tephra-block')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      ta.classList.add('kb-dropinto');
    });
    ta.addEventListener('dragleave', () => ta.classList.remove('kb-dropinto'));
    ta.addEventListener('drop', async (e) => {
      const payload = payloadOf(e);
      ta.classList.remove('kb-dropinto');
      if (!payload) return;
      e.preventDefault();
      const bit = snippetOf(payload);
      if (!bit) return;
      const at = caretFromPoint(ta, e.clientX, e.clientY);
      const line = ta.value.slice(0, at).split('\n').length - 1;
      await insertAtLine(line, bit.snippet, bit.select);
    });
  }

  function caretFromPoint(ta, x, y) {
    if (document.caretPositionFromPoint) {
      const pos = document.caretPositionFromPoint(x, y);
      if (pos && pos.offsetNode) return pos.offset;
    }
    if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(x, y);
      if (r) return r.startOffset;
    }
    return typeof ta.selectionStart === 'number' ? ta.selectionStart : ta.value.length;
  }

  /* ── the live render ── */
  let previewT = null;
  function queuePreview() {
    clearTimeout(previewT);
    previewT = setTimeout(loadPreview, 320);
  }

  async function loadPreview() {
    clearTimeout(previewT);
    if (!S.slug || S.rightTab !== 'render' || S.renderCollapsed) return;
    const host = $('#kbRender');
    if (!host) return;
    try {
      const res = await api('/kb/' + S.slug + '/render');
      S.previewBlocks = res.blocks || [];
      paintPreview(res);
    } catch {
      host.innerHTML = '';
      host.appendChild(el('p', 'kb-empty', 'Could not render this article.'));
    }
  }

  function paintPreview(res) {
    const host = $('#kbRender');
    if (!host) return;
    host.innerHTML = '';
    const blocks = res.blocks || [];
    if (!blocks.length) {
      host.appendChild(dropZone(0, true));
      host.appendChild(el('p', 'kb-empty',
        'Nothing here yet. Drag a block in from the left.'));
      return;
    }
    blocks.forEach((b) => {
      host.appendChild(dropZone(b.start));
      const wrap = el('div', 'kb-blk');
      wrap.dataset.start = b.start;
      wrap.dataset.end = b.end;
      wrap.innerHTML = b.html;
      // Clicking a rendered block puts the caret on its source, so the two
      // panes stay one document rather than two views you navigate apart.
      wrap.onclick = () => selectSourceLines(b.start, b.end);
      host.appendChild(wrap);
    });
    host.appendChild(dropZone((res.lines || 0)));
    window.tephraEnhanceRendered?.(host);
  }

  function dropZone(line, wide) {
    const z = el('div', 'kb-drop' + (wide ? ' wide' : ''));
    z.dataset.line = line;
    z.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes('application/x-tephra-block')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      clearDropMarks();
      z.classList.add('over');
    });
    z.addEventListener('dragleave', () => z.classList.remove('over'));
    z.addEventListener('drop', async (e) => {
      e.preventDefault();
      z.classList.remove('over');
      const bit = snippetOf(payloadOf(e));
      if (bit) await insertAtLine(Number(z.dataset.line), bit.snippet, bit.select);
    });
    return z;
  }

  function clearDropMarks() {
    document.querySelectorAll('.kb-drop.over').forEach((z) => z.classList.remove('over'));
  }

  function selectSourceLines(start, end) {
    const ta = $('#kbBody');
    if (!ta) return;
    const lines = ta.value.split('\n');
    const at = lines.slice(0, start).join('\n').length + (start ? 1 : 0);
    const to = at + lines.slice(start, end + 1).join('\n').length;
    ta.focus();
    ta.setSelectionRange(at, to);
    scrollToOffset(ta, at);
  }

  function fieldInput(f, value) {
    const id = 'kbf-' + f.key;
    if (f.kind === 'select') {
      const opts = ['<option value=""></option>']
        .concat(f.options.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`)).join('');
      return `<select id="${id}" data-kbfield="${esc(f.key)}">${opts}</select>`;
    }
    if (f.kind === 'textarea') {
      return `<textarea id="${id}" data-kbfield="${esc(f.key)}" rows="2"
        maxlength="${f.max_len || 5000}">${esc(value)}</textarea>`;
    }
    const type = f.kind === 'date' ? 'date' : 'text';
    const hint = f.kind === 'tags' ? ' placeholder="Comma separated"' : '';
    return `<input type="${type}" id="${id}" data-kbfield="${esc(f.key)}"
      value="${esc(value)}"${hint}>`;
  }

  /* The right column carries three things that all want the same space, so
     they take turns: the live render (the default, because it is what you
     look at while writing), the structure panel, and the metadata form. */
  function renderAside() {
    const box = $('#kbAside');
    if (!S.article) { box.innerHTML = ''; return; }
    const kbm = S.article.kb || {};
    const tpl = tplById(S.article.template);

    const fields = S.fields.map((f) => {
      const raw = kbm[f.key];
      const value = Array.isArray(raw) ? raw.join(', ') : (raw || '');
      return `
        <div class="kb-field${f.required ? ' req' : ''}">
          <label class="sv-fieldlabel" for="kbf-${esc(f.key)}">${esc(f.label)}</label>
          ${fieldInput(f, value)}
          <p class="kb-fieldhint">${esc(f.hint)}</p>
        </div>`;
    }).join('');

    box.innerHTML = `
      <div class="kb-tabs">
        <button type="button" data-kbtab="render">Render</button>
        <button type="button" data-kbtab="structure">Structure</button>
        <button type="button" data-kbtab="fields">Fields</button>
        <button type="button" class="kb-collapse" id="kbCollapse">\u00bb</button>
      </div>
      <div class="kb-pane" id="kbPaneRender">
        <div class="kb-render" id="kbRender"></div>
      </div>
      <div class="kb-pane" id="kbPaneStructure">
        <div class="kb-asidesect">
          <div class="eyebrow"><span>Sections</span><span>${esc(tpl ? tpl.name : '')}</span></div>
          <div id="kbOutline" class="kb-outline"></div>
        </div>
      </div>
      <div class="kb-pane" id="kbPaneFields">
        <div class="kb-asidesect">
          <div class="kb-fields admin-only">${fields}</div>
        </div>
        <div class="kb-asidesect kb-dangersect">
          <button class="sv-btn admin-only" id="kbRelease"
            title="Stop treating this note as a KB article. The prose is untouched.">
            Release from KB</button>
          <button class="sv-btn danger admin-only" id="kbDelete"
            title="Move this article to the vault trash. Recoverable from vault/.trash.">
            Delete article</button>
          <p class="kb-fieldhint">Release keeps the note and only drops its KB fields.
            Delete moves the whole note to the vault trash.</p>
        </div>
      </div>`;

    S.fields.forEach((f) => {
      const input = $('#kbf-' + f.key);
      if (!input) return;
      if (f.kind === 'select') input.value = kbm[f.key] || '';
      input.oninput = queueMeta;
      input.onchange = queueMeta;
    });
    $('#kbRelease').onclick = releaseArticle;
    wireDelete($('#kbDelete'));
    box.querySelectorAll('[data-kbtab]').forEach((b) => {
      b.onclick = () => setRightTab(b.dataset.kbtab);
    });
    $('#kbCollapse').onclick = () => setRenderCollapsed(!S.renderCollapsed);
    setRenderCollapsed(S.renderCollapsed, true);
    setRightTab(S.rightTab);
    renderOutline();
  }

  function setRightTab(tab) {
    S.rightTab = tab;
    const box = $('#kbAside');
    if (!box) return;
    box.querySelectorAll('[data-kbtab]').forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset.kbtab === tab)));
    ['render', 'structure', 'fields'].forEach((t) => {
      const pane = $('#kbPane' + t.charAt(0).toUpperCase() + t.slice(1));
      if (pane) pane.hidden = t !== tab;
    });
    if (tab === 'render') loadPreview();
  }

  function renderOutline() {
    const box = $('#kbOutline');
    if (!box || !S.article) return;
    box.innerHTML = '';
    const outline = S.article.outline || [];
    if (!outline.length) {
      box.appendChild(el('p', 'kb-empty', 'This article has no template attached.'));
      return;
    }
    outline.forEach((sec) => {
      const state = !sec.present ? 'missing' : sec.empty ? 'empty' : 'ok';
      const row = el('div', 'kb-sec kb-sec-' + state);
      const jump = el('button', 'kb-sec-name');
      jump.type = 'button';
      jump.textContent = sec.heading;
      jump.title = sec.hint;
      jump.onclick = () => jumpTo(sec.heading);
      row.appendChild(jump);
      const tag = el('span', 'kb-sec-state',
        state === 'ok' ? 'written' : state === 'empty' ? 'empty' : 'missing');
      row.appendChild(tag);
      if (!sec.present) {
        const add = el('button', 'kb-sec-add admin-only', 'Add');
        add.type = 'button';
        add.title = 'Append this heading, with its guidance, to the end of the article.';
        add.onclick = () => addSection(sec);
        row.appendChild(add);
      }
      if (!sec.required) row.classList.add('kb-sec-optional');
      box.appendChild(row);
    });
    const extra = S.article.extra_sections || [];
    if (extra.length) {
      const note = el('p', 'kb-outline-extra',
        'Also present: ' + extra.join(', '));
      box.appendChild(note);
    }
    if (S.article.has_guidance) {
      box.appendChild(el('p', 'kb-outline-warn',
        'Template guidance is still in this article. Exports strip it, but readers of '
        + 'the note itself will see it.'));
    }
  }

  function jumpTo(heading) {
    const ta = $('#kbBody');
    if (!ta) return;
    const at = ta.value.search(new RegExp('^##\\s+' + heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*$', 'mi'));
    if (at < 0) return;
    ta.focus();
    ta.setSelectionRange(at, at + heading.length + 3);
    // Scroll the heading to roughly a third down rather than to the very
    // top: a heading pinned to the top edge shows none of the section it
    // introduces, which is the thing you actually came to look at.
    const before = ta.value.slice(0, at).split('\n').length;
    const lineH = parseFloat(getComputedStyle(ta).lineHeight) || 20;
    ta.scrollTop = Math.max(0, (before - 3) * lineH);
  }

  async function addSection(sec) {
    const ta = $('#kbBody');
    if (!ta) return;
    const body = ta.value.replace(/\s*$/, '');
    ta.value = body + '\n\n## ' + sec.heading + '\n\n*TODO — ' + sec.hint + '*\n';
    await flushBody();
    jumpTo(sec.heading);
  }

  /* ── export mode ─────────────────────────────────────────────────────
     Preview and controls are one request: the server returns the content,
     the manifest and the warnings together, because they are three views of
     the same export and showing a preview next to a stale warning list
     would be worse than showing no warnings at all. */
  async function loadExport() {
    if (!S.slug) { S.exportData = null; return; }
    try {
      S.exportData = await api('/kb/' + S.slug + '/export'
        + `?target=${encodeURIComponent(S.target)}&links=${encodeURIComponent(S.links)}`
        + `&include_meta=${S.includeMeta}&house_style=${S.houseStyle}`);
    } catch (e) {
      S.exportData = null;
      toast('Export failed: ' + String((e && e.message) || e).slice(0, 140), 4500);
    }
  }

  const PREVIEW_CSS =
    "body{margin:0;padding:22px;background:#eef1f4;"
    + "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    + 'font-size:15px;color:#1c2024}'
    + '.fld{margin:0 0 18px}'
    + '.fld h4{margin:0 0 6px;font-size:11px;letter-spacing:.07em;text-transform:uppercase;'
    + 'color:#5b6470;font-weight:700}'
    + '.box{background:#fff;border:1px solid #c9d0d8;border-radius:3px;padding:14px 16px;'
    + 'min-height:38px}'
    + '.plain{margin:0;color:#1c2024}'
    + '.none{margin:0;color:#98a1ad;font-style:italic}';

  function previewDoc(data) {
    if (!data) return '<p>Nothing to preview.</p>';
    if (S.target === 'standalone') return data.content;
    if (S.target === 'servicenow') {
      /* Laid out as the destination form rather than as one document, because
         that document does not exist over there -- the article arrives as
         five separate boxes. A preview that showed a single flowing page
         would be a comfortable lie about what you are about to paste.
         The page carries no stylesheet beyond the box chrome, so everything
         visible inside a box is carried by the markup itself: what survives
         here is what survives the paste. */
      const boxes = (data.parts || []).map((p) => {
        const inner = p.kind === 'html'
          ? (p.content || '<p class="none">empty</p>')
          : (p.content ? '<p class="plain">' + esc(p.content) + '</p>'
            : '<p class="none">empty</p>');
        return `<section class="fld"><h4>${esc(p.field)}</h4>`
          + `<div class="box">${inner}</div></section>`;
      }).join('');
      return '<!doctype html><html><head><meta charset="utf-8"><style>'
        + PREVIEW_CSS + '</style></head><body>' + boxes + '</body></html>';
    }
    return '<!doctype html><html><head><meta charset="utf-8">'
      + '<style>body{margin:0;padding:26px;background:#fff;color:#1c2024}'
      + "pre{margin:0;white-space:pre-wrap;word-wrap:break-word;font-family:Consolas,Monaco,'Courier New',monospace;font-size:13px;line-height:1.55}</style>"
      + '</head><body><pre>' + esc(data.content) + '</pre></body></html>';
  }

  function renderExport() {
    const main = $('#kbMain');
    const aside = $('#kbAside');
    if (!S.article) {
      main.innerHTML = '';
      main.appendChild(el('p', 'kb-empty kb-empty-lg', 'Pick an article to export.'));
      aside.innerHTML = '';
      return;
    }
    const data = S.exportData;
    const fielded = S.target === 'servicenow';
    main.innerHTML = '<div class="kb-previewhead"><span>Preview</span>'
      + `<span class="kb-previewnote">${esc(
        fielded ? `${S.form || 'the form'} — one box per field, unstyled`
          : S.target === 'standalone' ? 'The portable file, exactly as it will open'
            : 'Plain output')}</span></div>`
      + '<iframe id="kbPreview" class="kb-preview" sandbox="allow-same-origin"'
      + ' title="Export preview"></iframe>';
    // srcdoc rather than a blob URL so nothing has to be revoked, and
    // sandboxed without allow-scripts so a pasted <script> in an article
    // can never run inside the app's own origin.
    $('#kbPreview').srcdoc = previewDoc(data);

    const targetOpts = S.targets.map((t) => {
      const label = { servicenow: 'ServiceNow form', standalone: 'Standalone HTML',
        markdown: 'Markdown', text: 'Plain text' }[t] || t;
      return `<option value="${esc(t)}"${t === S.target ? ' selected' : ''}>${esc(label)}</option>`;
    }).join('');

    const manifest = (data && data.manifest) || [];
    const warnings = (data && data.warnings) || [];

    aside.innerHTML = `
      <div class="kb-asidesect">
        <div class="eyebrow"><span>Target</span></div>
        <select id="kbTarget">${targetOpts}</select>
        <label class="sv-fieldlabel" for="kbLinks" style="margin-top:14px">Wiki links become</label>
        <select id="kbLinks">
          <option value="auto">KB number, else the article name</option>
          <option value="number">KB number link</option>
          <option value="url">Source URL link</option>
          <option value="text">Plain text only</option>
        </select>
        ${fielded
          ? '<label class="kb-check" title="Every published article carries the KB\u2019s'
            + ' own stylesheet in each field. Leave this on so yours look like the rest.">'
            + '<input type="checkbox" id="kbHouse"> Use the KB house stylesheet</label>'
          : '<label class="kb-check"><input type="checkbox" id="kbIncMeta">'
            + ' Include the metadata table</label>'}
      </div>
      <div class="kb-asidesect" id="kbCopySect"></div>
      <div class="kb-asidesect" id="kbMapSect"${fielded ? '' : ' hidden'}></div>
      <div class="kb-asidesect">
        <div class="eyebrow"><span>Attachments</span><span>${manifest.length}</span></div>
        <div class="kb-manifest" id="kbManifest"></div>
      </div>
      <div class="kb-asidesect" id="kbWarnSect"${warnings.length ? '' : ' hidden'}>
        <div class="eyebrow"><span>Check before publishing</span></div>
        <ul class="kb-warns">${warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>
      </div>`;

    $('#kbLinks').value = S.links;
    if ($('#kbIncMeta')) $('#kbIncMeta').checked = S.includeMeta;
    if ($('#kbHouse')) $('#kbHouse').checked = S.houseStyle;

    if (fielded) renderFieldCopy(data); else renderWholeCopy(data);
    if (fielded) renderMapping();

    const mbox = $('#kbManifest');
    if (!manifest.length) {
      mbox.appendChild(el('p', 'kb-empty', 'Nothing to attach — this article is text only.'));
    } else {
      manifest.forEach((m) => {
        const row = el('div', 'kb-manrow');
        row.innerHTML = `<span class="kb-mannum">${esc(m.n)}</span>`
          + `<span class="kb-manname">${esc(m.name)}</span>`
          + `<span class="kb-mancap">${esc(m.caption || m.kind)}</span>`;
        mbox.appendChild(row);
      });
    }

    $('#kbTarget').onchange = async (e) => { S.target = e.target.value; await loadExport(); renderExport(); };
    $('#kbLinks').onchange = async (e) => { S.links = e.target.value; await loadExport(); renderExport(); };
    if ($('#kbIncMeta')) {
      $('#kbIncMeta').onchange = async (e) => {
        S.includeMeta = e.target.checked; await loadExport(); renderExport();
      };
    }
    if ($('#kbHouse')) {
      $('#kbHouse').onchange = async (e) => {
        S.houseStyle = e.target.checked; await loadExport(); renderExport();
      };
    }
  }

  /* One copy button per form field, in the order the form asks for them, so
     filling the article in is a walk straight down this list rather than a
     hunt through one blob of HTML for where each section starts. */
  function renderFieldCopy(data) {
    const box = $('#kbCopySect');
    const parts = (data && data.parts) || [];
    box.innerHTML = `<div class="eyebrow"><span>Copy into ${esc(S.form || 'the form')}</span>
      <span>${parts.length}</span></div>`;
    if (!parts.length) {
      box.appendChild(el('p', 'kb-empty', 'Nothing to copy yet — this article has no content.'));
      return;
    }
    parts.forEach((p) => {
      const over = p.limit && p.chars > p.limit;
      const row = el('div', 'kb-fieldcopy' + (over ? ' over' : ''));
      const src = p.sections && p.sections.length ? p.sections.join(' · ') : '';
      row.innerHTML = `
        <div class="kb-fc-head">
          <span class="kb-fc-name">${esc(p.field)}</span>
          <span class="kb-fc-chars">${esc(p.chars)}${p.limit ? ' / ' + esc(p.limit) : ''}</span>
        </div>
        ${src ? `<div class="kb-fc-src">${esc(src)}</div>` : ''}`;
      const actions = el('div', 'kb-fc-actions');
      const copy = el('button', 'sv-btn primary', p.kind === 'html' ? 'Copy formatted' : 'Copy');
      copy.type = 'button';
      copy.onclick = () => (p.kind === 'html' ? copyRich(p.content) : copySource(p.content));
      actions.appendChild(copy);
      if (p.kind === 'html') {
        const srcBtn = el('button', 'sv-btn kb-fc-srcbtn', '<>');
        srcBtn.type = 'button';
        srcBtn.title = 'Copy this field as HTML source, for the editor’s <> view';
        srcBtn.onclick = () => copySource(p.content);
        actions.appendChild(srcBtn);
      }
      row.appendChild(actions);
      box.appendChild(row);
    });
  }

  function renderWholeCopy(data) {
    const box = $('#kbCopySect');
    box.innerHTML = '<div class="eyebrow"><span>Copy</span></div>';
    const row = el('div', 'kb-copyrow');
    const rich = el('button', 'sv-btn primary', 'Copy formatted');
    rich.type = 'button';
    rich.onclick = () => (data && data.mime === 'text/html'
      ? copyRich(data.content) : copySource(data && data.content));
    const src = el('button', 'sv-btn', 'Copy source');
    src.type = 'button';
    src.onclick = () => copySource(data && data.content);
    row.append(rich, src);
    box.appendChild(row);
    const dl = el('button', 'sv-btn', 'Download ' + (data ? data.filename : ''));
    dl.type = 'button';
    dl.onclick = () => {
      const q = `?target=${encodeURIComponent(S.target)}&links=${encodeURIComponent(S.links)}`
        + `&include_meta=${S.includeMeta}`;
      window.location.href = '/api/kb/' + S.slug + '/export/download' + q;
    };
    box.appendChild(dl);
  }

  /* The template decides where each section lands, which is right almost
     always and wrong exactly when someone writes a section the template
     never imagined. This is the override, and it persists into the article's
     own frontmatter so it travels with the file. */
  function renderMapping() {
    const box = $('#kbMapSect');
    const plan = (S.article && S.article.field_plan) || [];
    const rows = [];
    plan.forEach((f) => f.sections.forEach((h) => rows.push({ heading: h, field: f.field })));
    box.innerHTML = '<div class="eyebrow"><span>Section mapping</span></div>';
    if (!rows.length) {
      box.appendChild(el('p', 'kb-empty',
        'No sections yet. Headings you write become fields on the form.'));
      return;
    }
    rows.forEach((r) => {
      const row = el('div', 'kb-maprow');
      const name = el('span', 'kb-map-h', r.heading);
      name.title = r.heading;
      const sel = el('select', 'kb-map-f');
      S.sectionFields.forEach((f) => {
        const o = el('option', null, f);
        o.value = f;
        if (f === r.field) o.selected = true;
        sel.appendChild(o);
      });
      sel.onchange = async () => {
        S.fieldmap = { ...S.fieldmap, [r.heading]: sel.value };
        await flushMeta();
        await refreshArticle();
        await loadExport();
        renderExport();
      };
      row.append(name, sel);
      box.appendChild(row);
    });
  }

  /* Rich copy puts two flavours on the clipboard: text/html for an editor
     that understands formatting, and text/plain for one that does not. The
     execCommand path is not legacy cruft -- it is the only rich copy that
     works outside a secure context, and Tephra is routinely opened over
     plain http on a LAN address, where navigator.clipboard is undefined. */
  async function copyRich(html) {
    if (!html) return;
    try {
      if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
        await navigator.clipboard.write([new ClipboardItem({
          'text/html': new Blob([html], { type: 'text/html' }),
          'text/plain': new Blob([html], { type: 'text/plain' }),
        })]);
        toast('Copied — paste straight into the field');
        return;
      }
    } catch { /* fall through to the selection-based copy below */ }
    const holder = el('div', 'kb-copyholder');
    holder.setAttribute('contenteditable', 'true');
    holder.innerHTML = html;
    document.body.appendChild(holder);
    const range = document.createRange();
    range.selectNodeContents(holder);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const ok = document.execCommand('copy');
    sel.removeAllRanges();
    holder.remove();
    toast(ok ? 'Copied — paste straight into the field'
      : 'Could not reach the clipboard — use Download instead', 4000);
  }

  async function copySource(content) {
    if (!content) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(content);
      } else {
        const ta = el('textarea', 'kb-copyholder');
        ta.value = content;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
      }
      toast('Copied');
    } catch {
      toast('Could not reach the clipboard — use Download instead', 4000);
    }
  }

  /* ── loading ── */
  async function loadArticles() {
    try {
      const res = await api('/kb/articles');
      S.articles = res.articles || [];
    } catch { S.articles = []; }
    renderList();
    renderStats();
  }

  async function refreshArticle() {
    if (!S.slug) { S.article = null; return; }
    try {
      S.article = await api('/kb/' + S.slug);
      S.fieldmap = { ...(S.article.fieldmap || {}) };
    } catch { S.article = null; S.fieldmap = {}; }
  }

  async function openArticle(slug) {
    await flushBody();
    S.slug = slug;
    await refreshArticle();
    renderList();
    if (S.mode === 'export') { await loadExport(); renderExport(); } else renderWrite();
  }

  async function createArticle() {
    const tab = pick.querySelector('[data-pick][aria-pressed="true"]').dataset.pick;
    try {
      let row;
      if (tab === 'adopt') {
        if (!adoptSlug) return toast('Pick a note to adopt first');
        row = await api('/kb/' + adoptSlug + '/adopt', {
          method: 'POST', body: JSON.stringify({ kb_type: $('#kbAdoptType').value }),
        });
      } else {
        row = await api('/kb/articles', {
          method: 'POST',
          body: JSON.stringify({ title: $('#kbNewTitle').value, kb_type: $('#kbNewType').value }),
        });
      }
      showPick(false);
      await loadArticles();
      setMode('write');
      await openArticle(row.slug);
      window.tephraReloadList?.();
    } catch (e) {
      toast('Could not create: ' + String((e && e.message) || e).slice(0, 140), 4000);
    }
  }

  /* Click twice to delete, same as the note editor's own Delete chip.
     Deliberately the same gesture rather than a modal: a confirm dialog
     trains people to dismiss it, and this sits next to Release, which is
     the button most people actually want and which destroys nothing. */
  function wireDelete(btn) {
    if (!btn) return;
    let armed = false, timer = null;
    const disarm = () => {
      armed = false;
      btn.textContent = 'Delete article';
      btn.classList.remove('armed');
      clearTimeout(timer);
    };
    btn.onclick = async () => {
      if (!armed) {
        armed = true;
        btn.textContent = 'Delete — click again';
        btn.classList.add('armed');
        timer = setTimeout(disarm, 4000);
        return;
      }
      disarm();
      await deleteArticle();
    };
  }

  async function deleteArticle() {
    if (!S.slug) return;
    const slug = S.slug;
    const title = (S.article && S.article.title) || slug;
    // Drop the pending autosave before the note goes. A debounced flush that
    // landed after the delete would write the file straight back out of the
    // trash, which is how a deleted note comes back from the dead.
    clearTimeout(saveT);
    S.slug = null;
    S.article = null;
    try {
      await api('/notes/' + encodeURIComponent(slug), { method: 'DELETE' });
    } catch (e) {
      S.slug = slug;
      await refreshArticle();
      toast('Could not delete: ' + String((e && e.message) || e).slice(0, 140), 4000);
      return;
    }
    toast(`Moved “${title}” to the vault trash`);
    await loadArticles();
    // Land on whatever is next rather than on an empty pane -- the list is
    // already sorted, so the top of it is the most recently touched.
    if (S.articles.length) {
      await openArticle(S.articles[0].slug);
    } else {
      S.exportData = null;
      renderList();
      if (S.mode === 'export') renderExport(); else renderWrite();
    }
    // The note is gone from the vault, not just from this deck: the sidebar,
    // the graph and Crucible are all now holding a slug that no longer
    // resolves.
    window.tephraReloadList?.();
    window.tephraStudy?.refresh();
  }

  async function releaseArticle() {
    if (!S.slug) return;
    const slug = S.slug;
    try {
      await api('/kb/' + slug + '/release', { method: 'POST' });
      S.slug = null;
      S.article = null;
      await loadArticles();
      renderWrite();
      toast('Released — the note itself is untouched');
    } catch (e) {
      toast('Could not release: ' + String((e && e.message) || e).slice(0, 140), 4000);
    }
  }

  async function setMode(mode) {
    S.mode = mode;
    view.querySelectorAll('[data-kbmode]').forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset.kbmode === mode)));
    view.classList.toggle('kb-exporting', mode === 'export');
    if (mode === 'export') {
      await flushBody();
      await refreshArticle();
      await loadExport();
      renderExport();
    } else {
      renderWrite();
    }
  }

  /* ── column widths ──────────────────────────────────────────────────────
     Same shape as the notes sidebar's own grip in app.js: a CSS custom
     property on the root, clamped, dragged with document-level listeners so
     the pointer can leave the 9px strip without the drag dying, and
     remembered in localStorage. Deliberately the same rather than a second
     mechanism -- one of these to learn, not two. */
  const COLS = {
    list:  { var: '--kb-list-w',  key: 'tephra.kb.listw',  min: 150, max: 460, def: 238 },
    pal:   { var: '--kb-pal-w',   key: 'tephra.kb.palw',   min: 46,  max: 300, def: 152 },
    right: { var: '--kb-right-w', key: 'tephra.kb.rightw', min: 260, max: 900, def: 420 },
  };
  const COLLAPSE_KEY = 'tephra.kb.rightcollapsed';

  function setCol(name, px) {
    const c = COLS[name];
    const w = Math.min(c.max, Math.max(c.min, Math.round(px)));
    document.documentElement.style.setProperty(c.var, w + 'px');
    return w;
  }

  function restoreCols() {
    Object.keys(COLS).forEach((name) => {
      const c = COLS[name];
      let saved = parseInt(localStorage.getItem(c.key), 10);
      if (!(saved >= c.min && saved <= c.max)) saved = c.def;
      document.documentElement.style.setProperty(c.var, saved + 'px');
    });
    setRenderCollapsed(localStorage.getItem(COLLAPSE_KEY) === '1', true);
  }

  function wireGrips() {
    view.querySelectorAll('.kb-grip').forEach((grip) => {
      const name = grip.dataset.grip;
      const c = COLS[name];
      if (!c) return;
      // The right column grows leftwards, so its drag reads the opposite
      // direction from the other two.
      const sign = name === 'right' ? -1 : 1;
      let startX = 0, startW = 0;
      const onMove = (e) => setCol(name, startW + sign * (e.clientX - startX));
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.classList.remove('resizing-sidebar');
        grip.classList.remove('dragging');
        const w = parseInt(
          document.documentElement.style.getPropertyValue(c.var), 10);
        if (w) localStorage.setItem(c.key, String(w));
      };
      grip.addEventListener('mousedown', (e) => {
        e.preventDefault();
        // A collapsed render has no width to drag; reopen it instead of
        // starting a drag from zero.
        if (name === 'right' && S.renderCollapsed) return setRenderCollapsed(false);
        startX = e.clientX;
        startW = grip.parentElement.getBoundingClientRect().width;
        document.body.classList.add('resizing-sidebar');
        grip.classList.add('dragging');
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
      });
      // Double-click restores the default, the usual escape hatch for a
      // column dragged somewhere useless.
      grip.addEventListener('dblclick', () => {
        setCol(name, c.def);
        localStorage.setItem(c.key, String(c.def));
      });
    });
  }

  /* Collapsing hides the whole right column rather than only the render:
     Structure and Fields live in the same space, and leaving an empty
     column behind would be worse than either. */
  function setRenderCollapsed(on, quiet) {
    S.renderCollapsed = !!on;
    view.classList.toggle('kb-collapsed', S.renderCollapsed);
    const btn = $('#kbCollapse');
    if (btn) {
      btn.textContent = S.renderCollapsed ? '\u00ab' : '\u00bb';
      btn.title = S.renderCollapsed
        ? 'Show the render, structure and fields'
        : 'Hide the right column and give the markdown the space';
    }
    if (!quiet) localStorage.setItem(COLLAPSE_KEY, S.renderCollapsed ? '1' : '0');
    // Re-render on the way back so the preview is not showing stale text
    // written while it was hidden.
    if (!S.renderCollapsed && S.rightTab === 'render') loadPreview();
  }

  /* ── open / close ── */
  async function open() {
    S.open = true;
    view.classList.add('on');
    document.body.classList.add('kbdeck');
    document.getElementById('theme')?.classList.remove('on');
    if (!S.ready) {
      try {
        const t = await api('/kb/templates');
        S.templates = t.templates || [];
        S.fields = t.fields || [];
        S.targets = t.targets || ['servicenow'];
        S.sectionFields = t.section_fields || [];
        S.blocks = t.blocks || [];
        S.blockGroups = t.block_groups || [];
        S.form = t.form || '';
        S.ready = true;
        fillTypeSelects();
      } catch (e) {
        $('#kbMain').innerHTML = '';
        $('#kbMain').appendChild(el('p', 'kb-empty kb-empty-lg',
          'Could not load KB templates: ' + String((e && e.message) || e).slice(0, 200)));
        return;
      }
    }
    await loadArticles();
    if (!S.slug && S.articles.length) S.slug = S.articles[0].slug;
    await refreshArticle();
    renderList();
    setMode(S.mode);
  }

  function close() {
    flushBody();
    S.open = false;
    view.classList.remove('on');
    document.body.classList.remove('kbdeck');
    showPick(false);
  }

  /* ── wiring ── */
  view.querySelectorAll('[data-kbmode]').forEach((b) => {
    b.onclick = () => setMode(b.dataset.kbmode);
  });
  pick.querySelectorAll('[data-pick]').forEach((b) => {
    b.onclick = () => setPickTab(b.dataset.pick);
  });
  restoreCols();
  wireGrips();
  $('#kbReopen').onclick = () => setRenderCollapsed(false);
  $('#kbNew').onclick = () => showPick(true);
  $('#kbPickCancel').onclick = () => showPick(false);
  $('#kbPickGo').onclick = createArticle;
  $('#kbNewType').onchange = showTplSummary;
  $('#kbAdoptFind').oninput = (e) => renderAdoptList(e.target.value);
  $('#kbFilter').oninput = (e) => { S.filter = e.target.value; renderList(); };
  pick.onclick = (e) => { if (e.target === pick) showPick(false); };

  window.tephraKb = {
    open, close, isOpen: () => S.open,
    // Exposed for the same reason Crucible exposes refresh(): a vault switch
    // has to invalidate everything this deck is holding, and it has no way
    // of noticing on its own.
    reset: async () => {
      S.slug = null; S.article = null; S.exportData = null; S.articles = [];
      if (S.open) { await loadArticles(); setMode(S.mode); }
    },
  };
})();
