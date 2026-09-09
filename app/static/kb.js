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
    exportData: null,
    filter: '',
    picking: false,
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
        <div class="eyebrow"><span>Articles</span><span id="kbCount">—</span></div>
        <input type="search" id="kbFilter" placeholder="Filter articles…" autocomplete="off">
        <div id="kbRows" class="kb-rows"></div>
        <button class="newnote admin-only" id="kbNew">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.4"><path d="M12 5v14M5 12h14"/></svg>
          New article
        </button>
      </aside>
      <section class="kb-main" id="kbMain"></section>
      <aside class="kb-aside" id="kbAside"></aside>
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
    const meta = { kb_type: S.article ? S.article.template : '' };
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

  /* ── write mode ── */
  function renderWrite() {
    const main = $('#kbMain');
    if (!S.article) {
      main.innerHTML = '';
      main.appendChild(el('p', 'kb-empty kb-empty-lg',
        'Pick an article on the left, or start a new one.'));
      $('#kbAside').innerHTML = '';
      return;
    }
    const a = S.article;
    main.innerHTML = `
      <input type="text" id="kbTitle" class="kb-title" value="${esc(a.title)}"
             placeholder="Article title">
      <textarea id="kbBody" class="kb-editor" spellcheck="true"
                placeholder="Write the article in markdown."></textarea>`;
    $('#kbBody').value = a.body || '';
    $('#kbTitle').oninput = queueSave;
    $('#kbBody').oninput = queueSave;
    renderAside();
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
      <div class="kb-asidesect">
        <div class="eyebrow"><span>Structure</span><span>${esc(tpl ? tpl.name : '')}</span></div>
        <div id="kbOutline" class="kb-outline"></div>
      </div>
      <div class="kb-asidesect">
        <div class="eyebrow"><span>Metadata</span></div>
        <div class="kb-fields admin-only">${fields}</div>
      </div>
      <div class="kb-asidesect">
        <button class="sv-btn admin-only" id="kbRelease"
          title="Stop treating this note as a KB article. The prose is untouched.">
          Release from KB</button>
      </div>`;

    S.fields.forEach((f) => {
      const input = $('#kbf-' + f.key);
      if (!input) return;
      if (f.kind === 'select') input.value = kbm[f.key] || '';
      input.oninput = queueMeta;
      input.onchange = queueMeta;
    });
    $('#kbRelease').onclick = releaseArticle;
    renderOutline();
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
        + `&include_meta=${S.includeMeta}`);
    } catch (e) {
      S.exportData = null;
      toast('Export failed: ' + String((e && e.message) || e).slice(0, 140), 4500);
    }
  }

  function previewDoc(data) {
    if (!data) return '<p>Nothing to preview.</p>';
    if (S.target === 'standalone') return data.content;
    if (S.target === 'servicenow') {
      // A plain white page with no stylesheet of its own. That is the whole
      // point: everything visible here is carried by the markup itself, so
      // anything that survives the paste survives here too, and anything
      // that does not is visibly absent right now rather than after.
      return '<!doctype html><html><head><meta charset="utf-8">'
        + '<style>body{margin:0;padding:26px;background:#fff;'
        + "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
        + 'font-size:15px;color:#1c2024}</style></head><body>' + data.content + '</body></html>';
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
    main.innerHTML = '<div class="kb-previewhead"><span>Preview</span>'
      + `<span class="kb-previewnote">${esc(
        S.target === 'servicenow' ? 'Unstyled page — only what the markup carries'
          : S.target === 'standalone' ? 'The portable file, exactly as it will open'
            : 'Plain output')}</span></div>`
      + '<iframe id="kbPreview" class="kb-preview" sandbox="allow-same-origin"'
      + ' title="Export preview"></iframe>';
    // srcdoc rather than a blob URL so nothing has to be revoked, and
    // sandboxed without allow-scripts so a pasted <script> in an article
    // can never run inside the app's own origin.
    $('#kbPreview').srcdoc = previewDoc(data);

    const targetOpts = S.targets.map((t) => {
      const label = { servicenow: 'ServiceNow / rich paste', standalone: 'Standalone HTML',
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
        <label class="kb-check"><input type="checkbox" id="kbIncMeta"> Include the metadata table</label>
      </div>
      <div class="kb-asidesect">
        <div class="eyebrow"><span>Copy</span></div>
        <div class="kb-copyrow">
          <button class="sv-btn primary" id="kbCopyRich">Copy formatted</button>
          <button class="sv-btn" id="kbCopySrc">Copy source</button>
        </div>
        <p class="kb-fieldhint" id="kbCopyHint"></p>
        <button class="sv-btn" id="kbDownload">Download ${esc(data ? data.filename : '')}</button>
      </div>
      <div class="kb-asidesect">
        <div class="eyebrow"><span>Attachments</span><span>${manifest.length}</span></div>
        <div class="kb-manifest" id="kbManifest"></div>
      </div>
      <div class="kb-asidesect" id="kbWarnSect"${warnings.length ? '' : ' hidden'}>
        <div class="eyebrow"><span>Check before publishing</span></div>
        <ul class="kb-warns">${warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>
      </div>`;

    $('#kbLinks').value = S.links;
    $('#kbIncMeta').checked = S.includeMeta;
    $('#kbCopyHint').textContent = S.target === 'servicenow'
      ? 'Formatted pastes into the article body. Source pastes into the editor’s <> view.'
      : 'Formatted and source are the same for this target.';

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
    $('#kbIncMeta').onchange = async (e) => { S.includeMeta = e.target.checked; await loadExport(); renderExport(); };
    $('#kbCopyRich').onclick = () => copyRich(data);
    $('#kbCopySrc').onclick = () => copySource(data);
    $('#kbDownload').onclick = () => {
      const q = `?target=${encodeURIComponent(S.target)}&links=${encodeURIComponent(S.links)}`
        + `&include_meta=${S.includeMeta}`;
      window.location.href = '/api/kb/' + S.slug + '/export/download' + q;
    };
  }

  /* Rich copy puts two flavours on the clipboard: text/html for an editor
     that understands formatting, and text/plain for one that does not. The
     execCommand path is not legacy cruft -- it is the only rich copy that
     works outside a secure context, and Tephra is routinely opened over
     plain http on a LAN address, where navigator.clipboard is undefined. */
  async function copyRich(data) {
    if (!data) return;
    const html = data.mime === 'text/html' ? data.content : null;
    if (!html) return copySource(data);
    try {
      if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
        await navigator.clipboard.write([new ClipboardItem({
          'text/html': new Blob([html], { type: 'text/html' }),
          'text/plain': new Blob([html], { type: 'text/plain' }),
        })]);
        toast('Formatted article copied — paste into the article body');
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
    toast(ok ? 'Formatted article copied — paste into the article body'
      : 'Could not reach the clipboard — use Download instead', 4000);
  }

  async function copySource(data) {
    if (!data) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(data.content);
      } else {
        const ta = el('textarea', 'kb-copyholder');
        ta.value = data.content;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
      }
      toast('Source copied');
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
    try { S.article = await api('/kb/' + S.slug); } catch { S.article = null; }
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
