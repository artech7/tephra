/* ══════════════════════════════════════════════════════════════
   Sources panel: a read-only list built from the note's own `## Sources`
   section (see index.split_sources_block / parse_sources). Pulled out of
   the rendered prose so it isn't shown twice, the same way the Quiz
   section is -- in its own collapsible strip below the body. There's no
   form here: editing is source-mode only (⌘E), a `- [Title](url)` line
   per source, or any other bullet shown as plain text.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const $ = (s) => document.querySelector(s);

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  // Rolled up by default, and -- like Quiz -- not reset per note, so
  // switching notes keeps whatever the user last chose.
  let open = false;

  function syncOpen() {
    $('#sourcesToggle').setAttribute('aria-expanded', String(open));
    $('#sourcesBody').hidden = !open;
  }

  // Called when a note is opened, and after leaving source-edit mode -- the
  // same two points app.js refreshes note.html from, so this panel always
  // matches what ⌘E just saved.
  function render(sources) {
    const list = sources || [];
    const section = $('#sourcesEdit');
    section.hidden = list.length === 0;
    if (!list.length) return;
    $('#sourcesCount').textContent = `${list.length} source${list.length === 1 ? '' : 's'}`;
    const host = $('#sourcesList');
    host.innerHTML = '';
    list.forEach((s, i) => {
      const li = el('li', 'sources-item');
      li.id = 'src-' + (i + 1);
      if (s.url) {
        const a = el('a', 'sources-link', s.text);
        a.href = s.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        li.appendChild(a);
      } else {
        li.textContent = s.text;
      }
      host.appendChild(li);
    });
    syncOpen();
  }

  $('#sourcesToggle').onclick = () => { open = !open; syncOpen(); };

  // Opens the panel (if collapsed) and returns the #src-n element for a
  // citation marker's click handler to scroll to and highlight -- null if
  // that source doesn't exist (a note with fewer sources than the highest
  // [^N] cited).
  function openTo(n) {
    if (!open) { open = true; syncOpen(); }
    return document.getElementById('src-' + n);
  }

  window.tephraSourcesPanel = { render, openTo };
})();
