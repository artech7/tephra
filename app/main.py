"""Tephra — a self-hosted notes app that grows its own wiki."""
from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import dedupe
from . import guide_import
from . import importers
from . import settings as cfg
from . import index as idx
from . import study as st
from . import render as rndr
from . import vault

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = int(os.environ.get("TEPHRA_MAX_UPLOAD_MB", "200")) * 1024 * 1024

# Favoriting reuses the tag mechanism -- same trick "study" and "index" already
# play: it round-trips through frontmatter for free and is already indexed in
# notes.tags, so pinning favorites to the top costs no schema change. It is
# stripped back out of every outward-facing tag list so it never shows up as
# an ordinary, removable tag chip -- the star is its only affordance.
FAVORITE_TAG = "favorite"

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

def _note_dict(note: vault.Note) -> dict:
    """note.to_dict(), with the favorite flag pulled out of the tag list it
    actually lives in so it never renders as an ordinary tag chip."""
    d = note.to_dict()
    d["favorite"] = FAVORITE_TAG in d["tags"]
    d["tags"] = [t for t in d["tags"] if t != FAVORITE_TAG]
    return d


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
        favorite = FAVORITE_TAG in tags
        tags = [t for t in tags if t != FAVORITE_TAG]
        # Derived from tags rather than a new column: the importer and the
        # study toggle both maintain them, and it keeps the list query cheap.
        kind = "index" if "index" in tags else "study" if "study" in tags else "note"
        out.append({
            "slug": r["slug"], "title": r["title"], "updated": r["updated"],
            "tags": tags, "backlinks": r["backlinks"],
            "links_out": r["links_out"], "size": r["size"], "kind": kind,
            "flags": flags.get(r["slug"], 0), "favorite": favorite,
        })
    return out


@app.get("/api/notes/{slug}")
def get_note(slug: str):
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    # links_out/media still count the whole file -- a link or embed sitting
    # inside the quiz section is unusual but real, and shouldn't vanish from
    # those counts. The *displayed* HTML is prose only: quiz has its own
    # editor now, so rendering it a second time as a plain markdown list
    # inside the note body would just be the same content shown twice.
    resolve = resolver()
    _, targets, used = rndr.render(note.body, resolve)
    prose, _ = st.split_quiz(note.body)
    body_html, _, _ = rndr.render(prose, resolve)
    item = st.load_item(note)
    flagged = set(st.load_progress()["flagged"])
    flagged_qs = [{"id": q["id"], "question": q["question"]}
                  for q in item["quiz"] if q["id"] in flagged]
    return {
        **_note_dict(note),
        "flags": len(flagged_qs),
        "flagged_questions": flagged_qs,
        "category_history": st.parse_history(note.meta.get(st.HISTORY_KEY)),
        "html": body_html,
        "links_out": len(set(t.lower() for t in targets)),
        "media": used,
        "backlinks": idx.backlinks(db(), slug),
        "words": len(note.body.split()),
        "quiz": item["quiz"],
    }


@app.post("/api/notes")
def create_note(payload: NoteIn):
    title = (payload.title or "Untitled").strip() or "Untitled"
    note = vault.Note(slug=vault.unique_slug(title), title=title,
                      body=payload.body or "", tags=payload.tags or [])
    vault.write(note)
    idx.reindex_note(db(), note)
    return _note_dict(note)


