"""KB Authoring — export an article to something another system will accept.

The problem this solves is narrow and specific: Tephra renders an article
beautifully using its own stylesheet, and the KB system it has to be pasted
into has never heard of that stylesheet. Anything relying on a class name
arrives unstyled; anything relying on a `<style>` block arrives with the
block stripped. So export is not "give me the HTML" -- it is a deliberate
downgrade to constructs that survive a hostile sanitiser, done once, on
purpose, rather than discovered a paragraph at a time after pasting.

Four targets, one parse:

    servicenow   Semantic HTML with every style inlined on the element and
                 tables carrying presentational attributes as well as CSS.
                 Paste it into the WYSIWYG or into the source (`<>`) view --
                 the markup is the same either way, only the clipboard
                 flavour differs, and the frontend handles that.
    standalone   A complete, self-contained page: embedded stylesheet,
                 table of contents, images inlined as data URIs, no external
                 requests at all. This is the faithful one -- the artifact
                 that still opens correctly on a phone in three years.
    markdown     Portable source, wikilinks resolved, guidance stripped.
    text         Plain text with structure preserved by layout, for the
                 fields that accept nothing else.

Syntax parsing is deliberately shared with render.py rather than
reimplemented -- the regexes and the sheet splitter are imported, not
copied, so an article can never mean one thing on screen and another on
export. What differs is only the emission, which is the part that genuinely
has to differ.

Images are never silently dropped. `servicenow` and `markdown` replace each
one with a visible, numbered placeholder and record it in a manifest, so the
author knows exactly what to attach and where; `standalone` inlines the
bytes instead, because there is nothing to attach it to.
"""
from __future__ import annotations

import base64
import html
import re
from datetime import date

from markdown_it import MarkdownIt

from . import index as idx
from . import kb
from . import study as st
from . import vault
from .index import CITE_RE, EMBED_RE, WIKI_RE
from .render import (
    CALLOUT_RE,
    CALLOUT_VARIANTS,
    PLACEHOLDER,
    SHEETS_RE,
    URL_LINE_RE,
    _CALLOUT_STRIP_RE,
    _parse_sheets,
    _unwrap_placeholder_p,
    _skip_fences,
    _raw_br,
    _split_embed_extra,
)

TARGETS = ("servicenow", "standalone", "markdown", "text")
LINK_MODES = ("auto", "number", "url", "text")

# Images above this size are not worth inlining into a standalone page: the
# file stops being openable on the phone it was made portable for. They fall
# back to the same placeholder the other targets use, with a warning saying
# why.
MAX_INLINE_BYTES = 4 * 1024 * 1024

# How the KB actually links one article to another. Lifted verbatim from a
# live article rather than guessed: the shape this code shipped with
# (`kb_view.do?sysparm_article=`) is the ServiceNow platform-UI form, and the
# portal these articles are read in does not serve it.
KB_LINK_BASE = "https://kb.purestorage.com/csm?id=kb_article_view&sysparm_article="

# The house stylesheet, copied byte for byte out of a published article.
#
# Every field of every article carries this block, and ServiceNow stores and
# renders it untouched -- which settles the question this exporter was built
# around. A `<style>` block is not stripped, so matching the house look is a
# matter of shipping the house block rather than of inlining a private
# approximation of it. `code`, `pre` and `td` are therefore left alone by the
# inliner below: this block owns them, and an inline style would make a
# Tephra article the one that looks different.
HOUSE_STYLE = (
    '<style> body{ font-family: inter; font-size:12pt; }  code{ background-color: '
    '#faf7f1; font-family: 400 90%/1.4 "Space Mono",monospace; color:black;} pre { '
    'background: #333 !important; color: #ddd !important; border-width: 0.1em 0.1em '
    '0.1em 0.5em !important; font-variant-ligatures: none !important; border: solid '
    '#fe5000 !important; border-width: 0.1em 0.1em 0.1em 0.5em !important; '
    'text-shadow: 0px 0px black !important; font-family: 400 90%/1.4 "Space '
    'Mono",monospace !important; } td{padding: 16px !important;} </style>'
)

# Tags the house block styles. Skipped by the inliner whenever the block is
# being emitted, so its rules are the ones that apply.
HOUSE_OWNED = ("code", "pre")

# Nested ordered lists in the house articles run 1 -> A -> i -> I. markdown-it
# has no idea about that convention, so it is applied by depth afterwards.
_OL_DEPTH_STYLE = [
    "list-style-position: inside;",
    "list-style-position: inside; list-style-type: upper-alpha;",
    "list-style-position: inside; list-style-type: lower-roman;",
    "list-style-position: inside; list-style-type: upper-roman;",
]


# ── the look ───────────────────────────────────────────────────────────────
#
# One palette, two consumers: inlined per element for `servicenow`, and
# emitted as a stylesheet for `standalone`. Deliberately conservative --
# system fonts, real borders, no custom properties, nothing that depends on
# a stylesheet arriving. Colours are dark enough to survive being printed.

INK = "#1c2024"
MUTED = "#5b6470"
RULE = "#d7dce2"
WASH = "#f6f8fa"
ACCENT = "#0b6bcb"

