"""
Study-guide importers.

Everything lands on one normalised shape before it touches the vault:

    {"title", "category", "question", "answer", "id", "images": [filename, ...],
     "quiz": [{"question", "options", "answers", "why"}]}

`images` names files by filename only, not path -- where they actually live
on disk (flat, nested under an `images/` folder, split one folder per
section) is guide_import's problem to solve by searching, via
vault.find_images, not the guide author's to spell out. A name with no match
anywhere under the search root is reported back, not a failure: a typo in a
topic's image list shouldn't block the topics that don't have one.

Every external format still names one correct choice per question (`answer`,
singular) -- that's the interchange syntax people actually write. It's
wrapped into `answers: [index]` once normalised, matching study.py's
internal shape, which does allow more than one correct index (multi-select
questions built through the in-app quiz editor, not through import).

Adding a format means writing a parser to that shape and nothing else. Field
names are matched leniently on purpose — a guide someone exported from a
spreadsheet should not fail because the column says `explanation` instead of
`why`.
"""
from __future__ import annotations

import ast
import csv
import io
import json
import re

# Aliases accepted for each normalised field, in priority order.
ALIASES = {
    "title":    ("title", "topic", "name", "subject", "term"),
    "category": ("category", "cat", "section", "group", "area", "module"),
    "question": ("question", "q", "prompt", "front"),
    "answer":   ("answer", "a", "body", "content", "explanation", "back", "notes"),
    "id":       ("id", "slug", "key", "ref"),
}
QUIZ_ALIASES = {
    "question": ("question", "q", "prompt", "stem"),
    "options":  ("options", "o", "choices", "answers", "opts"),
    "answer":   ("answer", "a", "correct", "correct_index", "correct_answer", "key"),
    "why":      ("why", "explanation", "rationale", "note", "because", "feedback"),
}
IMAGE_ALIASES = ("images", "image", "pictures", "screenshots", "slides")
TOPIC_REF = ("topic", "t", "topic_id", "for", "parent", "title")

# In a CSV, `answer` is the topic's prose body, so it must not be read as the
# quiz key — that collision silently dropped every question. Explicit keys are
# tried first; bare `answer` is only accepted if it actually resolves against
# the options, which distinguishes "RAID 1" from "RAID 0 stripes data...".
CSV_KEY_FIRST = ("correct", "correct_index", "correct_answer", "correct_option", "key")


class ImportError_(ValueError):
    """Raised with a message meant to be shown to the user verbatim."""


def _pick(d: dict, names: tuple[str, ...], default=None):
    lower = {str(k).strip().lower(): v for k, v in d.items()}
    for n in names:
        if n in lower and lower[n] not in (None, ""):
            return lower[n]
    return default


def _resolve_answer(value, options: list[str], one_based: bool = False) -> int:
    """Accept an index, a letter, or the option text.

    Order matters: exact option text is checked *before* treating digits as an
    index, or an option literally named "9000" gets read as index 9000 and the
    question is silently dropped.

    Index base differs by format because author expectations do. Code-authored
    JSON and Python use 0-based; a spreadsheet author writing `2` means the
    second option. Either way, if one reading is out of range and the other
    fits, the one that fits wins.
    """
    if isinstance(value, bool) or value is None:
        raise ImportError_("quiz answer must be an index or option text")

    text = str(value).strip()
    if not text:
        raise ImportError_("quiz question has no answer")

    # 1. exact option text
    for i, opt in enumerate(options):
        if str(opt).strip().lower() == text.lower():
            return i

    # 2. single letter
    if len(text) == 1 and text.isalpha():
        idx = ord(text.upper()) - 65
        if 0 <= idx < len(options):
            return idx

    # 3. index
    if isinstance(value, int) or re.fullmatch(r"-?\d+", text):
        n = int(text)
        first, second = (n - 1, n) if one_based else (n, n - 1)
        for cand in (first, second):
            if 0 <= cand < len(options):
                return cand
        raise ImportError_(f"answer index {n} is outside the {len(options)} options")

    raise ImportError_(f"answer {text!r} does not match any option")


