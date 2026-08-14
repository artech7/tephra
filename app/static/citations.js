/* ══════════════════════════════════════════════════════════════
   Citation markers: [^1] in a note's prose, rendered by render.py as
   <sup class="cite-ref"><a class="cite-link" data-idx="1" data-text=""
   data-url="">1</a></sup>, indexing into that same note's own `## Sources`
   list (see sources-panel.js). Hovering one opens the same #lens popup a
   [[wikilink]] does -- app.js's own hover-lens listeners match `a.cite-link`
   alongside `a.wl` and build its content from these data attributes instead
   of fetching a note, so there's nothing to wire up here for that part.
   Clicking is citation-specific, though: it opens the Sources panel (if
   collapsed) and scrolls to + briefly highlights the matching #src-N entry
   there, rather than navigating anywhere.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const body = document.querySelector('#noteBody');

  body.addEventListener('click', (e) => {
    const link = e.target.closest('.cite-link');
    if (!link) return;
    e.preventDefault();
    if (link.classList.contains('missing')) return;
    const target = window.tephraSourcesPanel?.openTo(link.dataset.idx);
    if (!target) return;
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    target.classList.add('cite-highlight');
    setTimeout(() => target.classList.remove('cite-highlight'), 1400);
  });
})();
