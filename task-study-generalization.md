# Task: remove FB-specific naming so the app ships to anyone

## Why

Tephra was built around a personal FB study guide, and traces of that are
baked into module names, a hardcoded note title, and UI copy. A new user
importing their own guide should never see the letters "FB" anywhere.

## Scope — read this before starting

Three different things get conflated under "FB remnants." Only one is in
scope.

**In scope: FB-shaped naming.** One module name, one hardcoded constant, one
UI string, two comments. Shallow and cosmetic.

**Not in scope: the Study feature.** ~20 `/api/study/*` endpoints, quiz,
spaced repetition, categories, progress tracking. This is a general
capability that works on anything `importers.py` can parse. It is not a
remnant. Whether Tephra should ship with a study mode at all is a product
decision, and it should not be smuggled into a renaming task.

**Already clean: the data.** The guide itself lives in a vault, never in the
repo.

`importers.py` is already generic — `parse_python`, `parse_json`,
`parse_csv`, an `ALIASES` table absorbing column-naming variation, a
`FORMATS` registry and a `PARSERS` dict keyed on extension. It is a pluggable
importer system. Do not rewrite it; it is already the shape this task assumes.

## Complete inventory

Every FB reference in the codebase:

| Location | What it is |
|---|---|
| `app/fb_import.py` | Module name |
| `app/fb_import.py` | `ROOT_NOTE = "FB Study Guide"` — hardcoded |
| `app/fb_import.py` | Docstring |
| `app/main.py:14` | `from . import fb_import` |
| `app/main.py:658` | Docstring naming `fb_study_guide.py` |
| `app/main.py:670` | `fb_import.run_import(...)` |
| `app/static/study.js:552` | Empty-state copy naming the FB guide |
| `app/importers.py:139` | Comment referencing the original FB guide |
| `tools/import_fb_guide.py` | Entire file (also removed by tools consolidation) |

Confirm this is complete before starting — the inventory came from a partial
snapshot:

```bash
git grep -in 'fb[_ ]\|facebook' -- '*.py' '*.js' '*.mjs' '*.html' '*.md'
```

Anything not in the table above needs a decision before proceeding.

---

## Step 1 — rename the module

```bash
git mv app/fb_import.py app/guide_import.py
```

Update the import and call site in `app/main.py`. Rewrite the module
docstring to describe what it does — importing a standalone study guide as a
set of notes — keeping the existing explanation of *why* it lives in `app/`
rather than `tools/` (the server knows its own vault; a CLI importer has to
be told and can be told wrong).

**Commit:** `Rename fb_import to guide_import`

## Step 2 — derive the root note title

`ROOT_NOTE = "FB Study Guide"` is the substantive change. The imported guide
gets a root note, and its title should come from the import rather than a
constant.

Order of preference:

1. An explicit title passed by the caller (add an optional field to the
   `POST /api/study/import` payload)
2. A title found in the parsed guide, if the format carries one
3. The uploaded filename, stripped of extension and tidied
   (`my_guide.py` → "My Guide")
4. Fall back to `"Study Guide"`

Keep `ROOT_NOTE` as the step-4 default only, renamed to `DEFAULT_ROOT_NOTE`.

Note the interaction with existing vaults: notes already titled "FB Study
Guide" keep that title, because renaming them would break every wikilink
pointing at them. This change affects new imports only. Say so in the commit
message — a future reader will wonder.

**Commit:** `Derive imported guide root note title instead of hardcoding`

## Step 3 — UI copy

`app/static/study.js:552` currently names the FB guide in the empty state.
Rewrite generically — something to the effect of importing a study guide, or
marking any note as a study item from the editor.

While in there, check the rest of the Study tab for copy that assumes a guide
has already been imported. The empty state is what a new user sees first, and
it should read as an invitation rather than a reference to someone else's
document.

**Commit:** `Generalize study tab empty-state copy`

## Step 4 — comments

`app/importers.py:139` references the original FB guide when explaining a
parsing decision. The explanation is worth keeping; the reference is not.
Rewrite to describe the format shape itself, since that is the actual reason
the code is written that way.

**Commit:** `Drop FB references from comments`

## Step 5 — the first-run path

The stated goal is that a new user can either import an existing vault or
start fresh. Verify both actually work, since this is the part most likely to
have never been tested by anyone who is not you:

- Point `TEPHRA_VAULT` at an empty directory. Confirm the starter vault is
  created (`welcome-to-tephra.md`, `vault-layout.md`,
  `linking-and-the-auto-wiki.md`) and that its content reads as an
  introduction to Tephra, with no assumption of a study guide.
- Point it at a directory of plain markdown that was never a Tephra vault.
  Confirm it indexes, links resolve, and nothing errors on the missing
  `.index/`.
- Confirm the Study tab is coherent when no study items exist at all.

Fix what breaks. This is likely where the real work is, rather than in the
renaming.

**Commit:** `Fix first-run path for new and imported vaults`

---

## Checkpoints

`./run-tests.sh` after every commit. Watch specifically for tests that assert
on the string `"FB Study Guide"` — step 2 will break those, and the fix is to
assert on the derived title rather than to restore the constant.

Final sweep:

```bash
git grep -in 'fb[_ ]\|facebook' -- '*.py' '*.js' '*.mjs' '*.html'
```

Should return nothing outside of `CHANGELOG`-style history.

## Out of scope, worth recording

Making the Study feature optional — a config flag hiding the tab and its
routes for users who want only a notes wiki. Genuinely useful, materially
larger than this task, and it should not ride along on a rename. Open it as
its own spec if it turns out to be wanted.
