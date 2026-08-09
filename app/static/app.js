/* ══════════════════════════════════════════════════════════════
   Tephra frontend. No framework on purpose — the whole app is
   three static files the container serves, so it stays editable
   by whoever is self-hosting it.
   ══════════════════════════════════════════════════════════════ */
const $ = (s) => document.querySelector(s);
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const R = document.documentElement;

const api = async (path, opts = {}) => {
  const res = await fetch('/api' + path, {
    headers: opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error((await res.text()) || res.status);
  return res.status === 204 ? null : res.json();
};

function toast(msg, ms = 2600) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('on');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('on'), ms);
}

const state = { slug: null, note: null, notes: [], editing: false, dirty: false,
                sort: 'updated', tag: '', media: [], mediaOpen: {} };

// study.js is a separate file so this one stays readable; these three are the
// only things it needs from here.
window.tephraApi = api;
window.tephraToast = toast;
window.tephraOpenNote = (slug) => openNote(slug);
// after an in-app import the sidebar and graph need to catch up
window.tephraCurrentSlug = () => state.slug;
// Crucible calls this after flagging so the indicators update live.
window.tephraRefreshFlags = async () => {
  await loadList();
  if (state.slug && !state.dirty) {
    try {
      const fresh = await api('/notes/' + encodeURIComponent(state.slug));
      state.note = fresh;
      renderFlagChip(fresh);
    } catch {}
  }
};
window.tephraReloadList = async () => {
  window.tephraLinks?.poll();
  await loadList();
  await loadGraph();
  await loadMedia();
  if (state.slug) { try { await openNote(state.slug, false); } catch {} }
  else if (state.notes[0]) await openNote(state.notes[0].slug, false);
};

/* ══ THEME ═══════════════════════════════════════════════════
   Persisted server-side to vault/theme.json, so it rides along
   with the notes and survives container rebuilds.
   ═══════════════════════════════════════════════════════════ */
const DEFAULTS = { acc: '63,224,173', wall: 'aurora', wallUrl: null, blur: 30, frost: 55,
  sat: 200, scrim: 26, inset: 20, contrast: 0, auto: false, radius: 28, shine: 34,
  font_display: 'Bricolage Grotesque', font_serif: 'Newsreader', font_mono: 'JetBrains Mono',
  note_sort: 'updated', note_tag: '', media_open: {} };
let T = { ...DEFAULTS };
const FONT_FALLBACK = { display: "system-ui,sans-serif", serif: "Georgia,serif", mono: "ui-monospace,monospace" };

const WALLS = {
  aurora: null,
  slate: 'linear-gradient(150deg,#0E1C26 0%,#22384A 38%,#415C6E 72%,#16242E 100%)',
  ember: 'linear-gradient(150deg,#180B07 0%,#4E2317 40%,#9A4E2C 74%,#251009 100%)',
  bloom: 'linear-gradient(150deg,#1E0B26 0%,#4C1D46 40%,#8E3A62 72%,#25102A 100%)',
  night: 'linear-gradient(160deg,#03050C 0%,#0A1130 35%,#161A45 65%,#050614 100%)',
};

const hex = (r) => '#' + r.split(',').map((n) => (+n).toString(16).padStart(2, '0')).join('');

/* Accent is pulled from the wallpaper, so a hardcoded Crucible palette can
   land on top of it — which is exactly what happened: a peach wallpaper made
   both marks peach. Deriving Crucible from the accent's complement keeps the
   two distinguishable by construction rather than by luck. */
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) {
    h = mx === r ? ((g - b) / d + (g < b ? 6 : 0)) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h *= 60;
  }
  const l = (mx + mn) / 2;
  const s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
  return [h, s, l];
}
function hslToHex(h, s, l) {
  h = ((h % 360) + 360) % 360;
  s = Math.min(1, Math.max(0, s)); l = Math.min(1, Math.max(0, l));
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = l - c / 2;
  const seg = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]][Math.floor(h / 60) % 6];
  return '#' + seg.map((v) => Math.round((v + m) * 255).toString(16).padStart(2, '0')).join('');
}
function cruciblePalette(accRgb) {
  const [r, g, b] = accRgb.split(',').map(Number);
  let [h, s, l] = rgbToHsl(r, g, b);
  s = Math.max(s, 0.62);                 // a grey accent must still yield colour
  l = Math.min(Math.max(l, 0.55), 0.72);
  return [hslToHex(h + 165, s, l), hslToHex(h + 200, s, l - 0.04), hslToHex(h + 135, s, l + 0.05)];
}
const rgb = (h) => { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(','); };

function applyTheme() {
  R.style.setProperty('--acc', T.acc);
  R.style.setProperty('--accent', hex(T.acc));
  const [ca, cb, cc] = cruciblePalette(T.acc);
  R.style.setProperty('--cruc-a', ca);
  R.style.setProperty('--cruc-b', cb);
  R.style.setProperty('--cruc-c', cc);
  R.style.setProperty('--blur', T.blur + 'px');
  R.style.setProperty('--frost', (T.frost / 1000).toFixed(4));
  R.style.setProperty('--sat', T.sat + '%');
  R.style.setProperty('--scrim', (T.scrim / 100).toFixed(2));
  R.style.setProperty('--inset', T.inset + 'px');
  R.style.setProperty('--radius', T.radius + 'px');

  const shineA = T.shine / 100;
  R.style.setProperty('--edge-hi', `rgba(255,255,255,${shineA.toFixed(3)})`);
  R.style.setProperty('--edge', `rgba(255,255,255,${(shineA * 0.38).toFixed(3)})`);

  R.style.setProperty('--display', `'${T.font_display}',${FONT_FALLBACK.display}`);
  R.style.setProperty('--serif', `'${T.font_serif}',${FONT_FALLBACK.serif}`);
  R.style.setProperty('--mono', `'${T.font_mono}',${FONT_FALLBACK.mono}`);

  // Contrast is derived: the less the frost, blur and dim are doing,
  // the more the ink layer has to do to keep text legible.
  const auto = 0.52 - (T.frost / 200) * 0.20 - (T.blur / 70) * 0.12 - (T.scrim / 100) * 0.18;
  const ink = Math.max(0.02, Math.min(0.78, auto + T.contrast / 100));
  R.style.setProperty('--ink', ink.toFixed(3));

  $('#vInk').textContent = Math.round(ink * 100) + '%';
  $('#vBlur').textContent = T.blur + 'px';
  $('#vFrost').textContent = (T.frost / 10).toFixed(1) + '%';
  $('#vSat').textContent = T.sat + '%';
  $('#vScrim').textContent = T.scrim + '%';
  $('#vInset').textContent = T.inset + 'px';
  $('#vRadius').textContent = T.radius + 'px';
  $('#vShine').textContent = T.shine + '%';
  $('#vAcc').textContent = hex(T.acc).toUpperCase();
  $('#lgW').style.background = hex(T.acc);
  $('#autoAcc').toggleAttribute('data-on', !!T.auto);

  const isAurora = T.wall === 'aurora';
  document.body.dataset.wall = T.wall;
  $('#aurora').style.display = isAurora ? 'block' : 'none';
  $('#wall').style.display = isAurora ? 'none' : 'block';
  if (T.wall === 'custom' && T.wallUrl) $('#wall').style.backgroundImage = `url('${T.wallUrl}')`;
  else if (WALLS[T.wall]) $('#wall').style.backgroundImage = WALLS[T.wall];

  document.querySelectorAll('.wallopt').forEach((x) => x.removeAttribute('data-on'));
  const wsel = T.wall === 'custom' ? $('#wallUp') : document.querySelector(`.wallopt[data-wall="${T.wall}"]`);
  if (wsel) wsel.setAttribute('data-on', '');
  if (T.wall === 'custom' && T.wallUrl) $('#wallUp').style.backgroundImage = `url('${T.wallUrl}')`;

  document.querySelectorAll('.sw').forEach((x) => x.removeAttribute('data-on'));
  (document.querySelector(`.sw[data-acc="${T.acc}"]`) || document.querySelector('.sw.custom')).setAttribute('data-on', '');
  $('#accPick').value = hex(T.acc);

  if ($('#noteSort')) $('#noteSort').value = state.sort;
  ['rBlur:blur', 'rFrost:frost', 'rSat:sat', 'rScrim:scrim', 'rInset:inset', 'rContrast:contrast', 'rRadius:radius', 'rShine:shine']
    .forEach((pair) => { const [id, key] = pair.split(':'); $('#' + id).value = T[key]; });

  [['fontDisplay', 'font_display'], ['fontSerif', 'font_serif'], ['fontMono', 'font_mono']].forEach(([id, key]) => {
    $('#' + id).querySelectorAll('.fopt').forEach((o) => o.toggleAttribute('data-on', o.dataset.font === T[key]));
  });
}

let themeT;
function saveTheme() {
  T.note_sort = state.sort;
  T.note_tag = state.tag;
  T.media_open = state.mediaOpen;
  clearTimeout(themeT);
  themeT = setTimeout(() => api('/theme', { method: 'PUT', body: JSON.stringify(T) }).catch(() => {}), 400);
}
function setTheme(patch) { Object.assign(T, patch); applyTheme(); saveTheme(); }

/* Dominant-colour extraction. Buckets pixels by hue and weights each
   bucket by count x saturation, rather than trusting any single pixel —
   one specular highlight would otherwise return white. */
function accentFrom(img) {
  const n = 64, cv = document.createElement('canvas');
  cv.width = cv.height = n;
  const g = cv.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0, n, n);
  let d;
  try { d = g.getImageData(0, 0, n, n).data; } catch { return null; }

  const B = 18, bins = Array.from({ length: B }, () => ({ w: 0, r: 0, g: 0, b: 0, n: 0 }));
  for (let i = 0; i < d.length; i += 4) {
    const r = d[i] / 255, gg = d[i + 1] / 255, b = d[i + 2] / 255;
    const mx = Math.max(r, gg, b), mn = Math.min(r, gg, b), c = mx - mn;
    if (mx < 0.10 || c < 0.06) continue;
    let h = mx === r ? ((gg - b) / c + 6) % 6 : mx === gg ? (b - r) / c + 2 : (r - gg) / c + 4;
    h *= 60;
    const sat = c / mx, k = Math.floor((h / 360) * B) % B;
    const bin = bins[k];
    bin.w += sat * sat * (1 - Math.abs(mx - 0.66));
    bin.r += d[i]; bin.g += d[i + 1]; bin.b += d[i + 2]; bin.n++;
  }
  let win = null;
  for (const bin of bins) if (bin.n > 3 && (!win || bin.w > win.w)) win = bin;
  if (!win) return null;
  let out = [win.r / win.n, win.g / win.n, win.b / win.n];
  const mn = Math.min(...out);
  out = out.map((v) => mn + (v - mn) * 1.45);
  const lift = Math.min(2.6, 222 / Math.max(...out, 1));
  return out.map((v) => Math.max(0, Math.min(255, Math.round(v * lift)))).join(',');
}

/* ══ NOTES ═══════════════════════════════════════════════════ */

function fmtAgo(iso) {
  if (!iso) return '';
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.round(s / 60) + 'm ago';
  if (s < 86400) return Math.round(s / 3600) + 'h ago';
  return Math.round(s / 86400) + 'd ago';
}

/* The list is fetched once and then filtered and sorted client side, so
   changing sort or tapping a tag is instant and costs no round trip. */
const SORTS = {
  updated:   (a, b) => (b.updated || '').localeCompare(a.updated || ''),
  title:     (a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: 'base' }),
  backlinks: (a, b) => b.backlinks - a.backlinks || a.title.localeCompare(b.title),
  links_out: (a, b) => b.links_out - a.links_out || a.title.localeCompare(b.title),
  size:      (a, b) => b.size - a.size,
  flags:     (a, b) => (b.flags || 0) - (a.flags || 0) ||
                       a.title.localeCompare(b.title),
  kind:      (a, b) => ['index', 'study', 'note'].indexOf(a.kind) -
                       ['index', 'study', 'note'].indexOf(b.kind) ||
                       a.title.localeCompare(b.title),
};

