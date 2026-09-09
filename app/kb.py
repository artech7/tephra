"""KB Authoring — article templates, metadata schema, and the KB article list.

A KB article is an ordinary vault note. Nothing here introduces a second
storage format: the article's body is the same markdown every other note
uses, and everything KB-specific lives in frontmatter keys, which
vault.parse/vault.dump already round-trip into Note.meta untouched. Delete
.index/ and no KB article loses anything, because there was never anything
of it in the index to begin with.

`kb_type` is what makes a note an article. It names one of the templates
below, and that template drives three separate things:

    - the skeleton a new article starts from (section headings in order),
    - what the structure panel checks the article against,
    - the order sections are emitted in on export.

Templates are data, not code. Adding a seventh article type is one entry in
TEMPLATES with no other file touched -- deliberately, because "potentially
other types" is a certainty, not a maybe, in any team that writes KBs.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import vault

# The frontmatter key that marks a note as a KB article, and the prefix every
# other KB field shares. The prefix is not decoration: it keeps KB fields from
# ever colliding with `category`, `study`, or whatever the next feature wants,
# and it means a KB article opened in a plain text editor reads as an ordinary
# note with some extra headers rather than as a proprietary file.
TYPE_KEY = "kb_type"
PREFIX = "kb_"


@dataclass
class Section:
    """One required-or-not heading in a template.

    `shape` is a promise about what belongs under the heading, and the
    structure panel checks the section against it: "steps" must be a numbered
    list, "table" must contain a table, and so on. It is advisory at authoring
    time -- nothing here refuses to save a section that doesn't match.
    """
    heading: str
    hint: str
    required: bool = True
    shape: str = "prose"        # prose | steps | list | table | code


@dataclass
class Template:
    id: str
    name: str
    summary: str
    sections: list[Section] = field(default_factory=list)


# The guidance line a fresh article carries under each heading. It is written
# as visible italic text rather than an HTML comment because raw HTML is off
# in render.py -- a comment would render as literal visible markup, which is
# worse than useless. TODO_RE below is the contract: the structure panel
# flags these, and every export strips them, so shipping an article with
# untouched guidance in it takes deliberate effort.
TODO_MARK = "TODO —"
TODO_RE = re.compile(r"^\s*[*_]{1,2}\s*TODO\s*[—–-].*?[*_]{1,2}\s*$", re.M)


def _todo(hint: str) -> str:
    return f"*{TODO_MARK} {hint}*"


TEMPLATES: dict[str, Template] = {
    "troubleshooting": Template(
        id="troubleshooting",
        name="Troubleshooting",
        summary="A specific failure, its cause, and the fix. The default shape "
                "for anything that starts life as a support case.",
        sections=[
            Section("Summary", "One paragraph: what breaks, for whom, and what this article fixes.",
                    shape="prose"),
            Section("Symptoms", "What the user actually sees — exact error text, alert names, "
                                "observed behaviour. One bullet per distinct symptom.",
                    shape="list"),
            Section("Environment", "Products, versions, and platforms this applies to. Be specific; "
                                   "'all versions' is almost never true.",
                    shape="table"),
            Section("Cause", "Why it happens. If the root cause is unknown, say so plainly rather "
                             "than leaving this empty.",
                    shape="prose"),
            Section("Resolution", "Numbered steps that fix it. One action per step.",
                    shape="steps"),
            Section("Verification", "How the reader confirms the fix worked — the command to run, "
                                    "the value to expect.",
                    shape="prose"),
            Section("Related articles", "Links to adjacent KBs, tickets, or vendor documentation.",
                    required=False, shape="list"),
        ],
    ),
    "how-to": Template(
        id="how-to",
        name="How-To / Procedure",
        summary="A task the reader wants to complete, start to finish, with a way "
                "back out if it goes wrong.",
        sections=[
            Section("Goal", "What the reader will have accomplished by the end. One sentence.",
                    shape="prose"),
            Section("Prerequisites", "Access, versions, licences, and prior steps assumed. "
                                     "Everything that makes step 1 possible.",
                    shape="list"),
            Section("Steps", "Numbered, imperative, one action each. Put expected output under "
                             "the step that produces it.",
                    shape="steps"),
            Section("Verification", "How to confirm it worked.", shape="prose"),
            Section("Rollback", "How to undo it. An article without this is not finished.",
                    shape="steps"),
            Section("Related articles", "Adjacent procedures and reference material.",
                    required=False, shape="list"),
        ],
    ),
    "reference": Template(
        id="reference",
        name="Reference / Concept",
        summary="Explains what something is and how it behaves. Read to understand, "
                "not to do.",
        sections=[
            Section("Overview", "What this is and why the reader cares, before any detail.",
                    shape="prose"),
            Section("Key concepts", "The handful of terms the rest of the article depends on. "
                                    "Define each one where it is first used.",
                    shape="list"),
            Section("Details", "The substance. Use sub-headings freely; keep each one to a "
                               "single idea.",
                    shape="prose"),
            Section("Limits and caveats", "Boundaries, known gaps, and things that look supported "
                                          "but are not.",
                    required=False, shape="list"),
            Section("Related articles", "Where to go next.", required=False, shape="list"),
        ],
    ),
    "known-issue": Template(
        id="known-issue",
        name="Known Issue / Workaround",
        summary="A defect that is understood but not yet fixed. Its job is to stop "
                "the reader wasting time diagnosing it.",
        sections=[
            Section("Summary", "The defect in one paragraph, and whether a permanent fix exists yet.",
                    shape="prose"),
            Section("Affected versions", "Exactly which releases are affected, and which are not.",
                    shape="table"),
            Section("Impact", "What the reader loses or risks while this is unresolved.",
                    shape="prose"),
            Section("Workaround", "Numbered steps that restore service without the fix. Say clearly "
                                  "if there is none.",
                    shape="steps"),
            Section("Permanent fix", "The release that fixes it, or the tracking ID to watch.",
                    shape="prose"),
            Section("Related articles", "The parent defect, adjacent symptoms, vendor advisories.",
                    required=False, shape="list"),
        ],
    ),
    "faq": Template(
        id="faq",
        name="FAQ",
        summary="Several short, independent questions that don't each justify their "
                "own article.",
        sections=[
            Section("Scope", "What this FAQ covers, so the reader can tell in one line whether "
                             "they are in the right place.",
                    shape="prose"),
            Section("Questions", "One `###` heading per question, phrased the way a reader would "
                                 "ask it, with the answer directly beneath.",
                    shape="prose"),
            Section("Related articles", "Fuller treatments of anything answered only briefly here.",
                    required=False, shape="list"),
        ],
    ),
    "announcement": Template(
        id="announcement",
        name="Announcement / Change Notice",
        summary="A dated change to a service. Ages out, so it says up front when "
                "it stops being true.",
        sections=[
            Section("What is changing", "The change itself, in one paragraph, in plain language.",
                    shape="prose"),
            Section("When", "Dates and times, with the timezone spelled out.", shape="prose"),
            Section("Who is affected", "Which users, sites, or systems — and who is not.",
                    shape="list"),
            Section("What you need to do", "Actions the reader must take, numbered. 'Nothing' is "
                                           "a valid and welcome answer.",
                    shape="steps"),
            Section("Support", "Where to raise problems arising from this change.",
                    required=False, shape="prose"),
        ],
    ),
}

DEFAULT_TEMPLATE = "troubleshooting"


# ── metadata schema ────────────────────────────────────────────────────────
#
# Described as data for the same reason templates are: the authoring form is
# generated from this list, the structure panel checks against it, and the
# export writes it into the article header. Three consumers, one definition.


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"          # text | textarea | select | tags | date
    hint: str = ""
    options: list[str] = field(default_factory=list)
    required: bool = False
    max_len: int = 0            # 0 = no limit


FIELDS: list[Field] = [
    Field("kb_short_description", "Short description", "textarea", required=True, max_len=160,
          hint="The one line that shows in search results. Say what the reader gets, "
               "not what the article is about."),
    Field("kb_status", "Status", "select", options=["draft", "review", "published", "retired"],
          required=True, hint="Where this article is in your own workflow — Tephra's, not ServiceNow's."),
    Field("kb_audience", "Audience", "select", options=["internal", "customer", "partner"],
          required=True, hint="Who is allowed to read it. Drives the wording, not just the field."),
    Field("kb_number", "KB number", "text",
          hint="The identifier in your KB system, once it has one. Other articles link to "
               "this article by this number on export."),
    Field("kb_products", "Products / versions", "tags", required=True,
          hint="Everything this applies to. Specific beats broad."),
    Field("kb_keywords", "Keywords", "tags", required=True,
          hint="The words a reader would search for — including the wrong ones they "
               "actually type."),
    Field("kb_owner", "Owner", "text",
          hint="Who answers questions about this article."),
    Field("kb_review_by", "Review by", "date",
          hint="The date this stops being trustworthy without a fresh look."),
    Field("kb_source_url", "Source URL", "text",
          hint="Where this came from, if it started life somewhere else — a case, a "
               "vendor page, an existing article."),
]

FIELD_KEYS = tuple(f.key for f in FIELDS)


# ── frontmatter safety ─────────────────────────────────────────────────────
#
# vault.py's frontmatter parser is a deliberately tiny fixed-schema one, not
# YAML, and it has three edges that a free-text KB field will find
# immediately: a value is one line, a value that starts with "[" and ends
# with "]" is read back as a list, and list items are split on commas. So
# every value written from here is normalised to something that survives its
# own round trip, rather than the parser being widened to accommodate us.

_WS_RE = re.compile(r"\s+")


def _scalar(v) -> str:
    """One line, no leading `[` ambiguity, safe to write and read back."""
    s = _WS_RE.sub(" ", str(v if v is not None else "")).strip()
    # A value the parser would otherwise hand back as a list. Quoting it is
    # enough: parse() only treats "[...]" as a list when the *value* starts
    # with the bracket, and it strips surrounding quotes on the way out.
    if s.startswith("[") and s.endswith("]"):
        s = f'"{s}"'
    return s


def _list(v) -> list[str]:
    """Items that survive their own round trip through the frontmatter.

    dump() joins a list on ", " and parse() splits it back on ",", so an item
    containing a comma would come back as two. Brackets go the same way: a
    written item of `[FlashArray]` produces the line `key: [[FlashArray]]`,
    which parse() reads as neither a list nor a clean string -- and which
    looks exactly like a damaged wikilink, the one shape vault.py already had
    to grow a defence against.
    """
    items = v.split(",") if isinstance(v, str) else list(v or [])
    out = []
    for item in items:
        # Commas and brackets out before whitespace is collapsed, so removing
        # them can never leave a double space behind.
        s = str(item).replace(",", " ")
        s = _WS_RE.sub(" ", s.translate({ord(c): None for c in "[]"})).strip()
        if s and s not in out:
            out.append(s)
    return out


_LIST_FIELDS = {f.key for f in FIELDS if f.kind == "tags"}


def sanitize_meta(payload: dict) -> dict:
    """Filter a client payload down to KB fields, each normalised so it
    survives a frontmatter round trip. Unknown keys are dropped rather than
    written: this is the only writer of kb_* keys, so anything it doesn't
    recognise is a bug or a probe, not a feature."""
    out: dict = {}
    kb_type = _scalar(payload.get(TYPE_KEY, ""))
    if kb_type in TEMPLATES:
        out[TYPE_KEY] = kb_type
    for f in FIELDS:
        if f.key not in payload:
            continue
        if f.key in _LIST_FIELDS:
            vals = _list(payload[f.key])
            if vals:
                out[f.key] = vals
        else:
            s = _scalar(payload[f.key])
            if f.max_len and len(s) > f.max_len:
                s = s[: f.max_len].rstrip()
            if s:
                out[f.key] = s
    return out


def strip_meta(meta: dict) -> dict:
    """Everything that isn't ours, left exactly as it was."""
    return {k: v for k, v in meta.items()
            if k != TYPE_KEY and not k.startswith(PREFIX)}