_TAG_CSS = {
    "h1": f"font-size:1.75em;line-height:1.25;margin:0 0 .5em;color:{INK};font-weight:700",
    "h2": (f"font-size:1.3em;line-height:1.3;margin:1.8em 0 .6em;color:{INK};"
           f"font-weight:700;border-bottom:1px solid {RULE};padding-bottom:.3em"),
    "h3": f"font-size:1.08em;line-height:1.35;margin:1.4em 0 .45em;color:{INK};font-weight:700",
    "h4": f"font-size:1em;margin:1.2em 0 .4em;color:{INK};font-weight:700",
    "p": f"margin:0 0 .85em;line-height:1.65;color:{INK}",
    "ul": "margin:0 0 .9em;padding-left:1.5em",
    "ol": "margin:0 0 .9em;padding-left:1.5em",
    "li": f"margin:0 0 .35em;line-height:1.6;color:{INK}",
    "table": f"border-collapse:collapse;width:100%;margin:0 0 1.1em;border:1px solid {RULE}",
    "th": (f"border:1px solid {RULE};padding:8px 10px;text-align:left;"
           f"background:{WASH};font-weight:700;color:{INK};vertical-align:top"),
    "td": f"border:1px solid {RULE};padding:8px 10px;text-align:left;color:{INK};vertical-align:top",
    "pre": (f"background:{WASH};border:1px solid {RULE};border-radius:4px;padding:12px 14px;"
            "margin:0 0 1em;overflow:auto;font-family:Consolas,Monaco,'Courier New',monospace;"
            f"font-size:.9em;line-height:1.5;color:{INK};white-space:pre"),
    "code": (f"background:{WASH};border:1px solid {RULE};border-radius:3px;padding:1px 5px;"
             "font-family:Consolas,Monaco,'Courier New',monospace;font-size:.92em"),
    "blockquote": (f"margin:0 0 1em;padding:.1em 0 .1em 1em;border-left:3px solid {RULE};"
                   f"color:{MUTED}"),
    "a": f"color:{ACCENT};text-decoration:underline",
    "hr": f"border:0;border-top:1px solid {RULE};margin:1.6em 0",
}

# Callouts become a single-cell bordered table rather than a styled <div>.
# Every KB editor worth the name renders a table; a fair few flatten an
# unfamiliar div to a bare paragraph and lose the boundary entirely, which
# turns a warning into an ordinary sentence -- the one degradation that
# actually changes what the article means.
_CALLOUT_LOOK = {
    "note": ("#0b6bcb", "#eef4fc", "Note"),
    "tip": ("#12805c", "#eaf6f1", "Tip"),
    "warning": ("#a76100", "#fdf4e7", "Warning"),
    "danger": ("#c0342b", "#fdeeed", "Caution"),
}


def _md_instance() -> MarkdownIt:
    """A parser configured for export, not for the app.

    render.py's instance carries rules that emit Tephra's own classes for
    images and fences; those are exactly what must not reach an exported
    article, so export parses with a plain instance and does its own
    emission. The syntax accepted is identical -- the same CommonMark plus
    tables plus strikethrough -- because it is the same library with the
    same options.
    """
    m = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False})
    m.enable("table")
    m.enable("strikethrough")
    # The same `<br>` rule render.py adds, and for the same reason: a GFM
    # cell cannot contain a newline, so every tool that emits a multi-line
    # cell emits `<br>`, and with raw HTML off it would arrive as visible
    # "&lt;br&gt;" with the cell run onto one line. Published articles in the
    # destination KB lean on this heavily -- one of them holds 108 of them --
    # so an export that dropped it would quietly reflow their tables.
    m.inline.ruler.before("autolink", "raw_br", _raw_br)
    return m


_MD = _md_instance()

_esc = lambda s: html.escape(str(s or ""))
_attr = lambda s: html.escape(str(s or ""), quote=True)


# ── placeholders for things that cannot be pasted ──────────────────────────


def _placeholder_box(token: str, kind: str, name: str, caption: str) -> str:
    """The visible marker left where an image or diagram was.

    It is a table for the same reason callouts are, and it is loud on
    purpose: an author scanning a pasted draft must not be able to miss the
    three places they still owe an attachment.
    """
    detail = caption or name
    return (
        f'<table border="1" cellspacing="0" cellpadding="8" '
        f'style="border-collapse:collapse;width:100%;margin:0 0 1.1em;'
        f'border:1px dashed {MUTED};background:{WASH}">'
        f'<tr><td style="border:0;padding:10px 12px;color:{MUTED};'
        f'font-family:Consolas,Monaco,\'Courier New\',monospace;font-size:.9em">'
        f'<strong>[{_esc(kind)} {token}]</strong> {_esc(detail)}'
        f'<br>Attach <strong>{_esc(name)}</strong> here.'
        f'</td></tr></table>'
    )


def _data_uri(name: str) -> tuple[str, str]:
    """(data uri, warning). Empty uri means "fall back to a placeholder"."""
    p = vault.current().media / name
    if not p.is_file():
        return "", f"{name} is referenced but not in the vault's media folder."
    raw = p.read_bytes()
    if len(raw) > MAX_INLINE_BYTES:
        mb = len(raw) / (1024 * 1024)
        return "", (f"{name} is {mb:.1f} MB — too large to inline, left as a "
                    "placeholder so the page stays openable.")
    ext = p.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
            "avif": "image/avif"}.get(ext, "")
    if not mime:
        return "", f"{name} is not an image format that inlines; left as a placeholder."
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}", ""


