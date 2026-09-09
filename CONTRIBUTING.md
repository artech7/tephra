# Tephra

Self-hosted markdown notes app that grows a wiki out of your notes. Plain
markdown files on disk are the source of truth; everything else is derived.

## Layout

    app/                FastAPI server + static frontend
      main.py           routes, vault switching, lifespan
      index.py          SQLite/FTS5 index, link repair, phrase extraction
      vault.py          note read/write, slugify, path resolution
      render.py         markdown -> html
      study.py          Crucible: flashcards, quiz, fitting
      kb.py             KB Authoring: article templates, metadata schema
      kb_export.py      KB article -> ServiceNow / standalone / md / text
      settings.py       config file, recent vaults
      importers.py      study-guide import (json / py / csv / md)
      fb_import.py      FB study guide importer
      static/           app.js graph.js links.js study.js kb.js index.html style.css
    desktop/launcher.py webview window, loopback port, origin check
    tools/              operator scripts; NOT imported by the app
    tests/              api_*.py (python) + ui_*.mjs (node) + fixtures/
    packaging/          PyInstaller inputs, iconset, Inno Setup, entitlements
    .github/workflows/  installer builds

## Running

    python3 run.py                 native window, vault from config
    python3 run.py --headless      server only -- use this for agent work
    python3 run.py --vault ~/X     different vault
    python3 run.py --browser       browser tab instead of a window
    python3 run.py --reinstall     rebuild .venv from scratch
    python3 run.py --no-venv       current interpreter as-is

Python 3.10+. First run builds .venv/ and re-execs into it.

Dev vault is ~/Documents/Tephra-dev (disposable). Real notes live in
~/Documents/"FB Study" (94 notes) and ~/Documents/Pure1 -- never test
against those.

## Tests

    ./run-tests.sh        all 51 suites; 865 backend assertions, 1218 UI

It prints one line per suite (PASS/FAIL/CRASH plus that suite's count), an
overall percentage, and every failing check grouped by suite. The verbose
output goes to test-results.log -- gitignored locally, uploaded as a CI
artifact. CRASH means the suite died before printing its own tally, so its
counts are unknown and the reason is only in the log.

Run it before every commit. How the runner invokes things is not incidental:

- Backend suites need `PYTHONPATH=. .venv/bin/python`. Bare `python3` picks
  up system Python and fails on `fastapi`; without PYTHONPATH, `from
  app.main import app` fails because Python puts tests/ on the path, not the
  repo root. The venv is never activated -- run.py re-execs into it.
- `httpx` is a test-only dependency, listed in requirements-dev.txt and
  deliberately absent from requirements-run.txt. Install with
  `.venv/bin/python -m pip install -r requirements-dev.txt`.
- UI suites need jsdom (`npm install`). package.json and package-lock.json
  are both tracked.

The UI suites catch what the backend cannot, and they assert numbers rather
than vibes -- graph layout stops within 180 ticks, kinetic energy decays
monotonically, results are deterministic across runs, edge crossings are
counted. ui_cascade.mjs resolves the CSS cascade by hand because asserting
computed inputs missed a specificity bug ((0,1,1) beating (0,1,0)) that
painted the wrong gradient. Treat these numbers as contracts: if a change
makes them worse, the change is wrong, not the test.

## KB Authoring

The third deck, beside Tephra and Crucible. A KB article is an ordinary note
carrying a `kb_type` frontmatter key -- there is no second store, and
`vault.parse`/`vault.dump` already round-trip arbitrary extra keys, so no
schema changed to add this.

Templates and the metadata schema are both *data* (`TEMPLATES` and `FIELDS`
in app/kb.py). Adding an article type or a field is one entry; the authoring
form, the structure panel and the export header are all generated from those
two lists, so nothing in the frontend needs touching.

These facts come from a published article, not from guesswork -- a saved
page of a real KB article was read to settle them, and the assertions in
tests/api_kb.py pin them:

- **`<style>` blocks are not stripped.** Every field of every published
  article carries the same house stylesheet (Inter body, cream `code`,
  dark `pre` with a Pure-orange left border, `td{padding:16px !important}`).
  So `kb_export.HOUSE_STYLE` is that block, byte for byte, prepended to each
  rich-text fragment -- and `code`/`pre` are deliberately left *bare* by the
  inliner, because an inline style would make a Tephra article the one whose
  code blocks look different from every other article in the KB.
- **Internal links are `https://kb.purestorage.com/csm?id=kb_article_view&sysparm_article=KB…`**,
  not the platform-UI `kb_view.do` form.
- **Nested ordered lists run 1 -> A -> i -> I**, via `list-style-type` on
  each `<ol>`. Applied by depth after markdown-it, which knows nothing of it.
- **`<br>` inside a table cell is everywhere** (one article holds 108), so
  the export parser carries render.py's `raw_br` rule. Without it the export
  silently reflows their tables onto one line.

The destination KB has **no article body**. It has a form -- "Question and
Answer" -- with five separate rich-text boxes (Question, Environment, Answer,
Additional Information, Internal Notes), a Short description input, and a
plain Meta textarea capped at 4000 characters. One form serves every article
kind; Category is a separate taxonomy from the layout. So the ServiceNow
export does not produce a document, it produces one fragment per box, and
the export panel is a walk down the form rather than a single copy button.