def _apply_tags(note: vault.Note, tags: list[str]) -> None:
    """Set note.tags from a client payload, which never carries the favorite
    tag (it's stripped out on the way out, so the star can be its only
    affordance) -- so a plain overwrite here would silently unfavorite any
    note whose other tags get edited. Re-add it if it was there before."""
    was_favorite = FAVORITE_TAG in note.tags
    note.tags = tags
    if was_favorite and FAVORITE_TAG not in note.tags:
        note.tags = sorted(set(note.tags) | {FAVORITE_TAG})


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
                _apply_tags(renamed, payload.tags)
            vault.write(renamed)
            idx.rebuild(db())          # a retitle can repoint links vault-wide
            return {**_note_dict(renamed), "renamed_to": renamed.slug,
                    "quiz": st.load_item(renamed)["quiz"]}

    if payload.body is not None:
        note.body = payload.body
    if payload.tags is not None:
        _apply_tags(note, payload.tags)
    vault.write(note)
    idx.reindex_note(db(), note)
    # A hand-edited `## Quiz` section (source mode is still there for anyone
    # who prefers it) needs to reach the structured quiz editor too, or the
    # two views of the same markdown would drift apart.
    return {**_note_dict(note), "quiz": st.load_item(note)["quiz"]}


class QuizItemIn(BaseModel):
    question: str
    options: list[str]
    answers: list[int]
    why: str = ""


class QuizIn(BaseModel):
    items: list[QuizItemIn]


@app.put("/api/notes/{slug}/quiz")
def save_quiz(slug: str, payload: QuizIn):
    """The quiz editor's save path -- parallel to save_note's free-text one,
    for whoever would rather fill in a form than write `Q:`/`- [x]`/`Why:`
    by hand. Either way the only thing on disk is the same markdown: this
    re-renders the `## Quiz` section from structured items and splices it
    back after the prose, exactly what a hand edit would have produced.

    A question with under 2 options or no marked answer is left out of what
    gets written, the same tolerance parse_quiz already has reading it back
    in -- so a question the user hasn't finished composing yet just doesn't
    persist until it's answerable, rather than being saved broken.
    """
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    prose, _ = st.split_quiz(note.body)
    items = [it.model_dump() for it in payload.items
             if len(it.options) >= 2 and it.answers]
    note.body = prose + ("\n\n" + st.render_quiz(items) if items else "")
    vault.write(note)
    idx.reindex_note(db(), note)
    item = st.load_item(note)
    return {**_note_dict(note), "quiz": item["quiz"]}


@app.delete("/api/notes/{slug}")
def delete_note(slug: str):
    if not vault.delete(slug):
        raise HTTPException(404, "note not found")
    idx.drop_note(db(), slug)
    return {"ok": True, "trashed": slug}


@app.post("/api/notes/{slug}/favorite")
def toggle_favorite(slug: str):
    note = vault.read(slug)
    if not note:
        raise HTTPException(404, "note not found")
    on = FAVORITE_TAG not in note.tags
    note.tags = sorted(set(note.tags) | {FAVORITE_TAG}) if on \
        else [t for t in note.tags if t != FAVORITE_TAG]
    vault.write(note)
    idx.reindex_note(db(), note)
    return {"slug": slug, "favorite": on}


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
    # idx.apply_suggestion() already rebuilds once up front and then
    # incrementally reindexes every note it touches, so the index is fully
    # consistent by the time it returns -- a second full rebuild here was
    # just redoing that same disk scan for nothing.
    result = idx.apply_suggestion(db(), payload.term, payload.target)
    # An applied term should not come back as a suggestion either.
    idx.dismiss_term(payload.term, "applied")
    return result


@app.get("/api/audit")
def audit():
    """Read-only check for link damage — safe to call any time."""
    return idx.audit_links(db())


@app.get("/api/duplicates")
def find_duplicates():
    """Vault-wide near-duplicate scan -- the same content check a guide
    import runs against incoming topics, run here over every existing note
    so duplicates already on disk (from a merge that predates this check,
    or two guides that overlap) can be found and cleaned up by hand.
    Read-only: nothing is deleted or merged automatically."""
    return {"pairs": dedupe.scan_notes(vault.all_notes())}


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


