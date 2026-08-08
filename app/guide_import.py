"""
Importing a standalone study guide as a set of notes.

This lives in `app/` rather than `tools/` so the running server can call it.
That matters: a CLI importer has to be *told* which vault to write to, and
getting that wrong writes 76 notes into a directory the app never reads —
which looks exactly like the import silently failing. The server already
knows its own vault, so importing through it cannot miss.
"""
from __future__ import annotations

import ast
import re

from . import study, vault

DEFAULT_ROOT_NOTE = "Study Guide"


def read_literals(source: str):
    """Kept for the CLI's dry-run reporting; see importers.parse_python."""
    from .importers import parse_python
    topics = parse_python(source)
    return topics, [q for t in topics for q in t["quiz"]]


def tag_for(category: str) -> str:
    words = re.sub(r"[^\w\s]", " ", category).split()
    return words[0].lower() if len(words) == 1 else "".join(w[0] for w in words).lower()


def _title_from_filename(filename: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", filename or "")
    words = re.split(r"[\s_\-]+", stem.strip())
    words = [w for w in words if w]
    return " ".join(w if w.isupper() else w.capitalize() for w in words)


def root_title_for(filename: str, title: str | None = None) -> str:
    """Explicit title wins; otherwise tidy the uploaded filename; otherwise a
    generic fallback. Never assumes any particular guide."""
    return (title or "").strip() or _title_from_filename(filename) or DEFAULT_ROOT_NOTE


def _linked_titles(body: str) -> list[str]:
    """Titles a generated index note already links to, read back out of its
    own bullet list so a second guide can add to it rather than replace it."""
    return re.findall(r"^- \[\[(.+?)\]\]", body, flags=re.M)


def run_import(source: str, dry_run: bool = False, filename: str = "guide.py",
                title: str | None = None) -> dict:
    """Merges into the vault -- never overwrites a note it doesn't own.

    A title (or id) match only updates an existing note when that note was
    itself produced by a previous run of *this same guide* (tracked in
    meta["import_of"]/meta["source_id"]/meta["import_title"]). Any other
    title match -- a hand-written note, or one that came from a *different*
    guide -- is a real collision: the incoming topic is kept under a
    disambiguated title instead of clobbering it, and reported back so the
    caller can tell the user.

    Re-running the same guide stays idempotent even when that first run had
    to disambiguate: matching is keyed on (root note, the topic's *own*
    title as the source states it), not on whatever display title a past
    collision produced, so a re-import finds its own note again instead of
    piling up another one next to it. A category rename the user made by
    hand still sticks.

    Category and root index notes are pure navigation stubs this importer
    owns outright, so two guides that happen to share a category name merge
    onto one page instead of one replacing the other's links.

    Parsing is delegated by file type; everything below this line works on
    the one normalised topic shape, so a new format needs no changes here.
    """
    from . import importers
    topics = importers.parse(filename, source)
    root_note = root_title_for(filename, title)
    vault.ensure_dirs()
    existing = {n.slug: n for n in vault.all_notes()}
    title_to_slug = {n.title.strip().lower(): n.slug for n in existing.values()}
    id_to_slug = {n.meta.get("source_id"): n.slug for n in existing.values()
                  if n.meta.get("source_id")}
    # Notes this importer owns, keyed by the guide that made them and the
    # topic's own (un-suffixed) title -- stable across whatever disambiguated
    # display title a collision may have forced onto the note itself.
    owned_by_key = {
        (n.meta["import_of"], (n.meta.get("import_title") or n.title).strip().lower()): n.slug
        for n in existing.values() if n.meta.get("import_of")
    }
    # Notes this importer owns and can safely regenerate outright: index
    # pages, keyed by their current (possibly already-disambiguated) title.
    owned_index_slug = {
        n.title.strip().lower(): n.slug
        for n in existing.values() if n.meta.get("study_index") == "true"
    }

    created = updated = preserved = 0
    collisions: list[str] = []
    by_category: dict[str, list[str]] = {}

    for t in topics:
        title_ = t["title"]
        category = t["category"]

        match_slug = None
        if t.get("id"):
            cand = id_to_slug.get(t["id"])
            if cand and existing[cand].meta.get("import_of") == root_note:
                match_slug = cand
        if match_slug is None:
            match_slug = owned_by_key.get((root_note, title_.strip().lower()))
        prior = existing.get(match_slug) if match_slug else None

        collide_slug = title_to_slug.get(title_.lower())
        needs_suffix = collide_slug is not None and collide_slug != match_slug
        if needs_suffix:
            if prior is None:
                collisions.append(title_)
            display_title = f"{title_} ({root_note})"
        else:
            display_title = title_
        slug = match_slug or vault.unique_slug(display_title)

        qitems = t["quiz"]
        body = t["answer"]
        if qitems:
            body += "\n\n" + study.render_quiz(qitems)

        meta = {
            "study": "true",
            "category": category,
            "category_source": "import",
            "question": t["question"],
            "import_of": root_note,
            "import_title": title_,
        }
        if t.get("id"):
            meta["source_id"] = t["id"]
        if prior and (prior.meta.get("category_source") or "").strip() == "manual":
            meta["category"] = prior.meta.get("category", category)
            meta["category_source"] = "manual"
            preserved += 1

        note = vault.Note(
            slug=slug, title=display_title, body=body,
            tags=sorted({"study", tag_for(category)} | set(prior.tags if prior else [])),
            created=prior.created if prior else "",
            meta={**(prior.meta if prior else {}), **meta},
        )
        by_category.setdefault(meta["category"], []).append(display_title)
        if not dry_run:
            vault.write(note)
        updated += 1 if prior else 0
        created += 0 if prior else 1

    # Category indexes: shared, importer-owned navigation pages. A plain
    # category name already taken by a note we don't own is a real
    # collision; one we do own gets its topic list unioned, not replaced.
    category_title: dict[str, str] = {}
    for category, titles in sorted(by_category.items()):
        cslug = (owned_index_slug.get(category.lower())
                 or owned_index_slug.get(f"{category} ({root_note})".lower()))
        cprior = existing.get(cslug) if cslug else None
        collide_slug = title_to_slug.get(category.lower())
        if cprior is None and collide_slug is not None and collide_slug != cslug:
            collisions.append(category)
            cat_title = f"{category} ({root_note})"
            cslug = vault.unique_slug(cat_title)
        elif cprior is not None:
            cat_title = cprior.title
        else:
            cat_title = category
            cslug = vault.unique_slug(category)
        category_title[category] = cat_title

        linked = set(_linked_titles(cprior.body)) if cprior else set()
        all_titles = sorted(set(titles) | linked)
        roots = sorted(set(cprior.meta.get("import_roots") or []) | {root_note}) if cprior else [root_note]

        lines = [f"Study topics in **{cat_title}**. Part of "
                 + ", ".join(f"[[{r}]]" for r in roots) + ".", ""]
        lines += [f"- [[{t}]]" for t in all_titles]
        if not dry_run:
            vault.write(vault.Note(
                slug=cslug, title=cat_title, body="\n".join(lines),
                tags=["study", "index"],
                meta={"study": "false", "study_index": "true", "import_roots": roots}))

    # Root note: one per guide, keyed by its own title, so two different
    # guides never contend for it -- only a re-import of the same guide, or a
    # hand-written note with the exact same title, can match here.
    rslug = (owned_index_slug.get(root_note.lower())
             or owned_index_slug.get(f"{root_note} (import)".lower()))
    rprior = existing.get(rslug) if rslug else None
    rcollide_slug = title_to_slug.get(root_note.lower())
    if rprior is None and rcollide_slug is not None and rcollide_slug != rslug:
        collisions.append(root_note)
        root_title = f"{root_note} (import)"
        rslug = vault.unique_slug(root_title)
    elif rprior is not None:
        root_title = rprior.title
    else:
        root_title = root_note
        rslug = vault.unique_slug(root_note)

    root = [
        "Interactive study guide imported from the standalone app. "
        "Open the **Study** tab to browse, drill flashcards, or take a quiz.",
        "", "## Categories", "",
    ]
    for category, titles in sorted(by_category.items()):
        root.append(f"- [[{category_title[category]}]] — {len(titles)} "
                    f"topic{'s' if len(titles) != 1 else ''}")
    if not dry_run:
        vault.write(vault.Note(
            slug=rslug, title=root_title, body="\n".join(root),
            tags=["study", "index"], meta={"study": "false", "study_index": "true"}))

    return {
        "vault": str(vault.VAULT),
        "topics": len(topics),
        "questions": sum(len(t["quiz"]) for t in topics),
        "created": created,
        "updated": updated,
        "categories": len(by_category),
        "notes_total": created + updated + len(by_category) + 1,
        "manual_overrides_kept": preserved,
        "collisions": collisions,
        "dry_run": dry_run,
    }