# ── articles ───────────────────────────────────────────────────────────────


def template_of(note: vault.Note) -> Template | None:
    return TEMPLATES.get(str(note.meta.get(TYPE_KEY) or "").strip())


def is_article(note: vault.Note) -> bool:
    return template_of(note) is not None


def meta_of(note: vault.Note) -> dict:
    """The article's KB fields, with list fields always lists.

    A hand-edited file can carry `kb_keywords: dns` with no brackets, which
    vault.parse hands back as a plain string -- and the authoring form must
    never receive a string where it expects a list.
    """
    out: dict = {}
    for f in FIELDS:
        v = note.meta.get(f.key)
        if v is None:
            continue
        if f.key in _LIST_FIELDS:
            out[f.key] = _list(v)
        else:
            out[f.key] = _scalar(v)
    kt = str(note.meta.get(TYPE_KEY) or "").strip()
    if kt:
        out[TYPE_KEY] = kt
    return out


def new_body(template_id: str) -> str:
    """The skeleton a fresh article starts from: every section in order, each
    with its guidance line. Optional sections are included too -- an author
    deleting a heading they don't need is a better default than one never
    discovering the heading existed."""
    tpl = TEMPLATES.get(template_id) or TEMPLATES[DEFAULT_TEMPLATE]
    parts = []
    for s in tpl.sections:
        parts.append(f"## {s.heading}\n\n{_todo(s.hint)}")
    return "\n\n".join(parts) + "\n"


