"""
Study guide layer.

Study items are notes. Nothing lives in a separate store: a note becomes a
study item when its frontmatter says `study: true`, and its quiz questions are
a markdown section inside it. That keeps the whole feature inside the same
promise as the rest of Tephra — your content is readable files, and the app is
a lens over them.

Categorisation is two-tier, checked in order:

  1. `category_source: manual` or `import`  — ground truth, never re-guessed.
  2. k-NN over those ground-truth items      — learns *your* taxonomy.

Before anything is labelled, or when a note has no vocabulary in common with
what's been trained, a category name is derived from the note's own words
instead of guessed — a vault can be about anything, so nothing here assumes
a topic. Tier 2 is what makes corrections compound: fixing one category
shifts every similar item, because the corrected item joins the training set.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict

from . import sessions as sess
from . import vault

PROGRESS = "study-progress.json"
DEFAULT_QUIZ_COUNT = 12
MAX_QUIZ_COUNT = 200      # the whole imported bank is 135, so leave headroom

QUIZ_HEADING = re.compile(r"^##\s+Quiz\s*$", re.M | re.I)
Q_LINE = re.compile(r"^Q:\s*(.+?)\s*$", re.M)
OPT_LINE = re.compile(r"^-\s*(\[[ xX]\]\s*)?(.+?)\s*$")
WHY_LINE = re.compile(r"^Why:\s*(.+?)\s*$", re.M)

TRUTHY = {"true", "yes", "1", "on"}

CODE_FENCE = re.compile(r"```.*?```", re.S)

# Tuned by leave-one-out cross-validation over the imported corpus. Titles and
# the question line carry nearly all the signal; the tail of a long answer is
# mostly worked examples whose vocabulary belongs to other categories (a `grep`
# note is full of log filenames, which pulled it into Log Analysis every time).
W_TITLE = 5
W_QUESTION = 3
PROSE_CHARS = 600

_WORD = re.compile(r"[a-z0-9][a-z0-9_+-]{1,}")
_STOP = set("""the a an and or but if then than that this these those of in on at to for from by
with without into onto over under is are was were be been being it its as not no so such can
could should would will may might must do does did done have has had you your we our they them
their he she his her one two use used using see also when where which who what why how all any
both each few other some own same too much many every there here up down out off again during
until against among between through above below more most less least set get got make made""".split())


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2]


def suggest_name(text: str) -> str | None:
    """Derive a candidate study-group name straight from a note's own words,
    for when nothing in the vault is a real match yet.

    `text` is expected to already be `feature_text()`'s title-weighted blend,
    so a title's words repeat consecutively and naturally dominate — the
    same "title carries nearly all the signal" assumption the classifier
    itself is tuned on. A two-word phrase reads more like a category name
    ("Bee Keeping") than a single word, so a repeated bigram wins over a
    repeated single word; a self-paired bigram (an artifact of a one-word
    title repeating against itself at the weighting seam) doesn't count.
    """
    words = tokens(text)
    if not words:
        return None
    bigrams = Counter((a, b) for a, b in zip(words, words[1:]) if a != b)
    if bigrams:
        top_bg, bg_n = bigrams.most_common(1)[0]
        if bg_n >= 2:
            return " ".join(w.capitalize() for w in top_bg)
    top_w, w_n = Counter(words).most_common(1)[0]
    return top_w.capitalize() if w_n >= 2 else None


# ── parsing ────────────────────────────────────────────────────────────────

def is_study(note: vault.Note) -> bool:
    return str(note.meta.get("study", "")).strip().lower() in TRUTHY


def split_quiz(body: str) -> tuple[str, str]:
    """Return (prose, quiz_section). The quiz lives under a `## Quiz` heading
    so it renders as ordinary markdown when you read the note directly."""
    m = QUIZ_HEADING.search(body)
    if not m:
        return body, ""
    return body[: m.start()].rstrip(), body[m.end():].strip()


def _plain(text: str) -> str:
    """Strip wiki syntax from text that is never meant to be a link.

    Quiz questions, options and explanations are read aloud, not navigated. If a
    damaged file still contains `[[Answer [[Ping]]|answer ping]]`, the reader
    should see "answer ping" — the display must not depend on the file having
    been repaired yet.
    """
    from .index import flatten_nested_links, unlink
    if "[[" not in text:
        return text
    flat, _ = flatten_nested_links(text)
    return unlink(flat)


def parse_quiz(section: str) -> list[dict]:
    """Parse Q / option / Why blocks.

    `answers` is every `[x]`-marked option's index, not just one -- a
    question can have more than one correct choice, marked with multiple
    `[x]` lines. A malformed block is skipped rather than raising: this is
    user-edited markdown, and one typo must not take down the whole study
    section.
    """
    if not section.strip():
        return []
    out: list[dict] = []
    blocks = re.split(r"\n(?=Q:\s)", section.strip())
    for blk in blocks:
        qm = Q_LINE.search(blk)
        if not qm:
            continue
        question = qm.group(1).strip()
        options: list[str] = []
        answers: list[int] = []
        for line in blk.splitlines():
            om = OPT_LINE.match(line.strip())
            if line.strip().startswith("-") and om:
                marked = bool(om.group(1) and om.group(1).strip().lower() == "[x]")
                text = om.group(2).strip()
                if not text:
                    continue
                if marked:
                    answers.append(len(options))
                options.append(text)
        wm = WHY_LINE.search(blk)
        if len(options) < 2 or not answers:
            continue                    # unanswerable; leave it out
        out.append({
            "question": _plain(question),
            "options": [_plain(o) for o in options],
            "answers": answers,
            "why": _plain(wm.group(1).strip()) if wm else "",
        })
    return out


def render_quiz(items: list[dict]) -> str:
    lines = ["## Quiz", ""]
    for it in items:
        lines.append(f"Q: {it['question']}")
        marked = set(it["answers"])
        for i, opt in enumerate(it["options"]):
            lines.append(f"- {'[x] ' if i in marked else ''}{opt}")
        if it.get("why"):
            lines.append(f"Why: {it['why']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def quiz_id(slug: str, question: str) -> str:
    """Stable id from slug + question text, so progress survives reordering
    and re-import but resets if the question itself is rewritten."""
    import hashlib
    return slug + ":" + hashlib.sha1(question.encode()).hexdigest()[:10]


def load_item(note: vault.Note) -> dict:
    prose, quizsec = split_quiz(note.body)
    quiz = parse_quiz(quizsec)
    for q in quiz:
        q["id"] = quiz_id(note.slug, q["question"])
    return {
        "slug": note.slug,
        "title": note.title,
        "category": (note.meta.get("category") or "").strip() or None,
        "source": (note.meta.get("category_source") or "auto").strip(),
        "confidence": _as_float(note.meta.get("category_confidence")),
        "question": _plain((note.meta.get("question") or "").strip()) or None,
        "prose": prose,
        "quiz": quiz,
        "updated": note.updated,
        "tags": note.tags,
    }


def _as_float(v) -> float | None:
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def all_items() -> list[dict]:
    return [load_item(n) for n in vault.all_notes() if is_study(n)]


# ── classifier ─────────────────────────────────────────────────────────────

class Classifier:
    """TF-IDF weighted k-NN. Pure stdlib on purpose.

    The corpus here is dozens to low hundreds of short documents. sklearn
    would be a 60 MB dependency to do arithmetic that takes milliseconds,
    and it would have to be shipped in the container and every desktop build.
    """

    K = 5

    # Vote share turned out to be a near-useless confidence signal: one
    # category dominates the K neighbours even when it is wrong (median 0.60
    # correct vs 0.53 wrong). The margin between the top two categories
    # separates cleanly (0.32 vs 0.18), so that is what gates the flag.
    #
    # These thresholds catch ~85% of misclassifications at the cost of asking
    # about roughly 60% of new items. That trade is deliberate: an unreviewed
    # wrong category quietly corrupts the study guide, while a flagged one
    # costs a single click.
    MIN_SIM = 0.20
    MIN_MARGIN = 0.26

    def __init__(self) -> None:
        self.docs: list[tuple[Counter, float, str]] = []   # tf, norm, category
        self.idf: dict[str, float] = {}
        self.categories: list[str] = []

    def fit(self, labelled: list[tuple[str, str]]) -> None:
        self.docs.clear()
        self.categories = sorted({c for _, c in labelled})
        if not labelled:
            return
        df: Counter = Counter()
        raw = []
        for text, cat in labelled:
            tf = Counter(tokens(text))
            raw.append((tf, cat))
            df.update(tf.keys())
        n = len(raw)
        self.idf = {t: math.log((n + 1) / (d + 1)) + 1.0 for t, d in df.items()}
        for tf, cat in raw:
            vec, norm = self._vec(tf)
            self.docs.append((vec, norm, cat))

    def _vec(self, tf: Counter) -> tuple[Counter, float]:
        vec = Counter()
        for t, c in tf.items():
            idf = self.idf.get(t)
            if idf:
                vec[t] = (1.0 + math.log(c)) * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return vec, norm

    def predict(self, text: str) -> dict:
        if not self.docs:
            return self._content_guess(text)

        tf = Counter(tokens(text))
        qvec, qnorm = self._vec(tf)
        if not qvec:
            # Every one of this note's words is either a stopword or simply
            # doesn't appear anywhere in the trained vocabulary — the
            # strongest possible "nothing here is related" signal, whether
            # that's because the note is nearly blank or because it shares
            # no vocabulary at all with what's been trained on.
            return self._content_guess(text)

        scored = []
        for vec, norm, cat in self.docs:
            small, big = (qvec, vec) if len(qvec) < len(vec) else (vec, qvec)
            dot = sum(w * big.get(t, 0.0) for t, w in small.items())
            scored.append((dot / (qnorm * norm), cat, vec))
        scored.sort(key=lambda s: s[0], reverse=True)

        # sim_top is the raw similarity of the single nearest trained example,
        # independent of how votes split among the top K — a genuine "is
        # anything in this vault even close" signal, unlike the margin below
        # (which measures a close contest between plausible candidates, not
        # whether either candidate is actually relevant). But on a short note,
        # both vectors can be so sparse that ONE coincidentally shared rare
        # word (e.g. "history", shared by a whaling note and an unrelated
        # Windows event-log note) is enough to inflate cosine similarity past
        # a raw threshold on its own. So the nearest neighbour also has to
        # share more than one real term before it counts as evidence, not
        # just coincidence. Below either bar, forcing the nearest-but-unrelated
        # category onto a note is worse than admitting no real match exists
        # and naming the note from its own words instead.
        sim_top, _, top_vec = scored[0]
        shared_terms = sum(1 for t in qvec if t in top_vec)
        if sim_top < self.MIN_SIM or shared_terms < 2:
            return self._content_guess(text)

        votes: dict[str, float] = defaultdict(float)
        for sim, cat, _ in scored[: self.K]:
            votes[cat] += sim
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        total = sum(votes.values()) or 1.0
        top, top_score = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = (top_score - runner) / total

        return {
            "category": top,
            "confidence": round(min(top_score / total, 1.0), 3),
            "margin": round(margin, 3),
            "similarity": round(sim_top, 3),
            "low_confidence": sim_top < self.MIN_SIM or margin < self.MIN_MARGIN,
            "method": "knn",
            "alternatives": [{"category": c, "score": round(v / total, 3)}
                             for c, v in ranked[1:4]],
        }

    def _content_guess(self, text: str) -> dict:
        """Nothing in the user's own trained categories is a real match —
        rather than force the note under an unrelated label, derive a
        candidate name straight from the note's own words. This is also
        the whole story before anything has been labelled at all: a vault
        can be about any topic, so cold start assumes nothing."""
        return {"category": suggest_name(text), "confidence": 0.0,
                "method": "content", "low_confidence": True, "alternatives": []}


_clf = Classifier()
_fitted_on = -1


def feature_text(title: str, question: str | None, prose: str) -> str:
    """Weight the fields by how much signal they actually carry."""
    body = CODE_FENCE.sub(" ", prose or "")[:PROSE_CHARS]
    return " ".join([(title + " ") * W_TITLE,
                     ((question or "") + " ") * W_QUESTION,
                     body])


def training_set(items: list[dict]) -> list[tuple[str, str]]:
    """Only human-confirmed labels train the model. Auto-assigned categories
    are excluded deliberately — feeding a classifier its own guesses back is
    how you get confident nonsense."""
    return [
        (feature_text(it["title"], it["question"], it["prose"]), it["category"])
        for it in items
        if it["category"] and it["source"] in ("manual", "import")
    ]


def ensure_fitted(items: list[dict], force: bool = False) -> Classifier:
    global _fitted_on
    sig = hash(tuple(sorted(
        (it["slug"], it["category"], it["source"], it["updated"])
        for it in items if it["source"] in ("manual", "import")
    )))
    if force or sig != _fitted_on:
        _clf.fit(training_set(items))
        _fitted_on = sig
    return _clf


def classify_note(note: vault.Note, items: list[dict] | None = None) -> dict:
    items = items if items is not None else all_items()
    clf = ensure_fitted(items)
    prose, _ = split_quiz(note.body)
    return clf.predict(feature_text(note.title, note.meta.get("question"), prose))


def known_categories(items: list[dict]) -> list[str]:
    return sorted({it["category"] for it in items if it["category"]})


# ── progress ───────────────────────────────────────────────────────────────
#
# Quiz/flashcard progress -- answer history, flags, spaced-repetition stats --
# used to be one shared study-progress.json per vault. Two people quizzing
# the same vault at once were silently overwriting each other's answers and
# weak-spot tracking. It's now namespaced per *session*, so each browser has
# its own progress against a shared vault, same as everyone seeing the same
# notes but keeping separate reading positions.
#
# A caller with no session in play at all (a test or tool calling into
# study.py directly, with no HTTP request and thus no session_middleware
# having run) falls back to the original single shared file -- same
# behaviour this always had outside of a running server.

def progress_path():
    try:
        current = sess.current_session()
    except LookupError:
        return vault.VAULT / PROGRESS
    d = vault.VAULT / ".sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{current.id}-{PROGRESS}"


def load_progress() -> dict:
    p = progress_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text())
            data.setdefault("answers", {})
            data.setdefault("flagged", [])
            data.setdefault("settings", {})
            data["settings"].setdefault("quiz_count", DEFAULT_QUIZ_COUNT)
            return data
        except Exception:
            pass
    return {"answers": {}, "flagged": [],
            "settings": {"quiz_count": DEFAULT_QUIZ_COUNT}}


def save_progress(data: dict) -> None:
    vault.ensure_dirs()
    progress_path().write_text(json.dumps(data, indent=2))


def record_answer(qid: str, correct: bool) -> dict:
    data = load_progress()
    rec = data["answers"].setdefault(qid, {"seen": 0, "right": 0})
    rec["seen"] += 1
    if correct:
        rec["right"] += 1
    save_progress(data)
    return rec


# ── category history ────────────────────────────────────────────────────────
# Kept in the note's own frontmatter as one line, newest first:
#
#   category_history: Linux Commands @2026-07-30T07:12:00+00:00 ~auto | ...
#
# A single delimited string rather than JSON because the frontmatter parser
# treats a leading "[" as a list — structured syntax there would be misread.
HISTORY_KEY = "category_history"
HISTORY_MAX = 10
_ENTRY = re.compile(r"^(?P<cat>.*?)\s+@(?P<at>\S+)(?:\s+~(?P<src>\S+))?$")


def parse_history(raw) -> list[dict]:
    if not raw or not isinstance(raw, str):
        return []
    out = []
    for chunk in raw.split(" | "):
        m = _ENTRY.match(chunk.strip())
        if not m:
            continue
        cat = m.group("cat").strip()
        if cat:
            out.append({"category": cat, "at": m.group("at"),
                        "source": m.group("src") or "manual"})
    return out


def encode_history(entries: list[dict]) -> str:
    return " | ".join(
        f"{e['category']} @{e['at']} ~{e.get('source', 'manual')}"
        for e in entries[:HISTORY_MAX]
    )


def push_history(note: vault.Note, previous_category: str,
                 previous_source: str) -> None:
    """Record where the note was before this change.

    Records the *departed* state, not the new one, so the trail reads as a list
    of places the note has been and each entry is directly revertible.
    """
    previous_category = (previous_category or "").strip()
    if not previous_category:
        return
    entries = parse_history(note.meta.get(HISTORY_KEY))
    if entries and entries[0]["category"].lower() == previous_category.lower():
        return                      # no-op change; do not pad the trail
    entries.insert(0, {"category": previous_category,
                       "at": vault.now(), "source": previous_source or "manual"})
    note.meta[HISTORY_KEY] = encode_history(entries)


def flags_by_slug() -> dict[str, int]:
    """Flagged question ids are `<slug>:<hash>`, and slugify() can never emit a
    colon, so the prefix is an unambiguous note reference. That means the flag
    a question carries in Crucible is also a fact about a note in Tephra."""
    counts: dict[str, int] = {}
    for qid in load_progress()["flagged"]:
        slug = qid.rsplit(":", 1)[0]
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
    return counts


def set_quiz_count(n: int) -> int:
    """Remembered in the vault rather than the browser, so the choice survives
    a reinstall and follows the notes."""
    data = load_progress()
    n = max(1, min(int(n), MAX_QUIZ_COUNT))
    data["settings"]["quiz_count"] = n
    save_progress(data)
    return n


def set_flag(qid: str, flagged: bool) -> list[str]:
    data = load_progress()
    fl = set(data["flagged"])
    fl.add(qid) if flagged else fl.discard(qid)
    data["flagged"] = sorted(fl)
    save_progress(data)
    return data["flagged"]