class _Media:
    """Counts images and diagrams, and decides per target whether each becomes
    bytes or a placeholder plus a manifest row.

    Numbering is deferred rather than assigned on sight. Callouts and sheets
    are extracted from the body before the passes that follow them -- that
    ordering is load-bearing and documented in render.py -- so the order
    things are *met* is not the order they appear in the finished article. An
    author matching "Image 3" to the third gap on the page needs document
    order, so each placeholder carries a token and `finalize` numbers them by
    where they actually landed.
    """

    def __init__(self, embed: bool):
        self.embed = embed
        self.items: list[dict] = []
        self.warnings: list[str] = []

    def _token(self) -> str:
        # Letters and digits only, for the reason render.py's PLACEHOLDER
        # gives: nothing here is markdown-active, so it survives the parser.
        return f"xKBMEDIAx{len(self.items)}x"

    def image(self, name: str, caption: str = "") -> str:
        token = self._token()
        self.items.append({"token": token, "kind": "image", "name": name,
                           "caption": caption})
        if self.embed:
            uri, warn = _data_uri(name)
            if uri:
                cap = (f'<figcaption style="color:{MUTED};font-size:.9em;margin-top:.4em">'
                       f'{_esc(caption)}</figcaption>') if caption else ""
                return (f'<figure id="kb-image-{token}" style="margin:0 0 1.2em">'
                        f'<img src="{_attr(uri)}" alt="{_attr(caption or name)}" '
                        f'style="max-width:100%;height:auto;border:1px solid {RULE};'
                        f'border-radius:4px">{cap}</figure>')
            if warn:
                self.warnings.append(warn)
        return _placeholder_box(token, "Image", name, caption)

    def diagram(self, lang: str, source: str) -> str:
        token = self._token()
        name = f"{lang}-{token}.png"
        self.items.append({"token": token, "kind": "diagram", "name": name,
                           "caption": f"{lang} diagram", "source": source})
        self.warnings.append(
            f"{lang} diagram {token} cannot be pasted as a diagram — export the "
            "standalone HTML, screenshot it, and attach the image.")
        return _placeholder_box(token, "Diagram", name, f"{lang} diagram")

    def finalize(self, order_source: str):
        """Number the placeholders by where they ended up and hand back a
        resolver to apply to any fragment.

        A resolver rather than a rewritten string, because the ServiceNow
        target splits one article across several form fields: the numbering
        has to be decided once, over the whole document in reading order, and
        then applied to each fragment separately. Numbering each fragment on
        its own would restart at 1 in every box.
        """
        # An item whose token is nowhere in the output (an embed inside a
        # section that was stripped, say) sorts last rather than vanishing --
        # a manifest that quietly loses a row is the failure this whole
        # mechanism exists to prevent.
        def where(item: dict) -> tuple[bool, int]:
            at = order_source.find(item["token"])
            return (at < 0, at)

        self.items.sort(key=where)
        numbers = {}
        for n, item in enumerate(self.items, 1):
            numbers[item["token"]] = str(n)
            item["n"] = n

        def resolve(text: str) -> str:
            for token, num in numbers.items():
                text = text.replace(token, num)
            return text

        for item in self.items:
            item["name"] = resolve(item["name"])
            item.pop("token", None)
        self.warnings = [resolve(w) for w in self.warnings]
        return resolve


# ── link resolution ────────────────────────────────────────────────────────


def _link_text(title: str, shown: str, mode: str, known: dict) -> str:
    """A [[wikilink]] rendered for somewhere that has no idea what a vault is.

    An article that exists in the KB system and knows its own number becomes
    a real link to that number; one that does not becomes bold text, because
    a dead link in a published article is worse than a visible pointer to
    something the reader can search for.
    """
    hit = known.get(title.lower())
    if mode != "text" and hit:
        if mode in ("auto", "number") and hit["number"]:
            href = f"{KB_LINK_BASE}{hit['number']}"
            return (f'<a href="{_attr(href)}" style="{_TAG_CSS["a"]}">'
                    f'{_esc(shown)}</a>')
        if mode in ("auto", "url") and hit["url"]:
            return f'<a href="{_attr(hit["url"])}" style="{_TAG_CSS["a"]}">{_esc(shown)}</a>'
    return f"<strong>{_esc(shown)}</strong>"


# ── body construction ──────────────────────────────────────────────────────


def _callout(kind: str, title: str, inner_md: str, sub, house: bool = False) -> str:
    variant = CALLOUT_VARIANTS.get(kind.lower(), "note")
    border, wash, default_label = _CALLOUT_LOOK.get(variant, _CALLOUT_LOOK["note"])
    label = title.strip() or default_label
    inner = _style(_unwrap_placeholder_p(_MD.render(sub(inner_md))), house)
    return (
        f'<table border="1" cellspacing="0" cellpadding="0" '
        f'style="border-collapse:collapse;width:100%;margin:0 0 1.1em">'
        f'<tr><td style="border:1px solid {RULE};border-left:4px solid {border};'
        f'background:{wash};padding:12px 14px">'
        f'<p style="margin:0 0 .5em;font-weight:700;color:{border}">{_esc(label)}</p>'
        f'{inner}</td></tr></table>'
    )


def _sheets(content: str, sub, house: bool = False) -> str:
    """A sheets fence is a tabbed group on screen. Tabs are interaction, and
    interaction does not paste, so each sheet becomes a labelled table
    stacked in order -- the same information, laid out for a page rather
    than a pointer."""
    out = []
    for name, table_md in _parse_sheets(content):
        out.append(f'<p style="margin:1.2em 0 .35em;font-weight:700;color:{INK}">{_esc(name)}</p>')
        out.append(_style(_unwrap_placeholder_p(_MD.render(sub(table_md))), house))
    return "".join(out)


def _references(sources: list[dict]) -> str:
    if not sources:
        return ""
    rows = []
    for i, s in enumerate(sources, 1):
        text = _esc(s.get("text") or s.get("url") or "")
        url = s.get("url") or ""
        body = (f'<a href="{_attr(url)}" style="{_TAG_CSS["a"]}">{text}</a>'
                if url else text)
        rows.append(f'<li id="ref-{i}" style="{_TAG_CSS["li"]}">{body}</li>')
    return (f'<h2 style="{_TAG_CSS["h2"]}">References</h2>'
            f'<ol style="{_TAG_CSS["ol"]}">{"".join(rows)}</ol>')


def _meta_table(note: vault.Note) -> str:
    """The at-a-glance block a good KB article opens with. Built from the
    same field list the authoring form is built from, so a field added there
    appears here without this function changing."""
    m = kb.meta_of(note)
    rows = []
    for f in kb.FIELDS:
        if f.key in ("kb_short_description", "kb_status", "kb_source_url"):
            continue
        v = m.get(f.key)
        if not v:
            continue
        val = ", ".join(v) if isinstance(v, list) else v
        rows.append(
            f'<tr><th style="{_TAG_CSS["th"]};width:32%">{_esc(f.label)}</th>'
            f'<td style="{_TAG_CSS["td"]}">{_esc(val)}</td></tr>')
    if not rows:
        return ""
    return f'<table border="1" cellspacing="0" cellpadding="6" style="{_TAG_CSS["table"]}">{"".join(rows)}</table>'