async function loadList() {
  state.notes = await api('/notes');
  renderList();
}

function allTags() {
  return [...new Set(state.notes.flatMap((n) => n.tags))].sort();
}

// The 5-point star used for both the sidebar row toggle and the doc header
// button, kept as one literal so the two read as the same control.
const STAR_SVG = '<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round">'
  + '<path d="M12 3.4l2.65 5.53 6.02.73-4.42 4.16 1.18 5.94L12 16.9l-5.43 2.86 1.18-5.94-4.42-4.16 6.02-.73z"/></svg>';

async function toggleFavorite(slug) {
  const row = state.notes.find((n) => n.slug === slug);
  const onOpenNote = state.note && state.slug === slug ? state.note : null;
  const was = row ? row.favorite : !!onOpenNote?.favorite;
  const next = !was;
  if (row) row.favorite = next;
  if (onOpenNote) onOpenNote.favorite = next;
  renderList();
  renderFavBtn(state.note);
  if (next && state.slug === slug) {
    const btn = $('#favBtn');
    btn?.classList.remove('bump');
    void btn?.offsetWidth;                 // restart the animation on repeat clicks
    btn?.classList.add('bump');
  }
  try {
    const res = await api('/notes/' + encodeURIComponent(slug) + '/favorite', { method: 'POST' });
    if (row) row.favorite = res.favorite;
    if (onOpenNote) onOpenNote.favorite = res.favorite;
  } catch {
    if (row) row.favorite = was;
    if (onOpenNote) onOpenNote.favorite = was;
    toast('Could not update favorite');
  }
  renderList();
  renderFavBtn(state.note);
}

function renderFavBtn(note) {
  const btn = $('#favBtn');
  if (!btn) return;
  const on = !!note?.favorite;
  btn.classList.toggle('on', on);
  btn.setAttribute('aria-pressed', String(on));
  btn.title = on ? 'Favorited — click to remove from the top' : 'Favorite this note — pins it to the top';
}

function renderList() {
  const list = $('#noteList');
  const sort = SORTS[state.sort] ? state.sort : 'updated';
  // Favorites always float to the top, regardless of the active sort --
  // sort still decides the order within each group.
  const shown = state.notes
    .filter((n) => !state.tag || n.tags.includes(state.tag))
    .sort((a, b) => (b.favorite - a.favorite) || SORTS[sort](a, b));

  $('#noteCount').textContent = state.tag || shown.length !== state.notes.length
    ? `${shown.length} of ${state.notes.length}`
    : `${state.notes.length} notes`;

  list.innerHTML = '';
  if (!shown.length) {
    const e = document.createElement('div');
    e.className = 'empty';
    e.textContent = state.tag ? `Nothing tagged #${state.tag}.` : 'No notes yet.';
    list.appendChild(e);
  }
  // The trailing number changes meaning with the sort, so label it.
  const metric = { backlinks: 'backlinks', links_out: 'links out', size: 'characters' }[sort];
  for (const n of shown) {
    const el = document.createElement('div');
    el.className = 'node kind-' + n.kind;
    el.dataset.slug = n.slug;
    if (n.slug === state.slug) el.setAttribute('aria-current', 'page');
    const num = sort === 'size' ? (n.size > 999 ? Math.round(n.size / 1000) + 'k' : n.size)
      : sort === 'links_out' ? n.links_out
      : sort === 'title' || sort === 'kind' || sort === 'updated' ? (n.backlinks || '')
      : n.backlinks;
    const flagMark = n.flags
      ? `<span class="flagmark" title="${n.flags} flagged question${n.flags === 1 ? '' : 's'}">⚑</span>`
      : '';
    el.innerHTML = `<button class="star${n.favorite ? ' on' : ''}" type="button">${STAR_SVG}</button>`
      + `<span class="dot"></span><span class="t"></span>${flagMark}<span class="n">${num}</span>`;
    el.querySelector('.t').textContent = n.title;
    el.title = `${n.title}\n${n.kind} · ${n.backlinks} backlinks · ${n.links_out} links out`
      + (n.flags ? `\n${n.flags} flagged question${n.flags === 1 ? '' : 's'}` : '')
      + (metric ? `\nsorted by ${metric}` : '');
    const star = el.querySelector('.star');
    star.title = n.favorite ? 'Unfavorite' : 'Favorite — pin to the top';
    star.onclick = (e) => { e.stopPropagation(); toggleFavorite(n.slug); };
    el.onclick = () => openNote(n.slug);
    list.appendChild(el);
  }

  const tags = allTags();
  $('#tagSect').hidden = !tags.length;
  $('#tagClear').hidden = !state.tag;
  const cloud = $('#tagCloud');
  cloud.innerHTML = '';
  for (const t of tags) {
    const chip = document.createElement('span');
    chip.className = 'tag';
    chip.textContent = '#' + t;
    if (state.tag === t) chip.setAttribute('data-on', '');
    // Clicking a tag filters the list; clicking the active one clears it.
    chip.onclick = () => { state.tag = state.tag === t ? '' : t; renderList(); saveTheme(); };
    cloud.appendChild(chip);
  }
}

// A small glare + parallax shift that follows the cursor along whichever
// note row it's over -- delegated on the list rather than per-row, so it
// survives renderList() rebuilding the rows and never runs more than one
// row at a time. The CSS only ever reads these custom properties inside
// :hover, so a row keeps whatever value it was last given, but that's
// harmless -- it stops being visible the instant the pointer leaves.
if (!reduce) {
  $('#noteList').addEventListener('mousemove', (e) => {
    const row = e.target.closest('.node');
    if (!row) return;
    const r = row.getBoundingClientRect();
    const frac = (e.clientX - r.left) / (r.width || 1); // 0..1 across the row
    row.style.setProperty('--node-mx', (frac * 100).toFixed(1) + '%');
    row.style.setProperty('--node-shift', (frac - 0.5).toFixed(3));
  });
}

/* Media, grouped by type into collapsible sections. A flat grid of 100 files
   is unusable; the counts alone tell you what a vault holds. Each tile reveals
   a remove control on hover, and warns first if a note still embeds it. */
const MEDIA_GROUPS = [
  { kind: 'image', label: 'Images' },
  { kind: 'video', label: 'Video' },
  { kind: 'audio', label: 'Audio' },
  { kind: 'file',  label: 'Files' },
];

async function loadMedia() {
  state.media = await api('/media');
  renderMedia();
}

function renderMedia() {
  const media = state.media || [];
  $('#mediaCount').textContent = media.length;
  const host = $('#mediaGroups');
  host.innerHTML = '';
  if (!media.length) {
    host.innerHTML = '<div class="empty">Nothing attached yet. Drag a file onto a note.</div>';
    return;
  }
  for (const g of MEDIA_GROUPS) {
    const items = media.filter((m) => m.kind === g.kind);
    if (!items.length) continue;
    const open = state.mediaOpen[g.kind] !== false;   // open unless collapsed
    const sec = document.createElement('div');
    sec.className = 'mgroup';
    const head = document.createElement('button');
    head.className = 'mgroup-h' + (open ? ' open' : '');
    head.innerHTML = `<span class="mcaret">▸</span><span class="mlabel"></span>
      <span class="mcount">${items.length}</span>`;
    head.querySelector('.mlabel').textContent = g.label;
    head.onclick = () => {
      state.mediaOpen[g.kind] = !open;
      renderMedia();
      saveTheme();
    };
    sec.appendChild(head);

    if (open) {
      const grid = document.createElement('div');
      grid.className = 'mediagrid';
      for (const m of items) {
        const cell = document.createElement('div');
        cell.className = 'mcell';
        const link = document.createElement('a');
        link.href = m.url;
        link.target = '_blank';
        link.title = `${m.name}\n${Math.round((m.size || 0) / 1024)} KB`
          + (m.used_by?.length ? `\nused by ${m.used_by.length} note(s)` : '\nnot referenced by any note');
        if (m.kind === 'image') link.style.backgroundImage = `url('${m.url}')`;
        else link.textContent = m.name.slice(0, 16);
        cell.appendChild(link);
        if (m.used_by?.length) {
          const badge = document.createElement('span');
          badge.className = 'mused';
          badge.textContent = m.used_by.length;
          badge.title = 'Embedded in ' + m.used_by.join(', ');
          cell.appendChild(badge);
        }
        const rm = document.createElement('button');
        rm.className = 'mremove';
        rm.textContent = '×';
        rm.title = 'Remove from vault';
        let armed = false, timer = null;
        rm.onclick = async (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!armed) {
            armed = true;
            rm.classList.add('armed');
            rm.textContent = '✓';
            rm.title = m.used_by?.length
              ? `Still embedded in ${m.used_by.length} note(s) — click again to remove anyway`
              : 'Click again to remove';
            if (m.used_by?.length) toast(`${m.name} is used by ${m.used_by.join(', ')}`, 5000);
            timer = setTimeout(() => {
              armed = false; rm.classList.remove('armed'); rm.textContent = '×';
            }, 4000);
            return;
          }
          clearTimeout(timer);
          try {
            await api('/media/' + encodeURIComponent(m.name), { method: 'DELETE' });
            toast(`Moved ${m.name} to the vault trash`);
            await loadMedia();
            if (state.slug) await openNote(state.slug, false);
          } catch { toast(`Could not remove ${m.name}`); }
        };
        cell.appendChild(rm);
        grid.appendChild(cell);
      }
      sec.appendChild(grid);
    }
    host.appendChild(sec);
  }
}

async function openNote(slug, push = true) {
  if (state.dirty) await flush();
  let note;
  try { note = await api('/notes/' + encodeURIComponent(slug)); }
  catch { toast('That note is gone'); return loadList(); }

  state.slug = slug; state.note = note; state.editing = false;
  if (push && location.hash.slice(1) !== slug) location.hash = slug;

  // The topbar shows which vault you are in; the note names itself in its own
  // heading, so repeating it there was pure duplication.
  document.title = note.title + ' — Tephra';
  renderDocCrumb(note);
  $('#noteTitle').value = note.title;
  autoGrow($('#noteTitle'));
  $('#noteBody').innerHTML = note.html || '<p class="empty">Empty note. Click here to start writing.</p>';
  enhanceEmbeds();
  $('#noteSrc').value = note.body;
  $('#noteSrc').hidden = true;
  $('#noteBody').hidden = false;
  $('#metaWords').textContent = note.words + ' words';
  $('#metaLinks').textContent = note.links_out + ' links out';
  $('#metaBack').textContent = note.backlinks.length + ' backlinks';
  mark('saved', 'Saved ' + fmtAgo(note.updated));
  $('#doc').scrollTop = 0;

  renderBacklinks(note.backlinks);
  renderGraphCrumb(note);
  renderTagRow(note);
  renderFavBtn(note);
  renderStudyChip(note);
  renderFlagChip(note);
  renderDeleteButton();
  document.querySelectorAll('#noteList .node').forEach((el) =>
    el.toggleAttribute('aria-current', el.dataset.slug === slug));
  drawMini();
}

/* Link suggestions moved out of the note panel into the Links tab. Reviewing
   them one note at a time hid the size of the queue, and there was nowhere to
   see or undo what you had already turned down. */

/* Study state for the open note. This is the "turn into study guide item"
   affordance: one button when the note isn't one, and the category with an
   inline correction when it is. */
/* Deletion is two-step rather than a modal: the first click arms it, the
   second commits, and it disarms itself after a few seconds. Notes go to
   vault/.trash rather than being unlinked, so this is recoverable. */
/* The other half of the flag: a question flagged in Crucible shows up here, on
   the note it belongs to, and clicking it drills just those questions. */
/* Tags are free-form: any letters/digits/-/_ , 2-40 chars, lowercased and
   space-collapsed to '-'. "study" is excluded — it's owned by the study
   toggle, and editing it here without also touching note.meta.study would
   desync the two. */
