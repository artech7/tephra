"""
Vault: plain markdown files on disk are the source of truth.

Nothing in here depends on the index or the web layer. If you delete the
index database the vault is untouched; if you delete the app entirely you
still have a directory of markdown you can read, grep, and commit to git.
"""
from __future__ import annotations

import contextvars
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# TEPHRA_VAULT is an explicit, this-launch override (set by --vault or the
# desktop launcher) and always wins — main.py's lifespan deliberately skips
# the remembered vault whenever it's present. TEPHRA_DEFAULT_VAULT is a
# lower-priority *bootstrap* default: where to look before any vault has
# ever been chosen or remembered. A container always has some environment
# variable set for its default vault, so collapsing both into TEPHRA_VAULT
# would permanently block "the last vault you had open wins" under any
# deployment that sets one — which is exactly what happened here.
#
# --- concurrent sessions -----------------------------------------------
# This used to be four plain module globals (VAULT/NOTES/MEDIA/INDEX_DIR),
# rebound in place by use(). That was correct for one browser at a time,
# but the moment two browsers hit the same running server, switching the
# vault for one switched it for both — there was no notion of "whose"
# vault a request was even asking about.
#
# It's now a contextvars.ContextVar holding one immutable VaultPaths per
# logical context. sessions.session_middleware sets it once per incoming
# request (resolved from that browser's session cookie) before the route
# handler runs, so every vault.* call below sees the *requesting session's*
# vault, not a single process-wide one. Anything with no request in play at
# all — tools/ scripts, tests, the lifespan bootstrap before the first
# request — falls back to the module-level default below, which is exactly
# the old single-vault behaviour.
#
# `vault.VAULT`, `vault.NOTES`, `vault.MEDIA`, `vault.INDEX_DIR` still work
# unchanged for every external caller (main.py, index.py, study.py, ...) via
# the module __getattr__ near the bottom of this file (PEP 562) — only the
# bare, unprefixed uses *inside this module's own functions* had to change,
# since __getattr__ isn't consulted for a plain name lookup inside the
# module that defines it.


@dataclass(frozen=True)
class VaultPaths:
    vault: Path
    notes: Path
    media: Path
    index_dir: Path


def _paths_for(root: Path) -> VaultPaths:
    return VaultPaths(root, root / "notes", root / "media", root / ".index")


def _default_root() -> Path:
    return Path(os.environ.get("TEPHRA_VAULT") or os.environ.get("TEPHRA_DEFAULT_VAULT") or "/vault")


_ctx: contextvars.ContextVar[VaultPaths] = contextvars.ContextVar(
    "tephra_vault_paths", default=_paths_for(_default_root())
)


def current() -> VaultPaths:
    """The vault paths that apply right now -- per-request when a session
    middleware has set them, or the single process-wide default otherwise."""
    return _ctx.get()


def set_current(path: str | Path) -> Path:
    """Point *this* context (this request; or the whole process, for a
    caller with no per-request context at all) at a different vault.
    Never touches any other concurrently-running request's context --
    that's the whole point of using a ContextVar instead of a plain global.
    """
    root = Path(path).expanduser().resolve()
    _ctx.set(_paths_for(root))
    ensure_dirs()
    return root


def use(path: str | Path) -> Path:
    """Point the whole module at a different vault.

    Kept for callers with no notion of a per-request session at all --
    tools/ scripts, tests, and the lifespan bootstrap before the first
    request ever arrives. Request-scoped code should go through a session
    (see sessions.switch_vault) instead, so one browser's vault switch
    doesn't leak into another's.
    """
    return set_current(path)


def __getattr__(name):
    # PEP 562 module __getattr__: only reached when `name` isn't a real
    # attribute of this module already. Lets every existing `vault.VAULT` /
    # `vault.NOTES` / `vault.MEDIA` / `vault.INDEX_DIR` call site elsewhere
    # in the app keep working completely unchanged, now resolving to the
    # calling context's vault instead of one shared global.
    paths = current()
    if name == "VAULT":
        return paths.vault
    if name == "NOTES":
        return paths.notes
    if name == "MEDIA":
        return paths.media
    if name == "INDEX_DIR":
        return paths.index_dir
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def looks_like_vault(path: str | Path) -> bool:
    p = Path(path).expanduser()
    # A permission-restricted sibling (a docker volume, another user's
    # folder) must make that one entry unreadable, not crash the whole scan
    # or HTTP request that is looking past it.
    try:
        return (p / "notes").is_dir()
    except OSError:
        return False


# Directory names that are never useful to show or descend into while looking
# for vaults — dependency trees and VCS/OS internals, not candidate vaults.
WALK_SKIP = {"node_modules", "Library", ".git", ".venv"}
WALK_MAX_DEPTH = 4