def _norm_quiz(raw: list, one_based: bool = False) -> list[dict]:
    out = []
    for q in raw or []:
        if not isinstance(q, dict):
            continue
        question = _pick(q, QUIZ_ALIASES["question"])
        options = _pick(q, QUIZ_ALIASES["options"]) or []
        if isinstance(options, str):
            options = [o.strip() for o in re.split(r"\s*\|\s*|\s*;\s*", options) if o.strip()]
        options = [str(o) for o in options if str(o).strip()]
        if not question or len(options) < 2:
            continue
        try:
            answer = _resolve_answer(_pick(q, QUIZ_ALIASES["answer"], 0), options,
                                     one_based)
        except ImportError_:
            continue          # skip the question, don't fail the whole import
        out.append({"question": str(question).strip(), "options": options,
                    "answers": [answer],
                    "why": str(_pick(q, QUIZ_ALIASES["why"], "") or "").strip()})
    return out


def _norm_images(raw) -> list[str]:
    """A single filename, a delimited string of several, or a list of either
    -- matching how loosely every other field here is read. Order is kept
    (it becomes embed order in the note) and case-insensitive duplicates
    within one topic are dropped."""
    if isinstance(raw, str):
        items = [s.strip() for s in re.split(r"\s*[|;,]\s*", raw) if s.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        items = []
    seen: set[str] = set()
    out = []
    for name in items:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _norm_topic(raw: dict) -> dict | None:
    title = _pick(raw, ALIASES["title"])
    if not title:
        return None
    return {
        "id": str(_pick(raw, ALIASES["id"], "") or "").strip(),
        "title": str(title).strip(),
        "category": str(_pick(raw, ALIASES["category"], "Uncategorised")).strip()
                    or "Uncategorised",
        "question": str(_pick(raw, ALIASES["question"], "") or "").strip(),
        "answer": str(_pick(raw, ALIASES["answer"], "") or "").strip(),
        "images": _norm_images(_pick(raw, IMAGE_ALIASES, [])),
        "quiz": _norm_quiz(_pick(raw, ("quiz", "questions", "mcq", "items"), [])),
    }


def _attach_loose_quiz(topics: list[dict], quiz: list[dict]) -> None:
    """A flat quiz array referencing topics by id or title — the shape most
    exports produce, since it lets the quiz and topic data live as separate
    tables instead of nesting one inside the other."""
    by_id = {t["id"].lower(): t for t in topics if t["id"]}
    by_title = {t["title"].lower(): t for t in topics}
    for q in quiz or []:
        if not isinstance(q, dict):
            continue
        ref = str(_pick(q, TOPIC_REF, "") or "").strip().lower()
        target = by_id.get(ref) or by_title.get(ref)
        if target is None:
            continue
        target["quiz"].extend(_norm_quiz([q]))


# ── format parsers ─────────────────────────────────────────────────────────

def parse_python(source: str) -> list[dict]:
    """`TOPICS = [dict(...)]` / `QUIZ = [dict(...)]`, read with ast rather than
    imported — the source may start a server or need tkinter."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ImportError_(f"not valid Python: {exc}") from exc
    found: dict[str, list[dict]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in ("TOPICS", "QUIZ"):
            continue
        rows = []
        for el in getattr(node.value, "elts", []):
            if isinstance(el, ast.Call):
                rows.append({kw.arg: ast.literal_eval(kw.value) for kw in el.keywords})
            elif isinstance(el, ast.Dict):
                rows.append(ast.literal_eval(el))
        found[target.id] = rows
    if "TOPICS" not in found:
        raise ImportError_(
            "no TOPICS list found — a Python guide needs `TOPICS = [dict(...)]` "
            "at module level, optionally with a matching `QUIZ = [...]`")
    topics = [t for t in (_norm_topic(r) for r in found["TOPICS"]) if t]
    _attach_loose_quiz(topics, found.get("QUIZ", []))
    return topics


def parse_json(source: str) -> list[dict]:
    try:
        data = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ImportError_(f"not valid JSON: {exc}") from exc
    quiz: list = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = (_pick(data, ("topics", "items", "cards", "entries", "notes")) or [])
        quiz = _pick(data, ("quiz", "questions", "mcq")) or []
        if not rows and not quiz:
            raise ImportError_(
                "JSON has no `topics` array — expected "
                '{"topics": [{"title": ..., "category": ..., "answer": ...}]}')
    else:
        raise ImportError_("JSON root must be an object or an array")
    topics = [t for t in (_norm_topic(r) for r in rows if isinstance(r, dict)) if t]
    _attach_loose_quiz(topics, quiz)
    if not topics:
        raise ImportError_("no usable topics found — each needs at least a title")
    return topics


def parse_csv(source: str) -> list[dict]:
    """One row per quiz question, grouped into topics by title.

    A spreadsheet is how most people actually build a question bank, so this
    accepts either `options` as a single delimited cell or separate
    option/option_a/choice1 columns.
    """
    sample = source[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(source), dialect=dialect)
    if not reader.fieldnames:
        raise ImportError_("CSV has no header row")

    opt_cols = [f for f in reader.fieldnames
                if re.fullmatch(r"(option|choice|answer)[_ ]?[a-d1-6]", (f or "").strip().lower())]
    opt_cols.sort(key=lambda f: f.strip().lower()[-1])

    grouped: dict[str, dict] = {}
    skipped: list[str] = []
    rows = 0
    for row in reader:
        rows += 1
        topic = _norm_topic(row)
        if not topic:
            continue
        key = topic["title"].lower()
        slot = grouped.setdefault(key, topic)
        options = [str(row[c]).strip() for c in opt_cols if row.get(c)]
        if not options:
            inline = _pick(row, QUIZ_ALIASES["options"])
            if inline:
                options = [o.strip() for o in re.split(r"\s*\|\s*|\s*;\s*", str(inline)) if o.strip()]
        qtext = _pick(row, ("quiz_question", "mcq", "question", "q"))
        if qtext and len(options) >= 2:
            key = _pick(row, CSV_KEY_FIRST)
            if key in (None, ""):
                candidate = _pick(row, ("answer", "a"))
                try:
                    _resolve_answer(candidate, options, one_based=True)
                    key = candidate
                except ImportError_:
                    key = None
            if key in (None, ""):
                skipped.append(str(qtext)[:60])
                continue
            try:
                answer = _resolve_answer(key, options, one_based=True)
            except ImportError_ as exc:
                skipped.append(f"{str(qtext)[:40]} ({exc})")
                continue
            slot["quiz"].append({"question": str(qtext).strip(), "options": options,
                                 "answers": [answer],
                                 "why": str(_pick(row, QUIZ_ALIASES["why"], "") or "").strip()})
    if not rows:
        raise ImportError_("CSV had a header but no rows")
    topics = list(grouped.values())
    # A CSV where nothing at all resolved is a mapping problem, not a data
    # problem — say so instead of importing empty topics.
    if skipped and not any(t["quiz"] for t in topics):
        raise ImportError_(
            "found rows but no usable answers — mark the correct choice with a "
            "`correct` column holding the option text, its letter, or its index. "
            f"First skipped: {skipped[0]}")
    if not topics:
        raise ImportError_(
            "no usable rows — a CSV needs a title/topic column, and for quiz "
            "questions an option set plus a correct answer")
    return topics


def parse_markdown(source: str) -> list[dict]:
    """A single hand-written Tephra note, in its own on-disk shape: YAML-ish
    frontmatter plus a body with an optional `## Quiz` section.

    One file is one topic -- for many topics in one upload, use JSON, Python
    or CSV instead. Reuses vault's frontmatter parser and study's quiz parser
    rather than re-implementing either, so a note round-trips through import
    exactly as the app itself would read it off disk.
    """
    from . import study as _study
    from . import vault as _vault
    meta, body = _vault.parse(source)
    title = str(meta.get("title") or "").strip()
    if not title:
        raise ImportError_("markdown note needs a `title:` field in its frontmatter")
    prose, quiz_section = _study.split_quiz(body)
    return [{
        "id": str(meta.get("id") or "").strip(),
        "title": title,
        "category": str(meta.get("category") or "Uncategorised").strip() or "Uncategorised",
        "question": str(meta.get("question") or "").strip(),
        "answer": prose.strip(),
        "quiz": _study.parse_quiz(quiz_section),
    }]


FORMATS = [
    {
        "id": "python", "label": "Python", "extensions": [".py"],
        "summary": "Module-level TOPICS and QUIZ lists, read as data — never executed.",
        "example": 'TOPICS = [dict(id="icmp", cat="Networking", title="ICMP",\n'
                   '              q="What is ICMP?", a="""markdown answer""")]\n'
                   'QUIZ = [dict(t="icmp", q="Which layer?",\n'
                   '             o=["L2", "L3"], a=1, why="Rides on IP.")]',
    },
    {
        "id": "json", "label": "JSON", "extensions": [".json"],
        "summary": "The most portable option. Quiz questions can nest inside each "
                   "topic, or sit in a flat array that references topics by id or title. "
                   "A topic's `images` names files by filename only — import from a "
                   "folder and any image anywhere under it with a matching name is "
                   "found and embedded automatically, wherever it actually sits on disk.",
        "example": json.dumps({
            "name": "Storage Fundamentals",
            "topics": [{
                "id": "raid", "category": "Storage", "title": "RAID levels",
                "question": "What are the common RAID levels?",
                "answer": "**RAID 0** stripes...  \nSupports full markdown.",
                "images": ["raid-levels-diagram.png", "raid5-parity.png"],
                "quiz": [{
                    "question": "Which level has no redundancy?",
                    "options": ["RAID 0", "RAID 1", "RAID 5"],
                    "answer": 0,
                    "why": "Striping only — one disk lost is all data lost.",
                }],
            }],
        }, indent=2),
    },
    {
        "id": "csv", "label": "CSV / TSV", "extensions": [".csv", ".tsv"],
        "summary": "One row per quiz question, grouped into topics by title. "
                   "Good if you build banks in a spreadsheet.",
        "example": "category,title,answer,question,option_a,option_b,option_c,correct,why\n"
                   "Storage,RAID levels,\"RAID 0 stripes...\",Which has no redundancy?,"
                   "RAID 0,RAID 1,RAID 5,RAID 0,Striping only.",
    },
    {
        "id": "markdown", "label": "Markdown", "extensions": [".md"],
        "summary": "Tephra's own note shape: frontmatter plus a body, with an optional "
                   "`## Quiz` section. One file is one topic — for many topics at once "
                   "use JSON, Python or CSV instead. You can also skip the importer "
                   "and drop the file straight into vault/notes/, then reindex.",
        "example": "---\ntitle: RAID levels\ncategory: Storage\n"
                   "question: What are the common RAID levels?\n---\n\n"
                   "**RAID 0** stripes...\n\n## Quiz\n\n"
                   "Q: Which level has no redundancy?\n- [x] RAID 0\n- RAID 1\n"
                   "Why: Striping only.",
    },
]

PARSERS = {".py": parse_python, ".json": parse_json, ".csv": parse_csv, ".tsv": parse_csv,
           ".md": parse_markdown}
ACCEPTED = sorted(PARSERS)


def parse(filename: str, source: str) -> list[dict]:
    """Dispatch on extension, then fall back to sniffing the content so a
    misnamed file still imports."""
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext in PARSERS:
        return PARSERS[ext](source)

    head = source.lstrip()[:1]
    if head in "[{":
        return parse_json(source)
    if "TOPICS" in source and "=" in source:
        return parse_python(source)
    if "," in source.split("\n", 1)[0] or "\t" in source.split("\n", 1)[0]:
        return parse_csv(source)
    raise ImportError_(
        f"unrecognised file type {ext or '(none)'} — accepted: "
        + ", ".join(ACCEPTED))
