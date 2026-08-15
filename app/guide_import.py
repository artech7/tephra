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
import itertools
import re
from pathlib import Path
from typing import Callable

from . import dedupe, study, vault

DEFAULT_ROOT_NOTE = "Study Guide"

# Recognised guide file extensions -- kept here rather than importers.ACCEPTED
# so resolve_guide_source never has to import importers just to read a tuple.
GUIDE_EXTENSIONS = (".json", ".py", ".csv", ".tsv", ".md")


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


def _category_index_line(cat_title: str, roots: list[str]) -> str:
    if not roots:
        return f"Study topics in **{cat_title}**."
    return (f"Study topics in **{cat_title}**. Part of "
            + ", ".join(f"[[{r}]]" for r in roots) + ".")


def resolve_guide_source(path: str) -> tuple[Path, Path]:
    """A path the user typed or browsed to -> (the guide file, the folder to
    search for its images).

    A bare file names the guide directly; its own parent folder is searched
    for images. A folder must contain exactly one recognised guide file --
    zero is a typo in the path, more than one is a real ambiguity (which
    guide?) -- either way it's cheaper to stop and say so than to guess and
    import the wrong file.
    """
    from . import importers

    p = Path(path).expanduser()
    if not p.exists():
        raise importers.ImportError_(f"{p} does not exist")
    if p.is_file():
        return p, p.parent
    if not p.is_dir():
        raise importers.ImportError_(f"{p} is neither a file nor a folder")

    candidates = sorted(f for f in p.iterdir()
                        if f.is_file() and f.suffix.lower() in GUIDE_EXTENSIONS)
    if not candidates:
        raise importers.ImportError_(
            f"no study guide file ({', '.join(GUIDE_EXTENSIONS)}) found in {p}")
    if len(candidates) > 1:
        names = ", ".join(f.name for f in candidates)
        raise importers.ImportError_(
            f"found more than one guide file in {p} ({names}) — point at the exact file")
    return candidates[0], p


def _media_name(slug: str, filename: str) -> str:
    """Deterministic per (note, source filename) so re-importing the same
    guide overwrites the same media file instead of piling up `-2`, `-3`..."""
    stem = vault.slugify(Path(filename).stem)[:60] or "image"
    ext = Path(filename).suffix.lower()
    return f"{slug}--{stem}{ext}"


