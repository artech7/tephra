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

    ./run-tests.sh        all 47 suites; 629 backend assertions, 966 UI

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

## Working agreement

- Commit before starting; commit when tests pass.
- Develop against ~/Documents/Tephra-dev, never a real vault.
- Ask before adding a dependency, a framework, or a build step.
