/* ══════════════════════════════════════════════════════════════
   Quiz editor: a form for the note's own `## Quiz` section, for anyone who
   would rather fill in fields than write `Q:` / `- [x]` / `Why:` by hand.
   Both stay valid at once -- this is just another way to edit the same
   markdown. Source mode (⌘E) still shows and accepts the raw text.

   Lives entirely in the note body's own data model: on any change this
   PUTs the whole item list to /notes/{slug}/quiz, which re-renders the
   `## Quiz` section from it and splices it back after the note's prose.
   That endpoint hands back the note's fresh full body, forwarded to
   app.js via tephraSyncBody so a stale #noteSrc textarea never overwrites
   these edits on its own next autosave.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const $ = (s) => document.querySelector(s);
  const api = (...a) => window.tephraApi(...a);
  const toast = (...a) => window.tephraToast(...a);

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  let slug = null;
  let items = [];          // working copy: [{question, options:[...], answers:[...], why}]
  let saveTimer = null;
  let dirty = false;
  // Rolled up by default, and deliberately not reset per note -- switching
  // notes keeps whatever the user last chose instead of re-hiding a section
  // they just opened to work in.
  let open = false;

  function autoGrow(node) {
    node.style.height = 'auto';
    node.style.height = node.scrollHeight + 'px';
  }

  function chip(state, text) {
    const c = $('#quizSaveChip');
    c.dataset.state = state;
    c.textContent = text;
  }

  // A collapsed section has display:none, so scrollHeight reads 0 for
  // anything sized while hidden -- autoGrow() run during a hidden renderList()
  // would pin every textarea at 0px. Re-measure once the section is visible.
  function syncOpen() {
    $('#quizEditToggle').setAttribute('aria-expanded', String(open));
    $('#quizEditBody').hidden = !open;
    if (open) {
      requestAnimationFrame(() => {
        $('#quizList').querySelectorAll('.quizitem-q, .quizitem-why').forEach(autoGrow);
      });
    }
  }

  function touched() {
    dirty = true;
    chip('saving', 'Saving…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 700);
  }

  async function save() {
    clearTimeout(saveTimer); saveTimer = null;
    if (!slug || !dirty) return;
    dirty = false;
    const payload = { items: items.map((it) => ({
      question: it.question, options: it.options, answers: it.answers, why: it.why,
    })) };
    try {
      const saved = await api(`/notes/${encodeURIComponent(slug)}/quiz`, {
        method: 'PUT', body: JSON.stringify(payload),
      });
      chip('saved', 'Saved');
      // Deliberately not window.tephraReloadList() -- it re-opens the note,
      // which calls back into render() and would wipe out whatever's typed
      // in the form since (a race this module would then be fighting on
      // every single autosave, not just an unlucky one). The sidebar's
      // note-list row goes stale until the next natural refresh instead,
      // which is a much smaller cost.
      window.tephraSyncBody?.(saved.body, slug);
    } catch {
      dirty = true;
      chip('error', 'Not saved — retrying');
      setTimeout(save, 3000);
    }
  }

  // Renders fresh from the server: called when a note is opened, and after
  // leaving source-edit mode (so a hand-edited `## Quiz` block flows back
  // into the form). Never called mid-edit here, so it can't stomp on
  // whatever the user is in the middle of typing.
  function render(quiz, forSlug) {
    slug = forSlug;
    dirty = false;
    clearTimeout(saveTimer); saveTimer = null;
    items = (quiz || []).map((q) => ({
      question: q.question, options: [...q.options], answers: [...q.answers], why: q.why || '',
    }));
    chip('', '');
    renderList();
    syncOpen();
  }

  function renderList() {
    const host = $('#quizList');
    host.innerHTML = '';
    items.forEach((item, i) => host.appendChild(buildCard(item, i)));
    $('#quizEditCount').textContent = items.length
      ? `${items.length} question${items.length === 1 ? '' : 's'}` : '';
  }

  function buildCard(item, index) {
    const card = el('div', 'quizitem');

    const qRow = el('div', 'quizitem-qrow');
    const qInput = el('textarea', 'quizitem-q');
    qInput.rows = 1;
    qInput.placeholder = 'Question…';
    qInput.value = item.question;
    qInput.addEventListener('input', () => {
      item.question = qInput.value;
      autoGrow(qInput);
      touched();
    });
    qRow.appendChild(qInput);

    const del = el('button', 'quizitem-del', '');
    del.type = 'button';
    del.title = 'Delete this question';
    del.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
      + 'stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-8 '
      + '0v12a1 1 0 001 1h8a1 1 0 001-1V7"/></svg>';
    let armed = false, armTimer = null;
    del.onclick = () => {
      if (!armed) {
        armed = true; del.classList.add('armed'); del.title = 'Click again to delete';
        armTimer = setTimeout(() => { armed = false; del.classList.remove('armed'); del.title = 'Delete this question'; }, 4000);
        return;
      }
      clearTimeout(armTimer);
      items.splice(index, 1);
      touched();
      renderList();
    };
    qRow.appendChild(del);
    card.appendChild(qRow);

    const optsHost = el('div', 'quizitem-opts');
    item.options.forEach((_, oi) => optsHost.appendChild(buildOptionRow(item, oi)));
    card.appendChild(optsHost);

    const addOpt = el('button', 'quizitem-addopt', '+ Add answer option');
    addOpt.type = 'button';
    addOpt.onclick = () => {
      item.options.push('');
      touched();
      renderList();
      const rows = card.querySelectorAll('.quizopt-text');
      rows[rows.length - 1]?.focus();
    };
    card.appendChild(addOpt);

    const why = el('textarea', 'quizitem-why');
    why.rows = 1;
    why.placeholder = 'Why (shown after answering) — optional';
    why.value = item.why;
    why.addEventListener('input', () => { item.why = why.value; autoGrow(why); touched(); });
    card.appendChild(why);

    requestAnimationFrame(() => { autoGrow(qInput); autoGrow(why); });
    return card;
  }

  function buildOptionRow(item, oi) {
    const row = el('div', 'quizopt-row');

    const check = el('input', 'quizopt-check');
    check.type = 'checkbox';
    check.title = 'Correct answer';
    check.checked = item.answers.includes(oi);
    check.onchange = () => {
      const pos = item.answers.indexOf(oi);
      if (check.checked && pos === -1) item.answers.push(oi);
      else if (!check.checked && pos !== -1) item.answers.splice(pos, 1);
      touched();
    };
    row.appendChild(check);

    const text = el('input', 'quizopt-text');
    text.type = 'text';
    text.placeholder = `Option ${oi + 1}…`;
    text.value = item.options[oi];
    text.addEventListener('input', () => { item.options[oi] = text.value; touched(); });
    row.appendChild(text);

    const del = el('button', 'quizopt-del', '×');
    del.type = 'button';
    del.title = 'Remove this option';
    // Fewer than 2 options makes the question unanswerable and it stops
    // saving (see save_quiz) -- disabled rather than silently dropping it.
    del.disabled = item.options.length <= 2;
    del.onclick = () => {
      item.options.splice(oi, 1);
      item.answers = item.answers.filter((a) => a !== oi).map((a) => (a > oi ? a - 1 : a));
      touched();
      renderList();
    };
    row.appendChild(del);
    return row;
  }

  $('#quizEditToggle').onclick = () => { open = !open; syncOpen(); };

  $('#quizAdd').onclick = () => {
    items.push({ question: '', options: ['', ''], answers: [], why: '' });
    renderList();
    const cards = $('#quizList').querySelectorAll('.quizitem-q');
    cards[cards.length - 1]?.focus();
    // Not touched() -- an empty question is filtered out server-side
    // anyway (see save_quiz), so there's nothing worth saving until it's
    // actually filled in.
  };

  window.tephraQuizEdit = { render };
})();
