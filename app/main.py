"""Tephra — a self-hosted notes app that grows its own wiki."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import fb_import
from . import importers
from . import settings as cfg
from . import index as idx
from . import study as st
from . import render as rndr
from . import vault

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = int(os.environ.get("TEPHRA_MAX_UPLOAD_MB", "200")) * 1024 * 1024

SEEDS = [
    ("Welcome to Tephra", ["start"], """Everything you type saves itself. There is no
save button anywhere in this app, and there is not going to be one.

Your notes are plain markdown files in the vault directory you mounted. Open
them in any editor, grep them, commit them to git — this app is a way of
reading and connecting them, not a container they are trapped in.

## Linking

Type two square brackets to link a note: [[Linking and the Auto-Wiki]]. If the
note doesn't exist yet the link turns amber and clicking it creates the page.

## Media

Drag any file onto the editor. Images, video and audio embed inline; anything
else becomes a download chip. Paste a URL on its own line and it becomes a
bookmark card.

## The part that does the work

Tephra reads your whole vault looking for things you write about repeatedly
but never linked. See [[Linking and the Auto-Wiki]].
"""),
    ("Linking and the Auto-Wiki", ["start"], """A wiki is not a folder with
backlinks bolted on. It is a set of pages that agree on what things are called.
Keeping that agreement by hand is the work nobody sustains, which is why most
personal wikis quietly rot into a pile of daily notes.

Tephra does that maintenance for you. It looks for two things:

- **Unlinked mentions.** A page already exists and you wrote its name in prose
  without linking it. High confidence, one click to fix everywhere.
- **Emerging terms.** A phrase shows up across three or more notes and has no
  page yet. That's a concept you clearly have, that your vault doesn't know about.

Accept a suggestion and it creates the page if needed, then rewrites every
plain-text mention across the vault into a real link. Your markdown files change
on disk — that's the point, the links belong in the notes, not in a database.

See [[Welcome to Tephra]] to get started, or [[Vault Layout]] for where
everything lives.
"""),
    ("Vault Layout", ["reference"], """Everything lives under the directory you
mounted as `/vault`:

```
vault/
├── notes/          one markdown file per note, with YAML frontmatter
├── media/          images, video, audio, attachments
├── theme.json      your appearance settings
├── .index/         SQLite cache — safe to delete, rebuilds on start
└── .trash/         deleted notes, kept rather than destroyed
```

The index is derived. If it is ever wrong, delete `.index/index.db` and restart,
or hit Rebuild in the command palette. Nothing in `notes/` depends on it.