function normalizeTag(raw) {
  const t = raw.trim().toLowerCase().replace(/^#/, '').replace(/\s+/g, '-');
  return /^[\w-]{2,40}$/.test(t) ? t : null;
}

async function saveTags(tags) {
  try {
    const saved = await api('/notes/' + encodeURIComponent(state.slug), {
      method: 'PUT', body: JSON.stringify({ tags }),
    });
    state.note.tags = saved.tags;
    renderTagRow(state.note);
    loadList();
  } catch {
    toast('Could not update tags');
  }
}

function renderTagRow(note) {
  const host = $('#tagRow');
  if (!host) return;
  host.innerHTML = '';

  for (const t of note.tags) {
    const chip = document.createElement('span');
    chip.className = 'tag editable' + (t === 'study' ? ' locked' : '');
    const label = document.createElement('span');
    label.textContent = '#' + t;
    chip.appendChild(label);
    if (t === 'study') {
      chip.title = 'Managed by the study toggle above — remove it there.';
    } else {
      const x = document.createElement('button');
      x.className = 'tagx';
      x.type = 'button';
      x.textContent = '×';
      x.title = `Remove #${t}`;
      x.onclick = () => saveTags(note.tags.filter((o) => o !== t));
      chip.appendChild(x);
    }
    host.appendChild(chip);
  }

  const wrap = document.createElement('span');
  wrap.className = 'tagadd';
  const input = document.createElement('input');
  input.className = 'taginput';
  input.placeholder = note.tags.length ? '+ tag' : 'add a tag…';
  input.autocomplete = 'off';
  wrap.appendChild(input);

  const suggest = document.createElement('div');
  suggest.className = 'tagsuggest';
  suggest.hidden = true;
  wrap.appendChild(suggest);

  function closeSuggest() { suggest.hidden = true; suggest.innerHTML = ''; }

  function commit(raw) {
    if (!raw.trim()) return;
    const t = normalizeTag(raw);
    if (!t) { toast('Tags can only have letters, numbers, - and _'); return; }
    if (t === 'study') { toast('Use "Make study item" to add the study tag'); return; }
    input.value = '';
    closeSuggest();
    if (note.tags.some((o) => o.toLowerCase() === t)) return;
    saveTags([...note.tags, t]);
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); commit(input.value); }
    else if (e.key === 'Escape') { input.value = ''; closeSuggest(); }
  });
  // mousedown on a suggestion fires before the input's blur, so the click
  // still lands even though blur also closes the list.
  input.addEventListener('blur', () => setTimeout(closeSuggest, 150));
  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    suggest.innerHTML = '';
    if (!q) { closeSuggest(); return; }
    const options = allTags()
      .filter((t) => t.startsWith(q) && !note.tags.includes(t))
      .slice(0, 8);
    if (!options.length) { closeSuggest(); return; }
    for (const t of options) {
      const opt = document.createElement('div');
      opt.className = 'tagsuggest-item';
      opt.textContent = '#' + t;
      opt.onmousedown = (e) => { e.preventDefault(); commit(t); };
      suggest.appendChild(opt);
    }
    suggest.hidden = false;
  });

  host.appendChild(wrap);
}

function renderFlagChip(note) {
  const host = $('#flagChip');
  if (!host) return;
  host.innerHTML = '';
  const n = note.flags || 0;
  if (!n) return;
  const b = document.createElement('button');
  b.className = 'chipbtn flagged';
  b.innerHTML = `<span class="flagmark">⚑</span> ${n} flagged`;
  b.title = (note.flagged_questions || []).map((q) => '• ' + q.question).join('\n')
    + '\n\nClick to drill just these in Crucible';
  b.onclick = () => window.tephraStudy?.openFlagged(note.slug);
  host.appendChild(b);
}

/* Where the note sits, shown above its own heading rather than in the app
   header — so it travels with the note and is simply absent in Crucible. */
/* A one-line reminder of the note's group, sitting above the local graph so
   the panel says what you are looking at. */
function renderGraphCrumb(note) {
  const host = $('#graphCrumb');
  if (!host) return;
  const cat = ((note.meta || {}).category || '').trim();
  const prev = (note.category_history || [])[0];
  host.hidden = !cat;
  if (!cat) return;
  host.innerHTML = '';
  const now = document.createElement('span');
  now.className = 'gc-now';
  now.textContent = cat;
  host.appendChild(now);
  if (prev) {
    const was = document.createElement('span');
    was.className = 'gc-was';
    was.textContent = `was ${prev.category}`;
    was.title = `Moved from ${prev.category} ${fmtAgo(prev.at)}`;
    host.appendChild(was);
  }
}

function renderDocCrumb(note) {
  const host = $('#docCrumb');
  if (!host) return;
  host.innerHTML = '';
  const meta = note.meta || {};
  const category = (meta.category || '').trim();
  const parts = [];

  if (category) {
    parts.push({ label: category, target: category });
  } else if (note.tags?.length) {
    for (const t of note.tags.slice(0, 3)) parts.push({ label: '#' + t, tag: t });
  }
  host.hidden = !parts.length;
  if (!parts.length) return;

  parts.forEach((p, i) => {
    if (i) {
      const sep = document.createElement('span');
      sep.className = 'dc-sep';
      sep.textContent = '·';
      host.appendChild(sep);
    }
    const el = document.createElement('button');
    el.className = 'dc-part';
    el.textContent = p.label;
    if (p.tag) {
      el.title = `Show every note tagged #${p.tag}`;
      el.onclick = () => { state.tag = p.tag; renderList(); saveTheme(); };
    } else {
      // A category usually has an index note of the same name; link to it when
      // it exists, so this doubles as navigation rather than decoration.
      const idx = state.notes.find((n) => n.title.toLowerCase() === p.target.toLowerCase());
      if (idx) {
        el.title = `Open ${idx.title}`;
        el.onclick = () => openNote(idx.slug);
      } else {
        el.disabled = true;
      }
    }
    host.appendChild(el);
  });
}

function renderDeleteButton() {
  const host = $('#deleteChip');
  if (!host) return;
  host.innerHTML = '';
  let armed = false, timer = null;
  const b = document.createElement('button');
  b.className = 'chipbtn danger';
  b.textContent = 'Delete';
  b.title = 'Move this note to the vault trash';
  const disarm = () => {
    armed = false; b.textContent = 'Delete';
    b.classList.remove('armed'); clearTimeout(timer);
  };
  b.onclick = async () => {
    if (!armed) {
      armed = true;
      b.textContent = 'Delete — click again';
      b.classList.add('armed');
      timer = setTimeout(disarm, 4000);
      return;
    }
    disarm();
    const gone = state.slug, title = state.note?.title || gone;
    try {
      await api('/notes/' + encodeURIComponent(gone), { method: 'DELETE' });
    } catch {
      toast('Could not delete that');
      return;
    }
    state.dirty = false;                     // don't autosave a deleted note
    toast(`Moved “${title}” to the vault trash`);
    await loadList();
    await loadGraph();
    const next = state.notes.find((n) => n.slug !== gone);
    if (next) await openNote(next.slug);
    else {
      state.slug = null; state.note = null;
      $('#noteTitle').value = '';
      $('#docCrumb').hidden = true;
      $('#noteBody').innerHTML = '<p class="empty">No notes left. Create one.</p>';
    }
    window.tephraStudy?.refresh();
  };
  host.appendChild(b);
}

async function renderStudyChip(note) {
  const host = document.getElementById('studyChip');
  host.innerHTML = '';
  const meta = note.meta || {};
  const on = String(meta.study || '').toLowerCase() === 'true';
  // Unconditional: a note can carry category history from before it was
  // last disabled, and #trailChip is a persistent element that otherwise
  // keeps showing whatever the previously-open note left behind — the early
  // return below meant a plain, never-categorised note could still be
  // showing another note's "previously" trail.
  renderCategoryTrail(note);

  if (!on) {
    const wrap = document.createElement('span');
    wrap.className = 'studychip';

    const b = document.createElement('button');
    b.className = 'chipbtn';
    b.textContent = '+ Make study item';
    b.title = 'Add this note to the study guide and categorise it';
    b.onclick = async () => {
      b.disabled = true;
      b.textContent = 'Suggesting…';
      let guess, cats;
      try {
        [guess, cats] = await Promise.all([
          api(`/study/${state.slug}/suggest`),
          api('/study').then((d) => d.known_categories).catch(() => []),
        ]);
      } catch {
        toast('Could not get a suggestion');
        b.disabled = false;
        b.textContent = '+ Make study item';
        return;
      }
      showSuggestPanel(guess, cats);
    };
    wrap.appendChild(b);
    host.appendChild(wrap);

    // Shows the classifier's guess for confirmation rather than committing
    // it silently — the whole point of this panel is that nothing is written
    // until "Add to study guide" is clicked.
    function showSuggestPanel(guess, cats) {
      wrap.innerHTML = '';

      const label = document.createElement('span');
      label.className = 'chiplabel';
      // "content" means nothing in the vault or seed lexicon was a real
      // match, so this is a name pulled from the note's own wording, not a
      // probability — a percentage there would claim confidence that isn't real.
      label.textContent = !guess.category ? 'Study group'
        : guess.method === 'content' ? 'Suggested from this note’s own wording'
        : `Suggested${Number.isFinite(guess.confidence) ? `, ${Math.round(guess.confidence * 100)}% sure` : ''}`;
      wrap.appendChild(label);

      const input = document.createElement('input');
      input.className = 'chipinput';
      input.value = guess.category || '';
      input.placeholder = 'study group name';
      input.setAttribute('list', 'studyGroupSuggestions');
      wrap.appendChild(input);

      let dl = document.getElementById('studyGroupSuggestions');
      if (!dl) {
        dl = document.createElement('datalist');
        dl.id = 'studyGroupSuggestions';
        document.body.appendChild(dl);
      }
      dl.innerHTML = '';
      for (const c of cats || []) {
        const o = document.createElement('option');
        o.value = c;
        dl.appendChild(o);
      }

      const confirm = document.createElement('button');
      confirm.className = 'chipbtn';
      confirm.textContent = 'Add to study guide';
      confirm.onclick = async () => {
        confirm.disabled = true; cancel.disabled = true; input.disabled = true;
        try {
          const name = input.value.trim();
          const r = await api(`/study/${state.slug}/enable`, {
            method: 'POST', body: JSON.stringify(name ? { category: name } : {}),
          });
          const g = r.guess || {};
          toast(g.category
            ? `Added to ${g.category}${g.low_confidence ? ' — worth checking' : ''}`
            : 'Added — no category guess yet');
          await openNote(state.slug, false);
          window.tephraStudy?.refresh();
        } catch {
          toast('Could not add it');
          confirm.disabled = false; cancel.disabled = false; input.disabled = false;
        }
      };
      wrap.appendChild(confirm);

      const cancel = document.createElement('button');
      cancel.className = 'chipbtn';
      cancel.textContent = 'Cancel';
      cancel.onclick = () => renderStudyChip(note);
      wrap.appendChild(cancel);

      input.focus();
      input.select();
    }
    return;
  }

  const cat = (meta.category || '').trim();
  const source = (meta.category_source || 'auto').trim();
  const conf = parseFloat(meta.category_confidence);

  const wrap = document.createElement('span');
  wrap.className = 'studychip' + (source === 'auto' ? ' unsure' : '');

  const sel = document.createElement('select');
  sel.className = 'chipselect';
  let cats = [];
  try { cats = (await api('/study')).known_categories; } catch {}
  if (cat && !cats.includes(cat)) cats.unshift(cat);
  for (const c of cats) {
    const o = document.createElement('option');
    o.value = o.textContent = c;
    if (c === cat) o.selected = true;
    sel.appendChild(o);
  }
  const newOpt = document.createElement('option');
  newOpt.value = '__new__';
  newOpt.textContent = '+ New study group…';
  sel.appendChild(newOpt);

  async function applyCategory(to) {
    sel.disabled = true;
    try {
      const r = await api(`/study/${state.slug}/category`, {
        method: 'POST', body: JSON.stringify({ category: to }),
      });
      // Say what actually happened, not just that something did. "Moved X ->
      // Y" is the whole point of the revamp; a silent select told you nothing.
      toast(r.changed
        ? `Moved from ${r.from || 'no category'} to ${to} — the classifier learns from this`
        : `Already in ${to}`);
      await openNote(state.slug, false);
      window.tephraStudy?.refresh();
    } catch {
      toast('Could not change the category');
      sel.disabled = false;
    }
  }

  sel.onchange = () => {
    if (sel.value !== '__new__') { applyCategory(sel.value); return; }
    const input = document.createElement('input');
    input.className = 'chipinput';
    input.placeholder = 'new study group name';
    wrap.replaceChild(input, sel);
    input.focus();
    let done = false;
    const commit = () => {
      if (done) return;
      const name = input.value.trim();
      if (!name) { done = true; wrap.replaceChild(sel, input); return; }
      done = true;
      applyCategory(name);
    };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      else if (e.key === 'Escape') { done = true; wrap.replaceChild(sel, input); }
    });
    input.addEventListener('blur', commit);
  };

  const label = document.createElement('span');
  label.className = 'chiplabel';
  label.textContent = 'study group';
  wrap.appendChild(label);
  wrap.appendChild(sel);

  if (source === 'auto') {
    const tag = document.createElement('span');
    tag.className = 'chipflag';
    tag.textContent = Number.isFinite(conf) ? `guessed ${Math.round(conf * 100)}%` : 'guessed';
    tag.title = 'Tephra assigned this. Change it above if it is wrong — your correction teaches the classifier.';
    wrap.appendChild(tag);
  } else if (source === 'import') {
    const tag = document.createElement('span');
    tag.className = 'chipflag neutral';
    tag.textContent = 'from the guide';
    wrap.appendChild(tag);
  } else {
    const tag = document.createElement('span');
    tag.className = 'chipflag ok';
    tag.textContent = 'set by you';
    wrap.appendChild(tag);
  }
  host.appendChild(wrap);
}