def _fence(lang: str, code: str, media: _Media, house: bool = False) -> str:
    if lang in ("mermaid", "netdiagram"):
        return media.diagram(lang, code)
    tag = (f'<p style="margin:0 0 .25em;color:{MUTED};font-size:.85em;'
           f'font-family:Consolas,Monaco,\'Courier New\',monospace">{_esc(lang)}</p>'
           ) if lang else ""
    # Bare <pre> when the house block is coming: it claims pre with
    # !important anyway, and a bare tag is what published articles hold.
    pre = "<pre>" if house else f'<pre style="{_TAG_CSS["pre"]}">'
    return f'{tag}{pre}<code>{_esc(code)}</code></pre>'


_FENCE_CAPTURE = re.compile(r"^```([\w-]*)[ \t]*\n(?P<code>.*?)^```[ \t]*$", re.M | re.S)
_INLINE_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


class _Ctx:
    """The state one export shares across every fragment it renders.

    Media numbering, the stash of pre-rendered block fragments, and the
    resolved article map all have to be common to the whole document even
    though the document is rendered a section at a time -- otherwise images
    renumber per section and a citation in one field cannot point at the
    reference list in another.
    """

    def __init__(self, links: str, embed_images: bool, sources: list[dict],
                 house: bool = False):
        self.house = house
        self.links = links
        self.sources = sources
        self.media = _Media(embed_images)
        self.known = kb.by_number()
        self.blocks: list[str] = []
        self.toc: list[dict] = []
        self.anchors: set[str] = set()

    def stash(self, fragment: str) -> str:
        self.blocks.append(fragment)
        return PLACEHOLDER.format(len(self.blocks) - 1)

    def on_wiki(self, m):
        title = m.group(1).strip()
        shown = (m.group(2) or title).strip()
        return _link_text(title, shown, self.links, self.known)

    def on_cite(self, m):
        n = int(m.group(1))
        if 1 <= n <= len(self.sources):
            return f'<sup><a href="#ref-{n}" style="{_TAG_CSS["a"]}">{n}</a></sup>'
        return f"<sup>[{n}]</sup>"

    def on_embed(self, m):
        caption, _size = _split_embed_extra(m.group(2))
        return self.media.image(m.group(1).strip(), (caption or "").strip())

    def sub(self, text: str) -> str:
        """The nested pass a callout's or a sheet's own content gets. Same
        substitutions as the top level, minus the block-level ones that
        cannot legally appear inside one."""
        text = _skip_fences(text, EMBED_RE, lambda m: self.stash(self.on_embed(m)))
        text = _skip_fences(text, WIKI_RE, lambda m: self.stash(self.on_wiki(m)))
        text = _skip_fences(text, CITE_RE, lambda m: self.stash(self.on_cite(m)))
        return text


def _render_fragment(prose: str, ctx: _Ctx) -> str:
    """One section's markdown to export HTML.

    Pass order mirrors render.render's, and for the reasons documented there:
    callouts before anything inserts blank lines into them, sheets before the
    fence-skipping passes can claim their fence, embeds before wikilinks,
    everything before markdown runs.
    """
    if not prose.strip():
        return ""
    prose = CALLOUT_RE.sub(
        lambda m: "\n\n" + ctx.stash(_callout(
            m.group("type"), m.group("title"),
            _CALLOUT_STRIP_RE.sub("", m.group("lines")), ctx.sub, ctx.house)) + "\n\n",
        prose)
    prose = SHEETS_RE.sub(
        lambda m: "\n\n" + ctx.stash(_sheets(m.group("content"), ctx.sub, ctx.house)) + "\n\n", prose)
    prose = _FENCE_CAPTURE.sub(
        lambda m: "\n\n" + ctx.stash(_fence(m.group(1).split("|")[0].strip(),
                                            m.group("code"), ctx.media,
                                            ctx.house)) + "\n\n", prose)
    prose = EMBED_RE.sub(lambda m: "\n\n" + ctx.stash(ctx.on_embed(m)) + "\n\n", prose)
    prose = _INLINE_IMG_RE.sub(
        lambda m: "\n\n" + ctx.stash(ctx.media.image(m.group(2).rsplit("/", 1)[-1],
                                                     m.group(1).split("|")[0].strip())) + "\n\n",
        prose)
    prose = WIKI_RE.sub(lambda m: ctx.stash(ctx.on_wiki(m)), prose)
    prose = CITE_RE.sub(lambda m: ctx.stash(ctx.on_cite(m)), prose)
    prose = URL_LINE_RE.sub(
        lambda m: "\n\n" + ctx.stash(
            f'<p style="{_TAG_CSS["p"]}"><a href="{_attr(m.group(1))}" '
            f'style="{_TAG_CSS["a"]}">{_esc(m.group(1))}</a></p>') + "\n\n",
        prose)

    out = _style(_unwrap_placeholder_p(_MD.render(prose)), ctx.house)
    # Highest index first, for the reason render.render spells out: a
    # callout's own fragment can still hold a lower-indexed placeholder that
    # its nested render carried through untouched.
    for i in range(len(ctx.blocks) - 1, -1, -1):
        out = out.replace(PLACEHOLDER.format(i), ctx.blocks[i])
    return out


def _build_sections(note: vault.Note, *, links: str, embed_images: bool,
                    house: bool = False):
    """The article as a list of rendered sections, in document order."""
    _, sources_sec = idx.split_sources_block(st.split_quiz(note.body)[0])
    sources = idx.parse_sources(sources_sec)
    prose = kb.strip_todos(kb.exportable_body(note))

    ctx = _Ctx(links, embed_images, sources, house)
    out = []
    for sec in kb.sections(prose):
        out.append({"heading": sec["heading"],
                    "html": _render_fragment(sec["content"], ctx)})
    ctx.toc = _apply_heading_ids(out)
    ctx.anchors = anchor_targets(prose)
    return out, ctx, sources