Every template section names the field it feeds (`Section.field`), and
`kb_fieldmap` in an article's own frontmatter overrides that per article for
the section the template never imagined. An unmapped heading falls back to
Answer rather than being dropped: content that quietly goes nowhere is the
failure mode worth engineering against.

Export is the reason the feature exists: articles have to leave for a
ServiceNow KB that has never heard of Tephra's stylesheet. So export is a
deliberate downgrade, not a dump of the app's HTML:

- `servicenow` inlines every style on the element and gives tables
  presentational attributes as well as CSS. No classes, no `<style>`.
  Callouts become single-cell bordered tables -- a div flattens in a
  sanitiser, and a warning that flattens into a paragraph stops reading as
  a warning. Returns `parts`, not just `content`.
- `standalone` is the faithful artifact: self-contained page, embedded
  stylesheet, contents list, images inlined as data URIs.
- `markdown` and `text` are for fields that accept nothing else.

Syntax parsing is *imported* from render.py, never copied -- the same
regexes and the same sheet splitter -- so an article cannot mean one thing
on screen and another on export. Only emission differs, which is the part
that genuinely has to.

Deleting an article is the ordinary note delete (`DELETE /api/notes/{slug}`),
deliberately -- an article *is* a note, so it goes to `vault/.trash` and stays
recoverable rather than getting a second, harsher path of its own. The KB
deck's Delete sits next to Release, which drops only the `kb_` fields and
destroys nothing; both use the note editor's arm-then-confirm gesture. Delete
clears the pending autosave first: a debounced flush landing after the delete
writes the file straight back out of the trash.

Images are never silently dropped: each becomes a numbered placeholder plus
a manifest row, numbered in *document* order. That ordering is deferred
(see `_Media.finalize`, which returns a *resolver* rather than a string)
for two reasons: callouts and sheets are extracted before the passes that
follow them, so the order media is met is not the order it appears in; and
the numbering has to be decided once over the whole document and then
applied to each field fragment separately, or images restart at 1 in every
box.

The preview iframe renders the *form*, one labelled box per field, not a
flowing document -- and carries no stylesheet beyond the box chrome, so what
survives in the preview is what survives the paste. A preview using the
app's own CSS would be a comfortable lie.

### Anchors

Jump links use **ordinary markdown** -- `[text](#heading-id)` -- and no syntax
of Tephra's own, so an article carrying them reads the same in any other
markdown tool. `kb_export.heading_id()` derives the id from the heading text,
and `/api/kb/{slug}/render` returns the headings with the ids *that same
function* will give them, so a link the picker writes is a link that still
lands after the paste.

Two rules keep them alive through the export:

- `_apply_heading_ids()` runs once over the whole article, before anything is
  split into fields, so the document view and the per-field fragments agree
  on every id. Computed per view they would drift apart the moment a heading
  appeared twice.
- `_field_parts()` normally drops a section's heading when its field is fed
  by exactly one section -- the field *is* the heading. It keeps it when
  something links to it, because dropping the one thing a link points at
  turns that link into a jump to nowhere.

A link with no matching heading is a warning before publishing, not a silent
dead jump.

That anchors work at all is evidence, not assumption: a published article
carries a `<pre id="t_adding_the_blade_to_the_cluster__...">` pasted in from
the docs site that survived a save, so `id` attributes are not stripped. The
five form boxes render into one page, which is what lets a jump link in
Question reach a heading in Answer.

### The block palette

`BLOCKS` in app/kb.py is a list of draggable snippets -- data, like the
templates and the field schema, so adding a block is one entry and nothing
else. A block is **a way of writing markdown without typing the syntax**,
never a second document format: dropping one splices its `snippet` into the
same textarea you could have typed into, and the file on disk stays markdown.
`select` is the substring the editor highlights afterwards, so the first
thing typed replaces the placeholder.

