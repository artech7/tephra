/* ══════════════════════════════════════════════════════════════
   Sheets: a ```sheets fence -- several markdown tables in one card,
   switched by tabs, for the "one spreadsheet, several sheets" shape a
   single table can't express (a per-week course plan, a roster per
   team).

   The split with the backend is the opposite of netdiagram.js's. There,
   render.py is a dumb passthrough and this layer owns the whole format.
   Here render.py renders the tables itself -- the fence content is
   ordinary markdown, so its cells go through the same wikilink/embed
   pass as the rest of the note and a [[link]] in a cell reaches the
   graph. What lives here is only what the server can't do: switching
   tabs, and the grid editor.

   Two editing paths, both writing the same text:
     - the note's own source editor, since the stored form is just
       `## Sheet name` headings and plain GFM tables -- nothing special
       to learn, and it stays readable outside Tephra;
     - the grid editor below: click a cell, type, Tab/Enter to move,
       buttons for rows/columns/sheets. On every change it re-serializes
       the whole group and rewrites that one fence in the note body
       through app.js's tephraSaveNoteBody bridge -- the same arm's-
       length relationship netdiagram.js/quiz-editor.js keep with
       app.js's internals.

   A cell's text is markdown, so a wikilink is typed by hand as
   [[Note Title]] rather than picked from a list. One wrinkle that
   forces: GFM needs a literal `|` inside a cell escaped as `\|`, which
   makes [[Note|shown]] break a table unless escaped. splitRow below
   unescapes on the way into the grid and escapeCell re-escapes on the
   way out, so the grid shows what you'd expect and the file stays valid.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const $ = (s) => document.querySelector(s);

  /* ── parsing ──────────────────────────────────────────────── */

  const SHEET_HEAD_RE = /^##[ \t]+(.+?)[ \t]*$/;
  // A separator row: only dashes and optional alignment colons.
  const SEP_CELL_RE = /^:?-+:?$/;

  // Split one `| a | b |` row into cells, honouring GFM's `\|` escape so a
  // cell containing a literal pipe (most usefully [[Note|shown]]) survives
  // as one cell instead of splitting in two.
  function splitRow(line) {
    let t = line.trim();
    if (t.startsWith('|')) t = t.slice(1);
    if (t.endsWith('|')) t = t.slice(0, -1);
    const cells = [];
    let cur = '';
    for (let i = 0; i < t.length; i++) {
      if (t[i] === '\\' && t[i + 1] === '|') { cur += '|'; i++; continue; }
      if (t[i] === '|') { cells.push(cur.trim()); cur = ''; continue; }
      cur += t[i];
    }
    cells.push(cur.trim());
    return cells;
  }

  function isSeparatorRow(cells) {
    return cells.length > 0 && cells.every((c) => SEP_CELL_RE.test(c.trim()));
  }

  // -> [{ name, headers:[str], body:[[str]] }]
  function parseSheets(text) {
    const groups = [];
    let cur = null;
    for (const line of String(text || '').split('\n')) {
      const h = SHEET_HEAD_RE.exec(line);
      if (h) { cur = { name: h[1], rows: [] }; groups.push(cur); continue; }
      if (!/^\s*\|/.test(line)) continue;
      // A table with no heading above it (a lone table wrapped in the
      // fence) still gets a sheet, matching render.py's own fallback.
      if (!cur) { cur = { name: 'Sheet 1', rows: [] }; groups.push(cur); }
      const cells = splitRow(line);
      if (isSeparatorRow(cells)) continue;
      cur.rows.push(cells);
    }
    return groups.map((g) => {
      const headers = g.rows.length ? g.rows[0] : ['Column 1'];
      const width = headers.length;
      // Normalise every row to the header's width: a hand-written table
      // with a short row would otherwise render a ragged grid, and the
      // editor's per-column delete would go out of bounds on it.
      const body = g.rows.slice(1).map((r) => {
        const row = r.slice(0, width);
        while (row.length < width) row.push('');
        return row;
      });
      return { name: g.name, headers, body };
    });
  }

  /* ── serializing ──────────────────────────────────────────── */

  function escapeCell(v) {
    // A newline inside a cell would end the table row; a bare `|` would
    // split it. Both are collapsed rather than rejected -- an edit should
    // never be able to produce a file that no longer parses.
    return String(v == null ? '' : v).replace(/\r?\n/g, ' ').replace(/\|/g, '\\|').trim();
  }

  function serializeSheets(model) {
    const out = [];
    for (const s of model) {
      out.push('## ' + String(s.name || 'Sheet').replace(/\r?\n/g, ' ').trim());
      out.push('');
      out.push('| ' + s.headers.map(escapeCell).join(' | ') + ' |');
      out.push('| ' + s.headers.map(() => '---').join(' | ') + ' |');
      for (const row of s.body) {
        out.push('| ' + s.headers.map((_, i) => escapeCell(row[i])).join(' | ') + ' |');
      }
      out.push('');
    }
    return out.join('\n').trim();
  }

  /* ── persisting: rewrite only the Nth ```sheets fence, leaving the rest
     of the body byte-identical (same approach as netdiagram.js's
     setNetDiagramBody). ─────────────────────────────────────────────── */

  const SHEETS_FENCE_RE_G = /^```sheets[ \t]*\n[\s\S]*?^```[ \t]*$/gm;

  function setSheetsBody(body, index, newInnerText) {
    let i = -1;
    return body.replace(SHEETS_FENCE_RE_G, (whole) => {
      i++;
      if (i !== index) return whole;
      return '```sheets\n' + newInnerText + '\n```';
    });
  }

  /* ── reading view: tab switching ──────────────────────────── */

  function showSheet(card, n) {
    for (const t of card.querySelectorAll('.sheet-tab')) {
      const on = Number(t.dataset.sheet) === n;
      t.classList.toggle('on', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    }
    for (const p of card.querySelectorAll('.sheet-pane')) {
      p.classList.toggle('on', Number(p.dataset.sheet) === n);
    }
  }

  function enhanceSheets() {
    for (const card of document.querySelectorAll('#noteBody .sheets:not([data-processed])')) {
      card.setAttribute('data-processed', 'true');

      card.addEventListener('click', (e) => {
        const tab = e.target.closest('.sheet-tab');
        if (!tab || !card.contains(tab)) return;
        // A tab click must not bubble into the note body's own
        // double-click-to-edit handler and swap the whole note into the
        // source editor mid-navigation.
        e.stopPropagation();
        showSheet(card, Number(tab.dataset.sheet));
      });
      card.addEventListener('dblclick', (e) => {
        if (e.target.closest('.sheet-tab, .sheet-edit')) e.stopPropagation();
      });

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sheet-edit';
      btn.title = 'Edit as a grid';
      btn.textContent = 'Edit';
      btn.addEventListener('click', (e) => { e.stopPropagation(); openEditor(card); });
      card.appendChild(btn);
    }
  }

  /* ── the grid editor ─────────────────────────────────────────
     One shared overlay (like #lens / the netdiagram editor), editing
     whichever card was last opened. Every mutation goes through
     mutate(), which re-renders and reschedules a debounced save --
     there's no separate "apply" step to forget to press. ──────────── */

  let ed = null;          // { card, index, slug, model, active }
  let saveTimer = null;

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      if (!ed) return;
      const text = serializeSheets(ed.model);
      window.tephraSaveNoteBody?.(ed.slug, (body) => setSheetsBody(body, ed.index, text));
    }, 500);
  }

  function mutate(fn) {
    if (!ed) return;
    fn();
    renderGrid();
    scheduleSave();
  }

  function currentSheet() {
    return ed?.model[ed.active] || null;
  }

  function openEditor(card) {
    const overlay = $('#shtOverlay');
    if (!overlay) return;
    const index = Number(card.dataset.sheetsIndex);
    // Read the authoritative text from the note source, not from the
    // rendered DOM -- the DOM holds resolved <a> tags, not the original
    // [[wikilink]] text, so round-tripping through it would silently
    // rewrite every link in every cell into its display text.
    const src = $('#noteSrc')?.value || '';
    let raw = '';
    let i = -1;
    src.replace(SHEETS_FENCE_RE_G, (whole) => {
      i++;
      if (i === index) raw = whole.replace(/^```sheets[ \t]*\n/, '').replace(/\n?```[ \t]*$/, '');
      return whole;
    });
    const model = parseSheets(raw);
    if (!model.length) model.push({ name: 'Sheet 1', headers: ['Column 1'], body: [['']] });
    ed = { card, index, slug: window.tephraCurrentSlug?.(), model, active: 0 };
    overlay.hidden = false;
    renderGrid();
  }

  function closeEditor() {
    const overlay = $('#shtOverlay');
    if (overlay) overlay.hidden = true;
    if (ed) {
      // Flush immediately rather than letting the debounce fire after the
      // editor is gone, so closing and switching notes straight away can't
      // drop the last keystroke.
      clearTimeout(saveTimer);
      const text = serializeSheets(ed.model);
      window.tephraSaveNoteBody?.(ed.slug, (body) => setSheetsBody(body, ed.index, text));
    }
    ed = null;
  }

  function renderGrid() {
    const host = $('#shtGrid');
    const tabsHost = $('#shtTabs');
    if (!host || !tabsHost || !ed) return;

    // ── sheet tabs (bottom, like a spreadsheet) ──
    tabsHost.innerHTML = '';
    ed.model.forEach((s, i) => {
      const t = document.createElement('button');
      t.type = 'button';
      t.className = 'sht-tab' + (i === ed.active ? ' on' : '');
      t.textContent = s.name;
      t.title = 'Double-click to rename';
      t.addEventListener('click', () => { ed.active = i; renderGrid(); });
      t.addEventListener('dblclick', () => {
        const name = prompt('Sheet name', s.name);
        if (name && name.trim()) mutate(() => { s.name = name.trim(); });
      });
      tabsHost.appendChild(t);
    });
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'sht-tab sht-tab-add';
    add.textContent = '+';
    add.title = 'Add a sheet';
    add.addEventListener('click', () => mutate(() => {
      ed.model.push({ name: 'Sheet ' + (ed.model.length + 1), headers: ['Column 1'], body: [['']] });
      ed.active = ed.model.length - 1;
    }));
    tabsHost.appendChild(add);

    const sheet = currentSheet();
    if (!sheet) { host.innerHTML = ''; return; }

    // ── the grid itself ──
    host.innerHTML = '';
    const table = document.createElement('table');
    table.className = 'sht-table';

    const thead = document.createElement('thead');
    const hrow = document.createElement('tr');
    hrow.appendChild(document.createElement('th')).className = 'sht-corner';
    sheet.headers.forEach((h, c) => {
      const th = document.createElement('th');
      const inp = document.createElement('input');
      inp.value = h;
      inp.dataset.r = '-1';
      inp.dataset.c = String(c);
      inp.addEventListener('input', () => { sheet.headers[c] = inp.value; scheduleSave(); });
      inp.addEventListener('keydown', onCellKey);
      th.appendChild(inp);
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'sht-del';
      del.title = 'Delete this column';
      del.textContent = '×';
      del.disabled = sheet.headers.length <= 1;
      del.addEventListener('click', () => mutate(() => {
        sheet.headers.splice(c, 1);
        for (const row of sheet.body) row.splice(c, 1);
      }));
      th.appendChild(del);
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    sheet.body.forEach((row, r) => {
      const tr = document.createElement('tr');
      const rh = document.createElement('th');
      rh.className = 'sht-rowhead';
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'sht-del';
      del.title = 'Delete this row';
      del.textContent = '×';
      del.addEventListener('click', () => mutate(() => { sheet.body.splice(r, 1); }));
      rh.appendChild(del);
      tr.appendChild(rh);
      sheet.headers.forEach((_, c) => {
        const td = document.createElement('td');
        const inp = document.createElement('input');
        inp.value = row[c] == null ? '' : row[c];
        inp.dataset.r = String(r);
        inp.dataset.c = String(c);
        inp.addEventListener('input', () => { row[c] = inp.value; scheduleSave(); });
        inp.addEventListener('keydown', onCellKey);
        td.appendChild(inp);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  // Tab/Shift-Tab across a row, Enter/Shift-Enter down a column, arrows
  // only when the caret is already at the end of the text (so left/right
  // still move within a cell normally). Tab past the last cell of the last
  // row adds a row, the way a spreadsheet does -- typing shouldn't require
  // reaching for a button to keep going.
  function onCellKey(e) {
    const inp = e.currentTarget;
    const r = Number(inp.dataset.r);
    const c = Number(inp.dataset.c);
    const sheet = currentSheet();
    if (!sheet) return;

    const focus = (rr, cc) => {
      const sel = `#shtGrid input[data-r="${rr}"][data-c="${cc}"]`;
      const t = document.querySelector(sel);
      if (t) { t.focus(); t.select(); return true; }
      return false;
    };

    if (e.key === 'Escape') { e.preventDefault(); closeEditor(); return; }
    if (e.key === 'Tab') {
      e.preventDefault();
      const dir = e.shiftKey ? -1 : 1;
      if (focus(r, c + dir)) return;
      if (dir === 1) {
        if (focus(r + 1, 0)) return;
        mutate(() => { sheet.body.push(sheet.headers.map(() => '')); });
        focus(sheet.body.length - 1, 0);
      } else if (r >= 0) {
        focus(r - 1, sheet.headers.length - 1);
      }
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const dir = e.shiftKey ? -1 : 1;
      if (focus(r + dir, c)) return;
      if (dir === 1) {
        mutate(() => { sheet.body.push(sheet.headers.map(() => '')); });
        focus(sheet.body.length - 1, c);
      }
      return;
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); focus(r + 1, c); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); focus(r - 1, c); return; }
  }

  /* ── toolbar wiring ──────────────────────────────────────── */

  $('#shtAddRow')?.addEventListener('click', () => mutate(() => {
    const s = currentSheet();
    if (s) s.body.push(s.headers.map(() => ''));
  }));
  $('#shtAddCol')?.addEventListener('click', () => mutate(() => {
    const s = currentSheet();
    if (!s) return;
    s.headers.push('Column ' + (s.headers.length + 1));
    for (const row of s.body) row.push('');
  }));
  $('#shtDelSheet')?.addEventListener('click', () => {
    const s = currentSheet();
    if (!s || !ed) return;
    if (ed.model.length <= 1) { window.toast?.('A sheet group needs at least one sheet'); return; }
    if (!confirm(`Delete the sheet “${s.name}”?`)) return;
    mutate(() => {
      ed.model.splice(ed.active, 1);
      ed.active = Math.max(0, ed.active - 1);
    });
  });
  $('#shtClose')?.addEventListener('click', closeEditor);

  window.tephraSheets = {
    parse: parseSheets,
    serialize: serializeSheets,
    setBody: setSheetsBody,
    enhance: enhanceSheets,
  };
})();
