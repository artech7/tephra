# Task: remove vaults from the app

Two new actions in the vaults panel. They are deliberately separate, because
they make different promises about the user's files.

**Forget** — drop the path from the recents list. No filesystem write at all.
Reversible by pasting the path back into "Open existing".

**Move to Trash** — send the vault folder to the system Trash, and forget it in
the same operation. Recoverable via Finder's Put Back until Trash is emptied.

Do not rename the folder in place with a dot prefix. That is exactly the
failure `tools/find_vaults.py --recover` exists to clean up: Finder hides
dotfiles and the vault appears to have vanished.

`vault/.trash` (used for notes and media) does not compose here — a vault has
no enclosing vault to trash into.

---

## Dependency

Add `send2trash` to `requirements.txt` (runtime, not dev — the app imports it).

It is approved. Rationale: it handles `/Volumes/X/.Trashes` for external
drives and the Windows Recycle Bin, both of which matter because we ship a
Windows installer. A hand-rolled `shutil.move` to `~/.Trash` fails with EXDEV
the moment a vault lives on another filesystem.

`requirements_fingerprint()` in run.py hashes requirements.txt, so adding the
line makes the next `python3 run.py` rebuild the venv automatically. No manual
step needed.

Import it lazily inside the endpoint, not at module scope, so a missing
package degrades to a clear 500 on one route rather than breaking app start.

---

## Backend

### `app/settings.py`

```python
def forget_vault(path: str | Path) -> dict:
    """Drop a path from recents. The folder is not touched."""
```

Resolve the path the same way `remember_vault` does (`Path(p).expanduser().resolve()`)
so an unresolved `/tmp` argument still matches a stored `/private/tmp` entry.
Leave `cfg["vault"]` alone — callers must never forget the open vault.

### `app/main.py`

```
POST /api/vault/forget   {"path": "..."}
POST /api/vault/trash    {"path": "...", "confirm": "<folder name>"}
```

Both return the same shape as `/api/vault/list` so the panel can re-render from
the response without a second round trip.

Guardrails, all returning a message the UI can show verbatim:

| Condition | Status |
|---|---|
| path is the currently-open vault | 409 |
| path is not in recents | 404 |
| trash: `confirm` does not match the folder's basename | 400 |
| trash: it is the only vault in recents | 409 |
| trash: folder no longer exists | forget it instead, return 200 |

Refusing to trash the open vault is what keeps this safe: the app holds a live
SQLite connection into the current vault only, so any other vault can be moved
without touching the index. Do not add close-and-reopen logic — refuse instead.

---

## Frontend

### `app/static/app.js` — `renderVaults()`

Each non-current row gets a small `×` control. It must `stopPropagation`, or it
will also fire the row's `onclick` and switch to the vault being removed.

Rows already carry a `missing` class when the folder is gone. Those are the ones
users most want to clear, so the `×` should be visible (not hover-only) on them.

Clicking `×` opens a small inline confirm in the row, matching how
`#renameRow` already works — not a `window.confirm`:

- Missing folder → one button, "Remove from list".
- Existing folder → two buttons, "Remove from list" and "Move to Trash", plus a
  text input for the folder name that enables the Trash button only on an exact
  match.

Copy rules: "Remove from list" never says delete. "Move to Trash" says Trash.
Toasts follow the existing house voice — `Moved "X" to the Trash`, `Removed "X"
from the list — the folder is still at <path>`.

### `app/static/style.css`

`.vaultrow` is a button; the `×` must not be a nested `<button>` inside it.
Restructure to a wrapping div, or use a sibling positioned over the row. Nested
interactive elements are invalid HTML and behave inconsistently in WKWebView.

---

## Tests

### `tests/api_vaults.py`

Extend the existing suite. Cover: forget removes from recents and leaves the
folder on disk; forget refuses the current vault; forget of an unknown path
404s; trash moves the folder and drops it from recents; trash refuses a
mismatched `confirm`; trash refuses the open vault; trashing an
already-missing folder still cleans the recents entry.

For the trash tests, monkeypatch `send2trash` — the suite must not put real
folders in the developer's Trash.

### `tests/ui_vault_remove.mjs`

New suite in the style of `ui_rename.mjs`. Assert that the `×` does not trigger
a vault switch, that the Trash button is disabled until the typed name matches
exactly, and that a missing-folder row offers only "Remove from list".

---

## Definition of done

`./run-tests.sh` passes all suites, including the two new ones. Then verify by
hand: remove a dead `/private/tmp` entry (if any remain), and trash a scratch
vault created for the purpose — confirming it lands in Trash with Put Back
available.
