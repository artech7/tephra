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

  // A column's width is its dash count in the delimiter row -- see the long
  // note next to _sheet_widths in render.py, which is the authority on the
  // format and must agree with these three numbers. 3 or fewer means unset.
  const W_UNSET = 3, W_MIN = 6, W_MAX = 60;

  function widthFromCell(cell) {
    const n = (String(cell).match(/-/g) || []).length;
    return n <= W_UNSET ? null : Math.max(W_MIN, Math.min(W_MAX, n));
  }

  // Rebuild one delimiter cell at the given width, keeping whatever
  // alignment colons it already had -- a resize must not silently
  // re-align a column that was deliberately centred or right-aligned.
  function widthToCell(width, prev) {
    const p = String(prev || '');
    const left = p.startsWith(':') ? ':' : '';
    const right = p.endsWith(':') ? ':' : '';
    const n = width == null ? 3 : Math.max(W_MIN, Math.min(W_MAX, width));
    return left + '-'.repeat(n) + right;
  }

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
      // The delimiter row carries the column widths, so it's kept rather
      // than skipped -- but only the first one per sheet, which is the one
      // belonging to the sheet's own table.
      if (isSeparatorRow(cells)) {
        if (!cur.sep) cur.sep = cells;
        continue;
      }
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
      const sep = g.sep || [];
      // One entry per header, so a column added by hand to the header row
      // without a matching delimiter cell still has a slot to be resized.
      const widths = headers.map((_, i) => widthFromCell(sep[i] || ''));
      const align = headers.map((_, i) => sep[i] || '---');
      return { name: g.name, headers, body, widths, align };
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
      // Widths (and any alignment colons) survive a grid edit: writing a
      // bare '---' here would quietly reset every column the moment
      // someone typed in a cell.
      out.push('| ' + s.headers.map((_, i) =>
        widthToCell(s.widths ? s.widths[i] : null,
                    s.align ? s.align[i] : '---')).join(' | ') + ' |');
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

  /* ── persisting a column resize ────────────────────────────────
     Deliberately not a serializeSheets() round-trip. Re-emitting the whole
     group to change a column width would rewrite every cell in it, and a
     resize has no business touching cell text at all -- one bug in the
     `\|` escaping and dragging a column border would corrupt a wikilink.
     This rewrites exactly one line: the target sheet's delimiter row.
     ─────────────────────────────────────────────────────────────────── */

  function setSheetWidths(body, fenceIndex, sheetIndex, widths) {
    let f = -1;
    return body.replace(SHEETS_FENCE_RE_G, (whole) => {
      f++;
      if (f !== fenceIndex) return whole;
      const open = whole.match(/^```sheets[ \t]*\n/)[0];
      const inner = whole.replace(/^```sheets[ \t]*\n/, '').replace(/\n?```[ \t]*$/, '');
      let sheet = -1, done = false;
      const lines = inner.split('\n').map((line) => {
        if (done) return line;
        if (SHEET_HEAD_RE.test(line)) { sheet++; return line; }
        if (!/^\s*\|/.test(line)) return line;
        // A table with no `##` heading above it is sheet 0, matching
        // parseSheets and render.py's shared fallback.
        if (sheet === -1) sheet = 0;
        if (sheet !== sheetIndex) return line;
        const cells = splitRow(line);
        if (!isSeparatorRow(cells)) return line;
        done = true;
        return '| ' + cells.map((c, i) => widthToCell(widths[i], c)).join(' | ') + ' |';
      });
      return open + lines.join('\n') + '\n```';
    });
  }

  /* ── reading view: column resizing ─────────────────────────────
     The stored unit is characters, so a drag in pixels has to be converted
     -- measured off the table's own font rather than assumed, because the
     appearance panel can change the note font size underneath us and a
     hardcoded px-per-char would drift from what the delimiter row means.
     ─────────────────────────────────────────────────────────────────── */

  function charPx(table) {
    const probe = document.createElement('span');
    probe.textContent = '0'.repeat(20);
    probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre';
    table.appendChild(probe);
    const w = probe.getBoundingClientRect().width / 20;
    probe.remove();
    return w || 8;
  }

  function colsOf(table) {
    let cg = table.querySelector('colgroup');
    const headers = table.querySelectorAll('thead th');
    if (!cg) {
      cg = document.createElement('colgroup');
      for (let i = 0; i < headers.length; i++) cg.appendChild(document.createElement('col'));
      table.insertBefore(cg, table.firstChild);
    }
    // A table whose delimiter row had fewer cells than its header row comes
    // back with a short colgroup; pad it so every header has a col to size.
    while (cg.children.length < headers.length) cg.appendChild(document.createElement('col'));
    return [...cg.children];
  }

  function widthsOf(cols) {
    return cols.map((c) => {
      const m = /([\d.]+)ch/.exec(c.style.width || '');
      return m ? Math.round(Number(m[1])) : null;
    });
  }

  function attachGrips(card) {
    for (const pane of card.querySelectorAll('.sheet-pane')) {
      const table = pane.querySelector('table');
      if (!table) continue;
      const sheetIndex = Number(pane.dataset.sheet);
      table.querySelectorAll('thead th').forEach((th, c) => {
        if (th.querySelector('.sheet-grip')) return;
        const grip = document.createElement('span');
        grip.className = 'sheet-grip';
        grip.title = 'Drag to resize; double-click to reset';
        th.appendChild(grip);

        grip.addEventListener('pointerdown', (e) => {
          e.preventDefault();
          e.stopPropagation();
          const cols = colsOf(table);
          const unit = charPx(table);
          const startX = e.clientX;
          const startCh = widthsOf(cols)[c] ?? Math.round(th.getBoundingClientRect().width / unit);
          grip.classList.add('dragging');
          document.body.classList.add('sheet-resizing');
          // Fixed layout has to go on *now*, not on release: under auto
          // layout the <col> width is only a hint, so the column wouldn't
          // visibly follow the pointer and the drag would feel broken.
          pane.classList.add('sheet-fixed');
          grip.setPointerCapture?.(e.pointerId);

          const onMove = (ev) => {
            const ch = Math.max(W_MIN, Math.min(W_MAX,
              Math.round(startCh + (ev.clientX - startX) / unit)));
            cols[c].style.width = ch + 'ch';
          };
          const onUp = () => {
            grip.removeEventListener('pointermove', onMove);
            grip.removeEventListener('pointerup', onUp);
            grip.removeEventListener('pointercancel', onUp);
            grip.classList.remove('dragging');
            document.body.classList.remove('sheet-resizing');
            saveWidths(card, sheetIndex, widthsOf(colsOf(table)));
          };
          grip.addEventListener('pointermove', onMove);
          grip.addEventListener('pointerup', onUp);
          grip.addEventListener('pointercancel', onUp);
        });

        // Double-click a grip to hand the column back to auto sizing --
        // otherwise the only way out of a width you regret is the source
        // editor, since there's no width you can drag to that means "auto".
        grip.addEventListener('dblclick', (e) => {
          e.preventDefault();
          e.stopPropagation();
          const cols = colsOf(table);
          cols[c].style.width = '';
          const w = widthsOf(cols);
          if (!w.some((x) => x != null)) pane.classList.remove('sheet-fixed');
          saveWidths(card, sheetIndex, w);
        });
      });
    }
  }

  function saveWidths(card, sheetIndex, widths) {
    const fenceIndex = Number(card.dataset.sheetsIndex);
    const slug = window.tephraCurrentSlug?.();
    if (!slug || Number.isNaN(fenceIndex)) return;
    window.tephraSaveNoteBody?.(slug, (body) =>
      setSheetWidths(body, fenceIndex, sheetIndex, widths));
  }

  /* ── reading view: tab switching ──────────────────────────── */

  function showSheet(card, n) {
    for (const t of card.querySelectorAll('.sheet-tab')) {
      const on = Number(t.dataset.sheet) === n;
      t.classList.toggle('on', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on && viewing && viewing.card === card) {
        const title = $('#shtViewTitle');
        if (title) title.textContent = t.textContent;
      }
    }
    for (const p of card.querySelectorAll('.sheet-pane')) {
      p.classList.toggle('on', Number(p.dataset.sheet) === n);
    }
  }

  function enhanceSheets() {
    // A note re-render replaces #noteBody's innerHTML, which destroys the
    // placeholder marking where an expanded card came from -- leaving that
    // card orphaned inside the overlay with nowhere to return to. Drop it
    // rather than restoring a card that belongs to a note no longer shown.
    if (viewing && !viewing.placeholder.isConnected) {
      const ov = $('#shtViewOverlay');
      if (ov) ov.hidden = true;
      viewing.card.remove();
      viewing = null;
    }
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

      attachGrips(card);

      const exp = document.createElement('button');
      exp.type = 'button';
      exp.className = 'sheet-expand';
      exp.title = 'Expand to full screen';
      exp.textContent = '⤢';
      exp.addEventListener('click', (e) => { e.stopPropagation(); openViewer(card); });
      card.appendChild(exp);

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sheet-edit';
      btn.title = 'Edit as a grid';
      btn.textContent = 'Edit';
      btn.addEventListener('click', (e) => { e.stopPropagation(); openEditor(card); });
      card.appendChild(btn);
    }
  }

  /* ── fullscreen reading view ──────────────────────────────────
     Moves the real card into the overlay rather than cloning it: its tab
     buttons are already wired, and one live copy means there's no second
     DOM tree to keep in sync. A placeholder marks where it came from so
     closing can put it back in the right place in the note. ─────────── */

  let viewing = null;     // { card, placeholder }

  function openViewer(card) {
    const ov = $('#shtViewOverlay');
    const host = $('#shtViewBody');
    if (!ov || !host || viewing) return;
    const placeholder = document.createElement('div');
    placeholder.className = 'sheets-placeholder';
    card.parentNode.insertBefore(placeholder, card);
    host.appendChild(card);
    viewing = { card, placeholder };
    const first = card.querySelector('.sheet-tab');
    $('#shtViewTitle').textContent = first ? first.textContent : 'Sheets';
    syncFreezeLabel();
    ov.hidden = false;
  }

  function closeViewer() {
    const ov = $('#shtViewOverlay');
    if (ov) ov.hidden = true;
    if (viewing) {
      viewing.placeholder.replaceWith(viewing.card);
      viewing = null;
    }
  }

  function syncFreezeLabel() {
    const b = $('#shtFreeze');
    if (!b || !viewing) return;
    const on = viewing.card.classList.contains('freeze-col');
    b.textContent = on ? 'Unfreeze first column' : 'Freeze first column';
    b.classList.toggle('on', on);
  }

  $('#shtViewClose')?.addEventListener('click', closeViewer);
  $('#shtFreeze')?.addEventListener('click', () => {
    if (!viewing) return;
    viewing.card.classList.toggle('freeze-col');
    syncFreezeLabel();
  });
  $('#shtViewEdit')?.addEventListener('click', () => {
    if (!viewing) return;
    const card = viewing.card;
    // Put the card back in the note first: the grid editor reads the note
    // source, not the DOM, but leaving the card parked in a hidden overlay
    // would strand it there if the note re-rendered underneath.
    closeViewer();
    openEditor(card);
  });
  $('#shtViewOverlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'shtViewOverlay') closeViewer();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (viewing) { e.stopPropagation(); closeViewer(); }
  }, true);

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
    if (!model.length) model.push({ name: 'Sheet 1', headers: ['Column 1'], body: [['']], widths: [null], align: ['---'] });
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
      ed.model.push({ name: 'Sheet ' + (ed.model.length + 1), headers: ['Column 1'], body: [['']], widths: [null], align: ['---'] });
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
        // Widths and alignment are per-column too, so they shift with the
        // columns -- leaving them behind would slide every width one
        // column to the left.
        sheet.widths?.splice(c, 1);
        sheet.align?.splice(c, 1);
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
    (s.widths ||= []).push(null);      // a new column starts at auto width
    (s.align ||= []).push('---');
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
    widths: { parse: widthFromCell, cell: widthToCell, set: setSheetWidths,
              MIN: W_MIN, MAX: W_MAX, UNSET: W_UNSET },
    setBody: setSheetsBody,
    enhance: enhanceSheets,
  };
})();
