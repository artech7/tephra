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

    `field` is where this section lands in the destination form. It is not
    decoration: the KB this exports to does not have an article *body* at
    all, it has five separate rich-text fields, so an export that produced
    one blob of HTML would have nowhere to go. Every section names the field
    it feeds, and export groups sections by field.
    """
    heading: str
    hint: str
    required: bool = True
    shape: str = "prose"        # prose | steps | list | table | code
    field: str = "Answer"


@dataclass
class Template:
    id: str
    name: str
    summary: str
    sections: list[Section] = field(default_factory=list)


# The destination form. One form serves every article kind -- Category is a
# separate taxonomy from the form layout, so a "How to Article" and a
# troubleshooting article are typed into the same five boxes. That is why
# every template below maps onto this one list rather than each carrying a
# form of its own.
FORM = "Question and Answer"

# The fields sections can be routed to, in the order they appear on the form,
# so the export panel reads top to bottom the way the form does.
SECTION_FIELDS = ["Question", "Environment", "Answer",
                  "Additional Information", "Internal Notes"]

# Fields fed from metadata rather than from a section.
META_FIELDS = ["Short description", "Meta"]

# The Meta field is a plain textarea with a hard limit the form enforces.
META_MAX = 4000


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
    "question-answer": Template(
        id="question-answer",
        name="Question and Answer",
        summary="The destination form, one section per field. Start here when you "
                "already know the article is going straight into the KB.",
        sections=[
            Section("Question", "What the reader is actually asking, phrased the way they "
                                "would ask it. Not a title — a question.",
                    shape="prose", field="Question"),
            Section("Environment", "Products, versions, branches and platforms this applies "
                                   "to. Be specific; 'all versions' is almost never true.",
                    shape="table", field="Environment"),
            Section("Answer", "The answer itself. Numbered steps if there is anything to do, "
                              "one action per step.",
                    shape="steps", field="Answer"),
            Section("Additional Information", "Context that helps but is not the answer: "
                                              "related articles, background, caveats.",
                    required=False, shape="prose", field="Additional Information"),
            Section("Internal Notes", "Anything that must never reach an external audience — "
                                      "case numbers, internal tooling, unreleased fixes.",
                    required=False, shape="prose", field="Internal Notes"),
        ],
    ),
    "troubleshooting": Template(
        id="troubleshooting",
        name="Troubleshooting",
        summary="A specific failure, its cause, and the fix. The default shape "
                "for anything that starts life as a support case.",
        sections=[
            Section("Summary", "One paragraph: what breaks, for whom, and what this article fixes.",
                    shape="prose", field="Question"),
            Section("Symptoms", "What the user actually sees — exact error text, alert names, "
                                "observed behaviour. One bullet per distinct symptom.",
                    shape="list", field="Question"),
            Section("Environment", "Products, versions, and platforms this applies to. Be specific; "
                                   "'all versions' is almost never true.",
                    shape="table", field="Environment"),
            Section("Cause", "Why it happens. If the root cause is unknown, say so plainly rather "
                             "than leaving this empty.",
                    shape="prose", field="Answer"),
            Section("Resolution", "Numbered steps that fix it. One action per step.",
                    shape="steps", field="Answer"),
            Section("Verification", "How the reader confirms the fix worked — the command to run, "
                                    "the value to expect.",
                    shape="prose", field="Answer"),
            Section("Related articles", "Links to adjacent KBs, tickets, or vendor documentation.",
                    required=False, shape="list", field="Additional Information"),
        ],
    ),
    "how-to": Template(
        id="how-to",
        name="How-To / Procedure",
        summary="A task the reader wants to complete, start to finish, with a way "
                "back out if it goes wrong.",
        sections=[
            Section("Goal", "What the reader will have accomplished by the end. One sentence.",
                    shape="prose", field="Question"),
            Section("Prerequisites", "Access, versions, licences, and prior steps assumed. "
                                     "Everything that makes step 1 possible.",
                    shape="list", field="Environment"),
            Section("Steps", "Numbered, imperative, one action each. Put expected output under "
                             "the step that produces it.",
                    shape="steps", field="Answer"),
            Section("Verification", "How to confirm it worked.", shape="prose", field="Answer"),
            Section("Rollback", "How to undo it. An article without this is not finished.",
                    shape="steps", field="Answer"),
            Section("Related articles", "Adjacent procedures and reference material.",
                    required=False, shape="list", field="Additional Information"),
        ],
    ),
    "reference": Template(
        id="reference",
        name="Reference / Concept",
        summary="Explains what something is and how it behaves. Read to understand, "
                "not to do.",
        sections=[
            Section("Overview", "What this is and why the reader cares, before any detail.",
                    shape="prose", field="Question"),
            Section("Key concepts", "The handful of terms the rest of the article depends on. "
                                    "Define each one where it is first used.",
                    shape="list", field="Answer"),
            Section("Details", "The substance. Use sub-headings freely; keep each one to a "
                               "single idea.",
                    shape="prose", field="Answer"),
            Section("Limits and caveats", "Boundaries, known gaps, and things that look supported "
                                          "but are not.",
                    required=False, shape="list", field="Additional Information"),
            Section("Related articles", "Where to go next.",
                    required=False, shape="list", field="Additional Information"),
        ],
    ),
    "known-issue": Template(
        id="known-issue",
        name="Known Issue / Workaround",
        summary="A defect that is understood but not yet fixed. Its job is to stop "
                "the reader wasting time diagnosing it.",
        sections=[
            Section("Summary", "The defect in one paragraph, and whether a permanent fix exists yet.",
                    shape="prose", field="Question"),
            Section("Impact", "What the reader loses or risks while this is unresolved.",
                    shape="prose", field="Question"),
            Section("Affected versions", "Exactly which releases are affected, and which are not.",
                    shape="table", field="Environment"),
            Section("Workaround", "Numbered steps that restore service without the fix. Say clearly "
                                  "if there is none.",
                    shape="steps", field="Answer"),
            Section("Permanent fix", "The release that fixes it, or the tracking ID to watch.",
                    shape="prose", field="Answer"),
            Section("Related articles", "The parent defect, adjacent symptoms, vendor advisories.",
                    required=False, shape="list", field="Additional Information"),
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
                    shape="prose", field="Question"),
            Section("Questions", "One `###` heading per question, phrased the way a reader would "
                                 "ask it, with the answer directly beneath.",
                    shape="prose", field="Answer"),
            Section("Related articles", "Fuller treatments of anything answered only briefly here.",
                    required=False, shape="list", field="Additional Information"),
        ],
    ),
    "announcement": Template(
        id="announcement",
        name="Announcement / Change Notice",
        summary="A dated change to a service. Ages out, so it says up front when "
                "it stops being true.",
        sections=[
            Section("What is changing", "The change itself, in one paragraph, in plain language.",
                    shape="prose", field="Question"),
            Section("When", "Dates and times, with the timezone spelled out.",
                    shape="prose", field="Question"),
            Section("Who is affected", "Which users, sites, or systems — and who is not.",
                    shape="list", field="Environment"),
            Section("What you need to do", "Actions the reader must take, numbered. 'Nothing' is "
                                           "a valid and welcome answer.",
                    shape="steps", field="Answer"),
            Section("Support", "Where to raise problems arising from this change.",
                    required=False, shape="prose", field="Additional Information"),
        ],
    ),
}

DEFAULT_TEMPLATE = "troubleshooting"


# ── the block palette ──────────────────────────────────────────────────────
#
# Data, like the templates and the field schema, and for the same reason:
# "literally anything we have now and anything we add in the future" is only
# true if adding a block is one entry here and nothing else. The palette UI,
# the drag payload and the insertion are all generated from this list.
#
# `snippet` is plain markdown -- the file on disk stays the source of truth,
# and a block is only a way of writing that markdown without typing the
# syntax. `select` is the substring the editor highlights after a drop, so
# the first thing you type replaces the placeholder.


@dataclass
class Block:
    id: str
    label: str
    glyph: str
    group: str
    hint: str
    snippet: str
    select: str = ""
    # Inline blocks land inside the paragraph you drop them on rather than
    # becoming a block of their own.
    inline: bool = False


BLOCK_GROUPS = ("Text", "Structure", "Media", "Reference")

BLOCKS: list[Block] = [
    Block("heading", "Heading", "H2", "Text",
          "A section heading. Sections are what the export maps onto form fields.",
          "## Heading", "Heading"),
    Block("subheading", "Sub-heading", "H3", "Text",
          "A heading within a section.", "### Sub-heading", "Sub-heading"),
    Block("paragraph", "Paragraph", "¶", "Text",
          "Ordinary prose.", "Text.", "Text."),
    Block("bullets", "Bullet list", "•", "Text",
          "An unordered list — one item per distinct thing.",
          "- Item\n- Item\n- Item", "Item"),
    Block("numbered", "Numbered list", "1.", "Text",
          "Steps, in order. One action per step.",
          "1. Step\n2. Step\n3. Step", "Step"),
    Block("quote", "Quote", "“", "Text",
          "A quotation. For a note or warning box, use Callout instead.",
          "> Quotation.", "Quotation."),
    Block("callout", "Callout", "⚠", "Structure",
          "A boxed note. Change WARNING to NOTE, TIP, IMPORTANT, CAUTION or DANGER.",
          "> [!WARNING] Title\n> Text.", "Title"),
    Block("table", "Table", "▦", "Structure",
          "A 3-column table. Add rows by adding lines.",
          "| Column | Column | Column |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |",
          "Column"),
    Block("sheets", "Sheets", "▤", "Structure",
          "Several tables in one tabbed card. Each `## name` is a tab.",
          "```sheets\n## Sheet name\n\n| Column | Column |\n| --- | --- |\n|  |  |\n```",
          "Sheet name"),
    Block("code", "Code block", "⌨", "Structure",
          "A command or a config sample. Replace `bash` with the language.",
          "```bash\ncommand --here\n```", "command --here"),
    Block("divider", "Divider", "—", "Structure",
          "A horizontal rule.", "---"),
    Block("image", "Image", "▣", "Media",
          "An attachment from this vault. Exports as a numbered placeholder "
          "plus a manifest row.",
          "![[image.png|Caption|500]]", "image.png"),
    Block("mermaid", "Diagram", "◈", "Media",
          "A Mermaid diagram. Exports as a placeholder — attach a screenshot.",
          "```mermaid\ngraph TD\nA[Start] --> B[End]\n```", "A[Start]"),
    Block("netdiagram", "Net diagram", "⬚", "Media",
          "A device and cabling diagram.",
          "```netdiagram\ndevice a \"Device A\"\ndevice b \"Device B\"\n"
          "link a.P1 -> b.P1\n```", "Device A"),
    Block("link", "Link", "↱", "Reference",
          "An external link.", "[link text](https://example.com)", "link text"),
    Block("bookmark", "Bookmark", "⌸", "Reference",
          "A URL on its own line becomes a bookmark card.",
          "https://example.com", "https://example.com"),
    Block("wikilink", "Note link", "◉", "Reference",
          "A link to another note. Drag a note from the list below instead to "
          "pick one by name.",
          "[[Note Title]]", "Note Title", inline=True),
    Block("citation", "Citation", "¹", "Reference",
          "A footnote marker pointing at the Nth entry of this article's Sources.",
          "[^1]", "1", inline=True),
    Block("sources", "Sources", "≡", "Reference",
          "The source list citations point at. One bullet per source.",
          "## Sources\n\n- [Title](https://example.com)", "Title"),
]

BLOCKS_BY_ID = {b.id: b for b in BLOCKS}


def blocks_payload() -> list[dict]:
    return [asdict(b) for b in BLOCKS]


# ── splitting a body into droppable blocks ─────────────────────────────────


def split_blocks(body: str) -> list[dict]:
    """The body as its top-level markdown blocks, with the source lines each
    one occupies.

    This is what makes the live render droppable: every rendered block knows
    which lines it came from, so an insertion between two of them is a splice
    at a known line number rather than a guess at a character offset.

    Blank lines separate blocks, except inside a fence -- a ```sheets block
    holds blank lines and is emphatically one block. That is markdown's own
    block structure, so nothing here needs to know what any given block
    means.
    """
    lines = body.split("\n")
    out: list[dict] = []
    start = None
    fence = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if fence is None:
            m = re.match(r"^(`{3,}|~{3,})", stripped)
            if m:
                fence = m.group(1)[0] * 3
                if start is None:
                    start = i
                continue
        else:
            if re.match(r"^(`{3,}|~{3,})\s*$", stripped):
                fence = None
            continue
        if not stripped:
            if start is not None:
                out.append({"start": start, "end": i - 1,
                            "text": "\n".join(lines[start:i])})
                start = None
            continue
        if start is None:
            start = i
    if start is not None:
        out.append({"start": start, "end": len(lines) - 1,
                    "text": "\n".join(lines[start:])})
    return out


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
    form_field: str = ""        # the box on the destination form, if any