/* Where this note has been, newest first, each entry one click from being
   restored. Lives under the chip so the change and its undo sit together. */
function renderCategoryTrail(note) {
  const host = $('#trailChip');
  if (!host) return;
  host.innerHTML = '';
  const trail = note.category_history || [];
  if (!trail.length) { host.hidden = true; return; }
  host.hidden = false;

  const line = document.createElement('div');
  line.className = 'trail';
  const head = document.createElement('span');
  head.className = 'trail-h';
  head.textContent = trail.length === 1 ? 'previously' : `previously (${trail.length})`;
  line.appendChild(head);

  for (const e of trail.slice(0, 4)) {
    const b = document.createElement('button');
    b.className = 'trail-item';
    b.innerHTML = `<span class="trail-cat"></span><span class="trail-when"></span>`;
    b.querySelector('.trail-cat').textContent = e.category;
    b.querySelector('.trail-when').textContent = fmtAgo(e.at);
    b.title = `Move it back to ${e.category}`
      + (e.source === 'auto' ? ' (it was a guess then, and will be again)' : '');
    b.onclick = async () => {
      b.disabled = true;
      try {
        const r = await api(`/study/${state.slug}/revert`, {
          method: 'POST', body: JSON.stringify({ category: e.category }),
        });
        toast(`Moved back to ${r.category}`
          + (r.restored_source === 'auto' ? ' — restored as a guess, not a correction' : ''));
        await openNote(state.slug, false);
        window.tephraStudy?.refresh();
      } catch {
        toast('Could not move it back');
        b.disabled = false;
      }
    };
    line.appendChild(b);
  }
  if (trail.length > 4) {
    const more = document.createElement('span');
    more.className = 'trail-more';
    more.textContent = `+${trail.length - 4} older`;
    more.title = trail.slice(4).map((e) => `${e.category} — ${fmtAgo(e.at)}`).join('\n');
    line.appendChild(more);
  }
  host.appendChild(line);
}

function renderBacklinks(list) {
  $('#backCount').textContent = list.length;
  const el = $('#backList');
  if (!list.length) { el.innerHTML = '<div class="empty">Nothing links here yet.</div>'; return; }
  el.innerHTML = '';
  for (const b of list) {
    const d = document.createElement('div');
    d.className = 'mention';
    d.innerHTML = '<div class="m-t"></div><div class="m-x"></div>';
    d.querySelector('.m-t').textContent = b.title;
    d.querySelector('.m-x').textContent = b.excerpt;
    d.onclick = () => openNote(b.slug);
    el.appendChild(d);
  }
}

/* ══ AUTOSAVE ════════════════════════════════════════════════
   Debounce while the keys are moving, flush hard on blur, on
   navigation and on tab-hide, so a note is never more than one
   keystroke behind what's on disk.
   ═══════════════════════════════════════════════════════════ */
const chip = $('#saveChip');
let saveT = null;

function mark(stateName, text) {
  chip.dataset.state = stateName;
  chip.innerHTML = '<i></i>' + text;
}

async function flush() {
  clearTimeout(saveT); saveT = null;
  if (!state.slug || !state.dirty) return;
  const payload = { title: $('#noteTitle').value.trim() || 'Untitled', body: $('#noteSrc').value };
  state.dirty = false;
  try {
    const saved = await api('/notes/' + encodeURIComponent(state.slug), {
      method: 'PUT', body: JSON.stringify(payload),
    });
    if (saved.renamed_to && saved.renamed_to !== state.slug) {
      state.slug = saved.renamed_to;
      location.hash = state.slug;
    }
    mark('saved', 'Saved just now');
    // The header names the vault, never the note. Writing the note title here
    // survived the move and quietly undid it on every autosave.
    document.title = saved.title + ' — Tephra';
    loadList();
    // Otherwise a phrase typed just now doesn't show up in Links until
    // something unrelated (a vault switch, a full reload) happens to poll
    // again -- the suggestion engine only sees what's on disk, and nothing
    // was telling it disk content had changed.
    window.tephraLinks?.poll();
  } catch (e) {
    state.dirty = true;
    mark('error', 'Not saved — retrying');
    setTimeout(flush, 3000);
  }
}

function touched() {
  state.dirty = true;
  if (!saveT) mark('saving', 'Saving…');
  clearTimeout(saveT);
  saveT = setTimeout(flush, 700);
}

function autoGrow(el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; }

$('#noteTitle').addEventListener('input', (e) => { autoGrow(e.target); touched(); });
$('#noteSrc').addEventListener('input', touched);
$('#noteTitle').addEventListener('blur', flush);
addEventListener('visibilitychange', () => { if (document.hidden) flush(); });
addEventListener('beforeunload', (e) => { if (state.dirty) { flush(); e.preventDefault(); e.returnValue = ''; } });

/* ══ EDIT MODE ═══════════════════════════════════════════════ */
async function setEditing(on) {
  if (on === state.editing) return;
  state.editing = on;
  $('#noteSrc').hidden = !on;
  $('#noteBody').hidden = on;
  $('#editHint').textContent = on
    ? '⌘E OR CLICK AWAY TO PREVIEW · [[LINK]] · ![[EMBED]] · DRAG FILES IN'
    : 'CLICK THE TEXT TO EDIT · ⌘E TOGGLES SOURCE · DRAG FILES IN TO ATTACH';
  if (on) {
    const ta = $('#noteSrc');
    ta.style.height = 'auto';
    ta.style.height = Math.max(ta.scrollHeight, 320) + 'px';
    ta.focus();
  } else {
    await flush();
    const note = await api('/notes/' + encodeURIComponent(state.slug));
    state.note = note;
    $('#noteBody').innerHTML = note.html || '<p class="empty">Empty note. Click here to start writing.</p>';
    enhanceEmbeds();
    $('#metaWords').textContent = note.words + ' words';
    $('#metaLinks').textContent = note.links_out + ' links out';
    $('#metaBack').textContent = note.backlinks.length + ' backlinks';
    renderBacklinks(note.backlinks);
      loadList();
    drawMini();
  }
}

$('#noteBody').addEventListener('click', (e) => {
  if (e.target.closest('a')) return;   // links win over entering edit mode
  if (e.target.closest('.embed-cap')) return;   // caption click/edit wins too
  // A resize drag's mouseup fires a click right after it, but targeted
  // wherever the pointer ended up -- usually over the image, not the handle
  // -- so this can't be caught by looking at the click's own target.
  if (Date.now() - lastResizeAt < 400) return;
  setEditing(true);
});
$('#noteSrc').addEventListener('blur', () => setEditing(false));

/* wikilink navigation, including creating the missing page */
$('#noteBody').addEventListener('click', async (e) => {
  const a = e.target.closest('a.wl');
  if (!a) return;
  e.preventDefault();
  if (a.dataset.slug) return openNote(a.dataset.slug);
  const title = a.dataset.title;
  const r = await api(`/notes/${encodeURIComponent(state.slug)}/resolve`, {
    method: 'POST', body: JSON.stringify({ title }),
  });
  toast(r.created ? `Created “${title}”` : `Opened “${title}”`);
  await loadList();
  openNote(r.slug);
});

/* ══ HOVER LENS ══════════════════════════════════════════════ */
const lensCache = new Map();
let lensT;
// Which anchor the pending lens belongs to. The open is delayed and may await
// a fetch, so by the time it resolves the pointer may have moved on, or the
// note may have been re-rendered out from under it.
let lensFor = null;

function hideLens() {
  clearTimeout(lensT);
  lensFor = null;
  const lens = $('#lens');
  lens.classList.remove('on');
  lens.style.setProperty('--lmx', 0);
  lens.style.setProperty('--lmy', 0);
}

// Tilts the lens toward wherever the cursor sits over the link that opened
// it (-1..1 on each axis) -- CSS turns this into a few degrees of rotation
// and a sheen that slides across the card. Scoped to whichever single link
// is currently hovered, so it can't repeat the old dynamic-glass mistake of
// several panels each tracking the pointer independently.
if (!reduce) {
  document.addEventListener('mousemove', (e) => {
    if (!lensFor) return;
    const r = lensFor.getBoundingClientRect();
    const nx = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width / 2 || 1)));
    const ny = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / (r.height / 2 || 1)));
    const lens = $('#lens');
    lens.style.setProperty('--lmx', nx.toFixed(3));
    lens.style.setProperty('--lmy', ny.toFixed(3));
  });
}

document.addEventListener('mouseover', async (e) => {
  const a = e.target.closest('a.wl');
  if (!a) return;
  clearTimeout(lensT);
  lensFor = a;
  lensT = setTimeout(async () => {
    const lens = $('#lens');
    let data;
    if (a.dataset.slug) {
      if (!lensCache.has(a.dataset.slug)) {
        try { lensCache.set(a.dataset.slug, await api('/notes/' + a.dataset.slug)); }
        catch { return; }
      }
      const n = lensCache.get(a.dataset.slug);
      data = {
        k: 'NOTE', t: n.title,
        b: n.body.replace(/[#*`>\[\]]/g, '').slice(0, 260) || 'This note is empty.',
        m: `${n.links_out} links · ${n.backlinks.length} backlinks · ${fmtAgo(n.updated)}`,
      };
    } else {
      data = { k: 'NOT WRITTEN YET', t: a.dataset.title, b: 'No page for this yet. Click the link and Tephra will create it.', m: 'stub' };
    }
    // The await above can outlast a click that re-renders the note. A detached
    // anchor measures as 0,0, which would park the lens in the corner with no
    // pointer anywhere near it to dismiss it again.
    if (lensFor !== a || !a.isConnected) return;
    $('#lensKind').textContent = data.k;
    $('#lensTitle').textContent = data.t;
    $('#lensBody').textContent = data.b;
    $('#lensMeta').textContent = data.m;
    const r = a.getBoundingClientRect();
    let L = r.left, Tp = r.bottom + 12;
    if (L + 340 > innerWidth) L = innerWidth - 346;
    if (Tp + 230 > innerHeight) Tp = r.top - 230;
    lens.style.left = L + 'px'; lens.style.top = Tp + 'px';
    lens.classList.add('on');
  }, 160);
});

document.addEventListener('mouseout', (e) => {
  if (e.target.closest('a.wl')) hideLens();
});

// mouseout is not enough on its own. Removing a hovered element does not fire
// it, so clicking a wiki link re-renders the note and strands the lens with
// nothing left able to dismiss it. Capture phase, so it runs before the
// handler that does the re-rendering.
document.addEventListener('click', hideLens, true);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideLens(); });
// The note body scrolls, not the window, and the lens is position:fixed --
// without this it detaches from the link it belongs to.
window.addEventListener('scroll', hideLens, true);
window.addEventListener('blur', hideLens);

