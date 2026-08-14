"""
Markdown -> HTML, with the three syntaxes that make this a wiki rather than
a folder of documents:

    [[Note Title]]          a link; renders orange if the note doesn't exist
    [[Note Title|shown]]    same, with display text
    ![[picture.png]]        an embed, resolved to img/video/audio/file by extension
    ![[picture.png|400]]    an embed sized to 400px wide (or |50% of the column)
    ![[picture.png|caption|400]]   caption and size together
    ![alt|400](url)         a plain markdown image sized the same way, so a
                             note's own inline (non-attachment) images can be
                             corner-dragged too, not just ![[embeds]]
    [^1]                     a citation, referencing the Nth entry (1-indexed)
                             of this note's own `## Sources` list -- flagged
                             if there's no such entry
    ```mermaid               a fenced code block tagged "mermaid" renders as
    graph TD                 a diagram instead of code
    A --> B
    ```

A bare URL alone on a line becomes a bookmark card. That is deliberate:
pasting a link is the most common thing anyone does in a notes app, and it
should not require syntax.

Embeds placed on adjacent lines with no blank line between them render as a
row rather than stacked -- the same "no new syntax" instinct as the size
spec above. A blank line between two embeds keeps today's stacked layout.

Tables and plain blockquotes are standard CommonMark/GFM and need nothing
special. Callout/note boxes are not standard, but the syntax pasted-in
sources actually use for them (GitHub's and Obsidian's, which agree) is
recognised on top of an ordinary blockquote:

    > [!NOTE]
    > A note. TIP, IMPORTANT, WARNING, CAUTION, DANGER and Obsidian's wider
    > vocabulary (info, hint, danger, question, ...) all work too, mapped
    > onto a handful of visual variants; an unrecognised type still gets a
    > box rather than rendering as literal "[!TYPE]" text.

    > [!WARNING] Custom title
    > A custom title after the type, instead of the type name. Needs a
    > blank line before it like this one -- same as two ordinary
    > blockquotes, which CommonMark itself also reads as one if they run
    > together with no blank line between them.
"""
from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt

from . import vault
from .index import CITE_RE, EMBED_RE, WIKI_RE

md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False})
md.enable("table")
md.enable("strikethrough")

URL_LINE_RE = re.compile(r"^\s*(https?://\S+)\s*$", re.M)

# A ```fenced``` block, so WIKI_RE/CITE_RE/URL_LINE_RE below can skip over
# one instead of reaching inside it. Mermaid's own flowchart syntax uses
# `id[[Subroutine]]` for a subroutine-shaped node -- indistinguishable from
# a [[wikilink]] to WIKI_RE unless fence content is protected from it, so
# without this a Mermaid diagram using that node shape would get silently
# corrupted into a link mid-diagram. Simplified vs. full CommonMark fence
# rules (no tilde fences, no indented fences, no 4+ backtick fences) -- good
# enough to protect the ``` mermaid convention this file actually emits;
# md.render() below still does the real, spec-accurate fence parsing.
_FENCE_RE = re.compile(r"^```.*?\n.*?^```[ \t]*$", re.M | re.S)