# Named after the destination form's own fields wherever one exists, so the
# authoring panel and the KB form read the same way and nothing has to be
# translated in someone's head while they fill the form in. `label` is what
# the form calls it; the key keeps the kb_ prefix so it can never collide
# with `category`, `study`, or whatever the next feature wants.
#
# `form_field` names the box on the form this value is typed into, or is
# empty for the ones that are Tephra's own bookkeeping. That is what lets
# the export panel offer a copy button per field.
FIELDS: list[Field] = [
    Field("kb_short_description", "Short description", "textarea", required=True, max_len=160,
          form_field="Short description",
          hint="The one line that shows in search results. Say what the reader gets, "
               "not what the article is about."),
    Field("kb_knowledge_base", "Knowledge base", "text", required=True,
          hint="Which KB this is filed in, exactly as the form spells it."),
    Field("kb_category", "Category", "text", required=True,
          hint="The Category dropdown's value — the article kind, separate from the "
               "form layout."),
    Field("kb_audience", "Audience", "text", required=True,
          hint="Who is allowed to read it. An external audience needs KCS Confidence "
               "set to Validated first."),
    Field("kb_kcs_confidence", "KCS Confidence", "select",
          options=["Work in Progress", "Validated"],
          hint="How much the article has been proven in practice. Gates who may read it."),
    Field("kb_status", "Draft status", "select",
          options=["draft", "review", "published", "retired"], required=True,
          hint="Tephra's own workflow, not the KB's. Where this article is on your desk."),
    Field("kb_number", "Number", "text",
          hint="Assigned by the KB when the article is created — paste it back here "
               "afterwards, and other articles will link to this one by it."),
    Field("kb_pure_products", "Pure Product(s)", "tags", required=True,
          hint="Everything this applies to. Specific beats broad."),
    Field("kb_pure_features", "Pure Feature(s)", "tags",
          hint="The features involved, where the product alone is too coarse."),
    Field("kb_purity_branches", "Purity Branch(es) Affected", "tags",
          hint="Which branches carry the problem."),
    Field("kb_purity_versions_fix", "Purity Version(s) with Fix", "tags",
          hint="The releases that resolve it, once they exist."),
    Field("kb_keywords", "Meta", "tags", required=True, max_len=4000,
          form_field="Meta",
          hint="The words a reader would search for — including the wrong ones they "
               "actually type. Goes in the form's Meta box."),
    Field("kb_valid_to", "Valid to", "date",
          hint="The date this stops being trustworthy without a fresh look."),
    Field("kb_ownership_group", "Ownership Group", "text",
          hint="The team that answers for this article."),
    Field("kb_owner", "Owner", "text",
          hint="The person who answers questions about it."),
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
    if MAP_KEY in payload:
        raw = payload[MAP_KEY]
        pairs = dump_fieldmap(raw) if isinstance(raw, dict) else [
            x for x in dump_fieldmap(
                {h: d for h, _, d in (str(i).partition(_MAP_SPLIT) for i in (raw or []))})]
        if pairs:
            out[MAP_KEY] = pairs
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


# ── section -> form field ──────────────────────────────────────────────────
#
# The template decides where each section lands, which is right almost always
# and wrong exactly when an author writes a section the template never
# imagined. `kb_fieldmap` is the escape hatch: a per-article override, stored
# in the same frontmatter as everything else so it travels with the file.
#
# Stored as `Heading>Field` pairs because the header parser splits a list on
# commas and nothing else -- `>` is a separator it will never touch, and both
# halves are scrubbed of the two characters that could confuse it.

MAP_KEY = "kb_fieldmap"
_MAP_SPLIT = ">"


def _map_safe(text: str) -> str:
    return _WS_RE.sub(" ", str(text).replace(",", " ").replace(_MAP_SPLIT, " ")
                      .translate({ord(c): None for c in "[]"})).strip()


def parse_fieldmap(raw) -> dict[str, str]:
    """`[Summary>Question, Cause>Answer]` -> {"summary": "Question", ...}.

    Keyed lowercase, because it is matched against headings the author typed
    and capitalisation drifts.
    """
    out: dict[str, str] = {}
    items = raw.split(",") if isinstance(raw, str) else list(raw or [])
    for item in items:
        head, _, dest = str(item).partition(_MAP_SPLIT)
        head, dest = _map_safe(head), _map_safe(dest)
        if head and dest in SECTION_FIELDS:
            out[head.lower()] = dest
    return out


def dump_fieldmap(pairs: dict) -> list[str]:
    out = []
    for head, dest in (pairs or {}).items():
        head, dest = _map_safe(head), _map_safe(dest)
        if head and dest in SECTION_FIELDS:
            out.append(f"{head}{_MAP_SPLIT}{dest}")
    return out


def field_of(heading: str, tpl: Template | None, override: dict[str, str]) -> str:
    """Where one section goes. Override wins, then the template, then Answer.

    Answer is the fallback rather than "drop it" for the reason the manifest
    exists: content that quietly goes nowhere is the failure mode worth
    engineering against. A section in the wrong box is visible and fixable;
    a section that never arrives is neither.
    """
    key = (heading or "").strip().lower()
    if key in override:
        return override[key]
    if tpl:
        for sec in tpl.sections:
            if sec.heading.lower() == key:
                return sec.field
    return "Answer"


def exportable_body(note: vault.Note) -> str:
    """The part of a note the export actually sections up.

    `## Quiz` belongs to Crucible and `## Sources` becomes the reference
    list, so both are lifted out before sectioning -- exactly as
    kb_export._build_sections does. Shared rather than duplicated because
    the mapping editor lists whatever this returns: when the two disagreed,
    the panel offered a row for "Sources" that no copy button could ever
    honour.

    Imported locally to keep app/kb.py's own imports to vault alone -- this
    module is the one both main.py and kb_export.py depend on, and it has no
    business dragging the index and the study module in behind it.
    """
    from . import index as idx
    from . import study as st
    prose, _quiz = st.split_quiz(note.body)
    prose, _sources = idx.split_sources_block(prose)
    return prose


def field_plan(note: vault.Note) -> list[dict]:
    """[{field, sections: [heading, ...]}] in form order, for every field that
    has something in it. This is the shape both the export and the mapping
    editor read, so the panel can never disagree with what gets copied."""
    tpl = template_of(note)
    override = parse_fieldmap(note.meta.get(MAP_KEY))
    buckets: dict[str, list[str]] = {f: [] for f in SECTION_FIELDS}
    for sec in sections(exportable_body(note)):
        if not strip_todos(sec["content"]).strip():
            continue
        buckets[field_of(sec["heading"], tpl, override)].append(sec["heading"])
    return [{"field": f, "sections": buckets[f]} for f in SECTION_FIELDS if buckets[f]]


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