def walk(root: Path, depth: int = 0):
    """Yield vault directories under root, breadth stopping at each vault
    found (a vault's own subfolders are never candidate vaults) and depth
    capped so a search never wanders into an entire home directory. Symlinks
    are never followed, so a link cannot walk the search outside of `root`.
    """
    if depth > WALK_MAX_DEPTH or not root.is_dir():
        return
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for e in entries:
        try:
            if not e.is_dir() or e.is_symlink():
                continue
        except OSError:
            continue
        if e.name in WALK_SKIP:
            continue
        if looks_like_vault(e):
            yield e
            continue                      # do not descend into a vault
        yield from walk(e, depth + 1)


BROWSE_ROOT_ENV = "TEPHRA_BROWSE_ROOT"


def browse_root() -> Path:
    """Root the vault-picker's directory browser is confined to.

    Read fresh on every call rather than cached, so it always reflects the
    vault currently open (and TEPHRA_BROWSE_ROOT, if set) — not the vault
    that was open when the server started.
    """
    override = os.environ.get(BROWSE_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return current().vault.parent


def list_browsable(path: Path) -> list[dict]:
    """Immediate subdirectories of `path`, flagged with whether each looks
    like a vault. Symlinks are skipped outright — never listed, so browsing
    can never be used to hop outside the confined root via a linked entry.
    """
    out = []
    try:
        children = sorted(path.iterdir())
    except OSError:
        return out
    for e in children:
        try:
            if not e.is_dir() or e.is_symlink():
                continue
        except OSError:
            continue
        if e.name in WALK_SKIP:
            continue
        out.append({"name": e.name, "path": str(e), "is_vault": looks_like_vault(e)})
    return out

MEDIA_KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".bmp"},
    "video": {".mp4", ".webm", ".mov", ".m4v", ".ogv"},
    "audio": {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".opus"},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dirs() -> None:
    p = current()
    for d in (p.notes, p.media, p.index_dir):
        d.mkdir(parents=True, exist_ok=True)


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    for kind, exts in MEDIA_KINDS.items():
        if ext in exts:
            return kind
    return "file"


def slugify(title: str) -> str:
    s = unicodedata.normalize("NFKD", title)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "untitled"


def unique_slug(title: str, taken: set[str] | None = None) -> str:
    taken = taken if taken is not None else {p.stem for p in current().notes.glob("*.md")}
    base = slugify(title)
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


# ── frontmatter ────────────────────────────────────────────────────────────
# Deliberately a tiny fixed-schema parser rather than a YAML dependency:
# the format stays readable, and a malformed header can never blow up a
# whole vault scan.

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)