def strip_todos(body: str) -> str:
    """Remove untouched guidance lines. Every export runs this, so guidance
    can never reach a published article even if the author left it in."""
    return TODO_RE.sub("", body)


def has_todos(body: str) -> bool:
    return bool(TODO_RE.search(body))


# `## Heading` at the start of a line, outside any fenced block. Sections are
# split on h2 specifically: h3 and below are the author's own structure
# *within* a section, and a template says nothing about them.
_H2_RE = re.compile(r"^##[ \t]+(?P<heading>.+?)[ \t]*$", re.M)
_FENCE_RE = re.compile(r"^```.*?\n.*?^```[ \t]*$", re.M | re.S)


def _blank_fences(body: str) -> str:
    """Fenced content with its lines kept but blanked, so offsets into the
    result still line up with the original. A `## Heading` written inside a
    ```sheets fence is a sheet name, not a section of the article."""
    return _FENCE_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), body)


def sections(body: str) -> list[dict]:
    """Split an article body into its h2 sections, in document order.

    Returns [{heading, content, start}], plus a leading {heading: "", ...}
    entry when there is text above the first heading -- that text is a real
    part of the article (an intro paragraph, most often) and both the
    structure panel and the export need to see it rather than silently
    dropping it.
    """
    scan = _blank_fences(body)
    marks = [(m.start(), m.end(), m.group("heading").strip())
             for m in _H2_RE.finditer(scan)]
    out: list[dict] = []
    if not marks:
        text = body.strip()
        return [{"heading": "", "content": text, "start": 0}] if text else []
    lead = body[: marks[0][0]].strip()
    if lead:
        out.append({"heading": "", "content": lead, "start": 0})
    for i, (start, end, heading) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        out.append({"heading": heading, "content": body[end:stop].strip(), "start": start})
    return out