/* ══ DRAG AND DROP MEDIA ═════════════════════════════════════ */
const editor = $('#editor');
['dragenter', 'dragover'].forEach((ev) => editor.addEventListener(ev, (e) => {
  e.preventDefault(); editor.classList.add('dragging');
}));
['dragleave', 'drop'].forEach((ev) => editor.addEventListener(ev, (e) => {
  if (ev === 'dragleave' && editor.contains(e.relatedTarget)) return;
  editor.classList.remove('dragging');
}));
editor.addEventListener('drop', async (e) => {
  e.preventDefault();
  const files = [...(e.dataTransfer?.files || [])];
  if (!files.length) return;
  await setEditing(true);
  for (const f of files) {
    toast(`Uploading ${f.name}…`, 8000);
    const fd = new FormData();
    fd.append('file', f);
    try {
      const m = await api('/media', { method: 'POST', body: fd });
      insertAtCursor($('#noteSrc'), `\n\n![[${m.name}]]\n\n`);
      touched();
      toast(`Attached ${m.name}`);
    } catch { toast(`Upload failed: ${f.name}`); }
  }
  await flush();
  loadMedia();
});

function insertAtCursor(ta, text) {
  const s = ta.selectionStart ?? ta.value.length;
  ta.value = ta.value.slice(0, s) + text + ta.value.slice(ta.selectionEnd ?? s);
  ta.selectionStart = ta.selectionEnd = s + text.length;
  ta.style.height = 'auto';
  ta.style.height = Math.max(ta.scrollHeight, 320) + 'px';
}

/* ══ IMAGE RESIZE ══════════════════════════════════════
   Corner-drag scaling for ![[embed]] figures. The rendered width lives in
   the markdown source itself (![[pic.png|400]], Obsidian's own convention
   for image width) rather than anywhere client-side, so it survives a
   reload and reads sanely if the note is ever opened outside Tephra.
   Mirrors app/render.py's own parsing so the Nth embed here is the Nth
   embed there. ═══════════════════════════════════════ */
const EMBED_RE_G = /!\[\[\s*([^\]|]+?)\s*(?:\|([^\]]*))?\]\]/g;
const EMBED_SIZE_RE = /^\d+%?$/;

function splitEmbedExtra(raw) {
  if (raw == null) return [null, null];
  if (raw.includes('|')) {
    const i = raw.lastIndexOf('|');
    const cap = raw.slice(0, i), size = raw.slice(i + 1).trim();
    if (EMBED_SIZE_RE.test(size)) return [cap || null, size];
    return [raw, null];
  }
  return EMBED_SIZE_RE.test(raw.trim()) ? [null, raw.trim()] : [raw, null];
}

function setEmbedWidth(body, index, widthPx) {
  let i = -1;
  return body.replace(EMBED_RE_G, (whole, name, extra) => {
    i++;
    if (i !== index) return whole;
    const [caption] = splitEmbedExtra(extra);
    const fields = [name.trim()];
    if (caption) fields.push(caption);
    fields.push(String(widthPx));
    return `![[${fields.join('|')}]]`;
  });
}

function setEmbedCaption(body, index, caption) {
  let i = -1;
  return body.replace(EMBED_RE_G, (whole, name, extra) => {
    i++;
    if (i !== index) return whole;
    const [, size] = splitEmbedExtra(extra);
    const fields = [name.trim()];
    if (caption) fields.push(caption);
    if (size) fields.push(size);
    return `![[${fields.join('|')}]]`;
  });
}

/* Reordering works on the same "rows are adjacent lines" structure
   app/render.py's own grouping is built on: parse the body into groups of
   embeds (each group = one row, or a lone standalone embed) with the
   arbitrary text between groups kept verbatim, move one embed by its stable
   id, then rejoin. Group members are tracked by id rather than position so
   a move is never ambiguous even when two embeds share the same filename. */
function parseEmbedGroups(body) {
  const matches = [...body.matchAll(EMBED_RE_G)];
  if (!matches.length) return { fillers: [body], groups: [] };
  const fillers = [body.slice(0, matches[0].index)];
  const groups = [[{ id: 0, text: matches[0][0] }]];
  let cursor = matches[0].index + matches[0][0].length;
  for (let i = 1; i < matches.length; i++) {
    const m = matches[i];
    const gap = body.slice(cursor, m.index);
    if (/^[ \t]*\n?[ \t]*$/.test(gap)) {
      groups[groups.length - 1].push({ id: i, text: m[0] });
    } else {
      fillers.push(gap);
      groups.push([{ id: i, text: m[0] }]);
    }
    cursor = m.index + m[0].length;
  }
  fillers.push(body.slice(cursor));
  return { fillers, groups };
}

function assembleEmbedGroups(fillers, groups) {
  let out = fillers[0] || '';
  for (let i = 0; i < groups.length; i++) {
    out += groups[i].map((e) => e.text).join('\n') + (fillers[i + 1] || '');
  }
  // Leading/trailing whitespace only -- matches what vault.dump() already
  // does to every note on save regardless of how it was edited, so this
  // isn't introducing new behavior, just not waiting for a round trip to see it.
  return out.trim();
}

function moveEmbed(body, fromIdx, toIdx, side) {
  const { fillers, groups } = parseEmbedGroups(body);
  let fromGroupI = -1, fromPosI = -1, toGroupI = -1, toPosI = -1;
  for (let gi = 0; gi < groups.length; gi++) {
    for (let pi = 0; pi < groups[gi].length; pi++) {
      if (groups[gi][pi].id === fromIdx) { fromGroupI = gi; fromPosI = pi; }
      if (groups[gi][pi].id === toIdx) { toGroupI = gi; toPosI = pi; }
    }
  }
  if (fromGroupI === -1 || toGroupI === -1 || fromIdx === toIdx) return body;

  const [moved] = groups[fromGroupI].splice(fromPosI, 1);
  // Removing an earlier member of the *same* group shifts every later
  // position left by one, so the target position captured before the splice
  // is now stale.
  if (fromGroupI === toGroupI && fromPosI < toPosI) toPosI -= 1;

  if (groups[fromGroupI].length === 0) {
    // The source's row is gone -- close the gap by merging the filler text
    // that used to sit on either side of it into one. Collapsed to at most
    // one blank line so the merge itself can't stack up extra blank lines;
    // scoped to just this junction, not a blanket rewrite of the whole note.
    const merged = ((fillers[fromGroupI] || '') + (fillers[fromGroupI + 1] || '')).replace(/\n{3,}/g, '\n\n');
    fillers.splice(fromGroupI, 2, merged);
    groups.splice(fromGroupI, 1);
    if (fromGroupI < toGroupI) toGroupI -= 1;
  }

  groups[toGroupI].splice(side === 'before' ? toPosI : toPosI + 1, 0, moved);
  return assembleEmbedGroups(fillers, groups);
}

async function commitEmbedMove(fromIdx, toIdx, side) {
  if (!state.note) return;
  const newBody = moveEmbed(state.note.body, fromIdx, toIdx, side);
  if (newBody === state.note.body) return;
  state.note.body = newBody;
  $('#noteSrc').value = newBody;
  state.dirty = true;
  await flush();
  // A reorder restructures the DOM (rows gained or lost a member) rather
  // than tweaking one figure's own style in place, so -- unlike a resize --
  // this re-renders from the server's own layout logic instead of trying to
  // reproduce app/render.py's grouping rules a second time in JS.
  const note = await api('/notes/' + encodeURIComponent(state.slug));
  state.note = note;
  $('#noteBody').innerHTML = note.html || '<p class="empty">Empty note. Click here to start writing.</p>';
  enhanceEmbeds();
}

/* Handles are injected client-side rather than rendered server-side: they
   are pure UI chrome, only relevant while looking at the live preview, and
   keeping them out of app/render.py keeps the saved HTML (and the note
   shown to a viewer who never touches Tephra) free of them. */
function enhanceEmbeds() {
  for (const fig of $('#noteBody').querySelectorAll('.embed[data-kind="image"]')) {
    // The browser's own image drag-and-drop sits right under the handles
    // (they're positioned on top of the <img>) and, left alone, wins the
    // gesture: mousemove mostly stops firing once a native drag starts, so
    // the resize captures only a sliver of the drag before it's cut short.
    // Reordering below uses the *figure* as the native drag source instead,
    // which the image opting out here lets the browser fall back to.
    const img = fig.querySelector('img');
    if (img) {
      img.draggable = false;
      img.addEventListener('dragstart', (e) => e.preventDefault());
    }
    if (!fig.querySelector('.embed-handle')) {
      for (const corner of ['nw', 'ne', 'sw', 'se']) {
        const h = document.createElement('span');
        h.className = `embed-handle ${corner}`;
        h.addEventListener('mousedown', (e) => startResize(e, fig, corner));
        fig.appendChild(h);
      }
    }
    const capText = fig.querySelector('.embed-cap-text');
    if (capText && !capText.dataset.captionWired) {
      capText.dataset.captionWired = '1';
      capText.addEventListener('click', (e) => {
        // Not just tidiness: starting the edit replaces capText with an
        // <input>, detaching capText from the tree before this event finishes
        // bubbling -- the #noteBody handler's `closest('.embed-cap')` guard
        // can't find an ancestor from a detached node, so without this it'd
        // still call setEditing(true), which focuses #noteSrc and blurs the
        // input away before a single character gets typed.
        e.stopPropagation();
        startCaptionEdit(fig, capText);
      });
    }
    if (fig.dataset.reorderWired) continue;
    fig.dataset.reorderWired = '1';
    fig.draggable = true;
    fig.addEventListener('dragstart', (e) => {
      // A resize handle already preventDefault()s its own mousedown, which
      // should already stop native drag from starting on it -- this is a
      // second line of defense, not the primary guard. The caption text is
      // a click target of its own (to edit it, or just to place a cursor in
      // it), and a native figure-drag starting underneath it would hijack
      // that gesture into a reorder instead.
      if (e.target.closest('.embed-handle')) { e.preventDefault(); return; }
      if (e.target.closest('.embed-cap-text, .embed-cap-input')) { e.preventDefault(); return; }
      e.dataTransfer.setData('text/plain', String(fig.dataset.embedIndex));
      e.dataTransfer.effectAllowed = 'move';
      fig.classList.add('dragging');
    });
    fig.addEventListener('dragend', () => {
      fig.classList.remove('dragging');
      for (const f of $('#noteBody').querySelectorAll('.drop-before,.drop-after')) {
        f.classList.remove('drop-before', 'drop-after');
      }
    });
    fig.addEventListener('dragover', (e) => {
      e.preventDefault();
      const before = dropSide(e, fig) === 'before';
      fig.classList.toggle('drop-before', before);
      fig.classList.toggle('drop-after', !before);
    });
    fig.addEventListener('dragleave', (e) => {
      if (fig.contains(e.relatedTarget)) return;   // still inside, e.g. over the caption
      fig.classList.remove('drop-before', 'drop-after');
    });
    fig.addEventListener('drop', (e) => {
      e.preventDefault();
      fig.classList.remove('drop-before', 'drop-after');
      const fromIdx = Number(e.dataTransfer.getData('text/plain'));
      const toIdx = Number(fig.dataset.embedIndex);
      if (Number.isNaN(fromIdx) || Number.isNaN(toIdx) || fromIdx === toIdx) return;
      commitEmbedMove(fromIdx, toIdx, dropSide(e, fig));
    });
  }
}

function dropSide(e, fig) {
  const r = fig.getBoundingClientRect();
  return (e.clientX - r.left) < r.width / 2 ? 'before' : 'after';
}

