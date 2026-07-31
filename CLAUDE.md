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
      settings.py       config file, recent vaults
      importers.py      study-guide import (json / py / csv / md)
      fb_import.py      FB study guide importer
      static/           app.js graph.js links.js study.js index.html style.css
    desktop/launcher.py webview window, loopback port, origin check
    tools/              operator scripts; NOT imported by the app
    tests/              api_*.py (python) + ui_*.mjs (node, needs jsdom)
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
Dev vault is ~/Documents/Tephra-dev. Real notes are in ~/Documents/"FB Study"
(94 notes) and ~/Documents/Pure1 -- never test against those.

## Tests

127 backend assertions, 345 UI. Run ./run-tests.sh before every commit.

    python3 tests/api_test.py          core API (31)
    python3 tests/api_vaults.py        vault switching + import formats (39)
    python3 tests/api_repair.py        malformed-link detection + repair (32)
    python3 tests/api_links.py         link integrity + repair (25)

UI suites need jsdom (`npm install jsdom`), no package.json by design:

    node tests/ui_import.mjs       node tests/ui_notes.mjs
    node tests/ui_graph_sim.mjs    node tests/ui_flags.mjs
    node tests/ui_graph.mjs        node tests/ui_media.mjs
    node tests/ui_topbar.mjs       node tests/ui_repair_toast.mjs
    node tests/ui_crucible.mjs     node tests/ui_crumb.mjs
    node tests/ui_deck.mjs         node tests/ui_rename.mjs
    node tests/ui_cascade.mjs      node tests/ui_trail.mjs
    node tests/ui_quiz.mjs         node tests/ui_links.mjs
                                   node tests/ui_graph_tidy.mjs

The UI suites catch what the backend cannot, and they assert numbers rather
than vibes -- graph layout stops within 180 ticks, kinetic energy decays
monotonically, results are deterministic across runs, edge crossings are
counted. ui_cascade.mjs resolves the CSS cascade by hand because asserting
computed inputs missed a specificity bug ((0,1,1) beating (0,1,0)) that
painted the wrong gradient. Treat these numbers as contracts: if a change
makes them worse, the change is wrong, not the test.

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

## Traps

- tools/api_repair.py and tests/api_repair.py are DIFFERENT files.
- Close the index connection before vault paths move, or the next write
  lands in the previous vault's database.
- inside_our_venv() compares sys.prefix, not sys.executable: a venv's
  bin/python symlink resolves to the system interpreter and the check
  silently passes while outside the venv.
- Link rewriting must skip protected regions (code fences, existing links).
- A <label> wrapping a file input must not also call input.click(). The
  label already forwards activation; WKWebView never settles the re-fire and
  the button silently does nothing. This shipped twice.
- Vault rename goes through the app. Renaming in Finder leaves a dead
  recents entry pointing at an absolute path.

## Working agreement

- Commit before starting; commit when tests pass.
- Develop against ~/Documents/Tephra-dev, never a real vault.
- Ask before adding a dependency, a framework, or a build step.
