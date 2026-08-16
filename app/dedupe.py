"""
Near-duplicate detection for notes.

Title-matching (guide_import's usual path) misses the case where the same
content comes back under a slightly different title, from a different-named
guide, or was typed by hand. This catches that by comparing content instead
of titles.

Stdlib only (difflib), matching the project's existing stance on this: see
study.Classifier, a hand-rolled TF-IDF k-NN built specifically to avoid a
60 MB dependency for arithmetic on a few hundred short documents. difflib's
character-sequence ratio is the right tool here rather than that TF-IDF
cosine similarity, too -- cosine measures topic/vocabulary overlap (two
*different* RAID notes would score high), difflib measures how much of the
actual text matches, which is what "these are the same note, lightly
reworded" means.
"""
from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from multiprocessing import get_context
from typing import Iterable

# Below this, two notes are unrelated enough not to mention.
REPORT_THRESHOLD = 0.90
# At or above this, treat a duplicate as certain enough to skip
# automatically -- anything under it only ever gets reported, never acted
# on, so a false positive can't silently discard real content.
AUTO_SKIP_THRESHOLD = 0.97

_WS = re.compile(r"\s+")
_MD_NOISE = re.compile(r"[#*_`>-]")


def normalize(text: str) -> str:
    """Strip the markdown furniture that varies between two otherwise
    identical notes (heading markers, bullet dashes, emphasis) so formatting
    differences never masquerade as content differences."""
    text = _MD_NOISE.sub(" ", text or "")
    return _WS.sub(" ", text).strip().lower()


def content_text(title: str, question: str | None, answer: str) -> str:
    """The text that actually carries a note's meaning, for comparison.
    Unlike study.feature_text, title and question aren't repeated for
    weighting -- this is a literal similarity ratio, not a classifier
    feature vector."""
    return normalize(" ".join(filter(None, [title, question or "", answer])))


def _could_match(len_a: int, len_b: int, threshold: float) -> bool:
    """SequenceMatcher.ratio() is bounded above by 2*min(len)/(len_a+len_b)
    -- if the two texts differ enough in length, no comparison can reach
    the threshold, so the real (much more expensive) comparison can be
    skipped outright."""
    if len_a == 0 or len_b == 0:
        return len_a == len_b
    shorter, longer = sorted((len_a, len_b))
    return 2 * shorter / (shorter + longer) >= threshold


def similarity(a: str, b: str) -> float:
    if not _could_match(len(a), len(b), REPORT_THRESHOLD):
        return 0.0
    # autojunk (the default) treats characters that recur heavily in *b*
    # specially once a sequence passes 200 elements -- ordinary prose is
    # mostly spaces and common letters, so past ~200 chars this makes
    # ratio() silently order-dependent (0.98 one way, 0.05 the other, on
    # genuinely near-identical text). Every note-length string can cross
    # that line, so this is off unconditionally, not just for long inputs.
    sm = SequenceMatcher(None, a, b, autojunk=False)
    # quick_ratio() is a cheap (character-frequency) upper bound on the real
    # ratio() -- unaffected by autojunk, since it doesn't use the popular-
    # element bookkeeping that autojunk controls. Real note text is mostly
    # unrelated to other real note text, so this rejects the vast majority
    # of pairs before paying for the expensive one: on an 86-note vault this
    # cut a 283s scan to 69s with byte-identical results.
    if sm.quick_ratio() < REPORT_THRESHOLD:
        return 0.0
    return sm.ratio()


def best_match(text: str, corpus: Iterable[tuple[str, str]]) -> tuple[str, float] | None:
    """Highest-scoring (key, ratio) at or above REPORT_THRESHOLD, or None.
    `corpus` is (key, normalized_text) pairs -- what a "key" means (a slug,
    a title) is the caller's business, not this function's."""
    best_key, best_ratio = None, 0.0
    for key, other in corpus:
        r = similarity(text, other)
        if r > best_ratio:
            best_key, best_ratio = key, r
    if best_key is not None and best_ratio >= REPORT_THRESHOLD:
        return best_key, best_ratio
    return None