/* ══ IMAGE CAPTION ═════════════════════════════════════
   Click the caption bar to edit it in place. Swaps in a real <input> rather
   than making the span contenteditable -- one less cross-browser paste/
   Enter-inserts-<br> surface to deal with, and it's the same pattern
   #noteTitle already uses. The caption lives in the ![[name|caption|size]]
   source, same as width does, so it survives reload and reads sanely
   outside Tephra. ═══════════════════════════════════════ */
function startCaptionEdit(fig, capText) {
  const original = capText.dataset.caption || '';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'embed-cap-input';
  input.value = original;
  input.placeholder = 'Add a caption…';
  capText.replaceWith(input);
  input.focus();
  input.select();

  const finish = (save) => {
    input.removeEventListener('blur', onBlur);
    input.removeEventListener('keydown', onKeydown);
    if (save) commitCaption(fig, capText, input.value.trim());
    else capText.textContent = original || capText.dataset.fallback || '';
    input.replaceWith(capText);
  };
  function onBlur() { finish(true); }
  function onKeydown(e) {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  }
  input.addEventListener('blur', onBlur);
  input.addEventListener('keydown', onKeydown);
}

function commitCaption(fig, capText, newCaption) {
  capText.dataset.caption = newCaption;
  capText.textContent = newCaption || capText.dataset.fallback || '';
  if (!state.note) return;
  const idx = Number(fig.dataset.embedIndex);
  if (Number.isNaN(idx)) return;
  const newBody = setEmbedCaption(state.note.body, idx, newCaption);
  if (newBody === state.note.body) return;
  state.note.body = newBody;
  $('#noteSrc').value = newBody;
  touched();
}

let resizeState = null;
// A resize ends with a mouseup, which the browser follows with a synthesized
// click -- but targeted whereever the pointer physically ended up (usually
// over the image itself after a real drag, not the handle), so a click-target
// check can't reliably catch it. This is checked by timestamp instead, in
// the #noteBody click handler below.
let lastResizeAt = 0;

function startResize(e, fig, corner) {
  e.preventDefault();
  e.stopPropagation();
  fig.classList.add('resizing', 'sized');
  // Otherwise dragging across the note body selects its text on the way,
  // which both looks wrong and can itself derail the drag in some browsers.
  document.body.classList.add('resize-live');
  resizeState = {
    fig, corner, startX: e.clientX, slug: state.slug,
    startW: fig.getBoundingClientRect().width,
    minW: 60,
    maxW: (fig.parentElement || fig).clientWidth || fig.getBoundingClientRect().width,
  };
  document.addEventListener('mousemove', onResizeMove);
  document.addEventListener('mouseup', onResizeUp);
}

function onResizeMove(e) {
  if (!resizeState) return;
  const { fig, corner, startX, startW, minW, maxW } = resizeState;
  // A left-side corner (nw/sw) grows the image as the pointer moves away to
  // the left; a right-side corner (ne/se) grows it moving right. Either way
  // this only ever touches width -- height follows on its own since the
  // <img> keeps height:auto, so the drag can't distort the aspect ratio.
  const dir = (corner === 'nw' || corner === 'sw') ? -1 : 1;
  const dx = (e.clientX - startX) * dir;
  resizeState.lastW = Math.max(minW, Math.min(maxW, Math.round(startW + dx)));
  fig.style.width = resizeState.lastW + 'px';
}

async function onResizeUp() {
  document.removeEventListener('mousemove', onResizeMove);
  document.removeEventListener('mouseup', onResizeUp);
  document.body.classList.remove('resize-live');
  if (!resizeState) return;
  const { fig, slug, startW, lastW } = resizeState;
  resizeState = null;
  // The mouseup that ends a drag is always followed by a synthesized click,
  // wherever the pointer physically landed -- almost never still over the
  // handle after a real drag -- so the #noteBody click handler suppresses
  // by recency instead of by checking that click's target.
  lastResizeAt = Date.now();
  fig.classList.remove('resizing');
  // A note switch mid-drag (e.g. a keyboard shortcut while the button is
  // still down) must not write this resize into whatever note is open now.
  if (!fig.isConnected || state.slug !== slug || !state.note) return;
  // The width from the last move, not a fresh getBoundingClientRect() read --
  // that would depend on a reflow happening to already reflect the inline
  // style just set, which is a needless thing to depend on when the value is
  // already in hand.
  const w = lastW ?? Math.round(startW);
  const idx = Number(fig.dataset.embedIndex);
  if (Number.isNaN(idx)) return;
  const newBody = setEmbedWidth(state.note.body, idx, w);
  if (newBody === state.note.body) return;
  state.note.body = newBody;
  $('#noteSrc').value = newBody;
  touched();
}

/* ══ GRAPH ══════════════════════════════════════
   The full vault graph lives in graph.js. The old shared engine ran
   full-strength forces every frame forever, so it never settled and
   nodes were a moving target. Only the small local-graph thumbnail
   is drawn here, and it stops as soon as it comes to rest.
   ═════════════════════════════════════════════ */
let graphData = { nodes: [], links: [] };

async function loadGraph() {
  graphData = await api('/graph');
  $('#orbitCount').textContent = graphData.nodes.length + ' nodes';
}

function miniGraph(canvas) {
  const ctx = canvas.getContext && canvas.getContext('2d');
  if (!ctx) return { redraw() {} };
  let sim = null, frame = null, nodes = [], links = [], sig = '';

  function build() {
    const cur = graphData.nodes.findIndex((n) => n.slug === state.slug);
    if (cur < 0) { nodes = []; links = []; return; }
    const keep = new Set([cur]);
    for (const [a, b] of graphData.links) {
      if (a === cur) keep.add(b);
      if (b === cur) keep.add(a);
    }
    const list = [...keep].slice(0, 40);
    const remap = new Map(list.map((v, i) => [v, i]));
    nodes = list.map((i) => ({ ...graphData.nodes[i], self: i === cur }));
    links = graphData.links
      .filter(([a, b]) => remap.has(a) && remap.has(b))
      .map(([a, b]) => [remap.get(a), remap.get(b)]);
    const I = window.__tephraGraphInternals;
    sim = I ? I.createSim(nodes, links, { linkDistance: 120, charge: -2600 }) : null;
  }

  function paint() {
    const dpr = devicePixelRatio || 1;
    const r = canvas.getBoundingClientRect();
    if (canvas.width !== Math.round(r.width * dpr)) {
      canvas.width = Math.round(r.width * dpr);
      canvas.height = Math.round(r.height * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, r.width, r.height);
    const I = window.__tephraGraphInternals;
    if (!nodes.length || !I) return;
    const k = Math.min(r.width / (I.W + 200), r.height / (I.H + 200));
    const tx = (r.width - I.W * k) / 2, ty = (r.height - I.H * k) / 2;
    const P = (d) => [d.x * k + tx, d.y * k + ty];
    ctx.strokeStyle = 'rgba(255,255,255,.14)';
    ctx.lineWidth = 1;
    for (const [a, b] of links) {
      const [ax, ay] = P(nodes[a]), [bx, by] = P(nodes[b]);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    }
    for (const d of nodes) {
      const [x, y] = P(d);
      const col = d.kind === 'stub' ? '255,157,110' : T.acc;
      const rr = d.self ? 6 : 3.6;
      const g = ctx.createRadialGradient(x, y, 0, x, y, rr * 3.2);
      g.addColorStop(0, `rgba(${col},.5)`); g.addColorStop(1, `rgba(${col},0)`);
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, rr * 3.2, 0, 7); ctx.fill();
      ctx.fillStyle = `rgba(${col},.95)`;
      ctx.beginPath(); ctx.arc(x, y, rr, 0, 7); ctx.fill();
      ctx.strokeStyle = d.self ? '#fff' : 'rgba(255,255,255,.5)';
      ctx.lineWidth = d.self ? 2 : 1;
      ctx.beginPath(); ctx.arc(x, y, rr, 0, 7); ctx.stroke();
    }
  }

  function loop() {
    if (sim && sim.running() && !reduce) { sim.tick(); paint(); frame = requestAnimationFrame(loop); }
    else { paint(); frame = null; }
  }

  return {
    redraw() {
      const s = state.slug + ':' + graphData.nodes.length + ':' + graphData.links.length;
      if (s !== sig) { sig = s; build(); }
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(loop);
    },
  };
}

let mini = null;
function drawMini() { if (mini) mini.redraw(); }

/* ══ VIEW TOGGLE ═════════════════════════════════════════════ */
const gv = $('#graphview');
/* Write and Graph are the two canvas modes and share the segmented control.
   Crucible is an overlay on top of whichever one is active, so it has its own
   button and its own pressed state rather than competing for that slot. */
/* Tephra and Crucible are two sides of one deck. Clicking Tephra does not
   change which canvas mode is active underneath — it just brings that side
   back — so you can leave Crucible and land where you were. */
function setStudy(on) {
  $('#crucibleBtn')?.setAttribute('aria-pressed', String(!!on));
  $('#tephraBtn')?.setAttribute('aria-pressed', String(!on));
  if (on) window.tephraStudy?.open();
  else window.tephraStudy?.close();
}

function setView(v) {
  if (v === 'study') return setStudy(!window.tephraStudy?.isOpen());
  setStudy(false);
  document.querySelectorAll('.segmented button').forEach((b) =>
    b.setAttribute('aria-pressed', b.dataset.view === v));
  gv.classList.toggle('on', v === 'graph');
  if (v === 'graph') window.tephraGraph.open();
  else window.tephraGraph?.close();
  if (v === 'links') window.tephraLinks?.open();
  else window.tephraLinks?.close();
}
document.querySelectorAll('[data-view]').forEach((b) => (b.onclick = () => setView(b.dataset.view)));
$('#noteSort').onchange = (e) => { state.sort = e.target.value; renderList(); saveTheme(); };
$('#tagClear').onclick = () => { state.tag = ''; renderList(); saveTheme(); };
$('#favBtn').onclick = () => { if (state.slug) toggleFavorite(state.slug); };
$('#tephraBtn').onclick = () => setStudy(false);
$('#crucibleBtn').onclick = () => setStudy(true);
$('#gvClose').onclick = () => setView('write');
$('#orbit').onclick = () => setView('graph');


/* ══ COMMAND PALETTE ═════════════════════════════════════════ */
const pal = $('#palette'), scrim = $('#scrim'), pInput = $('#pInput'), pList = $('#pList');
let sel = 0, results = [];

async function renderPalette(q) {
  q = q.trim();
  results = q
    ? (await api('/search?q=' + encodeURIComponent(q))).map((r) => ({ ...r, kind: 'note' }))
    : state.notes.slice(0, 12).map((n) => ({ slug: n.slug, title: n.title, snippet: fmtAgo(n.updated), kind: 'note' }));
  if (q && !results.some((r) => r.title.toLowerCase() === q.toLowerCase())) {
    results.push({ kind: 'create', title: q, snippet: 'Create this note' });
  }
  sel = Math.min(sel, Math.max(results.length - 1, 0));
  pList.innerHTML = results.map((r, i) =>
    `<div class="pitem" ${i === sel ? 'data-sel' : ''}>
       <span class="pk">${r.kind === 'create' ? 'NEW' : '↵'}</span>
       <span class="pt">${escapeHtml(r.title)}</span>
       <span class="parrow">${escapeHtml(r.snippet || '')}</span>
     </div>`).join('') || '<div class="pitem" style="color:var(--faint)">No matches</div>';
  [...pList.children].forEach((el, i) => (el.onclick = () => choose(i)));
}
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function choose(i) {
  const r = results[i];
  if (!r) return;
  closePal();
  if (r.kind === 'create') {
    const n = await api('/notes', { method: 'POST', body: JSON.stringify({ title: r.title }) });
    await loadList();
    openNote(n.slug);
    setEditing(true);
  } else openNote(r.slug);
}
function openPal() { scrim.classList.add('on'); pal.classList.add('on'); pInput.value = ''; sel = 0; renderPalette(''); pInput.focus(); }
function closePal() { scrim.classList.remove('on'); pal.classList.remove('on'); }
$('#openPalette').onclick = openPal;
scrim.onclick = closePal;
let searchT;
pInput.oninput = (e) => { clearTimeout(searchT); searchT = setTimeout(() => renderPalette(e.target.value), 120); };

