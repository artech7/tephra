"""
Vault: plain markdown files on disk are the source of truth.

Nothing in here depends on the index or the web layer. If you delete the
index database the vault is untouched; if you delete the app entirely you
still have a directory of markdown you can read, grep, and commit to git.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("TEPHRA_VAULT", "/vault"))
NOTES = VAULT / "notes"
MEDIA = VAULT / "media"
INDEX_DIR = VAULT / ".index"


def use(path: str | Path) -> Path:
    """Point the whole module at a different vault.

    These are module globals read all over the app, so switching has to rebind
    them together — and every caller must re-derive paths from the module
    rather than caching them. The index connection is owned by main.py and is
    reopened there after this returns.
    """
    global VAULT, NOTES, MEDIA, INDEX_DIR
    VAULT = Path(path).expanduser().resolve()
    NOTES = VAULT / "notes"
    MEDIA = VAULT / "media"
    INDEX_DIR = VAULT / ".index"
    ensure_dirs()
    return VAULT


def looks_like_vault(path: str | Path) -> bool:
    p = Path(path).expanduser()
    return (p / "notes").is_dir()

MEDIA_KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".bmp"},
    "video": {".mp4", ".webm", ".mov", ".m4v", ".ogv"},
    "audio": {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".opus"},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dirs() -> None:
    for d in (NOTES, MEDIA, INDEX_DIR):
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
    taken = taken if taken is not None else {p.stem for p in NOTES.glob("*.md")}
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
        return NOTES / f"{self.slug}.md"

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
    p = NOTES / f"{slug}.md"
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
    fd, tmp = tempfile.mkstemp(dir=NOTES, suffix=".tmp")
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
    p = NOTES / f"{slug}.md"
    if not p.is_file():
        return False
    trash = VAULT / ".trash"
    trash.mkdir(exist_ok=True)
    shutil.move(str(p), str(trash / f"{slug}-{int(datetime.now().timestamp())}.md"))
    return True


def all_notes() -> list[Note]:
    ensure_dirs()
    out = []
    for p in sorted(NOTES.glob("*.md")):
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
        new_title, {p.stem for p in NOTES.glob("*.md")} - {slug}
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
    while (MEDIA / name).exists():
        name = f"{stem}-{n}{ext}"
        n += 1
    (MEDIA / name).write_bytes(data)
    return {
        "name": name,
        "url": f"/media/{name}",
        "kind": kind_of(name),
        "size": len(data),
    }


def media_list() -> list[dict]:
    ensure_dirs()
    out = []
    for p in sorted(MEDIA.iterdir()):
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