def _scan_row(items: list[tuple[str, str, str, str]], i: int) -> list[dict]:
    """Every match for items[i] among the notes after it in length-sorted
    order -- one "row" of the comparison matrix. Pulled out to a plain,
    picklable module-level function so a worker process can run it: a
    closure or a method wouldn't survive being sent across the process
    boundary.

    _could_match's bound (2*shorter/(shorter+longer)) is monotonically
    non-increasing as the longer side grows, for a fixed shorter side. So
    with items in ascending-length order, once items[i] can't match
    items[j] it can't match anything after j either (all of them are even
    longer) -- the loop breaks instead of paying an O(1) rejection, plus a
    normalize()/content_text() call for a note the length gap already
    ruled out, for every remaining note in the vault. What actually counts
    as a match is unchanged: similarity() and REPORT_THRESHOLD are exactly
    what they were, so this changes which candidates get *visited*, never
    which pairs get *reported*.
    """
    slug_a, title_a, updated_a, text_a = items[i]
    len_a = len(text_a)
    out = []
    for slug_b, title_b, updated_b, text_b in items[i + 1:]:
        if not _could_match(len_a, len(text_b), REPORT_THRESHOLD):
            break
        r = similarity(text_a, text_b)
        if r >= REPORT_THRESHOLD:
            out.append({"a_slug": slug_a, "a_title": title_a, "a_updated": updated_a,
                       "b_slug": slug_b, "b_title": title_b, "b_updated": updated_b,
                       "similarity": round(r, 3)})
    return out


# Below this many notes, spinning up worker processes (spawn/fork startup,
# pickling the whole vault's text across the process boundary) costs more
# than running _scan_row in-process saves -- the O(n^2) comparison itself
# is still cheap at this scale, as study.Classifier's own sizing assumption
# already banks on ("dozens to low hundreds of notes").
PARALLEL_MIN_NOTES = 40

# Set once per worker process by _init_worker, read by _scan_row_worker.
# A Pool's initializer runs exactly once per worker and its effect persists
# across every task that worker picks up afterward -- the whole point of
# using it, rather than re-pickling the full (sorted, length-heavy) items
# list on every single task, is that each worker pays that cost once
# instead of once per row.
_worker_items: list[tuple[str, str, str, str]] = []


def _init_worker(items: list[tuple[str, str, str, str]]) -> None:
    global _worker_items
    _worker_items = items


def _scan_row_worker(i: int) -> list[dict]:
    return _scan_row(_worker_items, i)


def scan_notes(notes: list) -> list[dict]:
    """Every pair of existing notes scoring at or above REPORT_THRESHOLD,
    highest first.

    Sorted by length first (see _scan_row) so most vaults visit a small
    fraction of the n^2 pairs; a vault where every note happens to be
    nearly the same length degrades back to the full scan. Past
    PARALLEL_MIN_NOTES notes, rows are split across a worker pool sized to
    the machine's own CPU count -- this is genuinely CPU-bound, pure-Python
    work (SequenceMatcher, no I/O to overlap), so more cores is the only
    lever left once the pruning above has already cut what there is to do.
    multiprocessing is stdlib, matching this module's existing stance (see
    the file docstring); if process creation fails for any reason -- a
    sandboxed environment that blocks fork/spawn, for instance -- this
    falls back to the sequential loop rather than turning a working scan
    into a broken one.
    """
    items = [(n.slug, n.title, n.updated,
              content_text(n.title, n.meta.get("question"), n.body))
             for n in notes]
    items.sort(key=lambda item: len(item[3]))

    n = len(items)
    workers = min(os.cpu_count() or 1, n)
    out = []
    if n >= PARALLEL_MIN_NOTES and workers > 1:
        try:
            # The platform default context: fork on Linux/macOS, spawn on
            # Windows (desktop/launcher.py calls freeze_support() for
            # exactly this -- a frozen build using spawn without it
            # re-launches the whole app in every worker instead of just
            # running _scan_row_worker).
            ctx = get_context()
            with ctx.Pool(workers, initializer=_init_worker, initargs=(items,)) as pool:
                # chunksize=1: row cost varies a lot (early, shorter rows
                # can have much wider length-windows than later ones), so
                # workers pull one row at a time instead of sitting on an
                # uneven fixed batch while another worker idles.
                for row in pool.imap_unordered(_scan_row_worker, range(n), chunksize=1):
                    out.extend(row)
        except Exception:
            out = []
            for i in range(n):
                out.extend(_scan_row(items, i))
    else:
        for i in range(n):
            out.extend(_scan_row(items, i))

    out.sort(key=lambda d: -d["similarity"])
    return out
