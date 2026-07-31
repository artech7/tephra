"""
Importing the standalone FB Study Guide.

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

ROOT_NOTE = "FB Study Guide"


def read_literals(source: str):
    """Kept for the CLI's dry-run reporting; see importers.parse_python."""
    from .importers import parse_python
    topics = parse_python(source)
    return topics, [q for t in topics for q in t["quiz"]]


def tag_for(category: str) -> str:
    words = re.sub(r"[^\w\s]", " ", category).split()
    return words[0].lower() if len(words) == 1 else "".join(w[0] for w in words).lower()


def run_import(source: str, dry_run: bool = False, filename: str = "guide.py") -> dict:
    """Idempotent. Re-running updates notes in place and never clobbers a
    category the user corrected by hand.

    Parsing is delegated by file type; everything below this line works on the
    one normalised topic shape, so a new format needs no changes here.
    """
    from . import importers
    topics = importers.parse(filename, source)
    vault.ensure_dirs()
    existing = {n.slug: n for n in vault.all_notes()}
    title_to_slug = {n.title.strip().lower(): n.slug for n in existing.values()}

    created = updated = preserved = 0
    by_category: dict[str, list[str]] = {}

    for t in topics:
        title = t["title"]
        category = t["category"]
        slug = title_to_slug.get(title.lower()) or vault.unique_slug(title)
        prior = existing.get(slug)

        qitems = t["quiz"]
        body = t["answer"]
        if qitems:
            body += "\n\n" + study.render_quiz(qitems)

        meta = {
            "study": "true",
            "category": category,
            "category_source": "import",
            "question": t["question"],
        }
        if t.get("id"):
            meta["source_id"] = t["id"]
        if prior and (prior.meta.get("category_source") or "").strip() == "manual":
            meta["category"] = prior.meta.get("category", category)
            meta["category_source"] = "manual"
            preserved += 1

        note = vault.Note(
            slug=slug, title=title, body=body,
            tags=sorted({"study", tag_for(category)} | set(prior.tags if prior else [])),
            created=prior.created if prior else "",
            meta={**(prior.meta if prior else {}), **meta},
        )
        by_category.setdefault(meta["category"], []).append(title)
        if not dry_run:
            vault.write(note)
        updated += 1 if prior else 0
        created += 0 if prior else 1

    # Category indexes and a root note: this is what turns flat topics into a
    # navigable wiki, and it is what the graph view renders.
    for category, titles in sorted(by_category.items()):
        slug = title_to_slug.get(category.lower()) or vault.unique_slug(category)
        lines = [f"Study topics in **{category}**. Part of [[{ROOT_NOTE}]].", ""]
        lines += [f"- [[{t}]]" for t in sorted(titles)]
        if not dry_run:
            vault.write(vault.Note(
                slug=slug, title=category, body="\n".join(lines),
                tags=["study", "index"],
                meta={"study": "false", "study_index": "true"}))

    root = [
        "Interactive study guide imported from the standalone app. "
        "Open the **Study** tab to browse, drill flashcards, or take a quiz.",
        "", "## Categories", "",
    ]
    for category, titles in sorted(by_category.items()):
        root.append(f"- [[{category}]] — {len(titles)} "
                    f"topic{'s' if len(titles) != 1 else ''}")
    if not dry_run:
        vault.write(vault.Note(
            slug=vault.slugify(ROOT_NOTE), title=ROOT_NOTE, body="\n".join(root),
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
        "dry_run": dry_run,
    }
