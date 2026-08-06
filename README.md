# Tephra

A self-hosted notes app that grows its own wiki.

Your notes are plain markdown files in a directory you control. Tephra reads
them, links them, and finds the connections you didn't make yourself.

---

## Quick start

```bash
docker compose up -d --build
```

Open <http://localhost:8080>. It seeds three notes on first run so the app
isn't empty.

To match file ownership to your host user (recommended, avoids root-owned
files in `./vault`):

```bash
UID=$(id -u) GID=$(id -g) docker compose up -d --build
```

Change the port with `TEPHRA_PORT=9000 docker compose up -d`.

### Without Docker

```bash
pip install -r requirements.txt
TEPHRA_VAULT=./vault uvicorn app.main:app --port 8000
```

---

## Vaults

A vault is a self-contained folder: its own notes, media, study progress and
theme. Nothing is shared between them.

Open the folder icon in the header (`⌥V`) to switch, or type a path and hit
**Create**. Recently used vaults are remembered in the platform config
directory — the one piece of state that cannot live in a vault, since it records
which vault to open.

**If your vault seems to have vanished**, it is almost certainly still there:

```bash
python3 tools/recover_vaults.py            # report hidden strays
python3 tools/recover_vaults.py --recover  # rename them back into view
```

A case-only rename needs two moves on a case-insensitive filesystem, and the
halfway state is a dot-prefixed folder that **Finder does not display**. An
interrupted rename could leave a vault sitting in plain sight but invisible.
Tephra now puts it back if the second move fails, and recovers any stray it
finds on the next start — but the tool is there for one left by an older build.

**Renaming.** Use *Rename this vault* in the drawer rather than Finder. A vault
is only ever a folder, so renaming it outside works — but the app records an
absolute path, which would leave a dead entry in recents and a vault that will
not reopen. The in-app rename moves the folder and updates the config together.
Case-only renames (`tephra` → `Tephra`) go via a temporary name, because on a
case-insensitive filesystem they are otherwise a no-op.

Switching repoints the running server and rebuilds its index; no restart. The
path field takes `~` and must be absolute. Creating over an existing vault is
refused, and opening a folder with no `notes/` directory is refused, so a typo
cannot scatter a vault across your home folder.

## Your data

Everything lives in the directory mounted at `/vault`:

```
vault/
├── notes/          one markdown file per note, YAML frontmatter
├── media/          images, video, audio, attachments
├── theme.json      appearance settings
├── .index/         SQLite cache — delete it any time
└── .trash/         deleted notes, kept rather than destroyed
```

The markdown files are the source of truth. The index is derived and
disposable: delete `.index/index.db` and restart, or `POST /api/reindex`, and
it rebuilds by rescanning the vault. That also means **you can edit notes
outside the app** — write markdown into `notes/` with any editor and hit
reindex to pick it up.

Because it's just files, version history is free:

```bash
cd vault && git init
# then, from cron:
git add -A && git commit -m "snapshot $(date -Iseconds)" || true
```

---

## Writing

| Syntax | Result |
|---|---|
| `[[Note Title]]` | Link. Amber if the note doesn't exist — click to create it. |
| `[[Note Title\|shown text]]` | Link with different display text. |
| `![[picture.png]]` | Embed. Resolved to image / video / audio / download by extension. |
| `![[picture.png\|400]]` | Embed sized to 400px wide (or `\|50%` of the column) — Obsidian's own convention, so it isn't a new idea to learn. |
| `![[picture.png\|caption\|400]]` | Caption and size together. |
| A URL alone on a line | Bookmark card. |

Everything else is standard markdown — headings, lists, tables, code fences,
blockquotes.