def _document_html(note: vault.Note, secs: list[dict], sources: list[dict],
                   include_meta: bool) -> str:
    """Every section stitched back into one document, headings and all. This
    is what the standalone page and the preview show; the field split below
    is a different view of the same rendered sections, never a second
    render."""
    parts = [_meta_table(note)] if include_meta else []
    for sec in secs:
        if sec["heading"]:
            parts.append(f'<h2 id="{_attr(sec.get("id", ""))}" '
                         f'style="{_TAG_CSS["h2"]}">{_esc(sec["heading"])}</h2>')
        parts.append(sec["html"])
    parts.append(_references(sources))
    return "".join(parts)


_TAGS_RE = re.compile(r"<[^>]+>")


def _visible_len(html_text: str) -> int:
    """Characters a reader would actually see. The form's limits count text,
    not markup, so a character count that included style attributes would be
    alarming and wrong."""
    return len(html.unescape(_TAGS_RE.sub("", html_text)).strip())


def _field_parts(note: vault.Note, secs: list[dict], sources: list[dict],
                 house: bool = True, anchors: set | None = None) -> list[dict]:
    """One fragment per form field, in the order the form asks for them.

    A field fed by exactly one section drops that section's heading -- the
    field *is* the heading, and repeating it inside the box is noise. A field
    fed by several keeps each heading, demoted to h3, because the box itself
    is already playing the h2's role.

    Unless something links to it. The five boxes are separate on the form but
    render into one page, so an anchor in Question reaches a heading in
    Answer -- and dropping the one heading a link points at turns that link
    into a jump to nowhere. A heading that is an anchor target is kept
    whatever the count says.
    """
    anchors = anchors or set()
    tpl = kb.template_of(note)
    override = kb.parse_fieldmap(note.meta.get(kb.MAP_KEY))
    buckets: dict[str, list[dict]] = {f: [] for f in kb.SECTION_FIELDS}
    for sec in secs:
        if not sec["html"].strip():
            continue
        buckets[kb.field_of(sec["heading"], tpl, override)].append(sec)

    refs = _references(sources)
    out: list[dict] = []
    meta = kb.meta_of(note)

    short = meta.get("kb_short_description", "")
    out.append({"field": "Short description", "kind": "text", "content": short,
                "chars": len(short), "limit": 160, "sections": []})

    for name in kb.SECTION_FIELDS:
        chunk = buckets[name]
        # The reference list belongs with the supporting material, not
        # stranded in whichever box happened to hold the last citation.
        extra = refs if (name == "Additional Information" and refs) else ""
        if not chunk and not extra:
            continue
        pieces = []
        for sec in chunk:
            linked = sec.get("id", "") in anchors
            if sec["heading"] and (len(chunk) > 1 or linked):
                pieces.append(f'<h3 id="{_attr(sec.get("id", ""))}" '
                              f'style="{_TAG_CSS["h3"]}">{_esc(sec["heading"])}</h3>')
            pieces.append(sec["html"])
        body = "".join(pieces) + extra
        if house:
            # Prepended per field, not once for the article: each box is
            # pasted into separately, and every published article carries the
            # block in every one of its fields.
            body = HOUSE_STYLE + body
        out.append({"field": name, "kind": "html", "content": body,
                    "chars": _visible_len(body), "limit": 0,
                    "sections": [s["heading"] for s in chunk if s["heading"]]})

    keywords = ", ".join(meta.get("kb_keywords", []) or [])
    out.append({"field": "Meta", "kind": "text", "content": keywords,
                "chars": len(keywords), "limit": kb.META_MAX, "sections": []})
    return out


# ── styling ────────────────────────────────────────────────────────────────


def _style_tag(s: str, tag: str, css: str, extra: str = "") -> str:
    """Add a style attribute to every `tag` that hasn't already got one.

    Regex over generated markup is safe here in a way it would not be over
    arbitrary HTML: every string this touches was produced by markdown-it or
    by this module a few lines earlier, so it is well-formed by
    construction, and the already-styled guard means our own fragments keep
    the styling they were emitted with.
    """
    def rep(m: re.Match) -> str:
        attrs = m.group(1) or ""
        if "style=" in attrs:
            return m.group(0)
        return f"<{tag}{extra}{attrs} style=\"{css}\">"
    return re.sub(rf"<{tag}((?:\s[^>]*)?)>", rep, s)


def _nest_ordered_lists(s: str) -> str:
    """Give each `<ol>` the marker its depth calls for: 1, then A, then i,
    then I. That progression is the house convention in published articles,
    and it is what makes a long nested procedure readable -- every level of a
    document full of bare `1.` markers looks like the same level."""
    out, depth, at = [], 0, 0
    for m in re.finditer(r"<ol(?:\s[^>]*)?>|</ol>", s):
        out.append(s[at:m.start()])
        at = m.end()
        if m.group(0) == "</ol>":
            depth = max(0, depth - 1)
            out.append(m.group(0))
        else:
            css = _OL_DEPTH_STYLE[min(depth, len(_OL_DEPTH_STYLE) - 1)]
            depth += 1
            out.append(f'<ol style="{css}">')
    out.append(s[at:])
    return "".join(out)


def _style(s: str, house: bool = False) -> str:
    """Inline the whole palette onto a fragment of generated HTML.

    With `house` set, the tags the house stylesheet owns are left bare so
    that block's rules apply to them -- otherwise a Tephra article would be
    the one article in the KB whose code blocks look different.
    """
    # A <code> inside a <pre> is a code *block* and must not also get the
    # inline chip's border and background. Rename it out of reach, style
    # everything else, put it back.
    s = s.replace("<pre><code", "<pre><kbcode")
    for tag, css in _TAG_CSS.items():
        if house and tag in HOUSE_OWNED:
            continue
        if tag == "ol":
            continue        # depth-aware, applied below
        extra = ' border="1" cellspacing="0" cellpadding="6"' if tag == "table" else ""
        s = _style_tag(s, tag, css, extra)
    s = s.replace("<pre><kbcode", "<pre><code")
    s = _nest_ordered_lists(s)
    # markdown-it emits a language class on a fenced block's <code>; it names
    # a stylesheet that will not be there, so it is noise at best.
    s = re.sub(r'<code class="[^"]*"', "<code", s)
    return s


