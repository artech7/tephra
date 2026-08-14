/* ══════════════════════════════════════════════════════════════
   Citation markers: [^1] in a note's prose, rendered by render.py as
   <sup class="cite-ref"><a class="cite-link" data-idx="1" data-text=""
   data-url="">1</a></sup>, indexing into that same note's own `## Sources`
   list (see sources-panel.js). Hovering shows a small popup with the
   source's text/url; clicking opens the Sources panel (if collapsed) and
   scrolls to + briefly highlights the matching #src-N entry there.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const $ = (s) => document.querySelector(s);
  const body = $('#noteBody');

  let popup = null;
  function ensurePopup() {
    if (!popup) {
      popup = document.createElement('div');
      popup.className = 'cite-popup';
      popup.hidden = true;
      document.body.appendChild(popup);
    }
    return popup;
  }

  function showPopup(link) {
    const p = ensurePopup();
    p.innerHTML = '';
    if (link.classList.contains('missing')) {
      p.textContent = `Source #${link.dataset.idx} not found in this note's Sources list.`;
    } else {
      const t = document.createElement('div');
      t.className = 'cite-popup-text';
      t.textContent = link.dataset.text || '';
      p.appendChild(t);
      if (link.dataset.url) {
        const u = document.createElement('div');
        u.className = 'cite-popup-url';
        u.textContent = link.dataset.url;
        p.appendChild(u);
      }
    }
    p.hidden = false;
    const r = link.getBoundingClientRect();
    const pw = p.offsetWidth, ph = p.offsetHeight;
    let left = r.left + r.width / 2 - pw / 2;
    left = Math.max(8, Math.min(left, innerWidth - pw - 8));
    let top = r.top - ph - 8;
    if (top < 8) top = r.bottom + 8;
    p.style.left = left + 'px';
    p.style.top = top + 'px';
  }

  function hidePopup() {
    if (popup) popup.hidden = true;
  }

  body.addEventListener('mouseover', (e) => {
    const link = e.target.closest('.cite-link');
    if (link) showPopup(link);
  });
  body.addEventListener('mouseout', (e) => {
    if (e.target.closest('.cite-link')) hidePopup();
  });
  body.addEventListener('focusin', (e) => {
    const link = e.target.closest('.cite-link');
    if (link) showPopup(link);
  });
  body.addEventListener('focusout', (e) => {
    if (e.target.closest('.cite-link')) hidePopup();
  });

  body.addEventListener('click', (e) => {
    const link = e.target.closest('.cite-link');
    if (!link) return;
    e.preventDefault();
    hidePopup();
    if (link.classList.contains('missing')) return;
    const target = window.tephraSourcesPanel?.openTo(link.dataset.idx);
    if (!target) return;
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    target.classList.add('cite-highlight');
    setTimeout(() => target.classList.remove('cite-highlight'), 1400);
  });
})();
