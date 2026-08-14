/* ══════════════════════════════════════════════════════════════
   Network/cabling diagrams: a ```netdiagram fence -- boxes (devices,
   optionally nested) wired point-to-point by named ports, with redundant
   paths tagged into a color. render.py passes the fence content through
   untouched (see its _fence_rule); everything else -- parsing, layout,
   SVG rendering, the drag editor, and serializing edits back into that
   same fence -- lives here, the same "dumb backend, smart frontend"
   split app.js's Mermaid integration uses, for the same reason: nothing
   server-side needs to understand this syntax's structure.

   Grammar:
     device <id> "<label>" [at <x>,<y>]
     link <id.PORT[-N]> -> <id.PORT[-N]> ["<label>"] [#<tag>]

   A dotted id (c1.fiom0) nests under the device named by everything
   before the last dot, which must already be declared -- no indentation
   to get wrong by hand. `at x,y` is what the drag editor writes back
   (relative to the parent, when nested); a device with no `at` gets a
   deterministic auto-layout instead. A port range like ETH1-4 expands
   and pairs positionally with the other side's range (equal length
   required); a whole range is ONE bundled line with a ×N badge, not N
   separate lines -- so a device's anchor points are one per LINK
   STATEMENT touching it, not one per individual port. Malformed lines
   collect as errors rather than aborting the parse, same "a typo can't
   take down the whole thing" philosophy as ## Quiz.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const SVGNS = 'http://www.w3.org/2000/svg';
  const $ = (s) => document.querySelector(s);

  /* ── parsing ──────────────────────────────────────────────── */

  const DEVICE_RE = /^device\s+(\S+)\s+"([^"]*)"(?:\s+at\s+(-?\d+)\s*,\s*(-?\d+))?\s*$/;
  const LINK_RE = /^link\s+(\S+)\s+->\s+(\S+)(?:\s+"([^"]*)")?(?:\s+#(\S+))?\s*$/;

  // "ETH1-4" -> ["ETH1","ETH2","ETH3","ETH4"]; "ETH1" -> ["ETH1"];
  // "Console" (no trailing numeric range) -> ["Console"], a single port.
  // Zero-padded ranges ("01"-"04") keep their width.
  function expandPortSpec(spec) {
    const m = /^(.*?)(\d+)-(\d+)$/.exec(spec);
    if (!m) return [spec];
    const [, prefix, startStr, endStr] = m;
    const start = parseInt(startStr, 10), end = parseInt(endStr, 10);
    if (!(start <= end)) return [spec];
    const width = startStr.length;
    const out = [];
    for (let n = start; n <= end; n++) out.push(prefix + String(n).padStart(width, '0'));
    return out;
  }

  // A port path's device id can itself contain dots (nesting), so the
  // split point is ambiguous from the text alone -- resolved by trying
  // the longest dotted prefix that matches an already-declared device.
  function resolvePortPath(path, deviceIds) {
    const segs = path.split('.');
    for (let i = segs.length - 1; i >= 1; i--) {
      const devId = segs.slice(0, i).join('.');
      if (deviceIds.has(devId)) return { deviceId: devId, portSpec: segs.slice(i).join('.') };
    }
    return null;
  }

  function parseNetDiagram(text) {
    const devices = new Map();
    const links = [];
    const errors = [];
    const lines = (text || '').split('\n');

    lines.forEach((raw, i) => {
      const line = raw.trim();
      if (!line || line.startsWith('link ')) return;
      if (!line.startsWith('device ')) { errors.push({ line: i + 1, message: 'Unrecognized line', raw }); return; }
      const m = DEVICE_RE.exec(line);
      if (!m) { errors.push({ line: i + 1, message: 'Malformed device line', raw }); return; }
      const [, id, label, xs, ys] = m;
      if (devices.has(id)) { errors.push({ line: i + 1, message: `Duplicate device "${id}"`, raw }); return; }
      const dot = id.lastIndexOf('.');
      const parentId = dot === -1 ? null : id.slice(0, dot);
      if (parentId && !devices.has(parentId)) {
        errors.push({ line: i + 1, message: `Parent device "${parentId}" not declared yet`, raw });
        return;
      }
      devices.set(id, {
        id, label, parentId,
        x: xs != null ? Number(xs) : null,
        y: ys != null ? Number(ys) : null,
        hasPos: xs != null,
      });
    });

    const deviceIds = new Set(devices.keys());
    lines.forEach((raw, i) => {
      const line = raw.trim();
      if (!line.startsWith('link ')) return;
      const m = LINK_RE.exec(line);
      if (!m) { errors.push({ line: i + 1, message: 'Malformed link line', raw }); return; }
      const [, fromPath, toPath, label, tag] = m;
      const from = resolvePortPath(fromPath, deviceIds);
      const to = resolvePortPath(toPath, deviceIds);
      if (!from) { errors.push({ line: i + 1, message: `Unknown device in "${fromPath}"`, raw }); return; }
      if (!to) { errors.push({ line: i + 1, message: `Unknown device in "${toPath}"`, raw }); return; }
      const fromPorts = expandPortSpec(from.portSpec);
      const toPorts = expandPortSpec(to.portSpec);
      if (fromPorts.length !== toPorts.length) {
        errors.push({ line: i + 1, message: `Port count mismatch: ${fromPorts.length} vs ${toPorts.length}`, raw });
        return;
      }
      links.push({
        idx: links.length, line: i + 1,
        fromDevice: from.deviceId, fromPortSpec: from.portSpec, fromPorts,
        toDevice: to.deviceId, toPortSpec: to.portSpec, toPorts,
        label: label || '', tag: tag || '',
      });
    });

    return { devices, links, errors };
  }

  /* ── serializing (inverse of the parser; canonical, not byte-exact --
     same normalizing round-trip Quiz's render_quiz already does) ──── */

  function serializeNetDiagram(model) {
    const lines = [];
    for (const d of model.devices.values()) {
      let line = `device ${d.id} "${d.label}"`;
      if (d.hasPos) line += ` at ${Math.round(d.x)},${Math.round(d.y)}`;
      lines.push(line);
    }
    if (model.devices.size && model.links.length) lines.push('');
    for (const l of model.links) {
      let line = `link ${l.fromDevice}.${l.fromPortSpec} -> ${l.toDevice}.${l.toPortSpec}`;
      if (l.label) line += ` "${l.label}"`;
      if (l.tag) line += ` #${l.tag}`;
      lines.push(line);
    }
    return lines.join('\n');
  }

  /* ── layout: resolves every device to an absolute {x,y,w,h} box. A
     device's own w/h comes from its label length and how many link-
     statement anchors it needs room for; a parent is sized to wrap its
     children in a simple vertical stack. Positions are absolute even for
     nested devices (a parent's origin plus the child's own relative
     offset), so rendering never needs to reason about nesting itself. ── */

  function countAnchors(model) {
    const counts = new Map();
    for (const l of model.links) {
      counts.set(l.fromDevice, (counts.get(l.fromDevice) || 0) + 1);
      counts.set(l.toDevice, (counts.get(l.toDevice) || 0) + 1);
    }
    return counts;
  }

  const PAD = 14, GAP = 16, HEADER = 34;

  function layoutNetDiagram(model) {
    const { devices } = model;
    const positions = new Map();
    const childrenOf = new Map();
    for (const d of devices.values()) {
      if (d.parentId) {
        if (!childrenOf.has(d.parentId)) childrenOf.set(d.parentId, []);
        childrenOf.get(d.parentId).push(d.id);
      }
    }
    const anchorCounts = countAnchors(model);

    function baseSize(d) {
      const w = Math.max(110, Math.ceil((d.label || d.id).length * 7.2) + 32);
      const ac = anchorCounts.get(d.id) || 0;
      const h = Math.max(50, ac * 22 + 16);
      return { w, h };
    }

    const sizeCache = new Map();
    function sizeOf(id) {
      if (sizeCache.has(id)) return sizeCache.get(id);
      const d = devices.get(id);
      const kids = childrenOf.get(id) || [];
      let size;
      if (!kids.length) size = baseSize(d);
      else {
        let maxW = 0, totalH = HEADER;
        for (const kid of kids) { const ks = sizeOf(kid); maxW = Math.max(maxW, ks.w); totalH += ks.h + GAP; }
        size = { w: Math.max(baseSize(d).w, maxW + PAD * 2), h: totalH + PAD - GAP };
      }
      sizeCache.set(id, size);
      return size;
    }

    function relOffset(id) {
      const d = devices.get(id);
      if (d.hasPos) return { x: d.x, y: d.y };
      const siblings = childrenOf.get(d.parentId) || [];
      let y = HEADER;
      for (const sib of siblings) {
        if (sib === id) break;
        y += sizeOf(sib).h + GAP;
      }
      return { x: PAD, y };
    }

    function place(id, originX, originY) {
      const size = sizeOf(id);
      positions.set(id, { x: originX, y: originY, w: size.w, h: size.h });
      for (const kid of childrenOf.get(id) || []) {
        const off = relOffset(kid);
        place(kid, originX + off.x, originY + off.y);
      }
    }

    let cursorX = 40;
    for (const d of devices.values()) {
      if (d.parentId != null) continue;
      let ox, oy;
      if (d.hasPos) { ox = d.x; oy = d.y; }
      else { ox = cursorX; oy = 40; }
      place(d.id, ox, oy);
      cursorX = Math.max(cursorX, ox + sizeOf(d.id).w + 60);
    }
    return positions;
  }

  /* ── anchors: for every link end, pick a side of its device's box
     (whichever faces the other device) and space it evenly among the
     other link-ends on that same side, sorted by the other device's
     position for fewer needless crossings. ─────────────────────── */

  function computeAnchorPoints(model, positions) {
    function center(id) {
      const p = positions.get(id);
      return { x: p.x + p.w / 2, y: p.y + p.h / 2 };
    }
    const bySide = new Map();
    function bucket(id) {
      if (!bySide.has(id)) bySide.set(id, { left: [], right: [], top: [], bottom: [] });
      return bySide.get(id);
    }
    const touches = [];
    for (const l of model.links) {
      touches.push({ link: l, deviceId: l.fromDevice, otherId: l.toDevice, end: 'from' });
      touches.push({ link: l, deviceId: l.toDevice, otherId: l.fromDevice, end: 'to' });
    }
    for (const t of touches) {
      const a = center(t.deviceId), b = center(t.otherId);
      const dx = b.x - a.x, dy = b.y - a.y;
      const side = Math.abs(dx) >= Math.abs(dy) ? (dx >= 0 ? 'right' : 'left') : (dy >= 0 ? 'bottom' : 'top');
      bucket(t.deviceId)[side].push(t);
    }
    const anchors = new Map();
    for (const [id, sides] of bySide) {
      const p = positions.get(id);
      for (const side of ['left', 'right', 'top', 'bottom']) {
        const list = sides[side];
        if (!list.length) continue;
        const horizontal = side === 'top' || side === 'bottom';
        list.sort((a, b) => {
          const ca = center(a.otherId), cb = center(b.otherId);
          return horizontal ? ca.x - cb.x : ca.y - cb.y;
        });
        list.forEach((t, i) => {
          const frac = (i + 1) / (list.length + 1);
          let x, y;
          if (side === 'left') { x = p.x; y = p.y + frac * p.h; }
          else if (side === 'right') { x = p.x + p.w; y = p.y + frac * p.h; }
          else if (side === 'top') { x = p.x + frac * p.w; y = p.y; }
          else { x = p.x + frac * p.w; y = p.y + p.h; }
          anchors.set(`${t.link.idx}:${t.end}`, { x, y });
        });
      }
    }
    return anchors;
  }

  /* ── SVG building: shared by the static inline card and the editable
     canvas -- interactivity is opt-in via callbacks so the same layout/
     render code serves both. ───────────────────────────────────────── */

  const TAG_PALETTE = ['63,224,173', '183,156,255', '255,157,110', '125,211,252',
    '255,143,177', '198,242,78', '167,196,255'];
  // Same fixed 7-swatch palette the graph view already uses for category
  // colors (graph.js's CATEGORY_PALETTE) -- one shared color language for
  // the whole app instead of a diagram inventing its own. Assigned by
  // order of first appearance in this one diagram (no need for the graph
  // view's alphabetical cross-session stability -- a diagram's tags are
  // whatever the user typed, freshly re-derived on every render).
  function tagColorMap(model) {
    const map = new Map();
    for (const l of model.links) {
      if (l.tag && !map.has(l.tag)) map.set(l.tag, TAG_PALETTE[map.size % TAG_PALETTE.length]);
    }
    return map;
  }

  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVGNS, tag);
    for (const k in attrs || {}) el.setAttribute(k, attrs[k]);
    return el;
  }

  function buildSvg(model, opts) {
    opts = opts || {};
    const positions = layoutNetDiagram(model);
    const anchors = computeAnchorPoints(model, positions);
    const tagColors = tagColorMap(model);
    let maxX = 40, maxY = 40;
    for (const p of positions.values()) { maxX = Math.max(maxX, p.x + p.w + 40); maxY = Math.max(maxY, p.y + p.h + 40); }
    const svg = svgEl('svg', { viewBox: `0 0 ${maxX} ${maxY}`, class: 'ndg-svg' });
    const linksLayer = svgEl('g', { class: 'ndg-links' });
    const devicesLayer = svgEl('g', { class: 'ndg-devices' });
    svg.appendChild(linksLayer);
    svg.appendChild(devicesLayer);

    const linkEls = new Map();
    for (const l of model.links) {
      const a = anchors.get(`${l.idx}:from`), b = anchors.get(`${l.idx}:to`);
      if (!a || !b) continue;
      const g = svgEl('g', { class: 'ndg-link', 'data-link-idx': l.idx });
      const line = svgEl('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: 'ndg-link-line' });
      // Inline, not a class -- an SVG presentation attribute would lose to
      // .ndg-link-line's own stroke rule (lower specificity than any
      // stylesheet rule), so the color has to be inline to actually win.
      if (l.tag) line.setAttribute('style', `stroke:rgb(${tagColors.get(l.tag)})`);
      g.appendChild(line);
      const parts = [];
      if (l.fromPorts.length > 1) parts.push(`×${l.fromPorts.length}`);
      if (l.label) parts.push(l.label);
      let label = null;
      if (parts.length) {
        label = svgEl('text', {
          x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 6,
          class: 'ndg-link-label', 'text-anchor': 'middle',
        });
        label.textContent = parts.join('  ');
        g.appendChild(label);
      }
      linksLayer.appendChild(g);
      linkEls.set(l.idx, { g, line, label });
      if (opts.onSelectLink) {
        g.addEventListener('mousedown', (e) => { e.stopPropagation(); opts.onSelectLink(l.idx); });
      }
    }

    const deviceEls = new Map();
    for (const d of model.devices.values()) {
      const p = positions.get(d.id);
      const g = svgEl('g', { class: 'ndg-device', 'data-id': d.id, transform: `translate(${p.x},${p.y})` });
      const rect = svgEl('rect', {
        width: p.w, height: p.h, rx: 10,
        class: d.parentId ? 'ndg-box ndg-box-nested' : 'ndg-box',
      });
      const text = svgEl('text', { x: 10, y: 22, class: 'ndg-label' });
      text.textContent = d.label;
      g.appendChild(rect);
      g.appendChild(text);
      devicesLayer.appendChild(g);
      deviceEls.set(d.id, { g, rect, text });
      if (opts.onDeviceDown) {
        g.addEventListener('mousedown', (e) => { e.stopPropagation(); opts.onDeviceDown(e, d.id); });
      }
    }

    return { svg, positions, anchors, linkEls, deviceEls };
  }

  /* ── mounting the static, non-editable card inside a note ───────── */

  function renderInline(el, model) {
    el.innerHTML = '';
    if (model.errors.length) {
      const warn = document.createElement('div');
      warn.className = 'ndg-errors';
      warn.textContent = model.errors.map((e) => `Line ${e.line}: ${e.message}`).join(' · ');
      el.appendChild(warn);
    }
    if (model.devices.size) el.appendChild(buildSvg(model).svg);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ndg-edit-btn';
    btn.textContent = 'Edit diagram';
    btn.addEventListener('click', () => openEditor(el));
    el.appendChild(btn);
  }

  function enhanceNetDiagram() {
    for (const el of document.querySelectorAll('#noteBody .netdiagram:not([data-processed])')) {
      el.setAttribute('data-processed', 'true');
      el.dataset.raw = el.textContent;
      renderInline(el, parseNetDiagram(el.dataset.raw));
    }
  }

  /* ── persisting an edit: rewrite only the Nth ```netdiagram fence's
     inner content, same "leave the rest of the body untouched" approach
     as app.js's setMermaidWidth (just replacing the whole body, not one
     line, since an edit here can touch any number of lines). ────────── */

  const NETDIAGRAM_FENCE_RE_G = /^```netdiagram\n([\s\S]*?\n```)[ \t]*$/gm;

  function setNetDiagramBody(body, index, newInnerText) {
    let i = -1;
    return body.replace(NETDIAGRAM_FENCE_RE_G, (whole) => {
      i++;
      if (i !== index) return whole;
      return '```netdiagram\n' + newInnerText + '\n```';
    });
  }

  /* ── the editor: a single shared overlay (like #lens), editing whichever
     diagram was last opened. All edits mutate `ed.model` directly; every
     mutation reschedules a debounced save (mirrors quiz-editor.js's 700ms
     pattern) that serializes and rewrites the note body through a small
     bridge app.js exposes (window.tephraSaveNoteBody) -- netdiagram.js
     never touches `state` directly, the same arm's-length relationship
     sources-panel.js/quiz-editor.js already keep with app.js's internals.
     ─────────────────────────────────────────────────────────────────── */

  let ed = null;
  let saveTimer = null;

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      if (!ed) return;
      const index = Number(ed.el.dataset.netdiagramIndex);
      const text = serializeNetDiagram(ed.model);
      window.tephraSaveNoteBody?.(ed.slug, (body) => setNetDiagramBody(body, index, text));
    }, 500);
  }

  function descendantsOf(model, id) {
    const out = [];
    (function walk(pid) {
      for (const d of model.devices.values()) if (d.parentId === pid) { out.push(d.id); walk(d.id); }
    })(id);
    return out;
  }

  function nextDeviceId(model, parentId) {
    const prefix = parentId ? parentId + '.' : '';
    let n = 1;
    while (model.devices.has(prefix + 'd' + n)) n++;
    return prefix + 'd' + n;
  }

  function updateSelectionHighlight() {
    if (!ed || !ed.view) return;
    for (const { g } of ed.view.deviceEls.values()) g.classList.remove('ndg-selected');
    for (const { g } of ed.view.linkEls.values()) g.classList.remove('ndg-selected');
    if (ed.selected?.type === 'device') ed.view.deviceEls.get(ed.selected.id)?.g.classList.add('ndg-selected');
    if (ed.selected?.type === 'link') ed.view.linkEls.get(ed.selected.idx)?.g.classList.add('ndg-selected');
  }

  function renderEditorCanvas() {
    const host = $('#ndgCanvas');
    host.innerHTML = '';
    ed.view = buildSvg(ed.model, {
      onDeviceDown: (e, id) => onDeviceDown(e, id),
      onSelectLink: (idx) => { ed.selected = { type: 'link', idx }; ed.linkMode = false; updateSelectionHighlight(); renderInspector(); },
    });
    host.appendChild(ed.view.svg);
    updateSelectionHighlight();
  }

  function fieldRow(labelText, value, onChange) {
    const row = document.createElement('label');
    row.className = 'ndg-field';
    const span = document.createElement('span');
    span.textContent = labelText;
    const input = document.createElement('input');
    input.type = 'text';
    input.value = value || '';
    input.addEventListener('change', () => onChange(input.value.trim()));
    row.appendChild(span);
    row.appendChild(input);
    return row;
  }

  // Same double-click-armed delete quiz-editor.js's card rows use -- a
  // single misclick can't lose a device or link, but confirming doesn't
  // need a whole separate dialog either.
  function deleteButton(onConfirm) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ndg-btn ndg-btn-danger';
    btn.textContent = 'Delete';
    let armed = false, timer = null;
    btn.addEventListener('click', () => {
      if (!armed) {
        armed = true;
        btn.textContent = 'Click again to delete';
        timer = setTimeout(() => { armed = false; btn.textContent = 'Delete'; }, 4000);
        return;
      }
      clearTimeout(timer);
      onConfirm();
    });
    return btn;
  }

  function updateLinkPorts(l, side, newSpec) {
    if (!newSpec) { window.toast?.('Ports can’t be empty'); renderInspector(); return; }
    const ports = expandPortSpec(newSpec);
    const other = side === 'from' ? l.toPorts : l.fromPorts;
    if (ports.length !== other.length) {
      window.toast?.(`Port count mismatch: ${ports.length} vs ${other.length}`);
      renderInspector();
      return;
    }
    if (side === 'from') { l.fromPortSpec = newSpec; l.fromPorts = ports; }
    else { l.toPortSpec = newSpec; l.toPorts = ports; }
    renderEditorCanvas();
    scheduleSave();
  }

  function deleteDevice(id) {
    const toRemove = new Set([id, ...descendantsOf(ed.model, id)]);
    for (const rid of toRemove) ed.model.devices.delete(rid);
    ed.model.links = ed.model.links.filter((l) => !toRemove.has(l.fromDevice) && !toRemove.has(l.toDevice));
    ed.model.links.forEach((l, i) => { l.idx = i; });
    ed.selected = null;
    renderEditorCanvas();
    renderInspector();
    scheduleSave();
  }

  function deleteLink(idx) {
    ed.model.links = ed.model.links.filter((l) => l.idx !== idx);
    ed.model.links.forEach((l, i) => { l.idx = i; });
    ed.selected = null;
    renderEditorCanvas();
    renderInspector();
    scheduleSave();
  }

  function addDevice(parentId) {
    const id = nextDeviceId(ed.model, parentId || null);
    ed.model.devices.set(id, { id, label: 'New device', parentId: parentId || null, x: null, y: null, hasPos: false });
    ed.selected = { type: 'device', id };
    ed.linkMode = false;
    renderEditorCanvas();
    renderInspector();
    scheduleSave();
  }

  function startLinkMode() {
    ed.linkMode = true;
    ed.linkFirst = null;
    ed.selected = null;
    updateSelectionHighlight();
    renderInspector();
  }

  function onDeviceDown(e, id) {
    if (ed.linkMode) {
      if (!ed.linkFirst) { ed.linkFirst = id; renderInspector(); return; }
      if (ed.linkFirst === id) return;
      const link = {
        idx: ed.model.links.length, line: 0,
        fromDevice: ed.linkFirst, fromPortSpec: 'PORT1', fromPorts: ['PORT1'],
        toDevice: id, toPortSpec: 'PORT1', toPorts: ['PORT1'],
        label: '', tag: '',
      };
      ed.model.links.push(link);
      ed.linkMode = false;
      ed.linkFirst = null;
      ed.selected = { type: 'link', idx: link.idx };
      renderEditorCanvas();
      renderInspector();
      scheduleSave();
      return;
    }
    startDrag(e, id);
  }

  function startDrag(e, id) {
    const view = ed.view;
    ed.selected = { type: 'device', id };
    updateSelectionHighlight();
    renderInspector();
    // document-level mousemove/mouseup, not pointer capture -- the same
    // convention startResize/startMermaidPan already use elsewhere in this
    // app, so a drag that leaves the box's own bounds (fast mouse
    // movement) keeps tracking instead of dropping the gesture.
    const startX = e.clientX, startY = e.clientY;
    const kids = descendantsOf(ed.model, id);
    const group = [id, ...kids];
    const startPositions = new Map(group.map((did) => [did, { ...view.positions.get(did) }]));
    let moved = false;
    function onMove(ev) {
      const dx = ev.clientX - startX, dy = ev.clientY - startY;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) moved = true;
      for (const did of group) {
        const sp = startPositions.get(did);
        const p = view.positions.get(did);
        p.x = sp.x + dx; p.y = sp.y + dy;
        view.deviceEls.get(did).g.setAttribute('transform', `translate(${p.x},${p.y})`);
      }
      updateLinkPositions(group);
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      if (moved) commitDevicePosition(id);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  // Only the dragged device's own model position needs writing back --
  // a dragged parent's descendants moved by the same delta on screen (see
  // startDrag), but their position relative to that parent, which is all
  // that's actually stored for a nested device, never changed.
  function updateLinkPositions(movedIds) {
    const view = ed.view;
    const anchors = computeAnchorPoints(ed.model, view.positions);
    view.anchors = anchors;
    const moved = new Set(movedIds);
    for (const l of ed.model.links) {
      if (!moved.has(l.fromDevice) && !moved.has(l.toDevice)) continue;
      const els = view.linkEls.get(l.idx);
      const a = anchors.get(`${l.idx}:from`), b = anchors.get(`${l.idx}:to`);
      if (!els || !a || !b) continue;
      els.line.setAttribute('x1', a.x); els.line.setAttribute('y1', a.y);
      els.line.setAttribute('x2', b.x); els.line.setAttribute('y2', b.y);
      if (els.label) { els.label.setAttribute('x', (a.x + b.x) / 2); els.label.setAttribute('y', (a.y + b.y) / 2 - 6); }
    }
  }

  function commitDevicePosition(id) {
    const d = ed.model.devices.get(id);
    const p = ed.view.positions.get(id);
    if (d.parentId) {
      const pp = ed.view.positions.get(d.parentId);
      d.x = Math.round(p.x - pp.x);
      d.y = Math.round(p.y - pp.y);
    } else {
      d.x = Math.round(p.x);
      d.y = Math.round(p.y);
    }
    d.hasPos = true;
    scheduleSave();
  }

  function renderInspector() {
    const host = $('#ndgInspector');
    host.innerHTML = '';
    if (ed.linkMode) {
      const hint = document.createElement('div');
      hint.className = 'ndg-hint';
      hint.textContent = ed.linkFirst
        ? `Click the destination device for "${ed.model.devices.get(ed.linkFirst)?.label || ed.linkFirst}"…`
        : 'Click the source device…';
      host.appendChild(hint);
      return;
    }
    if (!ed.selected) {
      const hint = document.createElement('div');
      hint.className = 'ndg-hint';
      hint.textContent = 'Click a device or link to edit it.';
      host.appendChild(hint);
      return;
    }
    if (ed.selected.type === 'device') {
      const d = ed.model.devices.get(ed.selected.id);
      if (!d) { ed.selected = null; renderInspector(); return; }
      host.appendChild(fieldRow('Label', d.label, (v) => { d.label = v || d.id; renderEditorCanvas(); scheduleSave(); }));
      const subBtn = document.createElement('button');
      subBtn.type = 'button';
      subBtn.className = 'ndg-btn';
      subBtn.textContent = '+ Nested device';
      subBtn.addEventListener('click', () => addDevice(d.id));
      host.appendChild(subBtn);
      host.appendChild(deleteButton(() => deleteDevice(d.id)));
    } else if (ed.selected.type === 'link') {
      const l = ed.model.links.find((x) => x.idx === ed.selected.idx);
      if (!l) { ed.selected = null; renderInspector(); return; }
      host.appendChild(fieldRow('From ports', l.fromPortSpec, (v) => updateLinkPorts(l, 'from', v)));
      host.appendChild(fieldRow('To ports', l.toPortSpec, (v) => updateLinkPorts(l, 'to', v)));
      host.appendChild(fieldRow('Label', l.label, (v) => { l.label = v; renderEditorCanvas(); scheduleSave(); }));
      host.appendChild(fieldRow('Tag (color group)', l.tag, (v) => { l.tag = v; renderEditorCanvas(); scheduleSave(); }));
      host.appendChild(deleteButton(() => deleteLink(l.idx)));
    }
  }

  function openEditor(sourceEl) {
    ed = {
      el: sourceEl,
      slug: window.tephraCurrentSlug?.(),
      model: parseNetDiagram(sourceEl.dataset.raw || ''),
      selected: null,
      linkMode: false,
      linkFirst: null,
      view: null,
    };
    renderEditorCanvas();
    renderInspector();
    $('#ndgEditor').classList.add('on');
  }

  function closeEditor() {
    $('#ndgEditor').classList.remove('on');
    if (ed) {
      const text = serializeNetDiagram(ed.model);
      ed.el.dataset.raw = text;
      renderInline(ed.el, ed.model);
    }
    ed = null;
  }

  $('#ndgAddDevice')?.addEventListener('click', () => { if (ed) addDevice(null); });
  $('#ndgAddLink')?.addEventListener('click', () => { if (ed) startLinkMode(); });
  $('#ndgClose')?.addEventListener('click', closeEditor);
  $('#ndgCanvas')?.addEventListener('mousedown', () => {
    if (ed && !ed.linkMode) { ed.selected = null; updateSelectionHighlight(); renderInspector(); }
  });

  window.tephraNetDiagram = {
    parse: parseNetDiagram,
    serialize: serializeNetDiagram,
    layout: layoutNetDiagram,
    anchors: computeAnchorPoints,
    expandPortSpec,
    enhance: enhanceNetDiagram,
    setBody: setNetDiagramBody,
  };
})();