/* ══ KEYBOARD ════════════════════════════════════════════════ */
addEventListener('keydown', (e) => {
  const k = e.key.toLowerCase();
  const mod = e.metaKey || e.ctrlKey;
  if (mod && k === 'k') { e.preventDefault(); openPal(); return; }
  if (mod && k === 's') { e.preventDefault(); flush(); toast('Saved — autosave is always on'); return; }
  if (mod && k === 'e') { e.preventDefault(); setEditing(!state.editing); return; }
  if (e.key === 'Escape') {
    closePal();
    // Close the topmost thing only, so Escape doesn't also dump you out of
    // Graph on the way past.
    if (window.tephraStudy?.isOpen()) return setStudy(false);
    if (vaultsEl().classList.contains('on')) return vaultsEl().classList.remove('on');
    if ($('#theme').classList.contains('on')) return $('#theme').classList.remove('on');
    setView('write');
  }
  if (pal.classList.contains('on')) {
    const n = results.length;
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = (sel + 1) % n; renderPalette(pInput.value); }
    if (e.key === 'ArrowUp') { e.preventDefault(); sel = (sel - 1 + n) % n; renderPalette(pInput.value); }
    if (e.key === 'Enter') { e.preventDefault(); choose(sel); }
    return;
  }
  if (e.altKey && k === 'g') { e.preventDefault(); setView('graph'); }
  if (e.altKey && k === 'd') { e.preventDefault(); setView('study'); }
  if (e.altKey && k === 't') { e.preventDefault(); $('#theme').classList.toggle('on'); }
  if (e.altKey && k === 'v') { e.preventDefault(); $('#vaultBtn').click(); }
  if (e.altKey && k === 'n') { e.preventDefault(); $('#newNote').click(); }
});

$('#newNote').onclick = async () => {
  const n = await api('/notes', { method: 'POST', body: JSON.stringify({ title: 'Untitled' }) });
  await loadList();
  await openNote(n.slug);
  $('#noteTitle').focus();
  $('#noteTitle').select();
};

/* ══ THEME DRAWER WIRING ═════════════════════════════════════ */
$('#themeBtn').onclick = () => $('#theme').classList.toggle('on');
$('#themeClose').onclick = () => $('#theme').classList.remove('on');
document.querySelectorAll('.wallopt[data-wall]').forEach((o) => (o.onclick = () => {
  const patch = { wall: o.dataset.wall };
  if (T.auto && o.dataset.acc) patch.acc = o.dataset.acc;
  setTheme(patch);
}));
$('#wallUp').onclick = () => $('#wallFile').click();
$('#wallFile').onchange = async (e) => {
  const f = e.target.files?.[0];
  if (!f) return;
  e.target.value = '';
  toast('Uploading wallpaper…', 8000);
  const fd = new FormData();
  fd.append('file', f);
  const m = await api('/media', { method: 'POST', body: fd });
  const im = new Image();
  im.onload = () => {
    const patch = { wall: 'custom', wallUrl: m.url };
    if (T.auto) { const a = accentFrom(im); if (a) patch.acc = a; }
    setTheme(patch);
    toast('Wallpaper saved to your vault');
  };
  im.src = m.url;
};
document.querySelectorAll('.sw[data-acc]').forEach((s) => (s.onclick = () => setTheme({ acc: s.dataset.acc, auto: false })));
$('#accPick').oninput = (e) => setTheme({ acc: rgb(e.target.value), auto: false });
$('#autoAcc').onclick = () => setTheme({ auto: !T.auto });
[['rContrast', 'contrast'], ['rSat', 'sat'], ['rBlur', 'blur'], ['rFrost', 'frost'], ['rScrim', 'scrim'], ['rInset', 'inset'], ['rRadius', 'radius'], ['rShine', 'shine']]
  .forEach(([id, key]) => ($('#' + id).oninput = (e) => setTheme({ [key]: +e.target.value })));
[['fontDisplay', 'font_display'], ['fontSerif', 'font_serif'], ['fontMono', 'font_mono']].forEach(([id, key]) => {
  $('#' + id).querySelectorAll('.fopt').forEach((o) => (o.onclick = () => setTheme({ [key]: o.dataset.font })));
});
$('#thReset').onclick = () => setTheme({ ...DEFAULTS, wallUrl: T.wallUrl });

/* ══ VAULTS ═════════════════════════════════════
   Switching vault repoints the server and rebuilds its index, so the whole
   client state has to be reloaded afterwards — theme included, since theme
   lives inside the vault.
   ═════════════════════════════════════════════ */
const vaultsEl = () => $('#vaults');

async function showVaultName() {
  try {
    const v = await api('/vault/info');
    const name = String(v.vault).split('/').filter(Boolean).pop() || v.vault;
    $('#crumbTitle').textContent = name;
    $('#vaultCrumb').title = v.vault + ' — click to switch vaults';
  } catch {}
}

async function renderVaults() {
  let data;
  try { data = await api('/vault/list'); } catch { return; }
  const box = $('#vaultList');
  box.innerHTML = '';
  $('#renameRow').hidden = true;
  for (const v of data.recent) {
    const row = document.createElement('button');
    row.className = 'vaultrow' + (v.current ? ' current' : '') + (v.exists ? '' : ' missing');
    const name = v.path.split('/').filter(Boolean).pop() || v.path;
    row.innerHTML = `<span class="vaultname"></span><span class="vaultpath"></span>`;
    row.querySelector('.vaultname').textContent = name + (v.current ? ' · open' : '');
    row.querySelector('.vaultpath').textContent = v.path;
    row.disabled = v.current;
    if (!v.exists) row.title = 'This folder no longer has a notes/ directory';
    row.onclick = () => switchVault('/vault/open', v.path);
    box.appendChild(row);
    if (v.current) {
      // Rename is offered only for the open vault: renaming one the app is not
      // serving would need a second index to be closed and reopened for no
      // real gain.
      const ren = document.createElement('button');
      ren.className = 'vaultrename';
      ren.textContent = 'Rename this vault';
      ren.onclick = (e) => {
        e.stopPropagation();
        $('#renameRow').hidden = false;
        $('#renameInput').value = name;
        $('#renameInput').focus();
        $('#renameInput').select();
      };
      box.appendChild(ren);
    } else {
      // Forgetting only makes sense for a vault the app isn't currently
      // serving. It drops the recents entry, not the folder — the vault is
      // still on disk and reopening it (by path, or via Browse) adds it
      // right back.
      const forget = document.createElement('button');
      forget.className = 'vaultforget';
      forget.textContent = 'Remove from this list';
      forget.title = 'Forgets this vault here only — the folder is untouched';
      forget.onclick = async (e) => {
        e.stopPropagation();
        try {
          await api('/vault/forget', { method: 'POST', body: JSON.stringify({ path: v.path }) });
          toast(`Removed ${name} from the list`);
          await renderVaults();
        } catch (err) {
          let detail = String((err && err.message) || err);
          try { detail = JSON.parse(detail).detail || detail; } catch {}
          toast(detail.slice(0, 160), 6000);
        }
      };
      box.appendChild(forget);
    }
  }
}

async function switchVault(endpoint, path, msgEl = $('#vaultMsg')) {
  msgEl.textContent = 'Switching…';
  try {
    const r = await api(endpoint, { method: 'POST', body: JSON.stringify({ path }) });
    // Theme is per-vault, so re-read it rather than carrying the old one over.
    try { T = { ...DEFAULTS, ...(await api('/theme')) }; } catch {}
    state.sort = SORTS[T.note_sort] ? T.note_sort : 'updated';
    state.tag = T.note_tag || '';
    state.slug = null; state.note = null; state.dirty = false;
    applyTheme();
    await loadList();
    await loadGraph();
    await loadMedia();
    if (state.notes[0]) await openNote(state.notes[0].slug, false);
    await renderVaults();
    await showVaultName();
  window.tephraLinks?.poll();
    window.tephraStudy?.refresh();
    msgEl.textContent = `Now in ${r.vault}` + (r.created ? ' (new)' : '');
    toast(r.created ? `Created vault at ${r.vault}` : `Opened ${r.vault}`);
    return true;
  } catch (e) {
    let detail = String((e && e.message) || e);
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    msgEl.textContent = detail;
    toast(detail.slice(0, 160), 6000);
    return false;
  }
}

async function doRename() {
  const name = $('#renameInput').value.trim();
  const msg = $('#vaultMsg');
  if (!name) { msg.textContent = 'Type a folder name first.'; return; }
  msg.textContent = 'Renaming…';
  try {
    const r = await api('/vault/rename', { method: 'POST', body: JSON.stringify({ name }) });
    $('#renameRow').hidden = true;
    await renderVaults();
    await showVaultName();
  window.tephraLinks?.poll();
    msg.textContent = `Vault folder is now ${r.name}`;
    toast(`Renamed to ${r.name}`);
  } catch (e) {
    let detail = String((e && e.message) || e);
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    msg.textContent = detail;
    toast(detail.slice(0, 160), 6000);
  }
}
$('#renameSave').onclick = doRename;
$('#renameCancel').onclick = () => { $('#renameRow').hidden = true; };
$('#renameInput').onkeydown = (e) => {
  if (e.key === 'Enter') doRename();
  if (e.key === 'Escape') { e.stopPropagation(); $('#renameRow').hidden = true; }
};

$('#vaultCrumb').onclick = () => $('#vaultBtn').click();
$('#vaultBtn').onclick = () => {
  vaultsEl().classList.toggle('on');
  $('#theme').classList.remove('on');
  if (vaultsEl().classList.contains('on')) showVaultHome();
};
$('#vaultClose').onclick = () => vaultsEl().classList.remove('on');

/* The drawer is three panes, only one visible at a time: the Recent Vaults
   home, an Open-existing browser, and a Create wizard. Reopening the drawer
   always lands back on the home pane, so a half-finished create/open never
   lingers as confusing state the next time it's opened. */
function showVaultHome() {
  $('#vaultHome').hidden = false;
  $('#vaultOpenPane').hidden = true;
  $('#vaultWizard').hidden = true;
  renderVaults();
}
function showVaultOpenPane() {
  $('#vaultHome').hidden = true;
  $('#vaultOpenPane').hidden = false;
  $('#vaultWizard').hidden = true;
  $('#vaultOpenMsg').textContent = '';
  $('#vaultPathInput').value = '';
  openBrowser.render();
}
function showVaultWizard() {
  $('#vaultHome').hidden = true;
  $('#vaultOpenPane').hidden = true;
  $('#vaultWizard').hidden = false;
  $('#vaultWizMsg').textContent = '';
  wizState = { parent: null, entries: [], fullPath: null };
  $('#wizName').value = '';
  $('#wizPathInput').value = '';
  goWizStep(1);
  wizBrowser.render();
}
$('#vaultGoOpen').onclick = showVaultOpenPane;
$('#vaultOpenBack').onclick = showVaultHome;
$('#vaultGoCreate').onclick = showVaultWizard;
$('#vaultWizBack').onclick = showVaultHome;

/* Directory browser, scoped server-side to vault.browse_root() (parent of the
   current vault, by default). Shared by the Open pane and the wizard's
   location step — each gets its own instance so browsing one never disturbs
   the other's position. */
