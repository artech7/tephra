# Task: collapse `tools/` into the app

## Why

Three of the five files in `tools/` duplicate functionality the app already
serves as endpoints, and two are misfiled. Since deployment moved to Docker,
every CLI invocation now costs a `docker compose exec`, container-relative
paths, and a shell that isn't where the notes are. A CLI utility is a worse
deal on a server than it was on the desktop.

Two of the scripts already say this themselves — `tools/repair.py` and
`tools/import_fb_guide.py` both open with docstrings telling the reader to
prefer the in-app control.

## Current contents of `tools/`

| File | Verdict |
|---|---|
| `repair.py` | Delete — duplicates `POST /api/repair` |
| `import_fb_guide.py` | Delete — duplicates `POST /api/study/import` |
| `find_vaults.py` | Promote discovery into the app; keep `--recover` only |
| `api_repair.py` | Move to `tests/` — it is a test |
| `links.js` | Resolve against `app/static/links.js` |

## Verify first

The analysis behind this spec was done against a partial snapshot, not the
repo. Confirm before deleting anything:

```bash
cd ~/Documents/tephra
git checkout -b cleanup

# Is tools/links.js a duplicate of the real frontend module?
md5sum tools/links.js app/static/links.js

# Does tools/repair.py contain anything beyond an argparse wrapper
# around idx.repair_links()?
cat tools/repair.py

# Does tools/api_repair.py import TestClient? (-> it is a test)
head -10 tools/api_repair.py
```

Stop and reassess if any of these disagree with the table above.

---

## Step 1 — delete `tools/repair.py`

`POST /api/repair?dry_run=<bool>` calls the same `idx.repair_links()`. The
endpoint is strictly better: it also runs `idx.rebuild()` and
`st.ensure_fitted(..., force=True)` afterward, which the CLI reimplemented by
hand and got only partly right.

Replacement for headless use:

```bash
curl -sX POST 'http://localhost:8080/api/repair?dry_run=true' | python3 -m json.tool
curl -sX POST 'http://localhost:8080/api/repair'
```

Document those two lines in `README.md` where the script was documented.

**Commit:** `Remove tools/repair.py; /api/repair covers it`

## Step 2 — delete `tools/import_fb_guide.py`

`POST /api/study/import` covers this, and the script's own docstring says the
server-side path cannot write to the wrong vault whereas the CLI can. Note
this file is also removed by `task-study-generalization.md`; whichever lands
first, the other should drop the step rather than conflict.

**Commit:** `Remove tools/import_fb_guide.py; /api/study/import covers it`

## Step 3 — promote vault discovery into the app

This is the only genuinely non-duplicated logic in `tools/`, and it fixes a
real UX problem: the vault picker is a bare text field, so opening a vault
means typing an absolute container path by hand.

### 3a. Move the traversal

Move `walk()` from `tools/find_vaults.py` into `app/vault.py`. Keep its
existing behaviour: depth limit of 4, skip `node_modules` / `Library` /
`.git` / `.venv`, skip symlinks, and do not descend into a directory once it
is identified as a vault.

**Delete `find_vaults.py`'s `is_vault()`.** `app/vault.py` already has
`looks_like_vault()`, which `GET /api/vault/list` uses. Two parallel
implementations of "is this a vault" will drift. Use the existing one.

### 3b. Add the endpoint

```
GET /api/vault/browse?path=<dir>
```

Returns immediate subdirectories of `path`, each flagged with whether it
looks like a vault:

```json
{
  "path": "/vaults",
  "parent": "/",
  "entries": [
    {"name": "Pure1", "path": "/vaults/Pure1", "is_vault": true},
    {"name": "Archive", "path": "/vaults/Archive", "is_vault": false}
  ]
}
```

Default `path` to the parent of the current vault, matching the
`suggested_parent` that `/api/vault/list` already returns.

### 3c. Containment — this is the security-sensitive part

The app has no authentication. A path parameter that walks the filesystem is
the one place where that matters, so it needs care rather than a quick check:

- Resolve with `Path(p).resolve()` **before** any containment check, so
  symlinks cannot escape.
- Reject anything not under a configured root. Default the root to the parent
  of the current vault; make it overridable via `TEPHRA_BROWSE_ROOT`.
- Reject `..` after resolution, not before.
- Return 403 rather than 404 on a containment failure, so the response does
  not confirm whether a path outside the root exists.
- Never follow symlinks out of the root even if the target is readable.

Add tests for each of these. Traversal is the kind of bug that is trivially
exploitable and easy to reintroduce.

### 3d. Frontend

In the vault picker, add a browse modal: list directories, mark vaults,
click to descend, click a vault to open it, plus an "up" control. **Keep the
text field** — it is the escape hatch when a vault lives somewhere the
browse root does not cover.

**Commit:** `Add GET /api/vault/browse and vault picker browse modal`

## Step 4 — keep a recovery-only script

Retain `--recover` from `find_vaults.py` as `tools/recover_vaults.py`, scoped
to one job: renaming back strays left by an interrupted vault rename
(`.something.tephra-renaming`, which Finder hides).

This one stays a script deliberately. It repairs a vault that may be broken
badly enough that the app will not start, and a recovery tool that requires
the server running is not a recovery tool. `docker compose exec` works even
when uvicorn is crash-looping.

Strip the discovery/listing code — that lives in `app/vault.py` now, and the
script should import it rather than carry a copy.

**Commit:** `Narrow find_vaults.py to tools/recover_vaults.py`

## Step 5 — move the misfiled files

```bash
git mv tools/api_repair.py tests/api_repair.py
```

For `tools/links.js`: if `md5sum` matched `app/static/links.js`, delete it.
If it differs, diff them — one is stale, and which one is stale determines
whether this is a deletion or a lost change worth recovering.

**Commit:** `Move misfiled files out of tools/`

---

## Result

`tools/` goes from five files to one. Two endpoints absorb the deleted
scripts, one new endpoint replaces the third and gives the vault picker a
real browser, and `is_vault()` / `looks_like_vault()` stop being two
implementations of the same predicate.

## Checkpoints

Run `./run-tests.sh` after **every** commit, not just at the end. All 21
suites should pass throughout — this is a refactor, so any red is a real
regression rather than expected churn.

Manual checks before merging:

- Browse to `/vaults`, confirm all three vaults are flagged `is_vault: true`
- Open a vault from the browse modal; confirm it lands in recents
- `curl -sX POST 'localhost:8080/api/repair?dry_run=true'` returns a report
  and writes nothing
- Confirm a path outside the browse root returns 403
- Confirm a symlink pointing outside the root is rejected