_HEADING_RE = re.compile(r"<h([1-6])([^>]*)>(.*?)</h\1>", re.S)
_TAGSTRIP_RE = re.compile(r"<[^>]+>")
# `[text](#anchor)` -- the ordinary markdown link, which is the whole point:
# anchoring needs no syntax of its own, and a note written with one reads the
# same in any other markdown tool.
ANCHOR_REF_RE = re.compile(r"\]\(#([^)\s]+)\)")


def heading_id(text: str) -> str:
    """A stable, readable id for a heading. Deterministic on the text alone,
    so an author can type `](#how-to-add-a-blade)` by hand and have it hit."""
    return re.sub(r"[^a-z0-9]+", "-", _TAGSTRIP_RE.sub("", text).lower()).strip("-")


def anchor_targets(body: str) -> set[str]:
    """Every anchor this article links to. Used to decide which headings must
    survive the export: the field split drops a heading when its field is fed
    by exactly one section, and dropping the one thing a link points at turns
    that link into a dead jump."""
    return {m.group(1).lower() for m in ANCHOR_REF_RE.finditer(body)}


def _apply_heading_ids(secs: list[dict]) -> list[dict]:
    """Give every heading in the article a unique id, in document order.

    Done once over the whole article and before anything is split into
    fields, so the document view and the per-field fragments agree on every
    id. Computed separately per view, they would drift apart the moment a
    heading appeared twice -- and an anchor that works in the preview but not
    after the paste is worse than one that never worked.
    """
    seen: dict[str, int] = {}
    toc: list[dict] = []

    def unique(text: str) -> str:
        base = heading_id(text) or f"section-{len(toc) + 1}"
        seen[base] = seen.get(base, 0) + 1
        return base if seen[base] == 1 else f"{base}-{seen[base]}"

    for sec in secs:
        if sec["heading"]:
            sec["id"] = unique(sec["heading"])
            toc.append({"level": 2, "text": sec["heading"], "id": sec["id"]})

        def rep(m: re.Match) -> str:
            level, attrs, inner = int(m.group(1)), m.group(2), m.group(3)
            if "id=" in attrs:
                return m.group(0)
            anchor = unique(inner)
            toc.append({"level": level, "text": _TAGSTRIP_RE.sub("", inner).strip(),
                        "id": anchor})
            return f'<h{level} id="{_attr(anchor)}"{attrs}>{inner}</h{level}>'

        sec["html"] = _HEADING_RE.sub(rep, sec["html"])
    return toc


# ── standalone page ────────────────────────────────────────────────────────

_PAGE_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#eef1f4;color:%(ink)s;
     font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
     font-size:16px;line-height:1.65;-webkit-text-size-adjust:100%%}
.wrap{max-width:52rem;margin:0 auto;padding:2.5rem 1.25rem 5rem}
.sheet{background:#fff;border:1px solid %(rule)s;border-radius:10px;
       padding:2.5rem clamp(1.1rem,4vw,3rem);box-shadow:0 1px 3px rgba(16,24,40,.06)}
.eyebrow{text-transform:uppercase;letter-spacing:.09em;font-size:.72rem;font-weight:700;
         color:%(accent)s;margin:0 0 .6rem}
.lede{font-size:1.08rem;color:%(muted)s;margin:0 0 1.6rem;line-height:1.6}
.toc{background:%(wash)s;border:1px solid %(rule)s;border-radius:8px;padding:1rem 1.25rem;
     margin:0 0 2rem}
.toc p{margin:0 0 .5rem;font-weight:700;font-size:.85rem;text-transform:uppercase;
       letter-spacing:.06em;color:%(muted)s}
.toc ol{margin:0;padding-left:1.2rem}
.toc li{margin:.2rem 0;line-height:1.5}
.toc .sub{margin-left:1rem;list-style:circle}
.toc a{color:%(ink)s;text-decoration:none}
.toc a:hover{text-decoration:underline}
.foot{margin:2rem 0 0;padding-top:1.2rem;border-top:1px solid %(rule)s;
      color:%(muted)s;font-size:.85rem}