@app.post("/api/study/import/reconcile")
def reconcile_study_indexes(dry_run: bool = False):
    """Drop dead [[links]] from importer-owned category index notes -- the
    "Part of [[Guide]]" line and topic bullet list an import writes.
    Neither is pruned by the import itself when a topic or a whole guide's
    root note is later deleted by hand, so this is the way to clean up
    that backlog without re-importing anything.
    """
    report = guide_import.reconcile_indexes(dry_run=dry_run)
    if (report["changed"] or report["removed"]) and not dry_run:
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
async def study_import(file: UploadFile = File(...), dry_run: bool = False,
                        title: str | None = Form(None)):
    """Import a standalone study guide into *this* vault.

    Takes the uploaded guide file, parses it as data, writes the notes, and
    reindexes so everything appears without a restart. No path argument
    means no way to import into the wrong directory. `title` optionally
    names the guide's root note; unset, it's derived from the filename.
    """
    raw = await file.read()
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, "that file is far larger than a study guide script")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "could not read that as text")
    try:
        summary = guide_import.run_import(source, dry_run=dry_run,
                                          filename=file.filename or "guide",
                                          title=title)
    except importers.ImportError_ as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not dry_run:
        summary["reindexed"] = idx.rebuild(db())
        st.ensure_fitted(st.all_items(), force=True)
    return summary


class StudyImportPathIn(BaseModel):
    path: str
    dry_run: bool = False
    title: str | None = None


@app.post("/api/study/import/path")
def study_import_path(payload: StudyImportPathIn):
    """Import a study guide straight off disk, images and all.

    Only meaningful when the server and the browser share a filesystem --
    running headless on the same machine, or the desktop build. That's the
    same trust boundary /api/vault/open already crosses (loopback-only,
    single-user). It's the wrong tool the moment the server runs somewhere
    the browser can't see into (a container, a different machine): a typed
    path there resolves against the *server's* filesystem and fails with
    "does not exist" even though the folder is sitting right in front of the
    person typing it. /api/study/import/upload below is the endpoint for
    that case -- the browser reads the files itself and sends the bytes, so
    no path ever needs to resolve on the server side at all.

    `path` may name the guide file itself or a folder containing it; either
    way its folder is searched for images the guide's topics reference by
    filename (see vault.find_images).
    """
    target = Path(payload.path).expanduser()
    if not target.is_absolute():
        raise HTTPException(400, "give an absolute path")
    try:
        summary = guide_import.run_import_from_path(
            str(target), dry_run=payload.dry_run, title=payload.title)
    except importers.ImportError_ as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not payload.dry_run:
        summary["reindexed"] = idx.rebuild(db())
        st.ensure_fitted(st.all_items(), force=True)
    return summary


# A large guide can take a while to write -- per-topic image placement and
# dedupe scoring against every existing note -- so the actual import runs off
# the request thread. The browser gets a job id back immediately and polls
# /api/study/import/status/<id> to drive a progress bar, rather than holding
# the connection open with nothing to show but a spinner. Plain module-level
# dict + lock, matching the Conn wrapper's own reasoning in index.py: this is
# a single-user, single-process app, not a service with real contention.
_import_jobs: dict[str, dict] = {}
_import_jobs_lock = threading.Lock()


def _run_import_job(job_id: str, source: str, dry_run: bool, filename: str,
                     title: str | None, images: dict[str, bytes], dupes: list[str]) -> None:
    def on_progress(done: int, total: int) -> None:
        with _import_jobs_lock:
            _import_jobs[job_id].update(done=done, total=total)

    try:
        summary = guide_import.run_import(source, dry_run=dry_run, filename=filename,
                                          title=title, images=images, progress=on_progress)
        summary["duplicate_image_names"] = sorted(set(dupes))
        if not dry_run:
            summary["reindexed"] = idx.rebuild(db())
            st.ensure_fitted(st.all_items(), force=True)
        with _import_jobs_lock:
            _import_jobs[job_id].update(finished=True, result=summary, error=None)
    except (importers.ImportError_, ValueError) as exc:
        with _import_jobs_lock:
            _import_jobs[job_id].update(finished=True, result=None, error=str(exc))
    except Exception as exc:
        # Parsing/validation errors above are the expected failure shape;
        # this is the backstop for anything else, because a job that raises
        # unnoticed here just leaves the browser polling forever with no way
        # to find out -- there's no request handler left to catch it for us.
        with _import_jobs_lock:
            _import_jobs[job_id].update(finished=True, result=None, error=f"import failed: {exc}")