def _place_images(slug: str, wanted: list[str], available: dict[str, Path | bytes],
                   dry_run: bool) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve a topic's requested image filenames against the images found
    under the search root, writing matches into vault media under a name
    derived from this note. Returns (embedded [(media name, original
    filename), ...], filenames that matched nothing) -- a miss is reported,
    not fatal, so one typo'd filename in a 40-topic guide doesn't block the
    other 39.

    The original filename comes back alongside the media name so the caller
    can caption the embed with it: the on-disk name is `{slug}--{filename}`,
    unique across the vault, but every one of a note's own images repeats
    that note's own (possibly long) title back at the reader as a prefix --
    exactly the string a caption should *not* be.

    `available` values are a Path when they came from vault.find_images (a
    server-side directory scan) or raw bytes when they came from files the
    browser itself read and uploaded -- either source resolves the same way
    from here on.
    """
    embedded, missing = [], []
    for filename in wanted:
        src = available.get(filename.lower())
        if src is None:
            missing.append(filename)
            continue
        name = _media_name(slug, filename)
        if not dry_run:
            data = src.read_bytes() if isinstance(src, Path) else src
            vault.import_media(name, data)
        embedded.append((name, filename))
    return embedded, missing


def run_import(source: str, dry_run: bool = False, filename: str = "guide.py",
                title: str | None = None,
                images: dict[str, Path | bytes] | None = None,
                progress: Callable[[int, int], None] | None = None) -> dict:
    """Merges into the vault -- never overwrites a note it doesn't own.

    `progress`, if given, is called with (done, total) once right after
    parsing (done=0, so a caller learns the total before any topic has been
    touched) and again after each topic is stepped past in the main loop --
    written, updated, or skipped as a near-duplicate, whichever applied.
    `done` reaches `total` exactly once every topic has been visited, so a
    caller can render a plain N-of-M bar without caring which outcome each
    topic got. Purely an observability hook; dry runs call it too; a caller
    with no interest in progress just doesn't pass one.

    `images` is a lowercased-filename -> (path or bytes) map: paths from
    vault.find_images (run_import_from_path's server-side directory scan),
    bytes from files a browser upload already read into memory
    (study_import_upload's flow). A caller with neither just doesn't pass
    one, and any topic's `images` list is reported as unmatched rather than
    failing the import.

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

    Title/id matching above only catches a topic that is *known* to be the
    same note. A topic that is a near-duplicate under a different title --
    reworded, or from a differently-named guide, or a hand-written note that
    already covers the same ground -- gets a content check instead (see
    dedupe.py): a near-certain match (>= dedupe.AUTO_SKIP_THRESHOLD) is
    skipped outright and never written; anything past dedupe.REPORT_THRESHOLD
    but short of that is imported as normal and reported back in
    `duplicates`, never silently dropped on a guess that might be wrong.

    Parsing is delegated by file type; everything below this line works on
    the one normalised topic shape, so a new format needs no changes here.
    """
    from . import importers
    topics = importers.parse(filename, source)
    if progress:
        progress(0, len(topics))
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
    # Content corpus for the dedup check, computed once rather than per
    # topic. Prose only -- quiz markup is stripped out so a heavy quiz
    # section can't skew the ratio away from the prose that actually
    # carries the content, matching what an incoming topic's own answer
    # text (no quiz rendered into it yet) looks like.
    existing_corpus = [
        (n.slug, dedupe.content_text(n.title, n.meta.get("question"),
                                     study.split_quiz(n.body)[0]))
        for n in existing.values()
    ]
    batch_corpus: list[tuple[str, str]] = []   # topics already accepted this run

    images = images or {}
    created = updated = preserved = skipped_duplicates = images_embedded = 0
    collisions: list[str] = []
    duplicates: list[dict] = []
    by_category: dict[str, list[str]] = {}
    missing_images: list[dict] = []

    total_topics = len(topics)
    for i, t in enumerate(topics, 1):
        title_ = t["title"]
        category = t["category"]
        content = dedupe.content_text(title_, t["question"], t["answer"])

        match_slug = None
        if t.get("id"):
            cand = id_to_slug.get(t["id"])
            if cand and existing[cand].meta.get("import_of") == root_note:
                match_slug = cand
        if match_slug is None:
            match_slug = owned_by_key.get((root_note, title_.strip().lower()))
        prior = existing.get(match_slug) if match_slug else None

        if prior is None:
            found = dedupe.best_match(content, itertools.chain(existing_corpus, batch_corpus))
            if found:
                dup_key, score = found
                dup_note = existing.get(dup_key)
                skip = score >= dedupe.AUTO_SKIP_THRESHOLD
                duplicates.append({
                    "title": title_,
                    "matches": dup_note.title if dup_note else dup_key,
                    "similarity": round(score, 3),
                    "skipped": skip,
                })
                if skip:
                    skipped_duplicates += 1
                    batch_corpus.append((title_, content))
                    if progress:
                        progress(i, total_topics)
                    continue

        batch_corpus.append((title_, content))

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
        embedded, missing = _place_images(slug, t.get("images") or [], images, dry_run)
        if embedded:
            # No blank line between the embeds -- render.py groups adjacent
            # embeds into one row, and sequential slide screenshots read
            # better side by side than stacked one per line. The original
            # filename becomes the caption (`|` is the embed syntax's own
            # field separator, so the rare filename containing one falls
            # back to no caption rather than a mis-parsed embed).
            body += "\n\n" + "\n".join(
                f"![[{n}]]" if "|" in orig else f"![[{n}|{orig}]]" for n, orig in embedded)
            images_embedded += len(embedded)
        if missing:
            missing_images.append({"topic": title_, "files": missing})
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
        if progress:
            progress(i, total_topics)

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

        # `linked` and `import_roots` both accumulate across every import
        # that has ever touched this category and neither is pruned when a
        # topic note or a whole guide's root note is later deleted by hand
        # -- so a stale title here would otherwise survive forever as a
        # dead [[link]] this importer itself wrote. Filtering against
        # title_to_slug (the vault as it stood before this run started)
        # drops anything that no longer resolves, every time the category
        # is touched by another import. reconcile_indexes() does the same
        # filtering on demand, for the case where nothing gets re-imported.
        linked = {t for t in (_linked_titles(cprior.body) if cprior else ())
                  if t.strip().lower() in title_to_slug}
        all_titles = sorted(set(titles) | linked)
        prior_roots = {r for r in (cprior.meta.get("import_roots") or ())
                       if r.strip().lower() in title_to_slug} if cprior else set()
        roots = sorted(prior_roots | {root_note})

        lines = [_category_index_line(cat_title, roots), ""]
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
        "skipped_duplicates": skipped_duplicates,
        "duplicates": duplicates,
        "dry_run": dry_run,
        "images_embedded": images_embedded,
        "missing_images": missing_images,
    }


def run_import_from_path(path: str, dry_run: bool = False, title: str | None = None,
                          progress: Callable[[int, int], None] | None = None) -> dict:
    """Import a guide plus its images straight off disk -- the counterpart to
    run_import's upload path, for guides that come with more image files than
    a browser upload should reasonably carry.

    The search root is the guide file's own folder (or the folder given, if a
    folder was given): every image anywhere under it, at any depth up to
    vault.find_images' limit, is fair game for a topic's `images` list to
    reference by filename.
    """
    from . import importers

    guide_path, search_root = resolve_guide_source(path)
    try:
        source = guide_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise importers.ImportError_(f"could not read {guide_path.name} as text: {exc}") from exc

    images, dupes = vault.find_images(search_root)
    summary = run_import(source, dry_run=dry_run, filename=guide_path.name, title=title,
                          images=images, progress=progress)
    summary["image_dir"] = str(search_root)
    summary["duplicate_image_names"] = dupes
    return summary


def reconcile_indexes(dry_run: bool = False) -> dict:
    """Drop dead references from importer-owned category index notes.

    run_import already filters a category's `linked` titles and
    `import_roots` against the vault every time that category gets
    re-imported (see the comment above that filtering) -- but a topic note
    or a whole guide's root note deleted by hand between imports leaves
    those stubs stale until the next import happens to touch that same
    category, which may be never. This runs the identical filter on
    demand, so cleaning up a duplicate guide doesn't require re-importing
    anything.

    Only touches notes with `import_roots` in their frontmatter -- the
    category index notes this importer generates and owns outright, never
    a hand-written note. A category with no topic left at all is removed
    rather than kept as an empty shell.

    `changed`/`removed` entries carry the specific dead titles dropped
    from each page (not just a bare count) -- the frontend shows these as
    a reviewable list before Clean-up runs, the same "see what's about to
    happen" shape /api/duplicates already gives Find-duplicate-notes.
    """
    notes = vault.all_notes()
    existing_titles = {n.title.strip().lower() for n in notes}
    report = {"scanned": 0, "changed": [], "removed": [], "dry_run": dry_run}
    for note in notes:
        if "import_roots" not in note.meta:
            continue
        report["scanned"] += 1
        linked = sorted(_linked_titles(note.body))
        all_titles = sorted(t for t in linked if t.strip().lower() in existing_titles)
        dead = sorted(t for t in linked if t.strip().lower() not in existing_titles)
        roots = sorted(r for r in (note.meta.get("import_roots") or ())
                       if r.strip().lower() in existing_titles)

        if not all_titles:
            report["removed"].append({"title": note.title, "slug": note.slug, "dead": dead})
            if not dry_run:
                vault.delete(note.slug)
            continue

        body = "\n".join([_category_index_line(note.title, roots), ""]
                         + [f"- [[{t}]]" for t in all_titles])
        # vault.write() round-trips a note's body through .strip() -- compare
        # stripped on both sides, or a fresh reconstruction with no trailing
        # newline reads as "changed" against every already-clean note too.
        if body.strip() != note.body.strip() or roots != sorted(note.meta.get("import_roots") or ()):
            report["changed"].append({"title": note.title, "slug": note.slug, "dead": dead})
            if not dry_run:
                note.meta["import_roots"] = roots
                note.body = body
                vault.write(note)
    return report


def strip_orphaned_topics(dry_run: bool = False) -> dict:
    """Un-study import-owned topic notes whose organizing category index has
    been deleted by hand.

    A topic note's own `category` field carries no link back to the index
    note that once grouped it -- the link only ever ran the other way, as a
    [[wikilink]] on the index page (see reconcile_indexes above). Deleting
    that index (a pure navigation stub, study: false) never touches the
    topics it pointed to, so they go on reporting a category Crucible has no
    index for and stay in quiz rotation indefinitely.

    Only category_source "import" topics are eligible. A category the user
    typed in by hand (category_source "manual") never required an index note
    to begin with, so applying this rule to it would strip notes that were
    never part of an index in the first place -- exactly the "questions from
    notes not in an index" this must leave alone.
    """
    notes = vault.all_notes()
    live_categories = {n.title.strip().lower() for n in notes
                       if n.meta.get("study_index") == "true"}
    report = {"scanned": 0, "orphaned": [], "dry_run": dry_run}
    for note in notes:
        if (note.meta.get("category_source") or "").strip() != "import":
            continue
        if not study.is_study(note):
            continue
        category = (note.meta.get("category") or "").strip()
        if not category:
            continue
        report["scanned"] += 1
        if category.lower() in live_categories:
            continue
        report["orphaned"].append({"title": note.title, "slug": note.slug, "category": category})
        if not dry_run:
            note.meta["study"] = "false"
            vault.write(note)
    return report
