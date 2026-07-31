/* ══════════════════════════════════════════════════════════════
   Study section. Four modes, matching the standalone app:
   browse by category, flashcards, multiple-choice quiz, search.
   Reads the same vault as everything else.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const S = {
    open: false, mode: 'browse', data: null,
    category: '', item: null,
    cards: [], cardIx: 0, cardFlipped: false,
    quiz: [], quizIx: 0, quizPicked: null, quizScore: 0, quizDone: false,
  };

  const api = window.tephraApi;
  const toast = window.tephraToast;

  /* One file input for the whole module, created once and kept OUTSIDE any
     label. A <label> forwards activation to a nested input on its own, so
     wrapping one and *also* calling input.click() makes the click bubble back
     to the label, which forwards it again. WKWebView never settles that and
     the dialog silently fails to open. Same trap as the wallpaper picker. */
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = '.py,.json,.csv,.tsv,.md,text/x-python,application/json,text/csv';
  fileInput.hidden = true;
  document.body.appendChild(fileInput);
  let importHost = null;
  fileInput.addEventListener('change', () => {
    const f = fileInput.files && fileInput.files[0];
    fileInput.value = '';                // same file twice still fires
    if (f) doImport(f, importHost);
  });
  function pickFile(host) { importHost = host; fileInput.click(); }

  /* ── shell ── */
  const view = el('div');
  view.id = 'studyview';
  view.className = 'deckpane';
  view.innerHTML = `
    <div class="sv-head">
      <div class="sv-brand">
        <div>
          <h3>Crucible</h3>
          <p id="svStats">—</p>
        </div>
      </div>
      <div class="sv-modes">
        <button data-mode="browse"  aria-pressed="true">Browse</button>
        <button data-mode="cards"   aria-pressed="false">Flashcards</button>
        <button data-mode="quiz"    aria-pressed="false">Quiz</button>
        <button data-mode="search"  aria-pressed="false">Search</button>
      </div>
      <button class="sv-import" id="svImport" title="Import a study guide script">Import guide</button>
    </div>
    <div class="sv-body">
      <aside class="sv-cats"><div class="eyebrow"><span>Categories</span></div><div id="svCatList"></div></aside>
      <section class="sv-main" id="svMain"></section>
    </div>`;
  // Lives inside the deck so the app header stays put while only the body
  // below it slides. Appending to <body> would have covered the header.
  (document.querySelector('.deck') || document.body).appendChild(view);

  // Available whatever the current state — the dropzone only appears when the
  // guide is empty, which made importing unreachable the moment anything at
  // all had been added.
  $('#svImport').onclick = () => pickFile(null);
  wireDrop(view.querySelector('.sv-body'));
  view.querySelectorAll('.sv-modes button').forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

  function setMode(m) {
    S.mode = m;
    view.querySelectorAll('.sv-modes button').forEach((b) =>
      b.setAttribute('aria-pressed', b.dataset.mode === m));
    render();
  }

  async function open(mode) {
    S.open = true;
    view.classList.add('on');
    // The notes shell slides out left as this comes in from the right; both
    // sides are driven from one class so they can never desynchronise.
    document.body.classList.add('crucible');
    document.getElementById('theme')?.classList.remove('on');
    try {
      S.data = await api('/study');
    } catch (e) {
      $('#svMain').innerHTML = '';
      $('#svMain').appendChild(el('div', 'sv-warn',
        'Could not load study data: ' + String((e && e.message) || e).slice(0, 200)));
      return;
    }
    try { S.vault = await api('/vault/info'); } catch { S.vault = null; }
    if (mode) S.mode = mode;
    renderCats();
    renderStats();
    render();
  }
  function close() {
    S.open = false;
    view.classList.remove('on');
    document.body.classList.remove('crucible');
  }

  function renderStats() {
    const t = S.data.totals, p = S.data.progress;
    const pct = p.answered ? Math.round((100 * p.correct) / p.answered) : null;
    $('#svStats').textContent =
      `${t.topics} TOPICS · ${t.questions} QUESTIONS` +
      (pct !== null ? ` · ${pct}% CORRECT OF ${p.answered}` : '') +
      (p.flagged ? ` · ${p.flagged} FLAGGED` : '') +
      (t.needs_review ? ` · ${t.needs_review} NEED A CATEGORY CHECK` : '');
  }

  function renderCats() {
    const box = $('#svCatList');
    box.innerHTML = '';
    const all = el('div', 'node' + (S.category === '' ? '' : ''), '');
    all.innerHTML = `<span class="dot"></span><span class="t">All categories</span><span class="n">${S.data.totals.topics}</span>`;
    if (!S.category) all.setAttribute('aria-current', 'page');
    // Clearing the open topic is the point: without this, changing category
    // re-rendered straight back into whatever card was open, so the only way
    // out was the "All topics" button.
    all.onclick = () => { S.category = ''; resetBrowse(); renderCats(); render(); };
    box.appendChild(all);
    for (const c of S.data.categories) {
      const n = el('div', 'node');
      n.innerHTML = `<span class="dot"></span><span class="t"></span><span class="n">${c.topics}</span>`;
      n.querySelector('.t').textContent = c.category;
      if (S.category === c.category) n.setAttribute('aria-current', 'page');
      n.onclick = () => { S.category = c.category; resetBrowse(); renderCats(); render(); };
      box.appendChild(n);
    }
  }

  /* Changing category clears the open card *and* any quiz in progress. Without
     the second part, switching category dropped you back into the previous
     round, built from a pool you were no longer looking at. */
  function resetBrowse() {
    S.item = null;
    S.quiz = []; S.quizIx = 0; S.quizPicked = null; S.quizScore = 0; S.quizDone = false;
  }

  const inCat = (it) => !S.category || it.category === S.category;

  function render() {
    const main = $('#svMain');
    main.innerHTML = '';
    // Nothing to study yet: show the importer rather than an empty grid.
    if (!S.data.totals.topics) return renderEmpty(main);
    if (S.mode === 'browse') return renderBrowse(main);
    if (S.mode === 'cards') return renderCards(main);
    if (S.mode === 'quiz') return renderQuiz(main);
    if (S.mode === 'search') return renderSearch(main);
  }

  /* ── browse ── */
  async function renderBrowse(main) {
    if (S.item) return renderTopic(main, S.item);
    const list = S.data.items.filter(inCat);
    if (!list.length) {
      main.appendChild(el('div', 'empty', 'No study items here yet. Open a note and use “Make study item”.'));
      return;
    }
    const grid = el('div', 'sv-grid');
    for (const it of list) {
      const card = el('button', 'sv-card');
      card.innerHTML = `
        <span class="sv-c-cat"></span>
        <span class="sv-c-title"></span>
        <span class="sv-c-q"></span>
        <span class="sv-c-foot"><span>${it.questions} question${it.questions === 1 ? '' : 's'}</span></span>`;
      card.querySelector('.sv-c-cat').textContent = it.category || 'Uncategorised';
      card.querySelector('.sv-c-title').textContent = it.title;
      card.querySelector('.sv-c-q').textContent = it.question || '';
      if (it.needs_review) {
        const chip = el('span', 'sv-review', 'check category');
        card.querySelector('.sv-c-foot').appendChild(chip);
      }
      if (it.flags) {
        const f = el('span', 'sv-flagged');
        f.innerHTML = `<span class="flagmark">⚑</span> ${it.flags}`;
        f.title = `${it.flags} flagged question${it.flags === 1 ? '' : 's'}`;
        card.querySelector('.sv-c-foot').appendChild(f);
      }
      card.onclick = async () => {
        S.item = await api('/study/item/' + it.slug);
        render();
      };
      grid.appendChild(card);
    }
    main.appendChild(grid);
  }

  async function renderTopic(main, item) {
    const back = el('button', 'sv-back', '← All topics');
    back.onclick = () => { S.item = null; render(); };
    main.appendChild(back);

    const head = el('div', 'sv-topic-head');
    head.appendChild(el('div', 'sv-c-cat', item.category || 'Uncategorised'));
    head.appendChild(el('h2', null, item.title));
    if (item.question) head.appendChild(el('p', 'sv-topic-q', item.question));
    main.appendChild(head);

    main.appendChild(categoryPicker(item));

    const body = el('div', 'body sv-prose');
    body.innerHTML = item.html;
    main.appendChild(body);

    if (item.quiz.length) {
      const h = el('div', 'eyebrow');
      h.innerHTML = `<span>Questions on this topic</span><span>${item.quiz.length}</span>`;
      h.style.borderTop = '1px solid var(--edge)';
      h.style.paddingTop = '18px';
      main.appendChild(h);
      for (const q of item.quiz) {
        const b = el('div', 'sv-qpeek');
        b.appendChild(el('div', 'sv-qpeek-q', q.question));
        const ans = el('div', 'sv-qpeek-a', '✓ ' + q.options[q.answer]);
        b.appendChild(ans);
        if (q.why) b.appendChild(el('div', 'sv-qpeek-w', q.why));
        main.appendChild(b);
      }
    }

    const openNote = el('button', 'sv-back', 'Open this note in the editor →');
    openNote.onclick = () => { close(); window.tephraOpenNote(item.slug); };
    main.appendChild(openNote);
  }

  /* The manual override. Present on every topic, not hidden behind a menu,
     because the classifier is wrong often enough that correcting it has to
     be the cheapest possible action. */
  function categoryPicker(item) {
    const wrap = el('div', 'sv-cat-edit');
    const label = el('span', 'sv-cat-label',
      item.source === 'manual' ? 'Category (you set this)'
        : item.source === 'import' ? 'Category (from the guide)'
          : `Category (auto${item.confidence ? `, ${Math.round(item.confidence * 100)}% sure` : ''})`);
    wrap.appendChild(label);

    const sel = el('select', 'sv-select');
    for (const c of S.data.known_categories) {
      const o = el('option', null, c);
      o.value = c;
      if (c === item.category) o.selected = true;
      sel.appendChild(o);
    }
    sel.onchange = async () => {
      await api(`/study/${item.slug}/category`, {
        method: 'POST', body: JSON.stringify({ category: sel.value }),
      });
      toast(`Moved to ${sel.value} — the classifier learns from this`);
      S.data = await api('/study');
      S.item = await api('/study/item/' + item.slug);
      renderCats(); renderStats(); render();
    };
    wrap.appendChild(sel);

    if (item.source === 'auto') {
      const hint = el('span', 'sv-cat-hint', 'auto-assigned — worth a glance');
      wrap.appendChild(hint);
    }
    return wrap;
  }

  /* ── flashcards ── */
  function renderCards(main) {
    S.cards = S.data.items.filter(inCat).filter((i) => i.question);
    if (!S.cards.length) {
      main.appendChild(el('div', 'empty', 'No flashcards here — topics need a question line.'));
      return;
    }
    if (S.cardIx >= S.cards.length) S.cardIx = 0;
    const it = S.cards[S.cardIx];

    const wrap = el('div', 'sv-card-stage');
    const card = el('div', 'sv-flash' + (S.cardFlipped ? ' flipped' : ''));
    card.appendChild(el('div', 'sv-c-cat', it.category || ''));
    card.appendChild(el('div', 'sv-flash-q', S.cardFlipped ? it.title : it.question));
    card.appendChild(el('div', 'sv-flash-hint',
      S.cardFlipped ? 'the answer topic' : 'click to reveal'));
    card.onclick = async () => {
      S.cardFlipped = !S.cardFlipped;
      render();
      if (S.cardFlipped) {
        // load the full answer lazily, only once flipped
        const full = await api('/study/item/' + it.slug);
        const box = document.querySelector('.sv-flash-body');
        if (box) box.innerHTML = full.html;
      }
    };
    wrap.appendChild(card);

    if (S.cardFlipped) {
      const b = el('div', 'body sv-flash-body');
      b.innerHTML = '<p style="color:var(--faint)">Loading…</p>';
      wrap.appendChild(b);
    }

    const nav = el('div', 'sv-nav');
    const prev = el('button', 'sv-btn', '← Previous');
    const next = el('button', 'sv-btn primary', 'Next →');
    const count = el('span', 'sv-count', `${S.cardIx + 1} / ${S.cards.length}`);
    prev.onclick = () => { S.cardIx = (S.cardIx - 1 + S.cards.length) % S.cards.length; S.cardFlipped = false; render(); };
    next.onclick = () => { S.cardIx = (S.cardIx + 1) % S.cards.length; S.cardFlipped = false; render(); };
    nav.append(prev, count, next);
    wrap.appendChild(nav);
    main.appendChild(wrap);
  }

  /* ── quiz ── */
  async function startQuiz(opts = {}) {
    const params = new URLSearchParams({ n: opts.n || 12 });
    if (S.category && !opts.slug) params.set('category', S.category);
    if (opts.slug) params.set('slug', opts.slug);
    if (opts.flagged) params.set('only_flagged', 'true');
    if (opts.weakest) params.set('weakest_first', 'true');
    const r = await api('/study/quiz?' + params);
    S.quiz = r.questions;
    S.quizIx = 0; S.quizPicked = null; S.quizScore = 0; S.quizDone = false;
    render();
  }

  function renderQuiz(main) {
    if (!S.quiz.length || S.quizDone) return renderQuizIntro(main);
    const q = S.quiz[S.quizIx];

    const wrap = el('div', 'sv-quiz');
    const bar = el('div', 'sv-progress');
    const fill = el('div', 'sv-progress-fill');
    fill.style.width = `${(S.quizIx / S.quiz.length) * 100}%`;
    bar.appendChild(fill);
    wrap.appendChild(bar);

    const meta = el('div', 'sv-quiz-meta');
    meta.appendChild(el('span', null, `${S.quizIx + 1} of ${S.quiz.length}`));
    meta.appendChild(el('span', 'sv-c-cat', q.category || ''));
    const flag = el('button', 'sv-flagbtn' + (q.flagged ? ' on' : ''),
      q.flagged ? '★ Flagged' : '☆ Flag');
    flag.onclick = async () => {
      q.flagged = !q.flagged;
      await api('/study/flag', { method: 'POST', body: JSON.stringify({ qid: q.id, flagged: q.flagged }) });
      // Push the change to the notes side so the indicator appears at once.
      S.data = await api('/study');
      renderStats();
      window.tephraRefreshFlags?.();
      render();
    };
    meta.appendChild(flag);
    if (q.flagged && q.slug) {
      const jump = el('button', 'sv-flagbtn', 'open note →');
      jump.title = 'Open this topic in Tephra';
      jump.onclick = () => { close(); window.tephraOpenNote(q.slug); };
      meta.appendChild(jump);
    }
    wrap.appendChild(meta);

    wrap.appendChild(el('div', 'sv-quiz-q', q.question));

    const opts = el('div', 'sv-opts');
    q.options.forEach((text, i) => {
      const b = el('button', 'sv-opt');
      b.textContent = text;
      if (S.quizPicked !== null) {
        if (i === q.answer) b.classList.add('right');
        else if (i === S.quizPicked) b.classList.add('wrong');
        b.disabled = true;
      }
      b.onclick = async () => {
        if (S.quizPicked !== null) return;
        S.quizPicked = i;
        const correct = i === q.answer;
        if (correct) S.quizScore++;
        await api('/study/answer', { method: 'POST', body: JSON.stringify({ qid: q.id, correct }) });
        render();
      };
      opts.appendChild(b);
    });
    wrap.appendChild(opts);

    if (S.quizPicked !== null) {
      const why = el('div', 'sv-why');
      why.appendChild(el('div', 'sv-why-h',
        S.quizPicked === q.answer ? 'Correct' : 'Not quite'));
      if (q.why) why.appendChild(el('div', null, q.why));
      const hint = el('button', 'sv-back', `Read the full topic: ${q.title} →`);
      hint.onclick = async () => {
        S.item = await api('/study/item/' + q.slug);
        setMode('browse');
      };
      why.appendChild(hint);
      wrap.appendChild(why);

      const next = el('button', 'sv-btn primary',
        S.quizIx + 1 < S.quiz.length ? 'Next question →' : 'See results');
      next.onclick = () => {
        if (S.quizIx + 1 < S.quiz.length) { S.quizIx++; S.quizPicked = null; }
        else S.quizDone = true;
        render();
      };
      wrap.appendChild(next);
    }
    main.appendChild(wrap);
  }

  /* How many questions are actually available for the current selection.
     The slider's ceiling tracks this, so it can never promise a 40-question
     round out of a category holding 9. */
  function poolFor(mode) {
    if (mode === 'flagged') return S.data.progress.flagged || 0;
    if (!S.category) return S.data.totals.questions || 0;
    const c = S.data.categories.find((x) => x.category === S.category);
    return c ? c.questions : 0;
  }

  let prefTimer = null;
  function rememberCount(n) {
    S.data.settings = S.data.settings || {};
    S.data.settings.quiz_count = n;
    clearTimeout(prefTimer);
    prefTimer = setTimeout(() => {
      api('/study/prefs', { method: 'POST', body: JSON.stringify({ quiz_count: n }) })
        .catch(() => {});
    }, 350);
  }

  function renderQuizIntro(main) {
    const wrap = el('div', 'sv-quiz-intro');
    if (S.quizDone) {
      const pct = Math.round((100 * S.quizScore) / S.quiz.length);
      wrap.appendChild(el('div', 'sv-score', `${S.quizScore} / ${S.quiz.length}`));
      wrap.appendChild(el('div', 'sv-score-sub', `${pct}% on this round`));
    } else {
      wrap.appendChild(el('h2', null, S.category || 'All categories'));
      wrap.appendChild(el('p', 'sv-topic-q',
        'Multiple choice. Flag anything you want to revisit — flagged questions can be drilled on their own.'));
    }

    const pool = poolFor('all');
    const flaggedPool = poolFor('flagged');
    const ceiling = Math.max(1, Math.min(pool, S.data.max_quiz || 200));
    let count = Math.min(Math.max(1, S.data.settings?.quiz_count ?? 12), ceiling);

    if (!pool) {
      wrap.appendChild(el('div', 'sv-warn',
        S.category ? `No questions in ${S.category} yet.` : 'No quiz questions yet.'));
      main.appendChild(wrap);
      return;
    }

    const slider = el('div', 'sv-slider');
    const head = el('div', 'sv-slider-head');
    const label = el('span', 'sv-slider-n');
    const avail = el('span', 'sv-slider-avail', `of ${pool} available`);
    head.append(label, avail);

    const input = el('input');
    input.type = 'range';
    input.min = '1';
    input.max = String(ceiling);
    input.value = String(count);

    const paint = () => {
      label.textContent = count >= pool
        ? `All ${pool} questions`
        : `${count} question${count === 1 ? '' : 's'}`;
      start.textContent = `Start · ${count >= pool ? 'all ' + pool : count}`;
      weak.textContent = `Weakest ${count >= pool ? pool : count} first`;
      flag.textContent = `Flagged only (${flaggedPool})`;
      flag.disabled = flaggedPool === 0;
    };
    input.oninput = () => { count = +input.value; rememberCount(count); paint(); };
    slider.append(head, input);

    // quick presets, because dragging to 5 or to "everything" is common
    const presets = el('div', 'sv-presets');
    for (const n of [5, 10, 20, 50].filter((n) => n < pool).concat([pool])) {
      const b = el('button', 'sv-chip', n === pool ? 'All' : String(n));
      b.onclick = () => { count = n; input.value = String(n); rememberCount(n); paint(); };
      presets.appendChild(b);
    }
    slider.appendChild(presets);
    wrap.appendChild(slider);

    const row = el('div', 'sv-nav');
    var start = el('button', 'sv-btn primary', '');
    var weak = el('button', 'sv-btn', '');
    var flag = el('button', 'sv-btn', '');
    start.onclick = () => startQuiz({ n: count });
    weak.onclick = () => startQuiz({ n: count, weakest: true });
    flag.onclick = () => startQuiz({ n: Math.min(count, flaggedPool) || flaggedPool, flagged: true });
    row.append(start, weak, flag);
    wrap.appendChild(row);
    paint();
    main.appendChild(wrap);
  }

  /* ── search ── */
  function renderSearch(main) {
    const box = el('input', 'sv-search');
    box.type = 'text';
    box.placeholder = 'Search topics, answers and questions…';
    main.appendChild(box);
    const out = el('div', 'sv-results');
    main.appendChild(out);

    let t;
    box.oninput = () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const q = box.value.trim().toLowerCase();
        out.innerHTML = '';
        if (q.length < 2) return;
        const hits = S.data.items.filter(inCat).filter((it) =>
          it.title.toLowerCase().includes(q) ||
          (it.question || '').toLowerCase().includes(q) ||
          (it.category || '').toLowerCase().includes(q));
        if (!hits.length) { out.appendChild(el('div', 'empty', 'Nothing matched.')); return; }
        for (const it of hits) {
          const r = el('div', 'mention');
          r.innerHTML = '<div class="m-t"></div><div class="m-x"></div>';
          r.querySelector('.m-t').textContent = it.title;
          r.querySelector('.m-x').textContent = it.question || it.category || '';
          r.onclick = async () => { S.item = await api('/study/item/' + it.slug); setMode('browse'); };
          out.appendChild(r);
        }
      }, 130);
    };
    setTimeout(() => box.focus(), 60);
  }

  /* ── first-run / empty state ──
     This screen exists because of a real failure: importing from the command
     line writes into whichever directory you name, and if that is not the
     vault the app is reading, everything looks empty with no clue why. So the
     import lives here, where the vault is not in question, and the path is
     printed either way. */
  function renderEmpty(main) {
    const wrap = el('div', 'sv-empty');
    wrap.appendChild(el('h2', null, 'No study items yet'));
    wrap.appendChild(el('p', 'sv-topic-q',
      'Import your standalone FB Study Guide, or mark any note as a study item from the editor.'));

    const drop = el('div', 'sv-drop');
    drop.innerHTML = `<span class="sv-drop-t">Import study guide</span>
      <span class="sv-drop-s">Click to choose, or drop a
        <code>.json</code> <code>.py</code> <code>.csv</code> file</span>`;
    drop.onclick = () => pickFile(drop);
    wireDrop(drop);
    wrap.appendChild(drop);

    // A reference, not a link out: someone authoring a guide for a different
    // product needs the exact shape, and needs it here.
    const help = el('details', 'sv-formats');
    help.innerHTML = '<summary>What formats can I upload?</summary>';
    const body = el('div', 'sv-formats-body');
    body.appendChild(el('div', 'sv-formats-load', 'Loading…'));
    help.appendChild(body);
    help.addEventListener('toggle', async () => {
      if (!help.open || help.dataset.loaded) return;
      help.dataset.loaded = '1';
      try {
        const { formats } = await api('/study/formats');
        body.innerHTML = '';
        for (const f of formats) {
          const blk = el('div', 'sv-fmt');
          blk.appendChild(el('div', 'sv-fmt-h',
            `${f.label} — ${f.extensions.join(' ')}`));
          blk.appendChild(el('div', 'sv-fmt-s', f.summary));
          const pre = el('pre');
          pre.textContent = f.example;
          blk.appendChild(pre);
          body.appendChild(blk);
        }
      } catch { body.textContent = 'Could not load the format list.'; }
    }, false);
    wrap.appendChild(help);

    if (S.vault) {
      const info = el('div', 'sv-vaultinfo');
      info.innerHTML = `Writing to <code>${S.vault.vault}</code> — `
        + `${S.vault.files_on_disk} note file${S.vault.files_on_disk === 1 ? '' : 's'} on disk, `
        + `${S.vault.study_items} study item${S.vault.study_items === 1 ? '' : 's'}.`;
      wrap.appendChild(info);
      if (S.vault.files_on_disk > S.vault.indexed) {
        const warn = el('div', 'sv-warn',
          'There are more files on disk than in the index. Reindexing…');
        wrap.appendChild(warn);
        api('/reindex', { method: 'POST' }).then(() => refreshAll());
      }
    }
    main.appendChild(wrap);
  }

  function wireDrop(node) {
    ['dragenter', 'dragover'].forEach((ev) => node.addEventListener(ev, (e) => {
      e.preventDefault(); node.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach((ev) => node.addEventListener(ev, (e) => {
      e.preventDefault(); node.classList.remove('over');
    }));
    node.addEventListener('drop', (e) => {
      e.preventDefault();
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) doImport(f, node);
    });
  }

  async function doImport(file, host) {
    const label = host && host.querySelector('.sv-drop-t');
    if (host) host.classList.add('busy');
    if (label) label.textContent = `Importing ${file.name}…`;
    toast(`Reading ${file.name}…`, 20000);

    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await api('/study/import', { method: 'POST', body: fd });
      toast(`Imported ${r.topics} topics, ${r.questions} questions, ${r.categories} categories`);
      await refreshAll();
      if (window.tephraReloadList) window.tephraReloadList();
    } catch (e) {
      // Surface the server's reason in the view, not just a toast that fades.
      let detail = String((e && e.message) || e);
      try { detail = JSON.parse(detail).detail || detail; } catch {}
      toast(detail.slice(0, 180), 6000);
      const main = $('#svMain');
      if (main) {
        const err = el('div', 'sv-warn', 'Import failed: ' + detail.slice(0, 240));
        main.appendChild(err);
      }
    } finally {
      if (host) host.classList.remove('busy');
      if (label) label.textContent = 'Import study guide';
    }
  }

  async function refreshAll() {
    S.data = await api('/study');
    try { S.vault = await api('/vault/info'); } catch {}
    renderCats(); renderStats(); render();
  }

  /* Entry point from a note's flag chip: opens Crucible straight into a quiz
     of just that note's flagged questions. */
  async function openFlagged(slug) {
    await open('quiz');
    S.category = '';
    renderCats();
    await startQuiz({ n: 50, flagged: true, slug });
    if (!S.quiz.length) {
      setMode('browse');
      toast('Those flags are gone — nothing left to drill');
    }
  }

  window.tephraStudy = { open, close, openFlagged, isOpen: () => S.open, refresh: async () => {
    if (S.open) { S.data = await api('/study'); renderCats(); renderStats(); render(); }
  } };
})();
