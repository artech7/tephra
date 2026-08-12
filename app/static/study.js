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
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Flashcard tilt + glow: mouse position relative to the card drives a
     small rotate3d and a specular highlight that slides across it, both
     scoped to this one element's own mousemove/mouseleave -- never a
     viewport-wide pointer listener, so it can't repeat the old dynamic-
     glass mistake of several things tracking the cursor independently.
     Also writes --mx/--my (reusing the same cx/cy already computed here
     rather than adding a second mousemove listener that would just fight
     this one over style.transform) for .sv-flash-face's own spotlight-
     border pseudo-element in style.css -- the same Windows-11-style holo
     border effect .sv-card and #lens use, driven by wireFoil there. */
  function wireTilt(tiltEl, glowEl) {
    tiltEl.addEventListener('mousemove', (e) => {
      const b = tiltEl.getBoundingClientRect();
      const cx = e.clientX - b.left - b.width / 2;
      const cy = e.clientY - b.top - b.height / 2;
      const dist = Math.sqrt(cx * cx + cy * cy);
      const deg = Math.min(Math.log(dist + 1) * 2, 10);
      tiltEl.style.transform =
        `scale3d(1.025,1.025,1.025) rotate3d(${cy / 140},${-cx / 140},0,${deg}deg)`;
      glowEl.style.background = `radial-gradient(circle at ${cx * 1.3 + b.width / 2}px `
        + `${cy * 1.3 + b.height / 2}px, rgba(255,255,255,.18), transparent 60%)`;
      tiltEl.style.setProperty('--mx', ((cx + b.width / 2) / b.width * 100).toFixed(1) + '%');
      tiltEl.style.setProperty('--my', ((cy + b.height / 2) / b.height * 100).toFixed(1) + '%');
    });
    tiltEl.addEventListener('mouseleave', () => {
      tiltEl.style.transform = '';
      glowEl.style.background = '';
      tiltEl.style.setProperty('--mx', '50%');
      tiltEl.style.setProperty('--my', '50%');
    });
  }

  /* Browse-grid cards: a lighter tilt than wireTilt's (these sit shoulder to
     shoulder in a grid, so a big lean reads as chaos, not depth) plus --mx/
     --my for the foil/glitter pseudo-elements in style.css. Own mousemove
     per card, same as wireTilt -- a shared container listener would mean
     every card in the grid re-computing on every pixel the cursor crosses. */
  function wireFoil(cardEl) {
    cardEl.addEventListener('mousemove', (e) => {
      const b = cardEl.getBoundingClientRect();
      const cx = e.clientX - b.left - b.width / 2;
      const cy = e.clientY - b.top - b.height / 2;
      const deg = Math.min(Math.sqrt(cx * cx + cy * cy) / 24, 6);
      cardEl.style.transform =
        `perspective(800px) translateY(-2px) rotate3d(${cy / 160},${-cx / 160},0,${deg}deg)`;
      cardEl.style.setProperty('--mx', ((cx + b.width / 2) / b.width * 100).toFixed(1) + '%');
      cardEl.style.setProperty('--my', ((cy + b.height / 2) / b.height * 100).toFixed(1) + '%');
    });
    cardEl.addEventListener('mouseleave', () => {
      cardEl.style.transform = '';
      cardEl.style.setProperty('--mx', '50%');
      cardEl.style.setProperty('--my', '50%');
    });
  }

  const S = {
    open: false, mode: 'browse', data: null,
    category: '', item: null,
    // cardsCategory starts undefined (never equal to S.category, which
    // starts '') so renderCards's very first call always fetches.
    cards: [], cardsCategory: undefined, cardIx: 0, cardFlipped: false,
    // quizPicked is always an array of chosen option indices, even for a
    // single-answer question -- one question shape, whether it has one
    // correct answer or several. quizSubmitted separates "still choosing"
    // (relevant only once a question allows more than one pick) from
    // "graded", since picking stops being instant the moment more than one
    // box can be checked.
    quiz: [], quizIx: 0, quizPicked: null, quizSubmitted: false, quizScore: 0, quizDone: false,
    // Rolled up by default -- a topic's quiz answers sit right under its
    // prose, and showing them open by default spoils the topic before the
    // reader gets to it.
    quizPeekOpen: false,
  };

  const api = window.tephraApi;
  const toast = window.tephraToast;

  const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

  /* One input for the whole module's import feature -- deliberately a
     folder picker (webkitdirectory), not a plain file picker, so a single
     dialog covers every case: a lone guide file, a guide plus flat images,
     or a guide plus images nested in subfolders. This is the browser's own
     filesystem access, not the server's -- it works from any device pointed
     at Tephra, including one that shares no filesystem at all with wherever
     the server runs (a container, a box across the network). Everything
     selected is read locally by the browser -- see the import confirmation
     modal below, which is the only thing that ever actually uploads it.

     Kept outside any label: a <label> forwards activation to a nested input
     on its own, so wrapping one and *also* calling input.click() makes the
     click bubble back to the label, which forwards it again. WKWebView
     never settles that and the dialog silently fails to open. Same trap as
     the wallpaper picker. */
  const folderInput = document.createElement('input');
  folderInput.type = 'file';
  folderInput.webkitdirectory = true;
  folderInput.multiple = true;
  folderInput.hidden = true;
  document.body.appendChild(folderInput);
  // A folder picker can't select a lone file that isn't already isolated in
  // its own folder -- the OS dialog only lets you descend into or choose a
  // whole directory. This plain multi-file picker is the counterpart: pick
  // one guide file, or select it together with its images (multi-select in
  // the same folder), with no directory requirement at all. Nested image
  // subfolders still need the folder picker below, since a flat file picker
  // can't walk into them.
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.multiple = true;
  fileInput.accept = '.json,.py,.csv,.tsv,.md,image/*';
  fileInput.hidden = true;
  document.body.appendChild(fileInput);
  // Picking (or dropping -- see wireDrop) files never imports anything by
  // itself; it only hands the file list to whichever caller asked for it
  // (openImportModal, or setPickedFiles on an already-open modal). Nothing
  // gets written until the confirm modal's own button is clicked -- that's
  // the whole point: no more silent imports into whatever vault happens to
  // be open.
  let onFolderPicked = null;
  folderInput.addEventListener('change', () => {
    const files = Array.from(folderInput.files || []);
    folderInput.value = '';
    if (files.length && onFolderPicked) onFolderPicked(files);
  });
  function pickFolder(cb) { onFolderPicked = cb; folderInput.click(); }
  let onFilesPicked = null;
  fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files || []);
    fileInput.value = '';
    if (files.length && onFilesPicked) onFilesPicked(files);
  });
  function pickFiles(cb) { onFilesPicked = cb; fileInput.click(); }

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
    </div>
    <div class="sv-body">
      <aside class="sv-cats"><div class="eyebrow"><span>Categories</span></div><div id="svCatList"></div></aside>
      <section class="sv-main" id="svMain"></section>
    </div>`;
  // Lives inside the deck so the app header stays put while only the body
  // below it slides. Appending to <body> would have covered the header.
  (document.querySelector('.deck') || document.body).appendChild(view);

  /* A right-edge slide-in drawer, same mechanic as the Appearance and Vault
     Health drawers (#theme / #health in app.js) -- reachable from the header
     button no matter what's showing in the body below (empty state, browse
     grid, a flashcard, a quiz), unlike the old copy that only existed inside
     the empty-state screen and vanished the moment the vault had one item in
     it. Lives on <body>, not inside `view`, so Crucible's own mode switches
     never tear it down. */
  const formatsDrawer = el('aside');
  formatsDrawer.id = 'svFormats';
  formatsDrawer.innerHTML = `
    <div class="th-head"><h4>What can I upload?</h4><button class="mini" id="svFormatsClose">×</button></div>
    <div class="th-body" id="svFormatsBody"><div class="sv-formats-load">Loading…</div></div>`;
  document.body.appendChild(formatsDrawer);
  let formatsLoaded = false;
  async function openFormats() {
    formatsDrawer.classList.add('on');
    if (formatsLoaded) return;
    const body = $('#svFormatsBody');
    try {
      const { formats } = await api('/study/formats');
      formatsLoaded = true;
      body.innerHTML = '';
      for (const f of formats) {
        const blk = el('div', 'sv-fmt');
        blk.appendChild(el('div', 'sv-fmt-h', `${f.label} — ${f.extensions.join(' ')}`));
        blk.appendChild(el('div', 'sv-fmt-s', f.summary));
        const pre = el('pre');
        pre.textContent = f.example;
        blk.appendChild(pre);
        body.appendChild(blk);
      }
    } catch { body.textContent = 'Could not load the format list.'; }
  }
  $('#svFormatsBtn').onclick = openFormats;
  $('#svFormatsClose').onclick = () => formatsDrawer.classList.remove('on');

  /* ── import confirmation modal ──
     The bug this exists to fix: picking or dropping a guide used to import
     it immediately, into whatever vault happened to be open -- easy to get
     wrong the moment vault-switching isn't the very last thing that
     happened (e.g. cleaning up other vaults, then importing, and only
     later noticing it landed in the wrong one). Nothing here writes
     anything until the modal's own confirm button is clicked, and the
     default path (a brand-new vault) can't merge into existing content by
     construction -- merging into the vault that's already open is an
     explicit, reviewed opt-in, never the default. */
  const modal = el('div', 'sv-importmodal');
  modal.id = 'svImportModal';
  modal.hidden = true;
  modal.innerHTML = `
    <div class="sv-importmodal-card" id="svImportModalCard">
      <div class="th-head"><h4>Import study guide</h4><button class="mini" id="svImportModalClose">×</button></div>
      <div class="th-body">
        <div class="sv-modetoggle">
          <button type="button" class="sv-modebtn" data-mode="new" aria-pressed="true">Import → new vault</button>
          <button type="button" class="sv-modebtn" data-mode="merge" aria-pressed="false">Merge → current vault</button>
        </div>

        <div class="sv-drop sv-importdrop" id="svImportDrop">
          <span class="sv-drop-t">Choose files…</span>
          <span class="sv-drop-s" id="svImportDropS">No files chosen yet — click here to pick a guide file
            (alone, or together with its images), or drop a guide file (or a whole folder with its images)
            anywhere on this card.</span>
          <button type="button" class="sv-drop-alt" id="svImportPickFolder">…or choose a folder instead</button>
        </div>

        <div id="svNewVaultPane">
          <label class="sv-fieldlabel" for="svNewVaultName">New vault name</label>
          <input type="text" id="svNewVaultName" placeholder="e.g. LDAP Study Guide" autocomplete="off">
          <div class="sv-pathpreview" id="svNewVaultPath"></div>
        </div>

        <div id="svMergePane" hidden>
          <div class="sv-mergebanner" id="svMergeBanner"></div>
          <button type="button" class="sv-btn" id="svMergeReviewBtn" disabled>Review merge</button>
          <div id="svMergeReviewOut"></div>
        </div>

        <div class="sv-warn" id="svImportModalError" hidden></div>

        <div class="sv-progress" id="svImportProgress" hidden>
          <div class="sv-progress-bar"><div class="sv-progress-fill" id="svImportProgressFill"></div></div>
          <div class="sv-progress-label" id="svImportProgressLabel"></div>
        </div>

        <div class="sv-importmodal-actions">
          <button type="button" class="sv-btn" id="svImportModalCancel">Cancel</button>
          <button type="button" class="sv-btn primary" id="svImportModalConfirm" disabled>Create Vault &amp; Import</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  const $$ = (s) => Array.from(modal.querySelectorAll(s));
  const isGuideFile = (f) => /\.(json|py|csv|tsv|md)$/i.test(f.name);
  const basename = (p) => (p || '').replace(/\/+$/, '').split('/').pop();

  const IM = { mode: 'new', files: null, reviewed: false, busy: false };

  async function ensureSuggestedParent() {
    if (S.suggestedParent) return S.suggestedParent;
    try { S.suggestedParent = (await api('/vault/list')).suggested_parent; }
    catch { S.suggestedParent = ''; }
    return S.suggestedParent;
  }

  function guessVaultName(files) {
    const guide = files && files.find(isGuideFile);
    if (!guide) return '';
    const stem = guide.name.replace(/\.[^.]+$/, '');
    const words = stem.split(/[\s_-]+/).filter(Boolean);
    return words.map((w) => (w === w.toUpperCase() ? w : w[0].toUpperCase() + w.slice(1))).join(' ');
  }

  function importDropSummary(files) {
    if (!files || !files.length) {
      return 'No files chosen yet — click here to pick a guide file (alone, or together with its images), '
        + 'or drop a guide file (or a whole folder with its images) anywhere on this card.';
    }
    const guide = files.find(isGuideFile);
    const images = files.length - (guide ? 1 : 0);
    if (!guide) {
      return `${files.length} file${files.length === 1 ? '' : 's'} chosen, but none looks like a study `
        + 'guide (.json/.py/.csv/.tsv/.md) — pick the guide file itself, or the folder it lives in.';
    }
    return `Guide: ${guide.name}` + (images ? ` — ${images} other file${images === 1 ? '' : 's'} alongside it` : '');
  }

  function syncModalUI() {
    $('#svNewVaultPane').hidden = IM.mode !== 'new';
    $('#svMergePane').hidden = IM.mode !== 'merge';
    $('#svImportDropS').textContent = importDropSummary(IM.files);
    const name = $('#svNewVaultName').value.trim();
    $('#svNewVaultPath').textContent = !name ? ''
      : S.suggestedParent ? `Will create: ${S.suggestedParent.replace(/\/+$/, '')}/${name}`
      : 'Will create alongside your other vaults.';
    const hasGuide = !!(IM.files && IM.files.some(isGuideFile));
    $('#svMergeReviewBtn').disabled = IM.busy || !hasGuide;
    const confirmBtn = $('#svImportModalConfirm');
    if (IM.mode === 'new') {
      confirmBtn.textContent = 'Create Vault & Import';
      confirmBtn.disabled = IM.busy || !(hasGuide && name);
    } else {
      confirmBtn.textContent = S.vault ? `Merge into ${basename(S.vault.vault)}` : 'Merge';
      confirmBtn.disabled = IM.busy || !IM.reviewed;
    }
    $('#svImportModalCancel').disabled = IM.busy;
    $$('.sv-modebtn').forEach((b) => (b.disabled = IM.busy));
  }

  function hideModalError() {
    const box = $('#svImportModalError');
    box.hidden = true; box.textContent = '';
  }
  function setModalErrorText(text) {
    const box = $('#svImportModalError');
    box.hidden = false; box.textContent = text;
  }
  function showModalError(e) {
    let detail = String((e && e.message) || e);
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    setModalErrorText(detail.slice(0, 300));
  }

  /* A large guide's own import runs as a background job (see postImport) so
     the bar can track real per-topic progress instead of an indeterminate
     spinner sitting there for however long a hundred-topic guide takes. */
  function showImportProgress() {
    $('#svImportProgressFill').style.width = '0%';
    $('#svImportProgressLabel').textContent = 'Starting…';
    $('#svImportProgress').hidden = false;
  }
  function setImportProgress(done, total) {
    const pane = $('#svImportProgress');
    if (pane.hidden) return;   // a stale poll landing after cancel/close
    const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
    $('#svImportProgressFill').style.width = pct + '%';
    $('#svImportProgressLabel').textContent = total
      ? `Importing — ${done} of ${total} topic${total === 1 ? '' : 's'} (${pct}%)`
      : 'Parsing the guide…';
  }
  function hideImportProgress() { $('#svImportProgress').hidden = true; }

  function setPickedFiles(files) {
    IM.files = files;
    IM.reviewed = false;
    $('#svMergeReviewOut').innerHTML = '';
    if (IM.mode === 'new' && !$('#svNewVaultName').value.trim()) {
      const guess = guessVaultName(files);
      if (guess) $('#svNewVaultName').value = guess;
    }
    hideModalError();
    syncModalUI();
  }

  function setMergeBanner() {
    $('#svMergeBanner').textContent = S.vault
      ? `This will merge into your currently open vault: "${basename(S.vault.vault)}" (${S.vault.vault}). `
        + 'New topics are added; topics a previous import of this same guide already created are updated in place.'
      : 'Could not tell which vault is currently open — close this and reopen Crucible, then try again.';
  }

  $$('.sv-modebtn').forEach((b) => {
    b.onclick = () => {
      if (IM.busy) return;
      IM.mode = b.dataset.mode;
      IM.reviewed = false;
      $$('.sv-modebtn').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      if (IM.mode === 'merge') { setMergeBanner(); $('#svMergeReviewOut').innerHTML = ''; }
      hideModalError();
      syncModalUI();
    };
  });
  $('#svNewVaultName').oninput = syncModalUI;

  $('#svImportDrop').onclick = (e) => {
    if (e.target.closest('#svImportPickFolder')) return;   // handled by its own listener below
    pickFiles(setPickedFiles);
  };
  $('#svImportPickFolder').onclick = (e) => { e.stopPropagation(); pickFolder(setPickedFiles); };
  wireDrop($('#svImportDrop'), setPickedFiles);
  wireDrop(modal, setPickedFiles);   // drop anywhere on the card, not just the drop target itself

  function renderMergeReview(r) {
    const out = $('#svMergeReviewOut');
    out.innerHTML = '';
    const list = el('ul', 'sv-reviewlist');
    const add = (text) => list.appendChild(el('li', null, text));
    add(`${r.topics} topic${r.topics === 1 ? '' : 's'} parsed — ${r.questions} question${r.questions === 1 ? '' : 's'}, `
      + `${r.categories} categor${r.categories === 1 ? 'y' : 'ies'}.`);
    add(`${r.created} new note${r.created === 1 ? '' : 's'} will be created`
      + (r.updated ? `, ${r.updated} existing note${r.updated === 1 ? '' : 's'} will be updated` : '') + '.');
    if (r.images_embedded) add(`${r.images_embedded} image${r.images_embedded === 1 ? '' : 's'} will be embedded.`);
    if (r.collisions && r.collisions.length) {
      add(`${r.collisions.length} title${r.collisions.length === 1 ? '' : 's'} match existing notes this importer `
        + `doesn't own — kept as separate notes, nothing overwritten: ${r.collisions.join(', ')}.`);
    }
    if (r.skipped_duplicates) {
      add(`${r.skipped_duplicates} topic${r.skipped_duplicates === 1 ? '' : 's'} look like near-duplicates of `
        + 'notes already here and will be skipped.');
    }
    const flagged = (r.duplicates || []).filter((d) => !d.skipped);
    if (flagged.length) {
      add(`${flagged.length} possible duplicate${flagged.length === 1 ? '' : 's'} will still be created, flagged for review.`);
    }
    const missingCount = (r.missing_images || []).reduce((n, m) => n + m.files.length, 0);
    if (missingCount) add(`${missingCount} referenced image${missingCount === 1 ? '' : 's'} not found — skipped, not fatal.`);
    if (r.duplicate_image_names && r.duplicate_image_names.length) {
      add(`${r.duplicate_image_names.length} image filename${r.duplicate_image_names.length === 1 ? '' : 's'} `
        + 'appeared more than once in the picked folder — the first match was used.');
    }
    out.appendChild(list);
  }

  const importPollMs = 300;
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));

  // Kicks off the import as a background job (see /api/study/import/upload)
  // and polls its status until it finishes -- a big guide's own write loop
  // can run long enough that holding one request open would leave nothing
  // for the UI to show but a frozen spinner. onProgress, if given, is called
  // with (done, total) on every poll so the caller can drive a progress bar.
  async function postImport(files, { dryRun = false, onProgress } = {}) {
    const fd = new FormData();
    for (const f of files) fd.append('files', f, f.name);
    const { job_id } = await api('/study/import/upload' + (dryRun ? '?dry_run=true' : ''),
      { method: 'POST', body: fd });
    for (;;) {
      const job = await api(`/study/import/status/${job_id}`);
      if (onProgress) onProgress(job.done, job.total);
      if (job.finished) {
        if (job.error) throw new Error(job.error);
        return job.result;
      }
      await tick(importPollMs);
    }
  }

  $('#svMergeReviewBtn').onclick = async () => {
    if (IM.busy || !IM.files || !IM.files.some(isGuideFile)) return;
    const btn = $('#svMergeReviewBtn');
    btn.disabled = true; btn.textContent = 'Reviewing…';
    hideModalError();
    showImportProgress();
    try {
      const r = await postImport(IM.files, { dryRun: true, onProgress: setImportProgress });
      IM.reviewed = true;
      renderMergeReview(r);
    } catch (e) {
      IM.reviewed = false;
      showModalError(e);
    } finally {
      hideImportProgress();
      btn.textContent = 'Review merge';
      syncModalUI();
    }
  };

  async function afterSuccessfulImport(r, toastPrefix) {
    closeImportModal();
    const { msg, needsAttention } = summarizeImport(r);
    toast((toastPrefix || '') + msg, needsAttention ? 8000 : undefined);
    await refreshAll();
    if (window.tephraReloadList) window.tephraReloadList();
  }

  function validVaultName(name) {
    return !!name && !name.includes('/') && name !== '.' && name !== '..' && !name.startsWith('.');
  }

  async function confirmCreateAndImport() {
    const name = $('#svNewVaultName').value.trim();
    if (!name || !IM.files) return;
    if (!validVaultName(name)) {
      setModalErrorText('That name won’t work as a folder name — avoid "/" and leading dots.');
      return;
    }
    IM.busy = true; syncModalUI(); hideModalError();
    try {
      await ensureSuggestedParent();
      const path = `${(S.suggestedParent || '').replace(/\/+$/, '')}/${name}`;
      await api('/vault/create', { method: 'POST', body: JSON.stringify({ path }) });
      showImportProgress();
      const r = await postImport(IM.files, { onProgress: setImportProgress });
      if (window.tephraAfterVaultSwitch) await window.tephraAfterVaultSwitch();
      await afterSuccessfulImport(r, `Created "${name}" — `);
    } catch (e) {
      showModalError(e);
    } finally {
      hideImportProgress();
      IM.busy = false; syncModalUI();
    }
  }

  async function confirmMerge() {
    if (!IM.reviewed || !IM.files) return;
    IM.busy = true; syncModalUI(); hideModalError();
    showImportProgress();
    try {
      const r = await postImport(IM.files, { onProgress: setImportProgress });
      await afterSuccessfulImport(r);
    } catch (e) {
      showModalError(e);
    } finally {
      hideImportProgress();
      IM.busy = false; syncModalUI();
    }
  }

  $('#svImportModalConfirm').onclick = () => (IM.mode === 'new' ? confirmCreateAndImport() : confirmMerge());

  function openImportModal(prefilledFiles) {
    IM.mode = 'new'; IM.files = null; IM.reviewed = false; IM.busy = false;
    $$('.sv-modebtn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === 'new')));
    $('#svNewVaultName').value = '';
    $('#svMergeReviewOut').innerHTML = '';
    hideModalError();
    modal.hidden = false;
    // Reachable from the topbar without ever opening Crucible, so S.vault
    // (the merge banner's "into <this vault>" name) can't rely on open()
    // having already fetched it.
    if (!S.vault) api('/vault/info').then((v) => { S.vault = v; syncModalUI(); }).catch(() => {});
    ensureSuggestedParent().then(syncModalUI);
    if (prefilledFiles && prefilledFiles.length) setPickedFiles(prefilledFiles);
    else syncModalUI();
  }
  function closeImportModal() { modal.hidden = true; }

  $('#svImportModalClose').onclick = closeImportModal;
  $('#svImportModalCancel').onclick = closeImportModal;
  modal.addEventListener('click', (e) => { if (e.target === modal && !IM.busy) closeImportModal(); });

  // Available whatever the current state — the dropzone only appears when the
  // guide is empty, which made importing unreachable the moment anything at
  // all had been added.
  $('#svImport').onclick = () => openImportModal();
  wireDrop(view.querySelector('.sv-body'), (files) => openImportModal(files));
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
    S.quiz = []; S.quizIx = 0; S.quizPicked = null; S.quizSubmitted = false;
    S.quizScore = 0; S.quizDone = false;
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
      if (!reduce) wireFoil(card);
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
      const open = S.quizPeekOpen;
      const h = el('button', 'sv-qpeek-toggle');
      h.type = 'button';
      h.setAttribute('aria-expanded', String(open));
      h.innerHTML = '<span class="sv-qpeek-caret">▸</span><span>Questions on this topic</span>'
        + `<span class="sv-qpeek-count">${item.quiz.length}</span>`;
      h.onclick = () => { S.quizPeekOpen = !S.quizPeekOpen; render(); };
      main.appendChild(h);
      if (open) {
        for (const q of item.quiz) {
          const b = el('div', 'sv-qpeek');
          b.appendChild(el('div', 'sv-qpeek-q', q.question));
          const ans = el('div', 'sv-qpeek-a', '✓ ' + q.answers.map((i) => q.options[i]).join(', '));
          b.appendChild(ans);
          if (q.why) b.appendChild(el('div', 'sv-qpeek-w', q.why));
          main.appendChild(b);
        }
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
    const newOpt = el('option', null, '+ New study group…');
    newOpt.value = '__new__';
    sel.appendChild(newOpt);

    async function apply(category) {
      await api(`/study/${item.slug}/category`, {
        method: 'POST', body: JSON.stringify({ category }),
      });
      toast(`Moved to ${category} — the classifier learns from this`);
      S.data = await api('/study');
      S.item = await api('/study/item/' + item.slug);
      renderCats(); renderStats(); render();
    }

    // Picking "+ New study group…" swaps the select for a text input rather
    // than a native prompt(), matching every other inline edit in this app.
    // Blur re-renders the whole topic anyway once a name is applied, so the
    // swapped-in input never needs to be manually put back except on cancel.
    sel.onchange = () => {
      if (sel.value !== '__new__') { apply(sel.value); return; }
      const input = el('input', 'sv-select');
      input.placeholder = 'New study group name';
      wrap.replaceChild(input, sel);
      input.focus();
      let done = false;
      const commit = () => {
        if (done) return;
        const name = input.value.trim();
        if (!name) { done = true; wrap.replaceChild(sel, input); return; }
        done = true;
        apply(name);
      };
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { done = true; wrap.replaceChild(sel, input); }
      });
      input.addEventListener('blur', commit);
    };
    wrap.appendChild(sel);

    if (item.source === 'auto') {
      const hint = el('span', 'sv-cat-hint', 'auto-assigned — worth a glance');
      wrap.appendChild(hint);
    }
    return wrap;
  }

  /* ── flashcards ──
     Cards are quiz questions, not topics -- one per Q: entry under a note's
     ## Quiz heading, same pool /api/study/quiz draws from for the
     multiple-choice mode. The whole point of a flashcard over multiple
     choice is recalling the answer yourself before it's shown, so the back
     is the marked-correct option(s) plus Why:, not the note's whole prose.
     n is the category's own ceiling (S.data.max_quiz), not the quiz mode's
     12-per-round default -- flipping through a deck should see everything
     available, not a sampled round of it. */
  async function loadCards() {
    const params = new URLSearchParams({ n: String(S.data.max_quiz || 200) });
    if (S.category) params.set('category', S.category);
    const r = await api('/study/quiz?' + params);
    S.cards = r.questions;
    S.cardsCategory = S.category;
    S.cardIx = 0; S.cardFlipped = false;
  }

  function renderCards(main) {
    // Fetched once per category and reused across flips/next/prev -- a fresh
    // load only when the category actually changes, tracked separately from
    // S.category because resetBrowse() (category switch) can't itself await.
    if (S.cardsCategory !== S.category) {
      main.appendChild(el('div', 'empty', 'Loading…'));
      loadCards().then(render);
      return;
    }
    if (!S.cards.length) {
      main.appendChild(el('div', 'empty',
        'No flashcards here — add a ## Quiz section with a Q: line to a note.'));
      return;
    }
    if (S.cardIx >= S.cards.length) S.cardIx = 0;
    const it = S.cards[S.cardIx];

    const wrap = el('div', 'sv-card-stage');

    // The click-to-flip is handled entirely in place, below, rather than
    // through the usual render() teardown-and-rebuild every other mode
    // uses -- a fresh element can't transition from a previous state it
    // never had, so a full re-render here would just snap to the flipped
    // side instead of turning.
    const tilt = el('div', 'sv-flash-tilt');
    const flip = el('div', 'sv-flash-flip' + (S.cardFlipped ? ' flipped' : ''));

    const front = el('div', 'sv-flash-face front');
    front.appendChild(el('div', 'sv-c-cat', it.category || ''));
    front.appendChild(el('div', 'sv-flash-q', it.question));
    front.appendChild(el('div', 'sv-flash-hint', 'click to reveal'));

    const back = el('div', 'sv-flash-face back');
    back.appendChild(el('div', 'sv-c-cat', it.category || ''));
    back.appendChild(el('div', 'sv-flash-title',
      it.answers.map((i) => it.options[i]).join(' · ')));
    if (it.why) {
      // .sv-flash-answer is the scroller resize() measures by class name
      // (see its own note below); .sv-why inside is the same boxed-
      // explanation look Quiz mode reveals after answering, so the two
      // modes read as one system rather than two different designs.
      const scroller = el('div', 'sv-flash-answer');
      scroller.appendChild(el('div', 'sv-why', it.why));
      back.appendChild(scroller);
    }
    if (it.slug) {
      const jump = el('button', 'sv-back', `Read the full topic: ${it.title} →`);
      jump.onclick = async (e) => {
        e.stopPropagation();
        S.item = await api('/study/item/' + it.slug);
        setMode('browse');
      };
      back.appendChild(jump);
    }
    back.appendChild(el('div', 'sv-flash-hint', 'click to flip back'));

    flip.append(front, back);
    tilt.appendChild(flip);
    const glow = el('div', 'sv-flash-glow');
    tilt.appendChild(glow);
    wrap.appendChild(tilt);

    // Faces are position:absolute (so both can occupy the same spot for the
    // flip), which means .sv-flash-flip needs an explicit height -- nothing
    // here sizes to its content on its own. scrollHeight on the visible
    // face still reports its true content height even while the face's own
    // box is pinned to whatever height was last set, which is what lets
    // this grow smoothly instead of jumping -- EXCEPT .sv-flash-answer has
    // its own overflow-y:auto (for the rare answer too long even for the
    // 62vh cap below), and a nested scroller absorbs its children's
    // overflow rather than passing it up, so the answer's true height never
    // reaches the face's own scrollHeight while that's active. Lifting the
    // constraint for one measurement is simpler than computing the
    // remaining chrome height by hand.
    function resize() {
      requestAnimationFrame(() => {
        const face = S.cardFlipped ? back : front;
        const scroller = face.querySelector('.sv-flash-answer');
        let full;
        if (scroller) {
          // .sv-flash-answer is flex:1, which is flex-grow:1 flex-shrink:1
          // flex-basis:0% -- flex-basis wins over any height set here
          // whenever it isn't itself `auto`, so setting height:auto (the
          // previous approach) never actually released this from flex
          // sizing. It kept measuring "however much of the CURRENT,
          // possibly still-too-small flip height flex-grow handed it" as
          // if that were the full content height, so flip never grew past
          // whatever it happened to already be -- exactly the cut-off
          // answer with its own stray internal scrollbar this replaces.
          // flex:none swaps it for ordinary content-based sizing so
          // face.scrollHeight reports the true full height needed.
          const prevFlex = scroller.style.flex, prevOverflow = scroller.style.overflowY,
                prevHeight = scroller.style.height;
          scroller.style.flex = 'none';
          scroller.style.overflowY = 'visible';
          scroller.style.height = 'auto';
          full = face.scrollHeight;
          scroller.style.flex = prevFlex;
          scroller.style.overflowY = prevOverflow;
          scroller.style.height = prevHeight;
        } else {
          full = face.scrollHeight;
        }
        flip.style.height = Math.min(Math.max(full, 220), innerHeight * 0.62) + 'px';
      });
    }

    tilt.onclick = () => {
      S.cardFlipped = !S.cardFlipped;
      flip.classList.toggle('flipped', S.cardFlipped);
      resize();
    };
    if (!reduce) wireTilt(tilt, glow);
    resize();

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
    S.quizIx = 0; S.quizPicked = null; S.quizSubmitted = false;
    S.quizScore = 0; S.quizDone = false;
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
    const multi = q.answers.length > 1;
    if (multi) wrap.appendChild(el('div', 'sv-quiz-hint', 'Select all that apply'));

    const picked = S.quizPicked || [];
    const answered = S.quizSubmitted;

    async function lockIn() {
      S.quizSubmitted = true;
      const correct = sameSet(picked, q.answers);
      if (correct) S.quizScore++;
      await api('/study/answer', { method: 'POST', body: JSON.stringify({ qid: q.id, correct }) });
      render();
    }

    const opts = el('div', 'sv-opts');
    q.options.forEach((text, i) => {
      const b = el('button', 'sv-opt');
      b.textContent = text;
      if (answered) {
        if (q.answers.includes(i)) b.classList.add('right');
        else if (picked.includes(i)) b.classList.add('wrong');
        b.disabled = true;
      } else if (multi && picked.includes(i)) {
        b.classList.add('picked');
      }
      b.onclick = () => {
        if (answered) return;
        if (multi) {
          const at = picked.indexOf(i);
          if (at === -1) picked.push(i); else picked.splice(at, 1);
          S.quizPicked = picked;
          render();
          return;
        }
        S.quizPicked = [i];
        lockIn();
      };
      opts.appendChild(b);
    });
    wrap.appendChild(opts);

    if (multi && !answered) {
      const submit = el('button', 'sv-btn primary', 'Submit');
      submit.disabled = picked.length === 0;
      submit.onclick = lockIn;
      wrap.appendChild(submit);
    }

    if (answered) {
      const why = el('div', 'sv-why');
      why.appendChild(el('div', 'sv-why-h',
        sameSet(picked, q.answers) ? 'Correct' : 'Not quite'));
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
        if (S.quizIx + 1 < S.quiz.length) {
          S.quizIx++; S.quizPicked = null; S.quizSubmitted = false;
        } else S.quizDone = true;
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
      'Import a study guide file, or mark any note as a study item from the editor.'));

    const drop = el('div', 'sv-drop');
    drop.innerHTML = `<span class="sv-drop-t">Import/Merge study guide</span>
      <span class="sv-drop-s">Click to choose a guide file — alone, or together with any images it
        references — or drop a <code>.json</code> <code>.py</code> <code>.csv</code>
        <code>.md</code> file, or a whole folder, right here</span>`;
    drop.onclick = () => openImportModal();
    wireDrop(drop, (files) => openImportModal(files));
    wrap.appendChild(drop);

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

  // Walks a drop's items out with the FileSystem Entry API when the browser
  // exposes it (webkitGetAsEntry, recursing into any dropped folder) so a
  // whole folder dropped at once yields every file inside it, images and
  // all -- dt.files alone only ever sees what was dropped directly, never
  // anything nested inside a folder entry. Falls back to the flat file list
  // for a browser (or a synthetic test event) that doesn't expose entries.
  async function filesFromDrop(dt) {
    const items = dt.items && Array.from(dt.items);
    const hasEntries = items && items.length
      && items.every((it) => typeof it.webkitGetAsEntry === 'function');
    if (!hasEntries) return Array.from((dt.files) || []);
    const out = [];
    async function walk(entry) {
      if (!entry) return;
      if (entry.isFile) {
        await new Promise((res) => entry.file((f) => { out.push(f); res(); }, res));
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        // readEntries returns at most one batch per call by spec -- keep
        // calling until it comes back empty, or a folder with more than a
        // batch's worth of slides silently loses the rest.
        let batch;
        do {
          batch = await new Promise((res) => reader.readEntries(res, () => res([])));
          for (const child of batch) await walk(child);
        } while (batch.length);
      }
    }
    await Promise.all(items.map((it) => walk(it.webkitGetAsEntry())));
    return out;
  }

  // onFiles(files) is called with whatever was dropped -- never imports by
  // itself. Every caller either opens the confirm modal fresh (pre-filled
  // with the dropped files) or, if the modal's already open, just updates
  // its picked-files state.
  function wireDrop(node, onFiles) {
    ['dragenter', 'dragover'].forEach((ev) => node.addEventListener(ev, (e) => {
      e.preventDefault(); node.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach((ev) => node.addEventListener(ev, (e) => {
      e.preventDefault(); node.classList.remove('over');
    }));
    node.addEventListener('drop', async (e) => {
      e.preventDefault();
      const dt = e.dataTransfer;
      if (!dt) return;
      const files = await filesFromDrop(dt);
      if (files.length) onFiles(files);
    });
  }

  // Shared by every import entry point -- all return the same guide_import
  // summary shape, images and all.
  function summarizeImport(r) {
    let msg = `Imported ${r.topics} topics, ${r.questions} questions, ${r.categories} categories`;
    if (r.images_embedded) {
      msg += `, ${r.images_embedded} image${r.images_embedded === 1 ? '' : 's'}`;
    }
    if (r.collisions && r.collisions.length) {
      msg += ` — ${r.collisions.length} matched an existing note by title and were kept separate`;
    }
    if (r.skipped_duplicates) {
      msg += ` — ${r.skipped_duplicates} skipped as near-duplicates of existing notes`;
    }
    const flagged = (r.duplicates || []).filter((d) => !d.skipped);
    if (flagged.length) {
      msg += ` — ${flagged.length} possible duplicate${flagged.length === 1 ? '' : 's'} kept, worth a look (Vault → Find duplicate notes)`;
    }
    const missingTopics = r.missing_images || [];
    const missingCount = missingTopics.reduce((n, m) => n + m.files.length, 0);
    if (missingCount) {
      msg += ` — ${missingCount} referenced image${missingCount === 1 ? '' : 's'} not found in the search folder`;
    }
    if (r.duplicate_image_names && r.duplicate_image_names.length) {
      msg += ` — ${r.duplicate_image_names.length} image filename${r.duplicate_image_names.length === 1 ? '' : 's'} appeared more than once, first match used`;
    }
    const needsAttention = (r.collisions && r.collisions.length) || r.skipped_duplicates
      || flagged.length || missingCount || (r.duplicate_image_names && r.duplicate_image_names.length);
    return { msg, needsAttention };
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
  }, openImportModal, openFormats };
})();