def _skip_fences(text: str, pattern: re.Pattern, repl) -> str:
    """pattern.sub(repl, text), but only in the gaps between ```fenced```
    blocks -- see _FENCE_RE."""
    parts, last = [], 0
    for m in _FENCE_RE.finditer(text):
        parts.append(pattern.sub(repl, text[last:m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(pattern.sub(repl, text[last:]))
    return "".join(parts)


# GitHub/Obsidian callout syntax: a blockquote whose first line is a bare
# `[!TYPE]` marker, optionally followed by a custom title on that same line.
# `[+-]?` is Obsidian's fold marker -- accepted so a foldable callout parses
# instead of leaking a stray `+`/`-` into the title, even though nothing here
# makes it actually foldable. Every subsequent `>`-prefixed line belongs to
# the callout; a line with no `>` at all ends it, same as any blockquote.
CALLOUT_RE = re.compile(
    r"^[ \t]*>[ \t]*\[!(?P<type>[\w-]+)\][+-]?[ \t]*(?P<title>[^\n]*)\n"
    r"(?P<lines>(?:[ \t]*>.*(?:\n|$))*)",
    re.M,
)
_CALLOUT_STRIP_RE = re.compile(r"^[ \t]*>[ \t]?", re.M)

# Sources pasted in from GitHub READMEs or an Obsidian vault use a much
# wider vocabulary of callout types than there's any use styling separately
# -- collapse them onto a handful of visual variants. Anything not listed
# still renders as a boxed callout (see _callout_html's fallback), just
# with the "note" look, rather than falling back to a plain blockquote with
# a literal "[!TYPE]" leaking into the text.
CALLOUT_VARIANTS = {
    "note": "note", "info": "note", "abstract": "note", "summary": "note", "tldr": "note",
    "quote": "note", "cite": "note", "example": "note", "question": "note",
    "help": "note", "faq": "note",
    "tip": "tip", "hint": "tip", "success": "tip", "check": "tip", "done": "tip",
    "important": "tip",
    "warning": "warning", "caution": "warning", "attention": "warning",
    "danger": "danger", "error": "danger", "failure": "danger", "fail": "danger",
    "missing": "danger", "bug": "danger",
}
# CommonMark *requires* U+0000 to be replaced with U+FFFD, so a NUL-delimited
# placeholder gets silently destroyed. Letters and digits only: nothing here
# is markdown-active, so the token survives the parser untouched.
PLACEHOLDER = "xTEPHRAxHOLDERx{}xENDx"

# A bare number (px) or a number with a trailing `%`, matching Obsidian's own
# `![[image.png|400]]` convention so it isn't a new idea to learn.
_SIZE_RE = re.compile(r"^\d+%?$")
# No blank line between two embeds -- at most a single newline, optionally
# padded with spaces/tabs -- means "these belong in one row." fullmatch, not
# match+$: bare `$` matches just before a trailing newline even without
# re.MULTILINE, which let two embeds separated by a *blank* line (two
# newlines) pass this check and get grouped into a row by mistake.
_ADJACENT_RE = re.compile(r"[ \t]*\n?[ \t]*")

# Obsidian resizes a *standard* markdown image the same way it resizes its
# own ![[embed]] syntax: a size tacked onto the end of the alt text with a
# `|`, e.g. ![a photo|400](pic.png). Reusing that convention here means a
# note dragged in from Obsidian already means the same thing, and one typed
# by hand needs no new syntax to learn beyond what embeds already use.
_INLINE_IMG_SIZE_RE = re.compile(r"^(.*)\|(\d+%?)$", re.S)


def _split_inline_img_alt(alt: str) -> tuple[str, str | None]:
    m = _INLINE_IMG_SIZE_RE.match(alt)
    if not m:
        return alt, None
    return m.group(1), m.group(2)


# Overrides markdown-it's own image rendering so a plain ![alt](url) --
# unlike ![[embed]], which is caught and rendered before md.render() ever
# runs -- can still carry a size and a stable index for the frontend's
# corner-drag resize to target. data-img-index counts images in the order
# markdown-it visits them, which for a single render() call is document
# order; a callout's own nested md.render() call (see _callout_html) starts
# its own count from 0, same scoping _embed_runs already uses per callout.
def _inline_image_rule(tokens, idx, options, env):
    token = tokens[idx]
    raw_alt = md.renderer.renderInlineAsText(token.children, options, env) if token.children else ""
    alt, size = _split_inline_img_alt(raw_alt)
    token.attrSet("alt", alt)
    token.attrSet("loading", "lazy")
    i = env.get("_img_i", 0)
    env["_img_i"] = i + 1
    css_width = size if size and size.endswith("%") else f"{size}px" if size else None
    style = f' style="width:{html.escape(css_width, quote=True)}"' if css_width else ""
    sized = " sized" if size else ""
    inner = md.renderer.renderToken(tokens, idx, options, env)
    return f'<span class="inline-img{sized}" data-img-index="{i}"{style}>{inner}</span>'


md.renderer.rules["image"] = _inline_image_rule


# ```mermaid fences render as <pre class="mermaid"> holding the raw diagram
# source; the frontend's enhanceMermaid() finds those and hands them to
# mermaid.run(), which replaces their content with the rendered SVG client-
# side. Every other language falls through to markdown-it's own default
# fence renderer unchanged (captured before this overwrites the rule).
#
# A manual resize (drag handles, app.js's startResize with kind='mermaid')
# persists as ```mermaid|500 -- the same `|size` convention embeds and
# inline images already use (![[img|400]], ![alt|400](url)), reusing
# _SIZE_RE so a hand-typed `|50%` works too, not just a dragged pixel
# value. data-mermaid-index gives the frontend a stable target for that
# rewrite, the same role data-img-index plays for inline images.
_default_fence = md.renderer.rules.get("fence")


def _fence_rule(tokens, idx, options, env):
    token = tokens[idx]
    info = (token.info or "").strip()
    lang_field, _, size_field = info.partition("|")
    lang = lang_field.strip().split()[0] if lang_field.strip() else ""
    if lang.lower() == "mermaid":
        i = env.get("_mmd_i", 0)
        env["_mmd_i"] = i + 1
        size = size_field.strip()
        size = size if _SIZE_RE.match(size) else None
        css_width = size if size and size.endswith("%") else f"{size}px" if size else None
        style = f' style="width:{html.escape(css_width, quote=True)}"' if css_width else ""
        sized = " sized" if css_width else ""
        return (f'<pre class="mermaid{sized}" data-mermaid-index="{i}"{style}>'
                f'{html.escape(token.content)}</pre>\n')
    return _default_fence(tokens, idx, options, env)


md.renderer.rules["fence"] = _fence_rule


def _split_embed_extra(raw: str | None) -> tuple[str | None, str | None]:
    """Split the text after an embed's first `|` into (caption, size).

    A lone field that looks like a size (`400`, `50%`) is a size with no
    caption. Two fields are caption then size. Anything else -- including a
    caption that itself happens to contain a literal `|` -- stays a caption
    verbatim, so a note written before this existed renders exactly as it
    always did.
    """
    if raw is None:
        return None, None
    if "|" in raw:
        cap, _, size = raw.rpartition("|")
        if _SIZE_RE.match(size.strip()):
            return (cap or None), size.strip()
        return raw, None
    if _SIZE_RE.match(raw.strip()):
        return None, raw.strip()
    return raw, None


def _embed_html(name: str, caption: str | None, size: str | None, idx: int) -> str:
    kind = vault.kind_of(name)
    url = f"/media/{html.escape(name, quote=True)}"
    label = html.escape(caption or name)
    missing = not (vault.MEDIA / name).is_file()
    if missing:
        return (f'<div class="embed missing"><div class="embed-cap">'
                f'<span class="kind">MISSING</span> {html.escape(name)}</div></div>')
    if kind == "image":
        inner = f'<img src="{url}" alt="{label}" loading="lazy">'
    elif kind == "video":
        inner = f'<video src="{url}" controls preload="metadata"></video>'
    elif kind == "audio":
        inner = f'<audio src="{url}" controls preload="metadata"></audio>'
    else:
        return (f'<a class="filechip g2" href="{url}" download>'
                f'<span class="ic"></span>{html.escape(name)}</a>')
    # The stored size is a bare number or a percentage (Obsidian's own
    # `|400` convention -- no unit to type). CSS requires one; a bare
    # `width:384` is invalid and browsers silently drop it, which read as
    # the image "losing" its scale on every re-render from disk.
    css_width = size if size and size.endswith("%") else f"{size}px" if size else None
    style = f' style="width:{html.escape(css_width, quote=True)}"' if css_width else ""
    sized = " sized" if size else ""
    # data-embed-index is this embed's position among all embeds in the note,
    # in document order -- the frontend's drag-resize uses it to find and
    # rewrite the matching ![[...]] occurrence in the raw source.
    # The caption was previously parsed and then only ever used as the
    # image's invisible `alt` text -- typed it, never saw it. It's now the
    # visible text in the bar under the embed, falling back to the filename
    # when unset. data-caption/data-fallback let the frontend's click-to-edit
    # tell "no caption yet" apart from "caption happens to equal filename".
    cap_shown = html.escape(caption) if caption else html.escape(name)
    # CSS truncates this to one line (see .embed-cap-text) so an unbroken
    # filename with no spaces -- an imported guide's deterministic media name
    # can run 60+ characters -- can't wrap the whole figure open. The title
    # attribute keeps the full text one hover away.
    cap_title = html.escape(caption or name, quote=True)
    view_link = (f'<a class="embed-view" href="{url}" '
                 f'title="Open at full size">View</a>') if kind == "image" else ""
    return (f'<figure class="embed g2{sized}" data-kind="{kind}" data-embed-index="{idx}"{style}>'
            f'<div class="embed-media">{inner}</div>'
            f'<figcaption class="embed-cap"><span class="kind">{kind.upper()}</span>'
            f'<span class="embed-cap-text" data-caption="{html.escape(caption or "", quote=True)}" '
            f'data-fallback="{html.escape(name, quote=True)}" title="{cap_title}">{cap_shown}</span>'
            f'{view_link}</figcaption></figure>')


def _embed_runs(body: str, stash) -> tuple[str, list[str]]:
    """Replace every ![[...]] with its rendered figure, grouping embeds that
    sit on adjacent lines (no blank line between) into one <div class="embed-
    row">. Positions shift as fragments are stashed, so this builds the
    result by slicing the original text between matches rather than using
    re.sub, which would only see one match at a time and lose the adjacency
    information it needs for grouping."""
    matches = list(EMBED_RE.finditer(body))
    used: list[str] = []
    if not matches:
        return body, used

    runs: list[list[re.Match]] = [[matches[0]]]
    for m in matches[1:]:
        prev = runs[-1][-1]
        if _ADJACENT_RE.fullmatch(body[prev.end():m.start()]):
            runs[-1].append(m)
        else:
            runs.append([m])

    out: list[str] = []
    cursor = 0
    idx = 0
    for run in runs:
        out.append(body[cursor:run[0].start()])
        figures = []
        for m in run:
            name = m.group(1).strip()
            used.append(name)
            caption, size = _split_embed_extra(m.group(2))
            figures.append(_embed_html(name, caption, size, idx))
            idx += 1
        frag = figures[0] if len(run) == 1 else f'<div class="embed-row">{"".join(figures)}</div>'
        out.append("\n\n" + stash(frag) + "\n\n")
        cursor = run[-1].end()
    out.append(body[cursor:])
    return "".join(out), used


# Inline markdown links ([text](url)) and linkify's bare-URL autolinks both
# come out of md.render() as a plain <a href="..."> with no target — clicking
# one navigates Tephra's own window away to the external site. There's no
# back button in the desktop build (a single pywebview window, no browser
# chrome) and no address bar in a kiosk-style tab either, so that's a dead
# end the user can only escape by closing the app. target="_blank" fixes
# both: a normal browser tab opens a new tab, and pywebview's
# OPEN_EXTERNAL_LINKS_IN_BROWSER (on by default) routes _blank navigation to
# the system browser instead of taking over the app window. The one-line
# bookmark card already sets this itself; this catches everything else.
_EXTERNAL_LINK_RE = re.compile(r'<a href="(https?://[^"]*)"((?:(?!target=)[^>])*)>')


def _open_externally(m: re.Match) -> str:
    return f'<a href="{m.group(1)}" target="_blank" rel="noopener noreferrer"{m.group(2)}>'


# Markdown wraps a placeholder sitting alone on its own line in a <p>, same
# as any other block -- unwanted once it's a block-level fragment itself
# (a figure, a bookmark card, a callout). Shared so a callout's own nested
# md.render() can unwrap a block-level embed inside it exactly as the outer
# render does, rather than leaving it stuck inside an invalid <p><figure>.
_PLACEHOLDER_P_RE = re.compile(r"<p>\s*(" + PLACEHOLDER.replace("{}", r"\d+") + r")\s*</p>")


def _unwrap_placeholder_p(rendered: str) -> str:
    return _PLACEHOLDER_P_RE.sub(r"\1", rendered)


def _callout_html(kind: str, title: str, inner_md: str, stash, on_wiki, used: list) -> str:
    variant = CALLOUT_VARIANTS.get(kind.lower(), "note")
    label = html.escape(title.strip()) if title.strip() else html.escape(kind.upper())
    # A callout's content runs the same embed + wikilink pass the top-level
    # body gets, not a plain md.render() -- an ![[embed]] or [[link]] inside
    # one is otherwise invisible to it (rendered as raw brackets) or, worse,
    # tracked nowhere (an image only ever embedded inside a callout would
    # never show up as "used", and a link made only from inside one would
    # never appear in that note's outgoing links or the graph).
    inner_text, embed_used = _embed_runs(inner_md, stash)
    used.extend(embed_used)
    inner_text = WIKI_RE.sub(lambda m: stash(on_wiki(m)), inner_text)
    inner = _unwrap_placeholder_p(md.render(inner_text))
    return (f'<div class="callout callout-{variant}">'
            f'<div class="callout-h">{label}</div>'
            f'<div class="callout-b">{inner}</div></div>')


def _callout_sub(body: str, stash, on_wiki, used: list) -> str:
    """Runs on the raw body, before the top-level _embed_runs -- that call
    inserts blank lines around a block embed's placeholder, and a blank
    line with no leading `>` ends a blockquote right there, splitting a
    callout that has an embed in it into three pieces (see the regression
    this replaced: text before the embed stayed boxed, the embed and
    everything after it fell out into a bare, unstyled blockquote). Callout
    detection has to run before that split can happen, and it strips
    `>` markers before handing content off to _embed_runs itself, so
    nothing here depends on blockquote continuation surviving at all.
    """
    def repl(m: re.Match) -> str:
        inner_md = _CALLOUT_STRIP_RE.sub("", m.group("lines"))
        frag = _callout_html(m.group("type"), m.group("title"), inner_md, stash, on_wiki, used)
        return "\n\n" + stash(frag) + "\n\n"
    return CALLOUT_RE.sub(repl, body)


def _bookmark_html(url: str) -> str:
    safe = html.escape(url, quote=True)
    host = re.sub(r"^www\.", "", url.split("/")[2]) if "//" in url else url
    letter = html.escape(host[:1].upper() or "?")
    path = url.split("/", 3)[3] if url.count("/") > 2 else ""
    return (f'<a class="bookmark g2" href="{safe}" target="_blank" rel="noopener">'
            f'<span class="favicon">{letter}</span>'
            f'<span class="bk-body"><span class="bk-t">{html.escape(host)}</span>'
            f'<span class="bk-u">{html.escape(path[:90] or url)}</span></span></a>')


def render(body: str, resolve, sources=()) -> tuple[str, list[str], list[str]]:
    """resolve(title) -> slug|None. Returns (html, link_targets, embed_names).

    sources is this note's own parsed `## Sources` list (idx.parse_sources's
    [{text, url}, ...] shape) -- [^N] markers in the body index into it, so
    the caller has to strip and parse that section itself first and hand the
    result back in here.

    Block-level HTML is swapped out for placeholders before markdown runs and
    swapped back after, so the markdown parser never sees our raw HTML and
    can't mangle or escape it.
    """
    # Flatten any nested links before parsing. A damaged file should render as
    # a sane single link rather than as visible bracket soup, whether or not the
    # repair pass has been run over it yet.
    from .index import flatten_nested_links
    body, _nested = flatten_nested_links(body)

    blocks: list[str] = []
    targets: list[str] = []
    used: list[str] = []

    def stash(fragment: str) -> str:
        blocks.append(fragment)
        return PLACEHOLDER.format(len(blocks) - 1)

    def on_wiki(m):
        title = m.group(1).strip()
        shown = (m.group(2) or title).strip()
        targets.append(title)
        slug = resolve(title)
        cls = "wl" if slug else "wl pending"
        attr = f'data-slug="{html.escape(slug, quote=True)}"' if slug else ""
        return (f'<a class="{cls}" {attr} '
                f'data-title="{html.escape(title, quote=True)}">'
                f'{html.escape(shown)}</a>')

    def on_cite(m):
        n = int(m.group(1))
        if 1 <= n <= len(sources):
            src = sources[n - 1]
            attrs = (f'data-text="{html.escape(src["text"], quote=True)}" '
                     f'data-url="{html.escape(src["url"] or "", quote=True)}"')
            return (f'<sup class="cite-ref"><a class="cite-link" href="#src-{n}" '
                    f'data-idx="{n}" {attrs}>{n}</a></sup>')
        return f'<sup class="cite-ref"><a class="cite-link missing" data-idx="{n}">{n}</a></sup>'

    # Callouts first, on the raw body -- _embed_runs (next) inserts blank
    # lines around a block embed's placeholder, and a blank line with no
    # leading `>` ends a blockquote right there, splitting a callout that
    # has an embed in it into three pieces. See _callout_sub's own note for
    # why extracting a callout's content up front, before that split can
    # happen, sidesteps the problem entirely rather than working around it.
    body = _callout_sub(body, stash, on_wiki, used)

    text, embed_used = _embed_runs(body, stash)
    used.extend(embed_used)

    # inline, so it must survive markdown; stash these too. Skipping fences
    # so a literal [[...]]/[^N]/bare URL inside a code sample (a Mermaid
    # [[Subroutine]] node, most concretely) isn't corrupted -- see _FENCE_RE.
    text = _skip_fences(text, WIKI_RE, lambda m: stash(on_wiki(m)))
    text = _skip_fences(text, CITE_RE, lambda m: stash(on_cite(m)))
    text = _skip_fences(text, URL_LINE_RE,
                         lambda m: "\n\n" + stash(_bookmark_html(m.group(1))) + "\n\n")

    out = _unwrap_placeholder_p(_EXTERNAL_LINK_RE.sub(_open_externally, md.render(text)))

    # Highest index first: a callout's own fragment can itself still contain
    # an embed or wikilink placeholder verbatim (stashed earlier, at a lower
    # index, then carried through untouched by the callout's own nested
    # md.render() -- see _callout_html). Substituting low-to-high would
    # revisit index 0 before the callout at, say, index 5 ever exposes it in
    # `out`, leaving the placeholder token as literal visible text. Every
    # nested placeholder's index is guaranteed lower than its container's,
    # since stash() only ever appends, so one high-to-low pass resolves any
    # depth of nesting in a single pass.
    for i in range(len(blocks) - 1, -1, -1):
        out = out.replace(PLACEHOLDER.format(i), blocks[i])
    return out, targets, used
