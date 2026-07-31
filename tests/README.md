# Tests

## Backend
```bash
python3 tests/api_test.py          # core API (31)
python3 tests/api_vaults.py        # vault switching + import formats (39)
python3 tests/api_repair.py        # malformed-link detection + repair (32)
python3 tests/api_links.py         # link integrity + repair (25)
```

## Frontend
```bash
npm install jsdom
node tests/ui_import.mjs           # study-guide import flow    (20)
node tests/ui_graph_sim.mjs        # graph physics + hit testing (14)
node tests/ui_graph.mjs            # graph navigation           (20)
node tests/ui_topbar.mjs           # Crucible button + view state (18)
node tests/ui_crucible.mjs         # brand match, slide, category nav (24)
node tests/ui_deck.mjs             # fixed header, deck slide, tab cycling (25)
node tests/ui_cascade.mjs          # which CSS rule actually paints each mark (12)
node tests/ui_quiz.mjs             # quiz length slider (27)
node tests/ui_notes.mjs            # sort, tag filter, delete (33)
node tests/ui_flags.mjs            # flags shared across both sides (20)
node tests/ui_media.mjs            # media grouping + removal (22)
node tests/ui_repair_toast.mjs     # what the repair notice says (15)
node tests/ui_crumb.mjs            # vault name in header, context on the note (17)
node tests/ui_rename.mjs           # renaming the open vault (18)
node tests/ui_trail.mjs            # study group control + history + revert (24)
node tests/ui_links.mjs            # central link review (29)
node tests/ui_graph_tidy.mjs       # layout clutter, measured (7)
```

The UI suites exist because this is where bugs hid repeatedly, and always in
ways the backend tests could never catch:

- A `<label>` wrapping a file input *and* calling `input.click()`. The label
  already forwards activation, so the click bubbled back and re-fired. WKWebView
  never settles that, so the button silently did nothing. Shipped twice.
- The graph ran full-strength forces every frame forever, so it never stopped
  moving and nodes were a moving target to click.

`ui_graph_sim.mjs` asserts numbers rather than vibes: the layout comes to a
complete stop within 180 ticks (~2s at 60fps), kinetic energy decays
monotonically, the result is deterministic across runs, coincident nodes
separate without dividing by zero, and hit testing round-trips through
arbitrary pan/zoom transforms.

`ui_graph.mjs` stubs `getContext()` to return `null`, which also proves the
interaction layer never assumes a canvas exists.

`ui_cascade.mjs` exists because of a bug the other suites could not see. The
Crucible palette was computed correctly and written to the right custom
properties — `ui_deck.mjs` proved that — but `.mark i` is specificity (0,1,1)
and beat a bare `.cruc-mark` at (0,1,0), so the element painted Tephra's
gradient regardless. Asserting the inputs was not enough; this suite resolves
the cascade by hand and asserts which rule wins for a given property on a
given element.

`ui_graph_tidy.mjs` measures clutter rather than describing it: nearest-neighbour
spacing, node overlaps, and edge crossings across each layout. Numbers on the
79-node shape the FB guide produces — clustering took crossings from 32 to 23,
and the radial tree to 0 with no settling at all.
