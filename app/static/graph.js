/* ══════════════════════════════════════════════════════════════
   Vault graph.

   The previous version applied full-strength forces on every frame
   forever, so it never stopped moving and nodes were a moving target
   to click. This one cools: force strength is scaled by an alpha that
   decays toward zero, and once it is below a floor the loop stops
   ticking entirely and only redraws on interaction. Settles in about
   two seconds and then holds still.
   ══════════════════════════════════════════════════════════════ */
(function () {
  const W = 1000, H = 700;          // world units; screen is a transform of this

  const TUNING = {
    alphaDecay: 0.045,      // ~130 ticks to settle (~2s), not d3's default ~300
    alphaMin: 0.004,
    velocityDecay: 0.55,    // heavier damping than the old 0.86 — less springy
    // Swept empirically against a 79-node vault: weaker gravity and much
    // stronger repulsion spread nodes to a ~25-unit minimum gap, so they are
    // actually distinguishable and clickable. The first attempt collapsed
    // everything into a 175-unit ball.
    charge: -8000,
    linkDistance: 90,
    linkStrength: 0.09,
    gravity: 0.005,
    maxStep: 18,            // clamp per-tick movement so nothing catapults
    cluster: 0.055,         // pull toward the category centroid
  };

  /* ── simulation (no canvas, no DOM — unit-testable) ── */
  function createSim(nodes, links, tuning = TUNING) {
    const t = { ...TUNING, ...tuning };
    const n = nodes.length;

    // Deterministic seeding on a circle, grouped by category so related nodes
    // start near each other and converge faster. Random seeding made the
    // layout different every open, which is disorienting.
    const groups = [...new Set(nodes.map((d) => d.category || d.kind || ''))].sort();
    nodes.forEach((d, i) => {
      const g = Math.max(groups.indexOf(d.category || d.kind || ''), 0);
      const ring = 120 + (g % 4) * 90;
      const ang = (i / Math.max(n, 1)) * Math.PI * 2 + g * 0.7;
      d.x = W / 2 + Math.cos(ang) * ring;
      d.y = H / 2 + Math.sin(ang) * ring;
      d.vx = d.vy = 0;
    });

    const sim = {
      nodes, links, alpha: 1, tuning: t,
      groups: new Set(nodes.map((d) => d.category || '').filter(Boolean)),
      running() { return this.alpha > t.alphaMin; },
      reheat(to = 0.5) { this.alpha = Math.max(this.alpha, to); },
      tick() {
        const a = this.alpha;
        // repulsion — n is small enough (hundreds) that O(n^2) is fine and
        // exact, so no quadtree approximation artefacts
        for (let i = 0; i < n; i++) {
          const p = nodes[i];
          for (let j = i + 1; j < n; j++) {
            const q = nodes[j];
            let dx = q.x - p.x, dy = q.y - p.y;
            let d2 = dx * dx + dy * dy;
            if (d2 < 1) { dx = (i % 7) - 3; dy = (j % 7) - 3; d2 = 25; }
            const f = (t.charge * a) / (d2 * Math.sqrt(d2));
            const fx = dx * f, fy = dy * f;
            p.vx += fx; p.vy += fy; q.vx -= fx; q.vy -= fy;
          }
        }
        // springs
        for (const [i, j] of links) {
          const p = nodes[i], q = nodes[j];
          if (!p || !q) continue;
          const dx = q.x - p.x, dy = q.y - p.y;
          const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const k = ((d - t.linkDistance) / d) * t.linkStrength * a;
          const fx = dx * k, fy = dy * k;
          p.vx += fx; p.vy += fy; q.vx -= fx; q.vy -= fy;
        }
        // Category clustering. Without it, 100+ notes settle into one
        // undifferentiated blob; with it each category forms a visible lobe,
        // which is the single biggest readability win at this scale.
        if (t.cluster && this.groups.size > 1) {
          const cen = new Map();
          for (const d of nodes) {
            const g = d.category || '';
            if (!g) continue;
            const c = cen.get(g) || { x: 0, y: 0, n: 0 };
            c.x += d.x; c.y += d.y; c.n++;
            cen.set(g, c);
          }
          for (const c of cen.values()) { c.x /= c.n; c.y /= c.n; }
          for (const d of nodes) {
            const c = cen.get(d.category || '');
            if (!c) continue;
            d.vx += (c.x - d.x) * t.cluster * a;
            d.vy += (c.y - d.y) * t.cluster * a;
          }
        }

        // gravity + integrate
        for (const d of nodes) {
          d.vx += (W / 2 - d.x) * t.gravity * a;
          d.vy += (H / 2 - d.y) * t.gravity * a;
          d.vx *= t.velocityDecay; d.vy *= t.velocityDecay;
          if (d.fixed) { d.vx = d.vy = 0; continue; }
          d.vx = Math.max(-t.maxStep, Math.min(t.maxStep, d.vx));
          d.vy = Math.max(-t.maxStep, Math.min(t.maxStep, d.vy));
          d.x += d.vx; d.y += d.vy;
        }
        this.alpha += (0 - this.alpha) * t.alphaDecay;
        if (this.alpha <= t.alphaMin) this.alpha = 0;
      },
      energy() {
        return nodes.reduce((s, d) => s + d.vx * d.vx + d.vy * d.vy, 0);
      },
    };
    return sim;
  }

  /* ── tidy radial tree ────────────────────────────────────────────────
     A force layout is the wrong tool for a vault that is actually a
     hierarchy: a root note links to category indexes, which link to topics.
     This lays that structure out explicitly — deterministic, no settling, and
     no crossings within a component. Angular space is divided by leaf count so
     dense branches get room instead of overlapping.
     ───────────────────────────────────────────────────────────────────── */
  function tidyTree(nodes, links, opts = {}) {
    const ring = opts.ring || 190;
    // Outer rings need more than linear spacing: the same angular wedge holds
    // far more siblings three levels out than one, so radius grows super-
    // linearly to buy circumference where the crowding actually is.
    const power = opts.power || 1.45;
    const n = nodes.length;
    if (!n) return { parent: [] };
    const adj = new Map(nodes.map((_, i) => [i, []]));
    for (const [a, b] of links) {
      if (adj.has(a) && adj.has(b)) { adj.get(a).push(b); adj.get(b).push(a); }
    }

    const seen = new Array(n).fill(false);
    const parent = new Array(n).fill(-1);
    const depth = new Array(n).fill(0);
    const kids = new Map(nodes.map((_, i) => [i, []]));
    const roots = [];

    // Components, biggest first, each rooted at its most connected node.
    const order = [...nodes.keys()].sort((a, b) => (nodes[b].deg || 0) - (nodes[a].deg || 0));
    for (const start of order) {
      if (seen[start]) continue;
      roots.push(start);
      seen[start] = true;
      const queue = [start];
      while (queue.length) {
        const cur = queue.shift();
        for (const nb of adj.get(cur)) {
          if (seen[nb]) continue;          // BFS spanning tree: no cycles
          seen[nb] = true;
          parent[nb] = cur;
          depth[nb] = depth[cur] + 1;
          kids.get(cur).push(nb);
          queue.push(nb);
        }
      }
    }

    const leaves = new Array(n).fill(0);
    (function count(i) {
      const ks = kids.get(i);
      leaves[i] = ks.length ? ks.reduce((s, k) => s + count(k), 0) : 1;
      return leaves[i];
    });
    const countLeaves = (i) => {
      const ks = kids.get(i);
      leaves[i] = ks.length ? ks.reduce((s, k) => s + countLeaves(k), 0) : 1;
      return leaves[i];
    };
    const total = roots.reduce((s, r) => s + countLeaves(r), 0) || 1;

    const cx = W / 2, cy = H / 2;
    let cursor = 0;
    const place = (i, a0, a1) => {
      const mid = (a0 + a1) / 2;
      const r = depth[i] ? Math.pow(depth[i], power) * ring : 0;
      nodes[i].x = cx + Math.cos(mid) * r;
      nodes[i].y = cy + Math.sin(mid) * r;
      nodes[i].vx = nodes[i].vy = 0;
      const ks = kids.get(i);
      if (!ks.length) return;
      // Siblings sorted by size so big branches sit together, not interleaved.
      const sorted = [...ks].sort((p, q) => leaves[q] - leaves[p]);
      // Purely leaf-proportional wedges starve small branches: a category with
      // one topic got the same sliver as a single leaf and ended up ~16px from
      // its neighbour. Blending toward equal division gives every branch a
      // usable minimum while big ones still get more room.
      const span = a1 - a0;
      const even = opts.even ?? 0.3;   // swept: best sibling spacing
      let at = a0;
      for (const k of sorted) {
        const frac = (1 - even) * (leaves[k] / leaves[i]) + even / sorted.length;
        const share = frac * span;
        place(k, at, at + share);
        at += share;
      }
    };
    for (const r of roots) {
      const share = (leaves[r] / total) * Math.PI * 2;
      place(r, cursor, cursor + share);
      cursor += share;
    }
    // Exposed so cross-branch links can be routed along the hierarchy
    // (hierarchical edge bundling) instead of drawn as straight lines that
    // cut across the radial layout.
    return { parent };
  }

  /* ── hierarchical edge bundling ──────────────────────────────────────
     A tidy tree only has zero crossings for its own spanning-tree edges.
     Every other link in the graph (the "cross" links: a related topic in
     a different category, a prerequisite, etc.) still wants to be drawn,
     and a straight line for those cuts across the clean radial structure.
     Routing them along the tree instead — up to the lowest common
     ancestor of the two endpoints and back down — turns that clutter into
     curves that follow the hierarchy, and lets shared stretches of path
     visually merge into thicker bundles instead of a hairball.
     ───────────────────────────────────────────────────────────────────── */
  function treePath(parent, a, b) {
    const upA = [a];
    for (let c = a; parent[c] !== -1 && parent[c] !== undefined; ) { c = parent[c]; upA.push(c); }
    const upB = [b];
    for (let c = b; parent[c] !== -1 && parent[c] !== undefined; ) { c = parent[c]; upB.push(c); }
    const indexInA = new Map(upA.map((node, i) => [node, i]));
    let lcaA = -1, lcaB = -1;
    for (let j = 0; j < upB.length; j++) {
      if (indexInA.has(upB[j])) { lcaA = indexInA.get(upB[j]); lcaB = j; break; }
    }
    if (lcaA === -1) return [a, b];               // no shared ancestor — just draw it straight
    return [...upA.slice(0, lcaA + 1), ...upB.slice(0, lcaB).reverse()];
  }

  // Blend the tree path toward a straight line between its endpoints.
  // beta=1 hugs the hierarchy exactly; beta=0 is a plain straight edge.
  // The first and last points are always the real node positions, whatever
  // beta is — only the middle of the curve bows toward the tree.
  function blendPath(nodes, path, beta) {
    const n = path.length;
    const a = nodes[path[0]], b = nodes[path[n - 1]];
    return path.map((idx, i) => {
      const p = nodes[idx];
      const t = n > 1 ? i / (n - 1) : 0;
      const lx = a.x + (b.x - a.x) * t, ly = a.y + (b.y - a.y) * t;
      return { x: beta * p.x + (1 - beta) * lx, y: beta * p.y + (1 - beta) * ly };
    });
  }

  const bundleKey = (a, b) => (a < b ? `${a}:${b}` : `${b}:${a}`);
  const BUNDLE_BETA = 0.82;   // 0 = straight line, 1 = hugs the hierarchy exactly

  // One bundle entry per non-tree link whose path is long enough to bend;
  // direct parent-child links (already the tree's own edges) are left out
  // since a 2-point "path" is just the straight line anyway.
  function buildBundles(nodes, links, parent) {
    const bundles = new Map();
    for (const [a, b] of links) {
      if (parent[a] === b || parent[b] === a) continue;
      const path = treePath(parent, a, b);
      if (path.length > 2) bundles.set(bundleKey(a, b), path);
    }
    return bundles;
  }

  function strokeSmoothPath(ctx, pts) {
    if (pts.length < 2) return;
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    if (pts.length === 2) { ctx.lineTo(pts[1].x, pts[1].y); ctx.stroke(); return; }
    for (let i = 1; i < pts.length - 1; i++) {
      const mx = (pts[i].x + pts[i + 1].x) / 2, my = (pts[i].y + pts[i + 1].y) / 2;
      ctx.quadraticCurveTo(pts[i].x, pts[i].y, mx, my);
    }
    const prev = pts[pts.length - 2], last = pts[pts.length - 1];
    ctx.quadraticCurveTo(prev.x, prev.y, last.x, last.y);
    ctx.stroke();
  }

  /* ── view transform helpers ── */
  const toScreen = (wx, wy, v) => [wx * v.k + v.tx, wy * v.k + v.ty];
  const toWorld = (sx, sy, v) => [(sx - v.tx) / v.k, (sy - v.ty) / v.k];

  function hitTest(nodes, sx, sy, v, radiusFn) {
    let best = null, bd = Infinity;
    const [wx, wy] = toWorld(sx, sy, v);
    for (const d of nodes) {
      const r = radiusFn(d) + 6 / v.k;      // constant screen-space slop
      const dx = d.x - wx, dy = d.y - wy;
      const dist2 = dx * dx + dy * dy;
      if (dist2 < r * r && dist2 < bd) { bd = dist2; best = d; }
    }
    return best;
  }

  window.__tephraGraphInternals = {
    createSim, hitTest, toScreen, toWorld, tidyTree, W, H, TUNING,
    treePath, blendPath, buildBundles, bundleKey,
  };

  /* ── the interactive view ── */
  const $ = (s) => document.querySelector(s);
  if (typeof document === 'undefined') return;

  const G = {
    open: false, sim: null,
    all: { nodes: [], links: [] },       // everything the server sent
    raw: { nodes: [], links: [] },       // what is actually on screen
    adj: new Map(), selected: null, hover: null,
    view: { k: 1, tx: 0, ty: 0 }, filter: '',
    layout: 'cluster', showStubs: true, showLeaves: true, labels: 'auto',
    dragging: null, panning: null, moved: false, frame: null, bundles: null,
    catColors: new Map(),
  };

  const radiusOf = (d) =>
    (d.kind === 'stub' ? 4.5 : 5.5) + Math.min(d.deg || 0, 10) * 0.9;

  // Same seven accent swatches already offered in the theme drawer, so the
  // graph never invents a color language of its own. Assignment is by a
  // stable alphabetical sort of whatever categories are actually present in
  // this vault -- not insertion/discovery order -- so a category keeps its
  // color across a session regardless of which note happened to load first.
  const CATEGORY_PALETTE = [
    '63,224,173', '183,156,255', '255,157,110', '125,211,252',
    '255,143,177', '198,242,78', '167,196,255',
  ];
  function buildCategoryColors(nodes) {
    const cats = [...new Set(nodes.map((d) => d.category).filter(Boolean))].sort();
    const map = new Map();
    cats.forEach((c, i) => map.set(c, CATEGORY_PALETTE[i % CATEGORY_PALETTE.length]));
    return map;
  }
  const catColorOf = (d) => (d.category && G.catColors.get(d.category)) || '198,214,212';

  // The color key: what would otherwise be silent (why is this node teal
  // and that one pink?) made legible. Stubs get one shared explanation of
  // the hollow-ring convention instead of their own color, since their
  // fill still follows category like everything else.
  function renderCatLegend() {
    const host = $('#gvCatLegend');
    if (!host) return;
    host.innerHTML = '';
    const cats = [...G.catColors.keys()];
    for (const c of cats) {
      const chip = document.createElement('span');
      chip.innerHTML = `<i style="background:rgb(${G.catColors.get(c)})"></i>`;
      chip.append(c);
      host.appendChild(chip);
    }
    const stub = document.createElement('span');
    stub.className = 'gv-stub-key';
    stub.innerHTML = '<i></i>Not written yet';
    host.appendChild(stub);
  }

  function buildAdjacency() {
    G.adj = new Map();
    G.raw.nodes.forEach((_, i) => G.adj.set(i, new Set()));
    for (const [a, b] of G.raw.links) {
      G.adj.get(a)?.add(b);
      G.adj.get(b)?.add(a);
    }
  }

  async function load() {
    G.userMoved = false;
    G.all = await window.tephraApi('/graph');
    rebuild();
    // keep the current note selected so opening the graph has a focal point
    const cur = G.raw.nodes.find((d) => d.slug === window.tephraCurrentSlug?.());
    select(cur || null, false);
  }

  /* Build the on-screen subset from the full graph. Filtering has to remap the
     link indices, because links reference node positions in the array. */
  function rebuild(keepView = false) {
    const all = G.all.nodes || [];
    const degree = new Map(all.map((_, i) => [i, 0]));
    for (const [a, b] of G.all.links) {
      degree.set(a, (degree.get(a) || 0) + 1);
      degree.set(b, (degree.get(b) || 0) + 1);
    }
    const keep = new Set();
    all.forEach((d, i) => {
      if (!G.showStubs && d.kind === 'stub') return;
      // "Leaves" are single-link notes — usually a topic hanging off its
      // category index. Hiding them collapses the fringe and leaves the
      // structure, which is what makes a big vault legible.
      if (!G.showLeaves && (degree.get(i) || 0) <= 1 && !d.index) return;
      keep.add(i);
    });
    if (!keep.size) all.forEach((_, i) => keep.add(i));

    const list = [...keep];
    const remap = new Map(list.map((v, i) => [v, i]));
    const nodes = list.map((i) => ({ ...all[i] }));
    nodes.forEach((d, i) => (d.i = i));
    const links = G.all.links
      .filter(([a, b]) => remap.has(a) && remap.has(b))
      .map(([a, b]) => [remap.get(a), remap.get(b)]);
    G.raw = { nodes, links };
    buildAdjacency();
    G.catColors = buildCategoryColors(nodes);
    renderCatLegend();

    const s = $('#gvStats');
    if (s) {
      const hidden = all.length - nodes.length;
      s.textContent = `${nodes.length} NOTES · ${links.length} LINKS`
        + (hidden ? ` · ${hidden} HIDDEN` : '');
    }

    if (G.layout === 'tree') {
      G.sim = null;
      const { parent } = tidyTree(nodes, links);
      G.bundles = buildBundles(nodes, links, parent);
      if (!keepView) { G.userMoved = false; fit(); }
      redraw();
    } else {
      G.bundles = null;
      G.sim = createSim(nodes, links);
      if (!keepView) G.userMoved = false;
      start();
    }
    if (G.selected) {
      const again = nodes.find((d) => d.slug && d.slug === G.selected.slug);
      select(again || null, false);
    }
  }

  /* Frame the nodes, not the nominal world box. The layout only occupies part
     of the world, so fitting the world left a large empty margin and made
     everything look tiny. */
  function fit() {
    const c = $('#graph');
    if (!c) return;
    const r = c.getBoundingClientRect();
    const ns = G.raw.nodes;
    if (!ns.length || !r.width) { G.view = { k: 1, tx: 0, ty: 0 }; return; }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const d of ns) {
      x0 = Math.min(x0, d.x); x1 = Math.max(x1, d.x);
      y0 = Math.min(y0, d.y); y1 = Math.max(y1, d.y);
    }
    const pad = 70;
    const bw = Math.max(x1 - x0, 1) + pad * 2, bh = Math.max(y1 - y0, 1) + pad * 2;
    const k = Math.max(0.25, Math.min(r.width / bw, r.height / bh, 2.2));
    G.view = {
      k,
      tx: r.width / 2 - ((x0 + x1) / 2) * k,
      ty: r.height / 2 - ((y0 + y1) / 2) * k,
    };
  }

  /* ── drawing ── */
  function draw() {
    const c = $('#graph');
    if (!c || !c.getContext) return;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const r = c.getBoundingClientRect();
    if (c.width !== Math.round(r.width * dpr)) {
      c.width = Math.round(r.width * dpr);
      c.height = Math.round(r.height * dpr);
    }
    const v = G.view;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, r.width, r.height);

    const accent = getComputedStyle(document.documentElement)
      .getPropertyValue('--acc').trim() || '63,224,173';
    const focus = G.hover || G.selected;
    const near = focus ? new Set([focus.i, ...(G.adj.get(focus.i) || [])]) : null;
    const matches = (d) => !G.filter ||
      (d.label || '').toLowerCase().includes(G.filter);

    // edges — in tree layout, any link that isn't a direct parent-child
    // edge is routed along the hierarchy (hierarchical edge bundling)
    // instead of drawn straight, so cross-branch links follow the tree's
    // shape rather than cutting across it. Low, uniform alpha means
    // stretches shared by several bundled edges naturally read brighter
    // from the overlap, without any extra bookkeeping.
    for (const [a, b] of G.raw.links) {
      const p = G.raw.nodes[a], q = G.raw.nodes[b];
      if (!p || !q) continue;
      const lit = near && (near.has(a) && near.has(b));
      const dim = near && !lit;
      const bundle = G.bundles && G.bundles.get(bundleKey(a, b));
      // An edge between two same-category notes is tinted with that
      // category's color at rest -- clusters read as clusters through
      // their connections too, not just through node color.
      const shared = p.category && p.category === q.category ? G.catColors.get(p.category) : null;
      ctx.strokeStyle = lit ? `rgba(${accent},.65)` : dim ? 'rgba(255,255,255,.035)'
        : shared ? `rgba(${shared},${bundle ? .16 : .22})`
        : (bundle ? 'rgba(255,255,255,.08)' : 'rgba(255,255,255,.13)');
      ctx.lineWidth = lit ? 1.7 : 0.85;
      if (bundle) {
        const pts = blendPath(G.raw.nodes, bundle, BUNDLE_BETA)
          .map(({ x, y }) => { const [sx, sy] = toScreen(x, y, v); return { x: sx, y: sy }; });
        strokeSmoothPath(ctx, pts);
      } else {
        const [ax, ay] = toScreen(p.x, p.y, v), [bx, by] = toScreen(q.x, q.y, v);
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      }
    }

    // nodes
    for (const d of G.raw.nodes) {
      const [x, y] = toScreen(d.x, d.y, v);
      const rr = radiusOf(d) * v.k;
      const lit = !near || near.has(d.i);
      const hit = matches(d);
      const col = catColorOf(d);
      const alpha = (lit ? 1 : 0.22) * (hit ? 1 : 0.25);
      const isStub = d.kind === 'stub';

      if (lit && hit) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, rr * 3.4);
        g.addColorStop(0, `rgba(${col},.45)`);
        g.addColorStop(1, `rgba(${col},0)`);
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, rr * 3.4, 0, 7); ctx.fill();
      }

      const isSel = G.selected && d.i === G.selected.i;
      if (isStub) {
        // Hollow and dashed, not a fixed color: "not written yet" is a
        // shape cue now, so a stub's category is still legible from the
        // color of its own ring instead of every stub looking the same.
        ctx.setLineDash([2.2 * v.k, 2.2 * v.k]);
        ctx.strokeStyle = `rgba(${col},${(isSel ? 1 : 0.85) * alpha})`;
        ctx.lineWidth = isSel ? 2.5 : 1.4;
        ctx.beginPath(); ctx.arc(x, y, rr, 0, 7); ctx.stroke();
        ctx.setLineDash([]);
      } else {
        ctx.fillStyle = `rgba(${col},${0.95 * alpha})`;
        ctx.beginPath(); ctx.arc(x, y, rr, 0, 7); ctx.fill();
        ctx.strokeStyle = isSel ? '#fff' : `rgba(255,255,255,${0.55 * alpha})`;
        ctx.lineWidth = isSel ? 2.5 : 1;
        ctx.beginPath(); ctx.arc(x, y, rr, 0, 7); ctx.stroke();
      }

      // Labels only where they are readable and useful: zoomed in, well
      // connected, hovered, selected, or matching a search.
      // Labels are the main source of visual noise. Show them for what you are
      // looking at, for hubs, and otherwise only once zoomed in far enough that
      // they have room.
      const show = isSel || d === G.hover || (G.filter && hit) ||
        (near && near.has(d.i) && v.k > 0.5) ||
        d.index || (v.k > 0.9 && (d.deg || 0) >= 3) || v.k > 1.4;
      if (show && lit) {
        ctx.font = `500 ${Math.max(10, 11 * Math.min(v.k, 1.3))}px "Bricolage Grotesque", sans-serif`;
        ctx.textAlign = 'center';
        const label = (d.label || '').slice(0, 30);
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(5,12,14,.72)';
        ctx.fillRect(x - tw / 2 - 4, y - rr - 20, tw + 8, 15);
        ctx.fillStyle = `rgba(240,247,245,${isSel ? 1 : 0.88 * alpha})`;
        ctx.fillText(label, x, y - rr - 9);
      }
    }
  }

  function start() {
    stop();
    const loop = () => {
      if (!G.open) return;
      if (!G.sim) { if (!G.userMoved) fit(); draw(); G.frame = null; return; }
      if (G.sim && G.sim.running()) {
        G.sim.tick();
        draw();
        G.frame = requestAnimationFrame(loop);
      } else {
        // Frame the finished layout once, unless the user has already moved
        // the view themselves.
        if (!G.userMoved) fit();
        draw();
        G.frame = null;                     // settled: stop burning frames
      }
    };
    G.frame = requestAnimationFrame(loop);
  }
  function stop() { if (G.frame) cancelAnimationFrame(G.frame); G.frame = null; }
  function kick(alpha = 0.35) { if (G.sim) { G.sim.reheat(alpha); if (!G.frame) start(); } }
  function redraw() { if (!G.frame) draw(); }

  /* ── selection panel: this is the "see other links" part ── */
  function select(node, focus = true) {
    G.selected = node;
    const panel = $('#gvPanel');
    if (!panel) return;
    if (!node) { panel.innerHTML = '<div class="gv-hint">Click a node to see what it connects to.</div>'; redraw(); return; }

    const neigh = [...(G.adj.get(node.i) || [])]
      .map((i) => G.raw.nodes[i])
      .filter(Boolean)
      .sort((a, b) => (a.label || '').localeCompare(b.label || ''));

    panel.innerHTML = '';
    const head = document.createElement('div');
    head.className = 'gv-p-head';
    head.innerHTML = `<div class="gv-p-kind">${node.kind === 'stub' ? 'NOT WRITTEN YET' : 'NOTE'}</div>
      <div class="gv-p-title"></div>
      <div class="gv-p-meta">${neigh.length} connection${neigh.length === 1 ? '' : 's'}</div>`;
    head.querySelector('.gv-p-title').textContent = node.label;
    panel.appendChild(head);

    const acts = document.createElement('div');
    acts.className = 'gv-p-acts';
    if (node.slug) {
      const openBtn = document.createElement('button');
      openBtn.className = 'sv-btn primary';
      openBtn.textContent = 'Open note';
      openBtn.onclick = () => openFromGraph(node.slug);
      acts.appendChild(openBtn);
    }
    const centreBtn = document.createElement('button');
    centreBtn.className = 'sv-btn';
    centreBtn.textContent = 'Centre';
    centreBtn.onclick = () => centreOn(node);
    acts.appendChild(centreBtn);
    panel.appendChild(acts);

    const list = document.createElement('div');
    list.className = 'gv-p-list';
    if (!neigh.length) list.innerHTML = '<div class="gv-hint">Nothing links here yet.</div>';
    for (const nb of neigh) {
      const row = document.createElement('button');
      row.className = 'gv-p-row' + (nb.kind === 'stub' ? ' stub' : '');
      row.innerHTML = '<span class="gv-p-dot"></span><span class="gv-p-lbl"></span>';
      row.querySelector('.gv-p-lbl').textContent = nb.label;
      // single click walks the graph, double click opens the note — so you can
      // explore neighbourhoods without leaving the view
      row.onclick = () => { select(nb); centreOn(nb); };
      row.ondblclick = () => { if (nb.slug) openFromGraph(nb.slug); };
      list.appendChild(row);
    }
    panel.appendChild(list);

    if (focus) centreOn(node);
    redraw();
  }

  function centreOn(node) {
    const c = $('#graph');
    if (!c) return;
    const r = c.getBoundingClientRect();
    G.view.tx = r.width / 2 - node.x * G.view.k;
    G.view.ty = r.height / 2 - node.y * G.view.k;
    redraw();
  }

  function zoomBy(factor, cx, cy) {
    const v = G.view;
    const k = Math.max(0.25, Math.min(4, v.k * factor));
    const [wx, wy] = toWorld(cx, cy, v);
    v.k = k;
    v.tx = cx - wx * k;
    v.ty = cy - wy * k;
    redraw();
  }

  /* ── input ── */
  function wire() {
    const c = $('#graph');
    if (!c || c.__wired) return;
    c.__wired = true;
    const local = (e) => {
      const r = c.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };

    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      const [x, y] = local(e);
      G.userMoved = true;
      zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, x, y);
    }, { passive: false });

    c.addEventListener('pointerdown', (e) => {
      const [x, y] = local(e);
      G.moved = false;
      const hit = hitTest(G.raw.nodes, x, y, G.view, radiusOf);
      if (hit) {
        G.dragging = hit;
        hit.fixed = true;
        c.setPointerCapture(e.pointerId);
      } else {
        G.panning = { x, y, tx: G.view.tx, ty: G.view.ty };
      }
    });

    c.addEventListener('pointermove', (e) => {
      const [x, y] = local(e);
      if (G.dragging) {
        G.moved = true;
        const [wx, wy] = toWorld(x, y, G.view);
        G.dragging.x = wx; G.dragging.y = wy;
        G.dragging.vx = G.dragging.vy = 0;
        kick(0.25);
        return;
      }
      if (G.panning) {
        G.moved = true;
        G.userMoved = true;
        G.view.tx = G.panning.tx + (x - G.panning.x);
        G.view.ty = G.panning.ty + (y - G.panning.y);
        redraw();
        return;
      }
      const hit = hitTest(G.raw.nodes, x, y, G.view, radiusOf);
      if (hit !== G.hover) {
        G.hover = hit;
        c.style.cursor = hit ? 'pointer' : 'grab';
        redraw();
      }
    });

    const release = (e) => {
      if (G.dragging) {
        // a click that never moved is a select, not a drag
        if (!G.moved) { G.dragging.fixed = false; select(G.dragging, false); }
        G.dragging = null;
      } else if (G.panning && !G.moved) {
        select(null, false);
      }
      G.panning = null;
    };
    c.addEventListener('pointerup', release);
    c.addEventListener('pointercancel', release);
    c.addEventListener('pointerleave', () => { G.hover = null; redraw(); });

    c.addEventListener('dblclick', (e) => {
      const [x, y] = local(e);
      const hit = hitTest(G.raw.nodes, x, y, G.view, radiusOf);
      if (hit && hit.slug) openFromGraph(hit.slug);
    });

    /* Optional chaining throughout: a missing toolbar control should degrade
       that one button, not throw and leave the whole graph unopenable — which
       is exactly what happened when a markup edit silently failed. */
    const on = (sel, ev, fn) => { const el = $(sel); if (el) el[ev] = fn; };
    on('#gvZoomIn', 'onclick', () => { const r = c.getBoundingClientRect(); zoomBy(1.25, r.width / 2, r.height / 2); });
    on('#gvZoomOut', 'onclick', () => { const r = c.getBoundingClientRect(); zoomBy(1 / 1.25, r.width / 2, r.height / 2); });
    on('#gvFit', 'onclick', () => { G.userMoved = false; fit(); redraw(); });
    on('#gvRelax', 'onclick', () => {
      if (G.layout === 'tree') return rebuild();
      G.raw.nodes.forEach((d) => (d.fixed = false));
      kick(1);
    });
    on('#gvLayout', 'onchange', (e) => { G.layout = e.target.value; rebuild(); });
    on('#gvStubs', 'onclick', () => {
      G.showStubs = !G.showStubs;
      $('#gvStubs').toggleAttribute('data-on', G.showStubs);
      rebuild(true);
    });
    on('#gvLeaves', 'onclick', () => {
      G.showLeaves = !G.showLeaves;
      $('#gvLeaves').toggleAttribute('data-on', G.showLeaves);
      rebuild(true);
    });
    on('#gvFind', 'oninput', (e) => { G.filter = e.target.value.trim().toLowerCase(); redraw(); });
    on('#gvFind', 'onkeydown', (e) => {
      if (e.key !== 'Enter') return;
      const hit = G.raw.nodes.find((d) => (d.label || '').toLowerCase().includes(G.filter));
      if (hit) select(hit);
    });
    window.addEventListener('resize', () => { if (G.open) { redraw(); } });
  }

  async function open() {
    G.open = true;
    wire();
    await load();
  }
  function close() { G.open = false; stop(); }

  // Opening a note from inside the graph needs the *overlay* closed, not
  // just the sim stopped -- #graphview's .on class and the segmented
  // control's pressed state live in app.js, so route through its setView
  // rather than this module's own close(). Falls back to close() if that
  // global isn't there yet, same degrade-one-thing-not-the-whole-view
  // reasoning as the optional-chained toolbar wiring above.
  function openFromGraph(slug) {
    if (window.tephraSetView) window.tephraSetView('write'); else close();
    window.tephraOpenNote(slug);
  }

  window.tephraGraph = { open, close, isOpen: () => G.open, select };
})();