/* Wide content scrolls inside its own box; the page itself never does. */
table{display:block;overflow-x:auto;max-width:100%%}
pre{overflow-x:auto}
img{max-width:100%%;height:auto}
@media (max-width:38rem){
  .wrap{padding:0}
  .sheet{border-radius:0;border-left:0;border-right:0;padding:1.6rem 1.1rem 3rem}
}
@media print{
  body{background:#fff}
  .sheet{border:0;box-shadow:none;padding:0}
  .toc{break-inside:avoid}
  a{text-decoration:none;color:%(ink)s}
}
""" % {"ink": INK, "muted": MUTED, "rule": RULE, "wash": WASH, "accent": ACCENT}


def _toc_html(toc: list[dict]) -> str:
    if len(toc) < 3:
        return ""
    items = []
    for h in toc:
        cls = ' class="sub"' if h["level"] == 3 else ""
        items.append(f'<li{cls}><a href="#{_attr(h["id"])}">{_esc(h["text"])}</a></li>')
    return f'<nav class="toc"><p>Contents</p><ol>{"".join(items)}</ol></nav>'


def _standalone(note: vault.Note, body: str, toc: list[dict]) -> str:
    m = kb.meta_of(note)
    tpl = kb.template_of(note)
    eyebrow = " · ".join(x for x in [tpl.name if tpl else "", m.get("kb_number", "")] if x)
    lede = m.get("kb_short_description", "")
    foot_bits = [f"Updated {_esc((note.updated or '')[:10])}" if note.updated else ""]
    if m.get("kb_owner"):
        foot_bits.append(f"Owner: {_esc(m['kb_owner'])}")
    if m.get("kb_review_by"):
        foot_bits.append(f"Review by {_esc(m['kb_review_by'])}")
    if m.get("kb_audience"):
        foot_bits.append(f"Audience: {_esc(m['kb_audience'])}")
    foot = " · ".join(b for b in foot_bits if b)
    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(note.title)}</title>"
        f'<meta name="description" content="{_attr(lede)}">'
        f"<style>{_PAGE_CSS}</style></head><body><div class=\"wrap\">"
        f'<article class="sheet">'
        + (f'<p class="eyebrow">{_esc(eyebrow)}</p>' if eyebrow else "")
        + f'<h1 style="{_TAG_CSS["h1"]}">{_esc(note.title)}</h1>'
        + (f'<p class="lede">{_esc(lede)}</p>' if lede else "")
        + _toc_html(toc)
        + body
        + (f'<p class="foot">{foot}</p>' if foot else "")
        + "</article></div></body></html>\n"
    )


# ── markdown and text ──────────────────────────────────────────────────────


def _markdown(note: vault.Note, *, links: str) -> tuple[str, _Media]:
    """Portable markdown: the article as source, with everything that only
    means something inside Tephra resolved into something that means the same
    thing anywhere. Callouts keep their boundary as a labelled blockquote,
    sheets lose their tabs but keep their tables, and diagrams and images
    become the same numbered placeholders the HTML targets leave."""
    prose, _quiz = st.split_quiz(note.body)
    prose, sources_sec = idx.split_sources_block(prose)
    sources = idx.parse_sources(sources_sec)
    prose = kb.strip_todos(prose).strip()

    media = _Media(embed=False)
    known = kb.by_number()

    def on_wiki(m):
        title = m.group(1).strip()
        shown = (m.group(2) or title).strip()
        hit = known.get(title.lower())
        if links != "text" and hit:
            # A URL is a link anywhere; a KB number is only a link inside the
            # KB system, so in portable markdown it is written as what it is
            # -- a reference the reader can search for -- rather than as an
            # href that resolves nowhere.
            if links in ("auto", "url") and hit["url"]:
                return f"[{shown}]({hit['url']})"
            if links in ("auto", "number") and hit["number"]:
                return f"[{shown}]({KB_LINK_BASE}{hit['number']})"
        return f"**{shown}**"

    def on_cite(m):
        n = int(m.group(1))
        return f"[{n}]" if 1 <= n <= len(sources) else f"[{n}?]"

    def placeholder(name: str, caption: str, kind: str = "image") -> str:
        token = media._token()
        media.items.append({"token": token, "kind": kind, "name": name,
                            "caption": caption})
        label = "Image" if kind == "image" else "Diagram"
        cap = f" — {caption}" if caption else ""
        return f"> **[{label} {token}{cap}]** Attach `{name}` here."

    def on_embed(m):
        caption, _size = _split_embed_extra(m.group(2))
        return placeholder(m.group(1).strip(), (caption or "").strip())

    def on_callout(m):
        variant = CALLOUT_VARIANTS.get(m.group("type").lower(), "note")
        label = m.group("title").strip() or _CALLOUT_LOOK.get(
            variant, _CALLOUT_LOOK["note"])[2]
        inner = _CALLOUT_STRIP_RE.sub("", m.group("lines")).strip()
        quoted = "\n".join(f"> {ln}" if ln else ">" for ln in inner.splitlines())
        return f"\n> **{label}**\n>\n{quoted}\n"

    def on_sheets(m):
        """Tabs are interaction and interaction does not travel. Each sheet
        becomes an h3 and its table, in order -- h3 rather than the h2 the
        fence uses internally, so a sheet name can never be mistaken for one
        of the article's own sections."""
        out = []
        for name, table_md in _parse_sheets(m.group("content")):
            out.append(f"### {name}\n\n{table_md.strip()}")
        return "\n\n" + "\n\n".join(out) + "\n\n"

    def on_fence(m):
        lang = m.group(1).split("|")[0].strip()
        if lang in ("mermaid", "netdiagram"):
            # _token() is derived from the item count, so it names the item
            # placeholder() is about to append -- the two agree by
            # construction, and the warning can name the diagram before it
            # exists.
            token = media._token()
            media.warnings.append(
                f"{lang} diagram {token} is source, not a picture — render the "
                "standalone HTML and attach a screenshot.")
            return placeholder(f"{lang}-{token}.png", f"{lang} diagram", kind="diagram")
        return m.group(0)

    prose = CALLOUT_RE.sub(on_callout, prose)
    prose = SHEETS_RE.sub(on_sheets, prose)
    prose = _FENCE_CAPTURE.sub(on_fence, prose)
    prose = _skip_fences(prose, EMBED_RE, on_embed)
    prose = _skip_fences(prose, _INLINE_IMG_RE,
                         lambda m: placeholder(m.group(2).rsplit("/", 1)[-1],
                                               m.group(1).split("|")[0].strip()))
    prose = _skip_fences(prose, WIKI_RE, on_wiki)
    prose = _skip_fences(prose, CITE_RE, on_cite)

    m = kb.meta_of(note)
    head = [f"# {note.title}", ""]
    if m.get("kb_short_description"):
        head += [f"> {m['kb_short_description']}", ""]
    facts = []
    for f in kb.FIELDS:
        if f.key in ("kb_short_description", "kb_status"):
            continue
        v = m.get(f.key)
        if v:
            facts.append(f"- **{f.label}:** {', '.join(v) if isinstance(v, list) else v}")
    if facts:
        head += facts + [""]

    tail = []
    if sources:
        tail = ["", "## References", ""]
        for i, s in enumerate(sources, 1):
            url = s.get("url") or ""
            text = s.get("text") or url
            tail.append(f"{i}. [{text}]({url})" if url else f"{i}. {text}")
    return "\n".join(head) + "\n" + prose.strip() + "\n" + "\n".join(tail) + "\n", media


_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^[\s|:-]+$")


def _text_table(rows: list[list[str]]) -> list[str]:
    """A markdown table laid out in fixed columns. Worth doing properly:
    tables carry the version matrices and port lists that are the whole
    point of half these articles, and a table flattened to prose loses the
    correspondence between a row and its values."""
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    cols = [max(len(r[i]) for r in rows) for i in range(width)]
    out = []
    for i, r in enumerate(rows):
        out.append("  ".join(c.ljust(cols[j]) for j, c in enumerate(r)).rstrip())
        if i == 0:
            out.append("  ".join("-" * cols[j] for j in range(width)))
    return out


def _plain(md_text: str) -> str:
    """Markdown reduced to text, keeping the structure that carries meaning:
    heading hierarchy, list indentation, table columns, and a link's target
    spelled out rather than thrown away."""
    lines, out, table = md_text.splitlines(), [], []
    in_fence = False
    for raw in lines:
        line = raw.rstrip()
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("    " + line)
            continue
        if _TABLE_ROW_RE.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not _TABLE_SEP_RE.match(line.replace("|", " ")) or any(c.strip("-: ") for c in cells):
                table.append(cells)
            continue
        if table:
            out.extend(_text_table(table))
            out.append("")
            table = []
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            text = h.group(2).strip()
            level = len(h.group(1))
            out.append("")
            if level <= 2:
                out.append(text.upper())
                out.append(("=" if level == 1 else "-") * len(text))
            else:
                out.append(text)
            out.append("")
            continue
        out.append(line)
    if table:
        out.extend(_text_table(table))

    s = "\n".join(out)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]*)\)", r"[image: \1]", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s, flags=re.S)
    s = re.sub(r"(?<!\w)([*_])(?!\s)(.+?)(?<!\s)\1(?!\w)", r"\2", s, flags=re.S)
    s = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", s)
    s = re.sub(r"^>[ \t]?", "| ", s, flags=re.M)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip() + "\n"