function makeBrowser({ listEl, pathEl, upBtn, onPick }) {
  let at = { path: null, parent: null, entries: [] };
  async function render(path) {
    listEl.textContent = 'Loading…';
    let data;
    try {
      data = await api('/vault/browse' + (path ? `?path=${encodeURIComponent(path)}` : ''));
    } catch (e) {
      let detail = String((e && e.message) || e);
      try { detail = JSON.parse(detail).detail || detail; } catch {}
      listEl.textContent = detail;
      return;
    }
    at = { path: data.path, parent: data.parent, entries: data.entries };
    pathEl.textContent = data.path;
    upBtn.disabled = data.parent === data.path;
    listEl.innerHTML = '';
    if (!data.entries.length) {
      listEl.innerHTML = '<div class="th-note">No subfolders here.</div>';
      return;
    }
    for (const entry of data.entries) {
      const row = document.createElement('button');
      row.className = 'vaultrow';
      row.innerHTML = `<span class="vaultname"></span><span class="vaultpath"></span>`;
      row.querySelector('.vaultname').textContent = entry.name + (entry.is_vault ? '  ·  vault' : '');
      row.querySelector('.vaultpath').textContent = entry.path;
      row.onclick = () => onPick(entry, render);
      listEl.appendChild(row);
    }
  }
  upBtn.onclick = () => { if (at.parent && at.parent !== at.path) render(at.parent); };
  return { render, current: () => at };
}

const openBrowser = makeBrowser({
  listEl: $('#vaultBrowseList'), pathEl: $('#vaultBrowsePath'), upBtn: $('#vaultBrowseUp'),
  onPick: async (entry, render) => {
    if (entry.is_vault) {
      if (await switchVault('/vault/open', entry.path, $('#vaultOpenMsg'))) showVaultHome();
    } else {
      render(entry.path);
    }
  },
});
$('#vaultPathOpenBtn').onclick = async () => {
  const p = $('#vaultPathInput').value.trim();
  if (!p) return ($('#vaultOpenMsg').textContent = 'Type a folder path first.');
  if (await switchVault('/vault/open', p, $('#vaultOpenMsg'))) showVaultHome();
};
$('#vaultPathInput').onkeydown = (e) => { if (e.key === 'Enter') $('#vaultPathOpenBtn').click(); };

/* Create wizard: pick a location by browsing (or typing one), name the new
   vault with a live path preview, then confirm. Location and name are kept
   apart so a typo in the name doesn't mean re-navigating the whole tree. */
let wizState = { parent: null, entries: [], fullPath: null };

const wizBrowser = makeBrowser({
  listEl: $('#wizBrowseList'), pathEl: $('#wizBrowsePath'), upBtn: $('#wizBrowseUp'),
  onPick: (entry, render) => render(entry.path),
});
$('#wizPathGo').onclick = () => {
  const p = $('#wizPathInput').value.trim();
  if (p) wizBrowser.render(p);
};
$('#wizPathInput').onkeydown = (e) => { if (e.key === 'Enter') $('#wizPathGo').click(); };

// Test hook: `const` bindings created inside one window.eval() call aren't
// visible to a later, separate eval() in jsdom, so tests that need to drive
// the browsers directly (e.g. to hit a 403 without a matching fixture folder)
// go through this instead. See graph.js's __tephraGraphInternals.
window.__tephraVaultInternals = { openBrowser, wizBrowser };

function goWizStep(n) {
  document.querySelectorAll('.wiz-pane').forEach((p) => { p.hidden = +p.dataset.n !== n; });
  document.querySelectorAll('.wiz-dots i').forEach((i) => i.classList.toggle('on', +i.dataset.n <= n));
  if (n === 2) { wizPreviewPath(); $('#wizName').focus(); }
  if (n === 3) { $('#wizConfirmPath').textContent = wizState.fullPath; }
}

function wizPreviewPath() {
  const name = $('#wizName').value.trim();
  const parent = (wizState.parent || '').replace(/\/+$/, '');
  const preview = $('#wizPathPreview');
  if (!name) { preview.textContent = parent ? `${parent}/…` : ''; preview.classList.remove('warn'); return; }
  preview.textContent = `${parent}/${name}`;
  const collides = wizState.entries.some((e) => e.name.toLowerCase() === name.toLowerCase());
  preview.classList.toggle('warn', collides);
  if (collides) preview.textContent += '  ·  a folder with this name already exists here';
}
$('#wizName').oninput = wizPreviewPath;

$('#wizNext1').onclick = () => {
  const at = wizBrowser.current();
  if (!at.path) return;
  wizState.parent = at.path;
  wizState.entries = at.entries;
  goWizStep(2);
};
$('#wizBack2').onclick = () => goWizStep(1);
$('#wizNext2').onclick = () => {
  const name = $('#wizName').value.trim();
  if (!name) { $('#vaultWizMsg').textContent = 'Type a vault name first.'; return; }
  wizState.fullPath = `${wizState.parent.replace(/\/+$/, '')}/${name}`;
  goWizStep(3);
};
$('#wizBack3').onclick = () => goWizStep(2);
$('#wizCreateBtn').onclick = async () => {
  if (await switchVault('/vault/create', wizState.fullPath, $('#vaultWizMsg'))) showVaultHome();
};

/* Summarise a repair report in one line. Counts, not jargon: "3 nested links"
   means something; "flatten_nested_links" does not. */
function describeRepair(r) {
  const sum = (k) => (r.notes || []).reduce((n, x) => n + (x[k] || 0), 0);
  const bits = [];
  if (sum('nested')) bits.push(`${sum('nested')} nested link${sum('nested') === 1 ? '' : 's'}`);
  if (sum('quiz_links')) bits.push(`${sum('quiz_links')} link${sum('quiz_links') === 1 ? '' : 's'} in quiz text`);
  if (sum('frontmatter')) bits.push(`${sum('frontmatter')} heading${sum('frontmatter') === 1 ? '' : 's'}`);
  if (sum('empty')) bits.push(`${sum('empty')} empty link${sum('empty') === 1 ? '' : 's'}`);
  const n = r.changed;
  let msg = `Cleaned up ${n} note${n === 1 ? '' : 's'}`;
  if (bits.length) msg += ` — ${bits.join(', ')}`;
  if (r.created?.length) {
    msg += `; created ${r.created.length} missing note${r.created.length === 1 ? '' : 's'}`;
  }
  return msg;
}

/* Vault Health, in the settings drawer: the auto-linker that produced nested
   links is fixed, but a vault it already damaged stays damaged until
   something rewrites it — so this has to be reachable, not just an endpoint. */
$('#auditRun').onclick = async () => {
  const out = $('#auditResult');
  out.textContent = 'Checking…';
  try {
    const [a, preview] = await Promise.all([
      api('/audit'),
      api('/repair?dry_run=true', { method: 'POST' }),
    ]);
    if (a.clean) {
      out.textContent = 'No malformed links found.';
      $('#repairRun').disabled = true;
      return;
    }
    const n = preview.changed;
    out.innerHTML = `<b>${n} note${n === 1 ? '' : 's'}</b> would be rewritten.`;
    const p = preview.notes.find((x) => x.preview && x.preview.before);
    if (p) {
      const box = document.createElement('div');
      box.className = 'auditsample';
      box.innerHTML = `<div class="abefore"></div><div class="aafter"></div>`;
      box.querySelector('.abefore').textContent = p.preview.before;
      box.querySelector('.aafter').textContent = p.preview.after;
      out.appendChild(box);
    }
    $('#repairRun').disabled = false;
  } catch { out.textContent = 'Could not run the check.'; }
};

$('#repairRun').onclick = async () => {
  const out = $('#auditResult');
  out.textContent = 'Repairing…';
  try {
    const r = await api('/repair', { method: 'POST' });
    out.textContent = describeRepair(r) + '.';
    $('#repairRun').disabled = true;
    toast(describeRepair(r), 6000);
    await loadList();
    await loadGraph();
    if (state.slug) await openNote(state.slug, false);
    window.tephraStudy?.refresh();
  } catch { out.textContent = 'Repair failed.'; }
};

$('#btnReindex').onclick = async () => {
  const out = $('#auditResult');
  out.textContent = 'Rebuilding…';
  try {
    const r = await api('/reindex', { method: 'POST' });
    await loadList(); await loadGraph(); await loadMedia();
    out.textContent = `Reindexed ${r.notes} notes.`;
  } catch { out.textContent = 'Reindex failed.'; }
};

$('#dupRun').onclick = async () => {
  const out = $('#dupResult');
  out.textContent = 'Scanning…';
  try {
    const { pairs } = await api('/duplicates');
    out.innerHTML = '';
    if (!pairs.length) { out.textContent = 'No near-duplicate notes found.'; return; }
    const head = document.createElement('div');
    head.innerHTML = `<b>${pairs.length}</b> possible duplicate pair${pairs.length === 1 ? '' : 's'}:`;
    out.appendChild(head);
    for (const p of pairs.slice(0, 30)) {
      const row = document.createElement('div');
      row.className = 'duprow';
      const a = document.createElement('button');
      a.className = 'dc-part'; a.textContent = p.a_title; a.title = 'Open ' + p.a_title;
      a.onclick = () => openNote(p.a_slug);
      const b = document.createElement('button');
      b.className = 'dc-part'; b.textContent = p.b_title; b.title = 'Open ' + p.b_title;
      b.onclick = () => openNote(p.b_slug);
      const pct = document.createElement('span');
      pct.className = 'dupscore';
      pct.textContent = Math.round(p.similarity * 100) + '%';
      row.append(a, document.createTextNode(' ↔ '), b, pct);
      out.appendChild(row);
    }
    if (pairs.length > 30) {
      const more = document.createElement('div');
      more.className = 'th-note';
      more.textContent = `+ ${pairs.length - 30} more, closest shown first.`;
      out.appendChild(more);
    }
  } catch { out.textContent = 'Could not scan for duplicates.'; }
};

/* ══ AMBIENT AURORA ══════════════════════════════════════════ */
(function () {
  const c = $('#aurora'), x = c.getContext('2d');
  let w, h;
  const blobs = [
    { r: .55, a: .40, sx: .00021, sy: .00016, px: 0, py: 0, useAcc: true },
    { r: .48, a: .34, sx: -.00017, sy: .00023, px: 2, py: 1, h: '183,156,255' },
    { r: .42, a: .26, sx: .00013, sy: -.00019, px: 4, py: 3, h: '255,157,110' },
    { r: .60, a: .44, sx: -.00011, sy: -.00014, px: 1, py: 5, h: '26,104,138' },
  ];
  const size = () => { w = c.width = Math.round(innerWidth * .45); h = c.height = Math.round(innerHeight * .45); };
  size(); addEventListener('resize', size);
  function draw(t) {
    x.fillStyle = '#050C0E'; x.fillRect(0, 0, w, h);
    for (const b of blobs) {
      const col = b.useAcc ? T.acc : b.h;
      const cx = w * (.5 + .42 * Math.sin(t * b.sx + b.px));
      const cy = h * (.5 + .42 * Math.cos(t * b.sy + b.py));
      const rr = Math.max(w, h) * b.r;
      const g = x.createRadialGradient(cx, cy, 0, cx, cy, rr);
      g.addColorStop(0, `rgba(${col},${b.a})`); g.addColorStop(1, `rgba(${col},0)`);
      x.fillStyle = g; x.beginPath(); x.arc(cx, cy, rr, 0, 7); x.fill();
    }
    requestAnimationFrame(draw);
  }
  reduce ? draw(0) : requestAnimationFrame(draw);
})();

/* ══ BOOT ════════════════════════════════════════════════════ */
addEventListener('hashchange', () => {
  const s = location.hash.slice(1);
  if (s && s !== state.slug) openNote(s, false);
});

(async function boot() {
  try { T = { ...DEFAULTS, ...(await api('/theme')) }; } catch {}
  state.sort = SORTS[T.note_sort] ? T.note_sort : 'updated';
  state.tag = T.note_tag || '';
  state.mediaOpen = T.media_open || {};
  applyTheme();
  mini = miniGraph($('#mini'));
  await loadList();
  await loadGraph();
  await loadMedia();
  // Repair runs server-side before the UI exists, so say what it did once the
  // window is actually up. Consumed on read, so a reload does not repeat it.
  try {
    const r = await api('/repair/last');
    if (r && r.changed) toast(describeRepair(r), 7000);
  } catch {}

  await showVaultName();
  window.tephraLinks?.poll();

  const want = location.hash.slice(1) || state.notes[0]?.slug;
  if (want) await openNote(want, false);
  drawMini();
  setInterval(() => { if (!state.dirty && state.note) mark('saved', 'Saved ' + fmtAgo(state.note.updated)); }, 20000);
})();