def parse(text: str) -> tuple[dict, str]:
    meta: dict = {}
    m = _FM.match(text)
    body = text
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            # `[a, b]` is a list; `[[Thing]]` is a damaged wikilink that leaked
            # into the header. Without this distinction a title of `[[DNS]]`
            # parsed as a list and crashed the index rebuild on open — which is
            # precisely the state a vault damaged by the old linker is in.
            if v.startswith("[") and v.endswith("]") and not v.startswith("[["):
                meta[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
            else:
                meta[k] = v.strip('"')
    return meta, body.lstrip("\n")


def dump(meta: dict, body: str) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


# Frontmatter keys the app owns. Everything else a note declares is carried
# in Note.meta and written back untouched, so features can add fields (and
# users can hand-edit them) without vault.py needing to know about them.
CORE_KEYS = ("title", "tags", "created", "updated")


@dataclass
class Note:
    slug: str
    title: str
    body: str = ""
    tags: list[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return current().notes / f"{self.slug}.md"

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "body": self.body,
            "tags": self.tags,
            "created": self.created,
            "updated": self.updated,
            "meta": self.meta,
        }


def read(slug: str) -> Note | None:
    p = current().notes / f"{slug}.md"
    if not p.is_file():
        return None
    meta, body = parse(p.read_text(encoding="utf-8"))
    # Belt and braces: one malformed header must never be able to put a
    # non-string where the index expects text.
    raw_title = meta.get("title")
    if isinstance(raw_title, list):
        raw_title = " ".join(str(x) for x in raw_title)
    return Note(
        slug=slug,
        title=(raw_title or "").strip() or slug.replace("-", " ").title(),
        body=body,
        tags=[str(t) for t in (meta.get("tags") or [])
              if isinstance(meta.get("tags"), list)],
        created=meta.get("created") or "",
        updated=meta.get("updated") or datetime.fromtimestamp(
            p.stat().st_mtime, timezone.utc
        ).isoformat(timespec="seconds"),
        meta={k: v for k, v in meta.items() if k not in CORE_KEYS},
    )


def write(note: Note) -> Note:
    """Atomic: write a temp file in the same directory, then rename over the
    target. A crash or a full disk mid-write leaves the old note intact
    rather than a truncated one."""
    ensure_dirs()
    note.updated = now()
    note.created = note.created or note.updated
    header = {
        "title": note.title,
        "tags": note.tags,
        "created": note.created,
        "updated": note.updated,
    }
    # Extra fields last so the core four stay at a predictable place in the file.
    for k, v in (note.meta or {}).items():
        if k not in CORE_KEYS:
            header[k] = v
    payload = dump(header, note.body)
    fd, tmp = tempfile.mkstemp(dir=current().notes, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, note.path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return note


def delete(slug: str) -> bool:
    p = current().notes / f"{slug}.md"
    if not p.is_file():
        return False
    trash = current().vault / ".trash"
    trash.mkdir(exist_ok=True)
    shutil.move(str(p), str(trash / f"{slug}-{int(datetime.now().timestamp())}.md"))
    return True


def all_notes() -> list[Note]:
    ensure_dirs()
    out = []
    for p in sorted(current().notes.glob("*.md")):
        n = read(p.stem)
        if n:
            out.append(n)
    return out


def rename(slug: str, new_title: str) -> Note | None:
    """Retitle and reslug, then repoint every [[wikilink]] that referenced
    the old title so renaming never silently breaks the graph."""
    note = read(slug)
    if not note:
        return None
    old_title = note.title
    new_slug = slug if slugify(new_title) == slug else unique_slug(
        new_title, {p.stem for p in current().notes.glob("*.md")} - {slug}
    )
    note.title = new_title
    if new_slug != slug:
        old_path = note.path
        note.slug = new_slug
        write(note)
        old_path.unlink(missing_ok=True)
    else:
        write(note)

    if old_title != new_title:
        pat = re.compile(r"\[\[\s*" + re.escape(old_title) + r"\s*(\|[^\]]*)?\]\]", re.I)
        for other in all_notes():
            if other.slug == note.slug:
                continue
            new_body = pat.sub(lambda m: f"[[{new_title}{m.group(1) or ''}]]", other.body)
            if new_body != other.body:
                other.body = new_body
                write(other)
    return note


def save_media(filename: str, data: bytes) -> dict:
    ensure_dirs()
    stem = slugify(Path(filename).stem)[:60] or "file"
    ext = Path(filename).suffix.lower()
    name = f"{stem}{ext}"
    n = 2
    media = current().media
    while (media / name).exists():
        name = f"{stem}-{n}{ext}"
        n += 1
    (media / name).write_bytes(data)
    return {
        "name": name,
        "url": f"/media/{name}",
        "kind": kind_of(name),
        "size": len(data),
    }


def import_media(name: str, data: bytes) -> dict:
    """Write to vault media at exactly the given name, overwriting.

    Unlike save_media's auto-uniquify (built for one-off drags into the media
    panel, where two unrelated uploads named `screenshot.png` must not
    collide), an import name is already deterministic per (note, source
    filename) -- see guide_import._media_name. Re-running the same guide
    should replace that one file in place, not accumulate `-2`, `-3`, ...
    copies on every run.
    """
    ensure_dirs()
    (current().media / name).write_bytes(data)
    return {
        "name": name,
        "url": f"/media/{name}",
        "kind": kind_of(name),
        "size": len(data),
    }


IMAGE_SCAN_MAX_DEPTH = 6


def find_images(root: Path, max_depth: int = IMAGE_SCAN_MAX_DEPTH) -> tuple[dict[str, Path], list[str]]:
    """Scan a directory tree for image files, keyed by lowercased filename.

    A guide's `images` list names files without saying which subdirectory
    they live in -- slide exports commonly land one folder per section, or
    everything flat -- so this walks the whole tree under `root` and lets a
    topic's filename resolve regardless of where it actually sits.

    First match wins in sorted (depth-first, alphabetical) order; every later
    file with a basename already claimed is reported back as a collision
    rather than silently shadowed -- two different slides both saved as
    `slide.png` is exactly the kind of mixup an import should surface, not
    guess at.
    """
    found: dict[str, Path] = {}
    dupes: list[str] = []

    def walk_(dir_: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(dir_.iterdir())
        except OSError:
            return
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    if e.name in WALK_SKIP or e.name.startswith("."):
                        continue
                    walk_(e, depth + 1)
                elif e.is_file() and e.suffix.lower() in MEDIA_KINDS["image"]:
                    key = e.name.lower()
                    if key in found:
                        dupes.append(e.name)
                    else:
                        found[key] = e
            except OSError:
                continue

    if root.is_dir():
        walk_(root, 0)
    return found, sorted(set(dupes))


def media_list() -> list[dict]:
    ensure_dirs()
    out = []
    for p in sorted(current().media.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            out.append(
                {
                    "name": p.name,
                    "url": f"/media/{p.name}",
                    "kind": kind_of(p.name),
                    "size": p.stat().st_size,
                }
            )
    return out