**Resizing an image.** Hover it and drag a corner — the same click-and-drag
gizmos as any slide editor, uniform scaling only (the image keeps its own
aspect ratio, so there's no distorting it). The width is written back into
the `![[...]]` line itself, so it's just text and survives outside Tephra.

**Side by side.** Put two or more embeds on adjacent lines, with no blank
line between them, and they lay out as a row instead of stacked:

    ![[before.png]]
    ![[after.png]]

A blank line between two embeds keeps them stacked, same as today.

**Rearranging.** Drag an image (by anywhere on it except a resize corner)
and drop it on another — the left half of the target inserts before it, the
right half inserts after, joining that image's row if it's part of one.
Building a grid is just doing this a few times: drop images next to each
other to form a row, drop one onto a different row to move it there. Saves
immediately, not on the usual autosave delay, since a drop is a deliberate,
discrete action rather than a keystroke.

**Saving is automatic.** There is no save button. Typing debounces for 700 ms
then writes; switching notes, leaving the tab, or closing the window flushes
immediately. Writes are atomic (temp file + rename), so an interrupted save
can't truncate a note. `⌘S` is intercepted and just confirms what already
happened.

### Keys

| | |
|---|---|
| `⌘K` | Search, jump, or create by typing a new title |
| `⌘E` | Toggle markdown source / rendered |
| `⌥G` | Graph view |
| `⌥N` | New note |
| `⌥T` | Appearance |

Drag files anywhere onto the editor to attach them.

---

## The auto-wiki

The panel on the right is the part that does work you'd otherwise never get
around to. It surfaces two things:

- **Unlinked mentions** — a page exists and you wrote its name in prose
  without linking it.
- **Emerging terms** — a phrase recurs across three or more notes and has no
  page yet. That's a concept you clearly have that your vault doesn't know
  about.

Accepting a suggestion creates the page if needed, then rewrites every
plain-text mention across the vault into a real link. **Your markdown files
change on disk** — deliberately. Links belong in the notes, not in a database
that could disappear.

### Link safety

The linker never writes inside a span it shouldn't. Two rules, both learned the
hard way:

- **Existing links are off limits.** Rewriting inside `[[Answer Ping|answer ping]]`
  produced `[[Answer [[Ping]]|answer ping]]`, which renders as raw brackets.
- **Quiz blocks are data, not prose.** Links injected there showed up as literal
  markup in questions and options, because the quiz renders plain text.

If a vault already has damage, **Vaults → Check links** audits read-only and
offers a repair. Repair flattens nested links keeping the text, strips markup
back out of quiz blocks keeping display text, and removes empty `[[]]` husks. It
rewrites the markdown, so the fix is in the files; it is idempotent, and
`GET /api/audit` / `POST /api/repair` expose it.

Phrase extraction is heuristic: an n-gram window with stopword and
grammatical-boundary filtering, a preference for proper nouns, and
suppression of phrases that are fragments of longer ones. It is tuned to
under-suggest rather than spam you. Tune `MIN_DOCS` and the `BOUNDARY` list
in `app/index.py` to taste. Verb forms like `answer`/`respond`/`return` are
excluded — "does not answer ping" was being extracted as the concept
"answer ping", which then became a note and got linked across the vault.

---

## Content check

If a note ever shows text like `[[Answer [[Ping]]|answer ping]]`, that is
damage, not a format. An earlier auto-linker substituted inside existing links,
so applying a suggestion for `Ping` could rewrite the *title half* of a link
that already existed. The linker now masks protected spans — wikilinks, embeds,
inline code and fenced code — so it cannot recur. But a vault it already damaged
stays damaged until something rewrites it.

**You should not have to do anything.** Repair runs automatically whenever a
vault is opened, and again on every vault switch. It is idempotent and
byte-identical on clean content, so there is no reason to hide it behind a
button — and it tells you what it did in a toast when the window comes up,
rather than changing your files silently. That notice is consumed on read, so
reloading doesn't re-announce work already done.

**Vaults → Content check** is there for when you want to see what it did:
*Check* previews with a before/after diff and writes nothing; *Repair* applies.

Four things get fixed:

- links nested inside other links, flattened to a single link — and the note
  that flattening names gets **created**, so `[[Answer [[Ping]]|answer ping]]`
  becomes a working link to a real (empty) `Answer Ping` note rather than a
  dead amber one. Created notes carry a `repaired` tag, so clicking that tag in
  the sidebar lists everything the repair invented for you to review, merge or
  delete.
- links written into `## Quiz` blocks, which belong as plain text
- the `question:` frontmatter header, which is flashcard prose, never a link
- empty `[[]]` husks

**Display never depends on the file being repaired.** Quiz questions, options and
explanations are stripped of wiki syntax when parsed, and the renderer flattens
nested links before it runs. Even a file nothing has rewritten yet shows
`answer ping`, not `[[Answer [[Ping]]|answer ping]]`.

Legitimate content is left byte-identical: real aliases (`[[Ping|pinging]]`),
embeds, inline code and fenced code all survive. The pass is idempotent.

Headless equivalent:

```bash
curl -sX POST 'http://localhost:8080/api/repair?dry_run=true' | python3 -m json.tool
curl -sX POST 'http://localhost:8080/api/repair'
```

`GET /api/audit` is a read-only check; `POST /api/repair?dry_run=true` previews.

## Graph layouts

Two, switchable in the graph toolbar:

- **Clustered** — force-directed, with an added pull toward each category's
  centroid so categories form visible lobes instead of one blob. Cuts edge
  crossings by about a third on a 79-node vault.
- **Tidy tree** — a radial hierarchy built from a BFS spanning tree. Your vault
  *is* hierarchical (a root note links to category indexes, which link to
  topics), so laying that out explicitly gives **zero edge crossings**, appears
  instantly with no settling, and is identical every time you open it.

Sibling wedges are allocated by a blend of descendant count and equal division.
Purely proportional starved small branches — a single-topic category got the
same sliver as one leaf and landed 16px from its neighbour.

Two clutter filters sit next to the layout picker:

- **Stubs** — hide notes that are referenced but not written yet.
- **Leaves** — hide single-link notes. On the imported guide that collapses the
  fringe of 62 topics and leaves the 14-node skeleton, which is often what you
  actually want to look at.

## Where you are

The header names the **vault**, not the note — the note already names itself in
its own heading, so repeating it there was duplication. Clicking it opens the
vault switcher.

The note's context sits above its heading instead: its study category, or its
tags when it has no category, and nothing at all when it has neither. The
category links to its index note and the tags filter the sidebar, so the line is
navigation rather than decoration. Because it lives in the editor it is simply
absent in Crucible.

## The notes list

Sort by recently edited (default), title, most linked to, most links out, type,
or length. The trailing number changes meaning with the sort, so hovering a note
spells out what it is counting.

Tags filter the list — click one to narrow, click it again or use **clear** to
release. Sort and tag selections persist to `theme.json` alongside the
appearance settings.

**Deleting** is a two-step button in the note's meta row: the first click arms
it, the second commits, and it disarms itself after four seconds. Notes move to
`vault/.trash/` rather than being destroyed, so a mistake is recoverable with
`mv`.

## Media

Grouped into Images / Video / Audio / Files, each section collapsible with a
count — a flat grid of a hundred files tells you nothing. Collapse state
persists to `theme.json`.

Hovering a tile reveals a remove control. It is two-step, and if a note still
embeds that file the confirmation says which notes, because removing it turns a
working embed into a `MISSING` placeholder. A small badge on each tile shows how
many notes reference it. Removed files go to `vault/.trash/media/`.

## Appearance

Every visual value is a CSS custom property, so theming is a handful of
`setProperty` calls rather than a rebuild. Settings persist to
`vault/theme.json`.

Each region of the UI carries its own `backdrop-filter`, so the sidebar
blurs the part of your wallpaper behind the sidebar and the editor blurs the
middle. The shell itself has no fill and no filter — if it did, it would
become a *backdrop root* and every panel would sample the shell instead of
the wallpaper.

Text contrast is derived rather than fixed:

```
ink = 0.52 − (frost × 0.20) − (blur × 0.12) − (dim × 0.18)
```

The less the frost, blur and dim are doing, the more the ink layer does. The
Text contrast slider offsets that result.

Upload a wallpaper and Tephra pulls an accent colour from it — pixels bucketed
by hue, each bucket weighted by count × saturation, then lifted until it reads
against dark glass.

---

## API

| | |
|---|---|
| `GET /api/notes` | list |
| `GET/PUT/DELETE /api/notes/{slug}` | read, autosave, trash |
| `POST /api/notes` | create |
| `POST /api/notes/{slug}/resolve` | create the note a stub link points at |
| `POST /api/media` · `GET /api/media` | upload, list |
| `GET /api/search?q=` | SQLite FTS5 |
| `GET /api/graph` | nodes and edges |
| `GET /api/suggestions` · `POST /api/suggestions/apply` | the auto-wiki |
| `GET/PUT /api/theme` | appearance |
| `POST /api/reindex` | rescan the vault |
| `GET /api/health` | healthcheck |

---

## Before you expose this

It's built for a trusted network and has **no authentication**. Anyone who can
reach the port can read and write every note.

If you want it reachable from outside your LAN, put it behind a reverse proxy
that handles auth and TLS — Caddy with `basic_auth`, Authelia, or a Tailscale
tailnet. Don't port-forward it directly.

Note rendering trusts your own markdown, including inline HTML in code you
paste. That's fine for a single-user vault and not fine for a shared one.

---

## Known limits

- Single user. No accounts, no concurrent-edit merging — two browser tabs
  editing one note will last-write-wins.
- External file edits need a reindex; there's no filesystem watcher yet.
- The graph is force-directed in canvas and starts to thin out past roughly
  1,500 nodes.
- Four large blurred regions is real GPU work. On a weak machine, drop the
  blur slider first.

---

## Desktop builds

The desktop app is the same server plus a native window — there is no second
implementation. `desktop/launcher.py` starts the FastAPI app on a random
loopback port and points a system webview at it.

Two things differ from the container build:

* **The vault defaults to `~/Documents/Tephra`**, not inside the app bundle.
  Installers replace application directories wholesale on update; user data
  must never live there. Override with `--vault` or the config file in the
  platform's app-support directory.
* **Cross-origin requests are refused.** A web page you happen to have open
  could otherwise `fetch()` `127.0.0.1` and read your vault. Browsers mark
  those requests with `Origin` and `Sec-Fetch-Site`; typing the address
  yourself sends neither, so the check costs you nothing and has no state to
  go stale.

  An earlier build used a per-launch session token instead. It was worse on
  both counts: a cookie from a previous launch shadowed the fresh token and
  produced `{"detail":"bad session token"}` until you cleared browser storage,
  and it was defending the vault from local processes that can already read
  `~/Documents/Tephra/notes/*.md` directly.

### Building

Desktop apps can't be cross-compiled: PyInstaller freezes for the OS it runs
on, `iconutil` and `codesign` are macOS-only, and Inno Setup is Windows-only.
You need each machine, or CI.

```bash
# macOS  (produces dist/Tephra-<ver>-macos-<arch>.dmg)
./packaging/build_macos.sh

# Windows (produces dist/Tephra-<ver>-windows-x64-setup.exe)
.\packaging\build_windows.ps1
```

Or push a tag and let `.github/workflows/build-installers.yml` build both on
GitHub's macOS and Windows runners. That's the practical route if you don't
have a Mac handy.

### Signing, and what happens if you skip it

Both scripts build fine unsigned, and both will produce something the OS
complains about:

| | Unsigned | Signed |
|---|---|---|
| macOS | Gatekeeper refuses to open it. Right-click → Open, or `xattr -dr com.apple.quarantine /Applications/Tephra.app` | Opens normally |
| Windows | SmartScreen warns "unrecognised app". More info → Run anyway | Warning fades as the certificate earns reputation |

For your own machines, unsigned is fine — you're one `xattr` away. It only
matters if you distribute it.

Signing needs an Apple Developer account ($99/yr) for macOS notarisation, and
an OV or EV code-signing certificate (~$200+/yr) for Windows. Set these
secrets and the workflow signs automatically; leave them unset and it doesn't:

`MACOS_CERT_P12`, `MACOS_CERT_PASSWORD`, `MACOS_KEYCHAIN_PASSWORD`,
`MACOS_SIGN_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`,
`WINDOWS_CERT_PFX`, `WINDOWS_CERT_PASSWORD`.

The macOS entitlements in `packaging/entitlements.plist` include
`allow-unsigned-executable-memory` and `disable-library-validation`. Both are
required — PyInstaller's bootloader maps unsigned pages and `dlopen`s bundled
libraries, and the hardened runtime kills the process at launch without them.

### Runtime notes

* **Windows** renders through Edge WebView2. It ships with Windows 11 and
  current Windows 10; the installer detects an older machine and pulls the
  bootstrapper.
* **macOS** uses WKWebView, which is built in. Sonoma and later will prompt
  once for access to your Documents folder.
* Frozen bundle is roughly 35 MB per platform.

---

## Running it as a desktop app, without installers

```bash
python3 run.py
```

That's the whole thing. First run builds a private virtualenv in `.venv/`,
installs dependencies into it, and re-launches itself inside it. Later runs
skip straight to opening the window. Your system Python is never touched, and
nothing is installed globally.

```bash
python3 run.py --vault ~/Notes    a different vault
python3 run.py --browser          browser tab instead of a native window
python3 run.py --headless         server only, no UI
python3 run.py --reinstall        rebuild .venv from scratch
python3 run.py --no-venv          use the current interpreter as-is
```

Needs Python 3.10 or newer. The vault defaults to `~/Documents/Tephra` and is
remembered after the first launch.

**Windows and macOS** ship a system webview (Edge WebView2 and WKWebView), so
the native window works out of the box. **Linux** doesn't, and pip can't
supply one — install `python3-gi gir1.2-webkit2-4.1`, or use `--browser`. If
the window can't open, Tephra tells you why and falls back to a browser tab
rather than dying.

If `python3 -m venv` fails on Debian or Ubuntu, that's the missing
`python3-venv` package, and the error message says so.

---

## Crucible — the study guide

Its own mode, with its own button and icon beside the Tephra wordmark rather
than sharing the Write/Graph control. It's an overlay: opening it doesn't take
you out of whichever canvas mode you were in, and Escape closes it without also
dropping you back to Write.

`⌥D` toggles it.

Named for a vessel that holds up under extreme heat, and for what a crucible
means in plain speech — a searching test.
 Browse by category, flashcards,
multiple-choice quiz with flagging, and search — the same four modes as the
standalone app, reading from your vault instead of a Python list.

### Upload formats

Four are accepted, and the importer shows the exact schema for each under
**What formats can I upload?**. `GET /api/study/formats` returns the same thing.

| Format | Extensions | Use it when |
|---|---|---|
| **JSON** | `.json` | The portable default. Best for a guide on a new product. |
| **Python** | `.py` | Module-level `TOPICS` / `QUIZ` lists. Read with `ast`, never executed. |
| **CSV / TSV** | `.csv` `.tsv` | You're building a question bank in a spreadsheet. |
| **Markdown** | `.md` | Tephra's own format — no import needed, drop files in `vault/notes/`. |

Minimal JSON:

```json
{ "topics": [ {
  "title": "RAID levels",
  "category": "Storage",
  "question": "What are the common RAID levels?",
  "answer": "**RAID 0** stripes...  full markdown supported",
  "quiz": [ { "question": "Which level has no redundancy?",
              "options": ["RAID 0", "RAID 1", "RAID 5"],
              "answer": 0,
              "why": "Striping only." } ] } ] }
```

Field names are matched leniently — `cat`/`category`, `q`/`question`,
`a`/`answer`, `why`/`explanation` all work, so an export from somewhere else
usually imports unchanged. Quiz questions can nest inside a topic or sit in a
flat `quiz` array referencing topics by `id` or `title`.

**Marking the correct answer.** Option text, a letter (`B`), or an index all
work. Indices are **0-based in JSON and Python** and **1-based in CSV**, because
that is what authors of each format expect; if one reading is out of range and
the other fits, the one that fits wins. Option text is checked before any index
reading, so an option literally named `9000` is not mistaken for index 9000.

If a file is misnamed, the content is sniffed. A question whose answer can't be
resolved is skipped rather than failing the import — except when *nothing*
resolves, which reports a mapping problem instead of importing empty topics.

### Importing the standalone guide

**Start Tephra, open the Study tab, and drop `fb_study_guide.py` on the
importer.** That is the reliable route: the running app knows its own vault, so
the notes cannot land somewhere it isn't reading.

That failure is worth naming, because it looks exactly like the import doing
nothing. The vault differs by how you launch:

| Launched with | Vault |
|---|---|
| `run.py` / desktop | `~/Documents/Tephra` |
| `docker compose` | `./vault` on the host |
| bare `uvicorn` with `TEPHRA_VAULT` unset | `/vault` |

Import to the wrong one and you get 76 notes in a folder nobody reads, an empty
Study tab, and no error. So the Study tab prints the vault path it is using.
Headless equivalent, which has no path argument and therefore no way to
import into the wrong directory:

```bash
curl -sX POST -F 'file=@guide.py' 'http://localhost:8080/api/study/import?dry_run=true'
curl -sX POST -F 'file=@guide.py' 'http://localhost:8080/api/study/import'
```

It reads `TOPICS` and `QUIZ` with `ast` rather than importing the module, so
the old app's server and tkinter are never touched. Importing also reindexes,
so notes, graph and backlinks appear without a restart.

Re-running is safe: notes update in place, nothing duplicates, and **manual
category corrections survive** — a re-import won't undo them.

It creates one note per topic, one index note per category, and a root
`FB Study Guide` note, so 62 flat topics become a linked wiki with 91 edges in
the graph view.

### How a study item is stored

```markdown
---
title: ICMP
tags: [study, nf]
study: true
category: Networking Fundamentals
category_source: import
question: What is ICMP and what is it used for?
---

**ICMP** is the Internet Control Message Protocol...

## Quiz

Q: At which OSI layer does ICMP operate?
- Layer 2 — Data Link
- [x] Layer 3 — Network
- Layer 4 — Transport
- Layer 7 — Application
Why: ICMP is IP protocol number 1 and rides directly on IP.
```

Still just markdown. `[x]` marks the right answer. Read it in any editor, or
hand-write a quiz block yourself and it appears in the app.

### Changing a note's study group

The control names itself and says where the label came from: **set by you**,
**from the guide**, or **guessed 71%**. Changing it announces both ends of the
move — "Moved from Log Analysis to Linux Commands" — rather than silently
swapping a value.

Underneath sits the trail of everywhere that note has been, newest first, with
how long ago. Click any entry to move it back.

Reverting restores the **source** as well as the label. A category the
classifier guessed goes back to being a guess, so an undone mistake stops
training the model toward the wrong answer — otherwise the correction you
withdrew would keep pulling similar notes with it.

History lives in the note's own frontmatter, capped at the last ten moves:

```yaml
category_history: Log Analysis @2026-07-30T07:12:00+00:00 ~manual | Linux Commands @2026-07-29T11:40:00+00:00 ~auto
```

One delimited line rather than JSON, because the frontmatter parser reads a
leading `[` as a list. It travels with the note if you copy the file elsewhere.

The right-hand panel also shows the current group above the local graph, with
the previous one beside it.

### Turning a note into a study item

Open any note and click **+ Make study item** in the meta row. It gets
`study: true`, a category, and a `study` tag. The category becomes a dropdown
in the same spot — change it any time, from the note or from the Study view.

### How categorisation works, and how good it is

Three tiers, checked in order:

1. `category_source: manual` or `import` — ground truth, never re-guessed.
2. **TF-IDF weighted k-NN** over those ground-truth items — learns *your*
   taxonomy from your own corrections.
3. A seed keyword lexicon — cold start only, before anything is labelled.

Correcting a category doesn't only fix that item. The corrected item joins the
training set, so every similar item shifts too. Auto-assigned labels are
deliberately **excluded** from training — feeding a classifier its own guesses
back is how you get confident nonsense.

Measured honestly by leave-one-out cross-validation on the 62 imported topics:

| | |
|---|---|
| Accuracy | **68%** |
| Flags itself for review | 61% of items |
| Wrong *and* confident | **3 of 62** |

68% is not great, and that's the real number. Lexical similarity can't fully
separate categories that genuinely overlap — a `grep` note is full of log
filenames, so it wants to be Log Analysis, and `tcpdump` legitimately belongs
to both Linux Commands and Wireshark. Three categories have only one example
each, which is not enough to learn from.

So the design target was **not** raw accuracy, it was *knowing when it's
unsure*. Vote share turned out to be a useless confidence signal (0.60 when
right, 0.53 when wrong). The margin between the top two categories separates
cleanly (0.32 vs 0.18), and gating on that dropped confident errors from 16 to
3. An unreviewed wrong category quietly corrupts your guide; a flagged one
costs one click.

Anything auto-assigned shows an amber `auto NN%` badge in the editor and a
`check category` chip in Study, and the header counts how many are waiting.
Accuracy improves as you correct things — it's a feedback loop, not a fixed
model.

`POST /api/study/reclassify` re-runs every auto-labelled item against the
current training set and reports what moved. Manual and imported labels are
untouched.

### Quiz length

A slider on the quiz screen, not a fixed 12. Its ceiling is the number of
questions actually available for the current selection, so it can never offer a
40-question round out of a category holding 9 — pick a small category and the
maximum drops with it. Preset chips cover 5 / 10 / 20 / 50 / All where they fit.

The choice is stored in `study-progress.json`, so it follows the vault rather
than the browser.

### Flags cross the boundary

Flagging a question in Crucible marks the **note** it came from, in Tephra.

Question ids are `<slug>:<hash>`, and `slugify()` can never produce a colon, so
the prefix is an unambiguous note reference — a flag in Crucible is therefore
also a fact about a note, with no extra bookkeeping.

- The sidebar shows a ⚑ against any note with flagged questions, with a count in
  its tooltip, and **Flagged first** is a sort option.
- The note's meta row grows a `⚑ N flagged` chip. Its tooltip lists the actual
  questions, and clicking it opens Crucible drilling *only* that note's flagged
  questions.
- A flagged question in the quiz gains an **open note →** link, so the jump
  works in both directions.
- Crucible's topic cards carry the same mark.

Flagging updates both sides immediately — no refresh, no reopening.

### Progress

Kept in `vault/study-progress.json` — per-question seen/right counts and your
flagged set, so it travels with the vault and survives reinstalls. Quiz modes:
a random round, **weakest first** (unseen, then worst hit rate), or **flagged
only**.

`⌥D` toggles Crucible. `POST /api/study/progress/reset` clears the stats.