Write mode is four columns: article list, palette, markdown, and a right
column shared by the live render (default), the structure panel and the
metadata form. All three dividers drag, and the right column collapses to
nothing when you want the width for writing -- widths and the collapsed flag
live in localStorage. The grips reuse the notes sidebar's own mechanism from
app.js (a CSS custom property on the root, document-level mousemove, clamped,
`body.resizing-sidebar`) rather than a second one; the markdown column is the
`1fr` that absorbs whatever the others give up.

Collapse is scoped `:not(.kb-exporting)` -- the same column holds the export
copy buttons in export mode, and a collapse meant for the render would take
those with it.

`split_blocks()` cuts a body into top-level blocks on blank lines, ignoring
blank lines inside a fence -- a ```sheets card split down the middle is not a
card. `GET /api/kb/{slug}/render` returns those blocks each with its source
line range and its HTML, and that range is the whole trick: an insertion
between two rendered blocks is a splice at a known line number rather than a
guess at where a pixel position falls in the source.

The authoring preview deliberately uses **render.py**, not the exporter --
it is what you write beside, so it should look like the rest of Tephra. Only
the *export* preview shows the destination's look. `enhanceMermaid`,
`enhanceCodeBlocks`, `tephraSheets.enhance` and `tephraNetDiagram.enhance`
all take an optional root now (defaulting to `#noteBody`, so every existing
caller is unchanged) and `window.tephraEnhanceRendered(root)` runs the set --
one implementation, two hosts.

## Invariants

- Markdown files on disk are the source of truth. The index is derived and
  disposable: deleting .index/ must lose nothing.
- Links live in the note text, not in the database. Accepting a suggestion
  rewrites the .md file.
- Single user, loopback only, no authentication. This is deliberate.
- The frontend has no framework and no build step. Keep it that way.
- The desktop build is the server build plus a window. Never a second
  implementation of anything.
- The vault never lives inside an app bundle or any installer-replaceable
  directory.
- run.py imports only the standard library. It runs before any dependency
  exists.
- Tests must never hardcode an absolute path. Resolve relative to the test
  file: `new URL('../app/static', import.meta.url).pathname` in .mjs,
  `os.path.dirname(__file__)` in .py. Both suites shipped with container
  paths baked in and neither had ever run outside that container.

## Traps

- `config_dir()` is duplicated in app/settings.py, desktop/launcher.py, and
  (as `config_path()`) tools/recover_vaults.py. Change one, change all three.
  Each checks `TEPHRA_CONFIG_DIR` before the platform branch -- that
  override exists so tests can isolate their config, because the macOS
  branch is reached before `XDG_CONFIG_HOME` is ever consulted.
- Moving the project folder invalidates .venv: console scripts bake in
  absolute paths, so `.venv/bin/pip` breaks while `.venv/bin/python` still
  works, which makes it look like a package problem. Fix with
  `python3 run.py --reinstall`. Prefer `python -m pip` over `bin/pip`.
- macOS resolves /tmp to /private/tmp. The app resolves vault paths, so a
  test comparing against an unresolved literal fails on two names for the
  same directory. Use `os.path.realpath`.
- Close the index connection before vault paths move, or the next write
  lands in the previous vault's database.
- `inside_our_venv()` compares sys.prefix, not sys.executable: a venv's
  bin/python symlink resolves to the system interpreter and the check
  silently passes while outside the venv.
- Link rewriting must skip protected regions (code fences, existing links).
- A `<label>` wrapping a file input must not also call `input.click()`. The
  label already forwards activation; WKWebView never settles the re-fire and
  the button silently does nothing. This shipped twice.
- Vault rename goes through the app. Renaming in Finder leaves a dead
  recents entry pointing at an absolute path.
- vault.py's frontmatter parser is a fixed-schema one, not YAML: a value is
  one line, `[...]` means a list, and list items split on commas. Anything
  writing free text into a header has to normalise for all three -- see
  kb.py's `_scalar`/`_list`, which is where a KB keyword containing a comma
  or a description starting with `[` would otherwise corrupt the file.
- The three decks (Tephra, Crucible, KB) are driven by one `setDeck(name)`
  in app.js, not by a boolean each. Two independent toggles can put two
  opaque full-deck panes on screen at once, and the loser is invisible
  rather than visibly wrong.

## Working agreement

- Commit before starting; commit when tests pass.
- Develop against ~/Documents/Tephra-dev, never a real vault.
- Ask before adding a dependency, a framework, or a build step.
