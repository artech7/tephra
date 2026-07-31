/* ══════════════════════════════════════════════════════════════
   Links — one place to approve or dismiss what the auto-wiki found.

   These used to sit in the note's context panel, three at a time, with a
   dismiss that only removed the row from the DOM. You could not see the whole
   queue, and saying no did not stick.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const api = () => window.tephraApi;
  const toast = (...a) => window.tephraToast(...a);

  const L = { open: false, tab: 'pending', pending: [], dismissed: [], busy: false };

  const view = el('div');
  view.id = 'linksview';
  view.innerHTML = `
    <div class="lv-head">
      <div>
        <h3>Links</h3>
        <p id="lvStats">—</p>
      </div>
      <div class="lv-tabs">
        <button data-tab="pending"   aria-pressed="true">To review</button>
        <button data-tab="dismissed" aria-pressed="false">Dismissed</button>
      </div>
    </div>
    <div class="lv-body"><div id="lvList"></div></div>`;

  function mount() {
    if (view.parentElement) return;
    (document.querySelector('#sideTephra') || document.body).appendChild(view);
    view.querySelectorAll('.lv-tabs button').forEach((b) => (b.onclick = () => {
      L.tab = b.dataset.tab;
      view.querySelectorAll('.lv-tabs button').forEach((x) =>
        x.setAttribute('aria-pressed', x.dataset.tab === L.tab));
      render();
    }));
  }

  async function load() {
    const [pending, dismissed] = await Promise.all([
      api()('/suggestions?limit=100'),
      api()('/suggestions/dismissed'),
    ]);
    L.pending = pending;
    L.dismissed = dismissed;
    updateBadge();
  }

  function updateBadge() {
    const b = $('#linksBadge');
    if (!b) return;
    b.textContent = L.pending.length || '';
    b.hidden = !L.pending.length;
  }

  async function open() {
    mount();
    L.open = true;
    // Always land on the actionable list. Remembering the Dismissed tab meant
    // opening Links could show an archive when you came to review a queue.
    L.tab = 'pending';
    view.querySelectorAll('.lv-tabs button').forEach((x) =>
      x.setAttribute('aria-pressed', x.dataset.tab === 'pending'));
    view.classList.add('on');
    $('#lvList').innerHTML = '<div class="empty">Looking through your notes…</div>';
    try { await load(); } catch { $('#lvList').innerHTML = '<div class="empty">Could not load suggestions.</div>'; return; }
    render();
  }
  function close() { L.open = false; view.classList.remove('on'); }

  function render() {
    const list = $('#lvList');
    const stats = $('#lvStats');
    list.innerHTML = '';
    stats.textContent =
      `${L.pending.length} TO REVIEW · ${L.dismissed.length} DISMISSED`;

    const rows = L.tab === 'pending' ? L.pending : L.dismissed;
    if (!rows.length) {
      list.appendChild(el('div', 'lv-empty', L.tab === 'pending'
        ? 'Nothing to review. Tephra suggests a link when a phrase turns up across three or more notes.'
        : 'Nothing dismissed yet. Anything you say no to is listed here, and can be brought back.'));
      return;
    }
    for (const row of rows) {
      list.appendChild(L.tab === 'pending' ? pendingRow(row) : dismissedRow(row));
    }
  }

  function pendingRow(s) {
    const card = el('div', 'lv-card');

    const head = el('div', 'lv-card-head');
    const left = el('div', 'lv-card-left');
    const kind = el('span', 'lv-kind ' + s.kind,
      s.kind === 'unlinked' ? 'page exists' : 'no page yet');
    left.appendChild(kind);
    left.appendChild(el('span', 'lv-term', s.term));
    head.appendChild(left);

    const acts = el('div', 'lv-acts');
    const yes = el('button', 'lv-btn yes',
      s.kind === 'unlinked' ? 'Link them' : 'Create & link');
    const no = el('button', 'lv-btn no', 'Not a link');
    acts.append(yes, no);
    head.appendChild(acts);
    card.appendChild(head);

    card.appendChild(el('div', 'lv-what', s.kind === 'unlinked'
      ? `A note called “${s.term}” already exists. This would turn ${s.mentions} plain mention${s.mentions === 1 ? '' : 's'} into ${s.mentions === 1 ? 'a link' : 'links'}.`
      : `This phrase appears in ${s.notes} notes with no page of its own. This would create the note and link every mention.`));

    // The whole point of a central area: see which notes are affected before
    // you commit, not after.
    const where = el('div', 'lv-where');
    where.appendChild(el('span', 'lv-where-h', 'in'));
    for (const w of (s.where || []).slice(0, 8)) {
      const b = el('button', 'lv-ref', w.title);
      b.title = `Open ${w.title}`;
      b.onclick = () => { close(); window.tephraOpenNote(w.slug); };
      where.appendChild(b);
    }
    if ((s.where || []).length > 8) {
      where.appendChild(el('span', 'lv-more', `+${s.where.length - 8} more`));
    }
    card.appendChild(where);

    yes.onclick = async () => {
      if (L.busy) return;
      L.busy = true; yes.disabled = no.disabled = true; yes.textContent = 'Linking…';
      try {
        const r = await api()('/suggestions/apply', {
          method: 'POST', body: JSON.stringify({ term: s.term, target: s.target }),
        });
        toast(`Linked “${r.title}” across ${r.notes_updated} note${r.notes_updated === 1 ? '' : 's'}`);
        await refresh();
      } catch {
        toast('Could not apply that');
        yes.disabled = no.disabled = false;
        yes.textContent = s.kind === 'unlinked' ? 'Link them' : 'Create & link';
      } finally { L.busy = false; }
    };

    no.onclick = async () => {
      if (L.busy) return;
      L.busy = true; yes.disabled = no.disabled = true;
      try {
        await api()('/suggestions/dismiss', { method: 'POST', body: JSON.stringify({ term: s.term }) });
        toast(`“${s.term}” won't be suggested again`);
        await refresh();
      } catch {
        toast('Could not dismiss that');
        yes.disabled = no.disabled = false;
      } finally { L.busy = false; }
    };
    return card;
  }

  function dismissedRow(d) {
    const card = el('div', 'lv-card dim');
    const head = el('div', 'lv-card-head');
    const left = el('div', 'lv-card-left');
    left.appendChild(el('span', 'lv-kind gone', d.note === 'applied' ? 'linked' : 'dismissed'));
    left.appendChild(el('span', 'lv-term', d.term));
    head.appendChild(left);
    const back = el('button', 'lv-btn', 'Suggest again');
    back.onclick = async () => {
      back.disabled = true;
      try {
        await api()('/suggestions/restore', { method: 'POST', body: JSON.stringify({ term: d.term }) });
        toast(`“${d.term}” is back in the review list`);
        await refresh();
      } catch { toast('Could not restore that'); back.disabled = false; }
    };
    head.appendChild(back);
    card.appendChild(head);
    if (d.at) {
      card.appendChild(el('div', 'lv-what',
        d.note === 'applied' ? 'You linked this one.' : 'You said this is not a link.'));
    }
    return card;
  }

  async function refresh() {
    await load();
    render();
    if (window.tephraReloadList) await window.tephraReloadList();
  }

  window.tephraLinks = {
    open, close, isOpen: () => L.open,
    // Kept current even when the pane is closed, so the tab badge is honest.
    async poll() {
      try {
        L.pending = await api()('/suggestions?limit=100');
        updateBadge();
      } catch {}
    },
  };
})();