# ── entry point ────────────────────────────────────────────────────────────


def _filename(note: vault.Note, ext: str) -> str:
    num = kb.meta_of(note).get("kb_number", "")
    stem = f"{num}-{note.slug}" if num else note.slug
    return f"{stem}.{ext}"


def export(note: vault.Note, *, target: str = "servicenow", links: str = "auto",
           include_meta: bool = True, house_style: bool = True) -> dict:
    """Render `note` for `target`. Never raises on content -- an article with
    a broken embed or an unknown fence language exports, with a warning
    saying what degraded, because an author mid-paste needs the output more
    than they need a stack trace."""
    if target not in TARGETS:
        raise ValueError(f"unknown export target: {target}")
    if links not in LINK_MODES:
        links = "auto"

    meta = kb.meta_of(note)
    common = {
        "target": target,
        "title": note.title,
        "slug": note.slug,
        "meta": meta,
        "generated": date.today().isoformat(),
    }

    if target in ("markdown", "text"):
        md_text, media = _markdown(note, links=links)
        raw = md_text if target == "markdown" else _plain(md_text)
        resolve = media.finalize(raw)
        ext = "md" if target == "markdown" else "txt"
        mime = "text/markdown" if target == "markdown" else "text/plain"
        return {**common, "content": resolve(raw), "mime": mime,
                "filename": _filename(note, ext), "parts": [],
                "manifest": media.items, "warnings": media.warnings}

    embed = target == "standalone"
    house = house_style and target == "servicenow"
    secs, ctx, sources = _build_sections(note, links=links, embed_images=embed,
                                         house=house)
    media = ctx.media
    body = _document_html(note, secs, sources, include_meta)
    toc = ctx.toc

    if target == "standalone":
        page = _standalone(note, body, toc)
        resolve = media.finalize(page)
        return {**common, "content": resolve(page), "parts": [],
                "mime": "text/html", "filename": _filename(note, "html"),
                "manifest": media.items, "warnings": media.warnings}

    # ── servicenow ──
    #
    # The destination has no article *body*: it has a form with one rich-text
    # box per section of the article. So the useful output is not one blob of
    # HTML but a list of fragments, one per box, in the order the form asks
    # for them -- `content` is still the whole document, because the preview
    # needs something to show and a caller that only wants the markup should
    # not have to reassemble it.
    parts = _field_parts(note, secs, sources, house, ctx.anchors)

    # Numbering is decided over the document, then applied to each fragment,
    # so an image is "Image 3" in whichever box it lands in rather than
    # restarting at 1 in every field. finalize also resolves the tokens
    # inside the warnings it collected, so it has to run before they are read.
    resolve = media.finalize(body)
    for part in parts:
        part["content"] = resolve(part["content"])

    warnings = list(media.warnings)
    if kb.has_todos(note.body):
        warnings.append("Template guidance was still in the article; it has been "
                        "stripped from this export but is still in the note.")
    over = [p for p in parts if p["limit"] and p["chars"] > p["limit"]]
    for p_ in over:
        warnings.append(f"{p_['field']} is {p_['chars']} characters; the form allows "
                        f"{p_['limit']}.")
    # The five boxes render into one page, so a jump link in Question can
    # reach a heading in Answer -- but only if that heading is really there.
    ids = {m.group(1) for m in re.finditer(r'<h[1-6] id="([^"]+)"',
                                           "".join(p["content"] for p in parts))}
    for dead in sorted(ctx.anchors - ids):
        warnings.append(f"Nothing in this article is called #{dead}, so that jump "
                        "link goes nowhere.")
    empty = [f for f in kb.SECTION_FIELDS
             if f in ("Question", "Answer") and not any(p["field"] == f for p in parts)]
    for f in empty:
        warnings.append(f"Nothing is mapped to {f}. Check the field mapping, or write "
                        "that section.")

    return {**common, "content": resolve(body), "mime": "text/html",
            "filename": _filename(note, "html"), "parts": parts,
            "form": kb.FORM,
            "manifest": media.items, "warnings": warnings}