def article_row(note: vault.Note) -> dict:
    """The list-row shape the KB deck's sidebar renders. Cheap on purpose --
    it runs for every article in the vault on every list load."""
    tpl = template_of(note)
    m = meta_of(note)
    return {
        "slug": note.slug,
        "title": note.title,
        "updated": note.updated,
        "kb_type": tpl.id if tpl else "",
        "type_name": tpl.name if tpl else "",
        "status": m.get("kb_status", "draft"),
        "audience": m.get("kb_audience", ""),
        "number": m.get("kb_number", ""),
        "short_description": m.get("kb_short_description", ""),
        "products": m.get("kb_products", []),
        "words": len(note.body.split()),
    }


def list_articles() -> list[dict]:
    rows = [article_row(n) for n in vault.all_notes() if is_article(n)]
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def by_number() -> dict[str, dict]:
    """kb_number -> {slug, title, number}, for resolving a [[wikilink]] to a
    real KB link on export. Built per export rather than cached: a vault this
    size scans in milliseconds, and a stale map would silently emit wrong
    article links, which is worse than emitting none."""
    out: dict[str, dict] = {}
    for n in vault.all_notes():
        if not is_article(n):
            continue
        num = _scalar(n.meta.get("kb_number") or "")
        if num:
            out[n.title.lower()] = {"slug": n.slug, "title": n.title, "number": num,
                                    "url": _scalar(n.meta.get("kb_source_url") or "")}
    return out


def templates_payload() -> list[dict]:
    return [asdict(t) for t in TEMPLATES.values()]


def fields_payload() -> list[dict]:
    return [asdict(f) for f in FIELDS]