@app.post("/api/study/import/upload")
async def study_import_upload(files: list[UploadFile] = File(...), dry_run: bool = False,
                               title: str | None = Form(None)):
    """Import a guide plus its images from files the browser itself read --
    a folder or a plain multi-file pick, or files dragged in -- and never
    asks the server to resolve a path at all. This is the one that works no
    matter what machine is running the server: a container, a headless box
    on the other side of the network, anything.

    Exactly one uploaded file must be a recognised guide format; every other
    file is treated as a candidate image, matched to topics by filename the
    same way /api/study/import/path matches against a directory scan --
    just against an in-memory map instead of files on disk.

    Returns a job id immediately; the actual import (and, if this isn't a
    dry run, the reindex) happens in the background -- see
    /api/study/import/status/<id>.
    """
    total = 0
    guide_name: str | None = None
    guide_bytes: bytes | None = None
    image_bytes: dict[str, bytes] = {}
    dupes: list[str] = []
    for f in files:
        data = await f.read()
        total += len(data)
        if total > MAX_UPLOAD:
            raise HTTPException(413, f"upload over {MAX_UPLOAD // 1024 // 1024} MB limit")
        # webkitdirectory sends each file's path relative to the picked
        # folder (e.g. "images/slide-04.png") -- only the basename is ever
        # matched against, same as a server-side directory scan matches by
        # filename regardless of which subfolder it's actually in.
        name = Path(f.filename or "").name
        if not name:
            continue
        ext = Path(name).suffix.lower()
        if ext in importers.PARSERS:
            if guide_name is not None:
                raise HTTPException(400, f"found more than one guide file among the uploaded "
                                          f"files ({guide_name}, {name}) — select just one guide "
                                          f"plus its images")
            guide_name, guide_bytes = name, data
        elif vault.kind_of(name) == "image":
            key = name.lower()
            if key in image_bytes:
                dupes.append(name)
            else:
                image_bytes[key] = data
        # anything else (a README, a .DS_Store swept up by a folder pick) is
        # silently ignored rather than rejected -- picking a whole folder
        # means picking whatever else lives in it too.

    if guide_name is None:
        raise HTTPException(400, "no study guide file (" + ", ".join(importers.ACCEPTED)
                                  + ") found among the uploaded files")
    try:
        source = guide_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, f"could not read {guide_name} as text")

    job_id = uuid.uuid4().hex
    with _import_jobs_lock:
        _import_jobs[job_id] = {"done": 0, "total": 0, "finished": False, "result": None, "error": None}
    threading.Thread(target=_run_import_job,
                     args=(job_id, source, dry_run, guide_name, title, image_bytes, dupes),
                     daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/study/import/status/{job_id}")
def study_import_status(job_id: str):
    """Polled by the browser every few hundred ms after a POST to
    /api/study/import/upload, to drive a progress bar off `done`/`total`
    while a large guide's topics are written. One-shot: a finished job's
    entry is dropped as soon as this hands it back, since the frontend only
    ever needs to observe `finished: true` once."""
    with _import_jobs_lock:
        job = _import_jobs.get(job_id)
        if job is not None and job["finished"]:
            del _import_jobs[job_id]
    if job is None:
        raise HTTPException(404, "unknown or already-collected import job")
    return job


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
    "radius": 28, "shine": 34,
    "font_display": "Bricolage Grotesque", "font_serif": "Newsreader", "font_mono": "JetBrains Mono",
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
