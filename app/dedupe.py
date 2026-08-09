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

import re
from difflib import SequenceMatcher
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


def scan_notes(notes: list) -> list[dict]:
    """Every pair of existing notes scoring at or above REPORT_THRESHOLD,
    highest first. O(n^2) comparisons -- fine at the scale this app targets
    (dozens to low hundreds of notes, the same assumption study.Classifier
    already makes); the length pre-filter in similarity() keeps the
    obviously-unrelated majority of pairs cheap.
    """
    texts = [(n.slug, n.title, content_text(n.title, n.meta.get("question"), n.body))
             for n in notes]
    out = []
    for i in range(len(texts)):
        slug_a, title_a, text_a = texts[i]
        for slug_b, title_b, text_b in texts[i + 1:]:
            r = similarity(text_a, text_b)
            if r >= REPORT_THRESHOLD:
                out.append({"a_slug": slug_a, "a_title": title_a,
                           "b_slug": slug_b, "b_title": title_b,
                           "similarity": round(r, 3)})
    out.sort(key=lambda d: -d["similarity"])
    return out