Because the notes are just files, `git init` inside the vault gives you full
version history for free. A cron job running `git commit -am snapshot` once an
hour is a perfectly good backup strategy.
"""),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Recover a vault stranded by an interrupted rename before anything else.
    # It is dot-prefixed, so the user cannot see it in Finder to recover it
    # themselves.
    for probe in {vault.VAULT, Path(cfg.load().get("vault") or vault.VAULT)}:
        try:
            stranded = list(probe.parent.glob(".*.tephra-renaming"))
        except OSError:
            continue
        for st_dir in stranded:
            if not (st_dir / "notes").is_dir():
                continue
            restored = st_dir.parent / st_dir.name[1:-len(".tephra-renaming")]
            if restored.exists():
                continue
            try:
                st_dir.rename(restored)
                print(f"[tephra] recovered a vault left mid-rename -> {restored}")
                cfg.remember_vault(restored)
                os.environ.pop("TEPHRA_VAULT", None)
                vault.use(restored)
            except OSError:
                pass

    # A vault chosen in a previous session wins over the launch default.
    remembered = cfg.load().get("vault")
    if remembered and not os.environ.get("TEPHRA_VAULT") and vault.looks_like_vault(remembered):
        vault.use(remembered)
    vault.ensure_dirs()
    con = idx.connect()
    idx.init(con)
    if not any(vault.NOTES.glob("*.md")):
        for title, tags, body in SEEDS:
            vault.write(vault.Note(slug=vault.slugify(title), title=title,
                                   tags=tags, body=body))
    n = idx.rebuild(con)
    # Self-heal on open. The pass is idempotent and byte-identical on clean
    # content, so there is no reason to make the user find a button for damage
    # an older build wrote into their files.
    fixed = idx.repair_links(con)
    app.state.last_repair = fixed if fixed["changed"] else None
    if fixed["changed"]:
        print(f"[tephra] repaired malformed links in {fixed['changed']} note(s)")
        n = idx.rebuild(con)
    # Record the vault on every start, so config always names what is open —
    # otherwise a first run leaves nothing for a rename or the recents list.
    cfg.remember_vault(vault.VAULT)
    print(f"[tephra] vault={vault.VAULT} notes={n}")
    app.state.db = con
    yield
    con.close()


app = FastAPI(title="Tephra", lifespan=lifespan)


def db():
    return app.state.db


def resolver():
    tmap = {
        r["title"].strip().lower(): r["slug"]
        for r in db().execute("SELECT slug,title FROM notes")
    }
    return lambda title: tmap.get(title.strip().lower())


class NoteIn(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None


class StudyIn(BaseModel):
    category: str | None = None
    question: str | None = None


class AnswerIn(BaseModel):
    qid: str
    correct: bool


class FlagIn(BaseModel):
    qid: str
    flagged: bool = True


class SuggestIn(BaseModel):
    term: str
    target: str | None = None


# ── notes ──────────────────────────────────────────────────────────────────

@app.get("/api/notes")
def list_notes():
    rows = db().execute(
        """SELECT n.slug, n.title, n.tags, n.updated,
                  (SELECT COUNT(*) FROM links WHERE dst=n.slug) AS backlinks,
                  (SELECT COUNT(*) FROM links WHERE src=n.slug) AS links_out,
                  length(n.body) AS size
           FROM notes n ORDER BY n.updated DESC"""
    ).fetchall()
    flags = st.flags_by_slug()
    out = []
    for r in rows:
        tags = [t for t in r["tags"].split(",") if t]
        # Derived from tags rather than a new column: the importer and the
        # study toggle both maintain them, and it keeps the list query cheap.
        kind = "index" if "index" in tags else "study" if "study" in tags else "note"
        out.append({
            "slug": r["slug"], "title": r["title"], "updated": r["updated"],
            "tags": tags, "backlinks": r["backlinks"],
            "links_out": r["links_out"], "size": r["size"], "kind": kind,
            "flags": flags.get(r["slug"], 0),
        })
    return out


@app.get("/api/notes/{slug}")
def get_note(slug: str):
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    body_html, targets, used = rndr.render(note.body, resolver())
    item = st.load_item(note)
    flagged = set(st.load_progress()["flagged"])
    flagged_qs = [{"id": q["id"], "question": q["question"]}
                  for q in item["quiz"] if q["id"] in flagged]
    return {
        **note.to_dict(),
        "flags": len(flagged_qs),
        "flagged_questions": flagged_qs,
        "category_history": st.parse_history(note.meta.get(st.HISTORY_KEY)),
        "html": body_html,
        "links_out": len(set(t.lower() for t in targets)),
        "media": used,
        "backlinks": idx.backlinks(db(), slug),
        "suggestions": idx.suggestions(db(), slug, limit=6),
        "words": len(note.body.split()),
    }


@app.post("/api/notes")
def create_note(payload: NoteIn):
    title = (payload.title or "Untitled").strip() or "Untitled"
    note = vault.Note(slug=vault.unique_slug(title), title=title,
                      body=payload.body or "", tags=payload.tags or [])
    vault.write(note)
    idx.reindex_note(db(), note)
    return note.to_dict()


@app.put("/api/notes/{slug}")
def save_note(slug: str, payload: NoteIn):
    """The autosave endpoint. Called on a debounce while typing, so it has to
    be cheap and it has to be safe to call with a partial payload."""
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")

    if payload.title is not None and payload.title.strip() != note.title:
        renamed = vault.rename(slug, payload.title.strip() or "Untitled")
        if renamed:
            if payload.body is not None:
                renamed.body = payload.body
            if payload.tags is not None:
                renamed.tags = payload.tags
            vault.write(renamed)
            idx.rebuild(db())          # a retitle can repoint links vault-wide
            return {**renamed.to_dict(), "renamed_to": renamed.slug}

    if payload.body is not None:
        note.body = payload.body
    if payload.tags is not None:
        note.tags = payload.tags
    vault.write(note)
    idx.reindex_note(db(), note)
    return note.to_dict()


@app.delete("/api/notes/{slug}")
def delete_note(slug: str):
    if not vault.delete(slug):
        raise HTTPException(404, "note not found")
    idx.drop_note(db(), slug)
    return {"ok": True, "trashed": slug}


@app.post("/api/notes/{slug}/resolve")
def resolve_stub(slug: str, payload: NoteIn):
    """Clicking an amber link: create the missing note it points at."""
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    found = db().execute("SELECT slug FROM notes WHERE lower(title)=?",
                         (title.lower(),)).fetchone()
    if found:
        return {"slug": found["slug"], "created": False}
    note = vault.Note(slug=vault.unique_slug(title), title=title, body="")
    vault.write(note)
    idx.reindex_note(db(), note)
    return {"slug": note.slug, "created": True}


# ── media ──────────────────────────────────────────────────────────────────

@app.post("/api/media")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file over {MAX_UPLOAD // 1024 // 1024} MB limit")
    return vault.save_media(file.filename or "upload", data)


@app.get("/api/media")
def media():
    """Includes which notes embed each file, so deleting can warn rather than
    silently breaking an embed."""
    items = vault.media_list()
    rows = db().execute("SELECT slug, body FROM notes").fetchall()
    for m in items:
        m["used_by"] = [r["slug"] for r in rows if m["name"] in (r["body"] or "")]
    return items


@app.delete("/api/media/{name}")
def delete_media(name: str):
    p = (vault.MEDIA / name).resolve()
    if not str(p).startswith(str(vault.MEDIA.resolve())) or not p.is_file():
        raise HTTPException(404, "no such file")
    rows = db().execute("SELECT slug, body FROM notes").fetchall()
    used = [r["slug"] for r in rows if name in (r["body"] or "")]
    trash = vault.VAULT / ".trash" / "media"
    trash.mkdir(parents=True, exist_ok=True)
    import shutil as _sh
    _sh.move(str(p), str(trash / p.name))
    return {"ok": True, "trashed": name, "was_used_by": used}


@app.get("/media/{name}")
def serve_media(name: str):
    p = (vault.MEDIA / name).resolve()
    if not str(p).startswith(str(vault.MEDIA.resolve())) or not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p)


# ── discovery ──────────────────────────────────────────────────────────────

@app.get("/api/search")
def search(q: str = "", limit: int = 20):
    return idx.search(db(), q, limit)


@app.get("/api/graph")
def graph():
    return idx.graph(db())


@app.get("/api/suggestions")
def get_suggestions(limit: int = 12):
    return idx.suggestions(db(), None, limit)


class DismissIn(BaseModel):
    term: str
    note: str = ""


@app.post("/api/suggestions/dismiss")
def dismiss_suggestion(payload: DismissIn):
    idx.dismiss_term(payload.term, payload.note)
    return {"ok": True, "term": payload.term}


@app.post("/api/suggestions/restore")
def restore_suggestion(payload: DismissIn):
    idx.restore_term(payload.term)
    return {"ok": True, "term": payload.term}


@app.get("/api/suggestions/dismissed")
def dismissed_suggestions():
    data = idx.load_dismissed()["dismissed"]
    return sorted(data.values(), key=lambda d: d.get("at", ""), reverse=True)


@app.post("/api/suggestions/apply")
def apply_suggestion(payload: SuggestIn):
    result = idx.apply_suggestion(db(), payload.term, payload.target)
    # An applied term should not come back as a suggestion either.
    idx.dismiss_term(payload.term, "applied")
    idx.rebuild(db())
    return result


@app.get("/api/audit")
def audit():
    """Read-only check for link damage — safe to call any time."""
    return idx.audit_links(db())


@app.get("/api/repair/last")
def last_repair():
    """What the automatic pass fixed when this vault was opened.

    Consumed on read: the client shows it once, and a page reload does not
    re-announce work that already happened.
    """
    report = getattr(app.state, "last_repair", None)
    app.state.last_repair = None
    return report or {"changed": 0}


@app.post("/api/repair")
def repair(dry_run: bool = False):
    """Fix nested links, links inside quiz blocks, and empty link husks.

    `dry_run=true` reports what would change and writes nothing. It previously
    accepted the parameter and ignored it, which meant the preview committed.
    """
    report = idx.repair_links(db(), dry_run=dry_run)
    if report["changed"] and not dry_run:
        idx.rebuild(db())
        st.ensure_fitted(st.all_items(), force=True)
    return report


@app.post("/api/reindex")
def reindex():
    return {"notes": idx.rebuild(db())}



# ── study guide ────────────────────────────────────────────────────────────
# Study items are notes; this is a projection over the vault, not a store.

def _study_payload() -> dict:
    items = st.all_items()
    st.ensure_fitted(items)
    prog = st.load_progress()
    answers = prog["answers"]
    flagged = set(prog["flagged"])

    cats: dict[str, dict] = {}
    for it in items:
        c = it["category"] or "Uncategorised"
        slot = cats.setdefault(c, {"category": c, "topics": 0, "questions": 0})
        slot["topics"] += 1
        slot["questions"] += len(it["quiz"])

    seen = right = 0
    for rec in answers.values():
        seen += rec["seen"]
        right += rec["right"]

    return {
        "items": [{
            "slug": it["slug"], "title": it["title"], "category": it["category"],
            "source": it["source"], "confidence": it["confidence"],
            "question": it["question"], "questions": len(it["quiz"]),
            "needs_review": it["source"] == "auto",
            "flags": sum(1 for q in it["quiz"] if q["id"] in flagged),
        } for it in sorted(items, key=lambda x: (x["category"] or "~", x["title"]))],
        "categories": sorted(cats.values(), key=lambda c: c["category"]),
        "known_categories": st.known_categories(items),
        "progress": {"answered": seen, "correct": right, "flagged": len(flagged)},
        "settings": prog.get("settings", {"quiz_count": st.DEFAULT_QUIZ_COUNT}),
        "max_quiz": st.MAX_QUIZ_COUNT,
        "totals": {"topics": len(items),
                   "questions": sum(len(i["quiz"]) for i in items),
                   "needs_review": sum(1 for i in items if i["source"] == "auto")},
    }


@app.get("/api/study")
def study_overview():
    return _study_payload()


class VaultIn(BaseModel):
    path: str
    create: bool = False


def _open_vault(path: str, create: bool) -> dict:
    """Repoint the app at another directory and rebuild from it.

    Loopback-only and single-user, but this still takes a filesystem path from
    an HTTP request, so it validates rather than trusting: absolute after
    expansion, not a file, and for an existing vault it must actually contain
    notes/ so a typo cannot scatter a vault across a home directory.
    """
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise HTTPException(400, "give an absolute path")
    if target.exists() and not target.is_dir():
        raise HTTPException(400, "that path is a file, not a folder")
    if str(target) in ("/", str(Path.home().anchor)):
        raise HTTPException(400, "that is the filesystem root")

    existing = vault.looks_like_vault(target)
    if not existing and not create:
        raise HTTPException(404, f"no vault at {target} — create it?")
    if existing and create:
        raise HTTPException(409, f"a vault already exists at {target}")

    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / "notes").mkdir(exist_ok=True)
    except OSError as exc:
        raise HTTPException(400, f"cannot use that folder: {exc}")

    # Order matters: close the old index before the paths move, or the next
    # write lands in the previous vault's database.
    try:
        db().close()
    except Exception:
        pass
    vault.use(target)
    con = idx.connect()
    idx.init(con)
    app.state.db = con

    seeded = False
    if not any(vault.NOTES.glob("*.md")):
        for title, tags, body in SEEDS:
            vault.write(vault.Note(slug=vault.slugify(title), title=title,
                                   tags=tags, body=body))
        seeded = True
    n = idx.rebuild(con)
    fixed = idx.repair_links(con)
    app.state.last_repair = fixed if fixed["changed"] else None
    if fixed["changed"]:
        n = idx.rebuild(con)
    st.ensure_fitted(st.all_items(), force=True)
    cfg.remember_vault(target)
    print(f"[tephra] vault switched -> {target} ({n} notes)")
    return {"vault": str(target), "notes": n, "created": not existing,
            "seeded": seeded}


@app.get("/api/vault/list")
def vault_list():
    c = cfg.load()
    recent = []
    for p in c.get("recent", []):
        recent.append({"path": p, "exists": vault.looks_like_vault(p),
                       "current": str(vault.VAULT) == p})
    if not any(r["current"] for r in recent):
        recent.insert(0, {"path": str(vault.VAULT), "exists": True, "current": True})
    return {"current": str(vault.VAULT), "recent": recent,
            "suggested_parent": str(cfg.default_vault().parent)}


class ForgetIn(BaseModel):
    path: str


@app.post("/api/vault/forget")
def vault_forget(payload: ForgetIn):
    """Drop a vault from the recents list. The folder on disk is never
    touched -- this only forgets it until it is opened again.

    The open vault can't be forgotten: vault_list() re-injects whichever
    vault is currently open even when it isn't in the config's recent list,
    so forgetting it would just have it reappear on the next render.
    """
    target = str(Path(payload.path).expanduser().resolve())
    if target == str(vault.VAULT):
        raise HTTPException(400, "switch to another vault before removing this one")
    cfg.forget_vault(target)
    return {"path": target, "forgotten": True}


@app.get("/api/vault/browse")
def vault_browse(path: str | None = None):
    """List immediate subdirectories of `path`, flagged with whether each
    looks like a vault, for the vault picker's browse modal.

    No authentication guards this app, so a path parameter that walks the
    filesystem is treated with care: resolved before any check (so a symlink
    cannot be used to escape), confined to `vault.browse_root()`, and a
    containment failure is a 403 rather than a 404 so the response never
    confirms whether a path outside the root exists.
    """
    root = vault.browse_root()
    target = Path(path).expanduser().resolve() if path else root
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(403, "outside the browse root")
    if not target.is_dir():
        raise HTTPException(404, f"no such directory: {target}")

    return {
        "path": str(target),
        "parent": str(target.parent),
        "entries": vault.list_browsable(target),
    }


class RenameIn(BaseModel):
    name: str


@app.post("/api/vault/rename")
def vault_rename(payload: RenameIn):
    """Rename the folder the current vault lives in.

    Renaming it in Finder works too — a vault is only ever a folder — but the
    app records an absolute path, so doing it outside leaves a dead entry in
    recents and a vault that will not reopen. This keeps the two in step.
    """
    name = payload.name.strip().strip("/")
    if not name:
        raise HTTPException(400, "give the vault a name")
    if any(c in name for c in "/\\") or name in (".", ".."):
        raise HTTPException(400, "that is a path, not a folder name")
    if len(name) > 120:
        raise HTTPException(400, "that name is too long")

    current = vault.VAULT.resolve()
    target = current.parent / name
    if target == current:
        return {"vault": str(current), "renamed": False}

    # A case-only change is a no-op move on a case-insensitive filesystem, so
    # go via a temporary name. macOS makes this the common case, not an edge one.
    case_only = str(target).lower() == str(current).lower()
    if target.exists() and not case_only:
        raise HTTPException(409, f"{name} already exists alongside this vault")

    try:
        db().close()
    except Exception:
        pass
    # A case-only change needs two moves on a case-insensitive filesystem, and
    # the halfway state is a DOT-PREFIXED folder — invisible in Finder. If the
    # second move failed, the vault appeared to vanish. Track the temp name so
    # the failure path can always put it back.
    tmp = None
    try:
        if case_only:
            tmp = current.parent / f".{name}.tephra-renaming"
            current.rename(tmp)
            tmp.rename(target)
            tmp = None
        else:
            current.rename(target)
    except OSError as exc:
        landed = current
        if tmp is not None and tmp.exists():
            try:
                tmp.rename(current)           # undo the half-completed move
            except OSError:
                landed = tmp                  # could not undo; at least serve it
        vault.use(landed)
        con = idx.connect(); idx.init(con); idx.rebuild(con); app.state.db = con
        cfg.remember_vault(landed)
        detail = f"could not rename: {exc}"
        if landed != current:
            detail += (f" — your vault is intact at {landed}, which Finder hides "
                       "because the name starts with a dot")
        raise HTTPException(400, detail)

    vault.use(target)
    con = idx.connect()
    idx.init(con)
    n = idx.rebuild(con)
    app.state.db = con
    st.ensure_fitted(st.all_items(), force=True)
    cfg.rename_vault(current, target)
    print(f"[tephra] vault renamed -> {target}")
    return {"vault": str(target), "name": name, "notes": n, "renamed": True}


@app.post("/api/vault/open")
def vault_open(payload: VaultIn):
    return _open_vault(payload.path, create=False)


@app.post("/api/vault/create")
def vault_create(payload: VaultIn):
    return _open_vault(payload.path, create=True)


@app.get("/api/study/formats")
def study_formats():
    return {"accepted": importers.ACCEPTED, "formats": importers.FORMATS}


@app.get("/api/vault/info")
def vault_info():
    """Which directory is actually in use. Surfaced in the UI because a vault
    mismatch is invisible otherwise — the app looks empty while the notes sit
    in a folder nobody is reading."""
    notes = list(vault.NOTES.glob("*.md")) if vault.NOTES.is_dir() else []
    return {
        "vault": str(vault.VAULT),
        "notes_dir": str(vault.NOTES),
        "files_on_disk": len(notes),
        "indexed": db().execute("SELECT COUNT(*) c FROM notes").fetchone()["c"],
        "study_items": sum(1 for n in vault.all_notes() if st.is_study(n)),
    }


@app.post("/api/study/import")
async def study_import(file: UploadFile = File(...), dry_run: bool = False):
    """Import the standalone guide into *this* vault.

    Takes the fb_study_guide.py upload, parses it as data, writes the notes,
    and reindexes so everything appears without a restart. No path argument
    means no way to import into the wrong directory.
    """
    raw = await file.read()
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, "that file is far larger than a study guide script")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "could not read that as text")
    try:
        summary = fb_import.run_import(source, dry_run=dry_run,
                                       filename=file.filename or "guide")
    except importers.ImportError_ as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not dry_run:
        summary["reindexed"] = idx.rebuild(db())
        st.ensure_fitted(st.all_items(), force=True)
    return summary


@app.get("/api/study/item/{slug}")
def study_item(slug: str):
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    item = st.load_item(note)
    prog = st.load_progress()
    flagged = set(prog["flagged"])
    for q in item["quiz"]:
        q["flagged"] = q["id"] in flagged
        q["stats"] = prog["answers"].get(q["id"], {"seen": 0, "right": 0})
    item["html"] = rndr.render(item["prose"], resolver())[0]
    return item


@app.post("/api/study/{slug}/enable")
def study_enable(slug: str, payload: StudyIn):
    """The 'turn into study guide item' action.

    Classifies immediately so the note lands in a category without a second
    step, but records how the label was arrived at. An explicit category from
    the caller is treated as a human decision and becomes training data.
    """
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")

    note.meta["study"] = "true"
    if payload.question:
        note.meta["question"] = payload.question.strip()

    if payload.category:
        note.meta["category"] = payload.category.strip()
        note.meta["category_source"] = "manual"
        note.meta.pop("category_confidence", None)
        guess = {"category": payload.category, "manual": True}
    else:
        guess = st.classify_note(note)
        note.meta["category"] = guess["category"] or ""
        note.meta["category_source"] = "auto"
        note.meta["category_confidence"] = guess.get("confidence", 0)

    prior = (note.meta.get("category") or "").strip()
    if prior and prior != note.meta.get("category"):
        st.push_history(note, prior, (note.meta.get("category_source") or "auto"))
    if "study" not in note.tags:
        note.tags = sorted(set(note.tags) | {"study"})
    vault.write(note)
    idx.reindex_note(db(), note)
    return {"slug": slug, "guess": guess, "item": st.load_item(note)}


@app.post("/api/study/{slug}/disable")
def study_disable(slug: str):
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    note.meta["study"] = "false"
    note.tags = [t for t in note.tags if t != "study"]
    vault.write(note)
    idx.reindex_note(db(), note)
    return {"slug": slug, "study": False}


@app.post("/api/study/{slug}/category")
def study_set_category(slug: str, payload: StudyIn):
    """Manual override. Marked `manual` so it is never re-guessed, and it
    joins the training set — correcting one item shifts every similar one."""
    if not payload.category:
        raise HTTPException(400, "category required")
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    was = (note.meta.get("category") or "").strip()
    was_source = (note.meta.get("category_source") or "auto").strip()
    new = payload.category.strip()
    if new == was:
        return {"slug": slug, "category": was, "changed": False,
                "history": st.parse_history(note.meta.get(st.HISTORY_KEY))}

    st.push_history(note, was, was_source)
    note.meta["category"] = new
    note.meta["category_source"] = "manual"
    note.meta.pop("category_confidence", None)
    vault.write(note)
    idx.reindex_note(db(), note)
    items = st.all_items()
    st.ensure_fitted(items, force=True)
    return {"slug": slug, "category": new, "from": was, "changed": True,
            "history": st.parse_history(note.meta.get(st.HISTORY_KEY)),
            "training_size": len(st.training_set(items))}


@app.post("/api/study/{slug}/revert")
def study_revert(slug: str, payload: StudyIn):
    """Move a note back to where it was.

    Restores the *source* it had then, not just the label. That matters: a
    category the classifier guessed should go back to being a guess, otherwise
    an undone mistake keeps training the model toward the wrong answer.
    """
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    entries = st.parse_history(note.meta.get(st.HISTORY_KEY))
    if not entries:
        raise HTTPException(400, "this note has no history to revert to")

    target = entries[0]
    if payload.category:
        match = next((e for e in entries
                      if e["category"].lower() == payload.category.strip().lower()), None)
        if not match:
            raise HTTPException(404, "that category is not in this note's history")
        target = match

    was = (note.meta.get("category") or "").strip()
    was_source = (note.meta.get("category_source") or "auto").strip()
    st.push_history(note, was, was_source)
    note.meta["category"] = target["category"]
    note.meta["category_source"] = target["source"]
    if target["source"] == "auto":
        # It was a guess before; let it be a guess again rather than a
        # human-confirmed label the classifier will learn from.
        guess = st.classify_note(note)
        note.meta["category_confidence"] = guess.get("confidence", 0)
    else:
        note.meta.pop("category_confidence", None)
    vault.write(note)
    idx.reindex_note(db(), note)
    items = st.all_items()
    st.ensure_fitted(items, force=True)
    return {"slug": slug, "category": target["category"], "from": was,
            "restored_source": target["source"],
            "history": st.parse_history(note.meta.get(st.HISTORY_KEY)),
            "training_size": len(st.training_set(items))}


@app.get("/api/study/{slug}/suggest")
def study_suggest_category(slug: str):
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    return st.classify_note(note)


@app.post("/api/study/reclassify")
def study_reclassify():
    """Re-run every auto-labelled item against the current training set.
    Manual and imported labels are left alone."""
    items = st.all_items()
    st.ensure_fitted(items, force=True)
    changed = []
    for it in items:
        if it["source"] != "auto":
            continue
        note = vault.read(it["slug"])
        if not note:
            continue
        guess = st.classify_note(note, items)
        if guess["category"] and guess["category"] != it["category"]:
            note.meta["category"] = guess["category"]
            note.meta["category_confidence"] = guess.get("confidence", 0)
            vault.write(note)
            idx.reindex_note(db(), note)
            changed.append({"slug": it["slug"], "from": it["category"],
                            "to": guess["category"]})
    return {"changed": changed, "checked": sum(1 for i in items if i["source"] == "auto")}


@app.get("/api/study/quiz")
def study_quiz(category: str = "", n: int = 12, only_flagged: bool = False,
               weakest_first: bool = False, slug: str = ""):
    import random
    items = st.all_items()
    prog = st.load_progress()
    flagged = set(prog["flagged"])
    pool = []
    for it in items:
        if category and (it["category"] or "") != category:
            continue
        if slug and it["slug"] != slug:
            continue
        for q in it["quiz"]:
            if only_flagged and q["id"] not in flagged:
                continue
            stats = prog["answers"].get(q["id"], {"seen": 0, "right": 0})
            pool.append({**q, "slug": it["slug"], "title": it["title"],
                         "category": it["category"], "stats": stats,
                         "flagged": q["id"] in flagged})
    if weakest_first:
        # unseen first, then worst hit-rate: drills what you keep missing
        pool.sort(key=lambda q: (q["stats"]["seen"] > 0,
                                 q["stats"]["right"] / max(q["stats"]["seen"], 1)))
    else:
        random.shuffle(pool)
    return {"questions": pool[:max(1, min(n, st.MAX_QUIZ_COUNT))], "pool": len(pool)}


@app.post("/api/study/answer")
def study_answer(payload: AnswerIn):
    return st.record_answer(payload.qid, payload.correct)


@app.post("/api/study/flag")
def study_flag(payload: FlagIn):
    return {"flagged": st.set_flag(payload.qid, payload.flagged)}


class PrefsIn(BaseModel):
    quiz_count: int


@app.post("/api/study/prefs")
def study_prefs(payload: PrefsIn):
    return {"quiz_count": st.set_quiz_count(payload.quiz_count)}


@app.post("/api/study/progress/reset")
def study_reset():
    st.save_progress({"answers": {}, "flagged": []})
    return {"ok": True}


# ── theme ──────────────────────────────────────────────────────────────────

def theme_file():
    """Same reason as index.db_path(): theme is per-vault, so this path has to
    be re-derived every call or switching vault writes into the old one."""
    return vault.VAULT / "theme.json"
DEFAULT_THEME = {
    "acc": "63,224,173", "wall": "aurora", "wallUrl": None,
    "blur": 30, "frost": 55, "sat": 200, "scrim": 26,
    "inset": 20, "contrast": 0, "auto": True,
    # UI state that should follow the vault rather than the browser
    "note_sort": "updated", "note_tag": "", "media_open": {},
}


@app.get("/api/theme")
def get_theme():
    f = theme_file()
    if f.is_file():
        try:
            return {**DEFAULT_THEME, **json.loads(f.read_text())}
        except Exception:
            pass
    return DEFAULT_THEME


@app.put("/api/theme")
def put_theme(payload: dict):
    vault.ensure_dirs()
    merged = {**DEFAULT_THEME, **{k: v for k, v in payload.items()
                                  if k in DEFAULT_THEME}}
    theme_file().write_text(json.dumps(merged, indent=2))
    return merged


@app.get("/api/health")
def health():
    n = db().execute("SELECT COUNT(*) c FROM notes").fetchone()["c"]
    return {"ok": True, "notes": n, "vault": str(vault.VAULT)}


# ── static ─────────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.exception_handler(404)
async def spa_fallback(request, exc):
    if request.url.path.startswith(("/api", "/media", "/static")):
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(STATIC / "index.html")
