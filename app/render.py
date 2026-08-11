"""
Markdown -> HTML, with the three syntaxes that make this a wiki rather than
a folder of documents:

    [[Note Title]]          a link; renders orange if the note doesn't exist
    [[Note Title|shown]]    same, with display text
    ![[picture.png]]        an embed, resolved to img/video/audio/file by extension
    ![[picture.png|400]]    an embed sized to 400px wide (or |50% of the column)
    ![[picture.png|caption|400]]   caption and size together

A bare URL alone on a line becomes a bookmark card. That is deliberate:
pasting a link is the most common thing anyone does in a notes app, and it
should not require syntax.

Embeds placed on adjacent lines with no blank line between them render as a
row rather than stacked -- the same "no new syntax" instinct as the size
spec above. A blank line between two embeds keeps today's stacked layout.
"""
from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt

from . import vault
from .index import EMBED_RE, WIKI_RE

md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False})
md.enable("table")
md.enable("strikethrough")

URL_LINE_RE = re.compile(r"^\s*(https?://\S+)\s*$", re.M)
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
    view_link = (f'<a class="embed-view" href="{url}" target="_blank" rel="noopener" '
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


def _bookmark_html(url: str) -> str:
    safe = html.escape(url, quote=True)
    host = re.sub(r"^www\.", "", url.split("/")[2]) if "//" in url else url
    letter = html.escape(host[:1].upper() or "?")
    path = url.split("/", 3)[3] if url.count("/") > 2 else ""
    return (f'<a class="bookmark g2" href="{safe}" target="_blank" rel="noopener">'
            f'<span class="favicon">{letter}</span>'
            f'<span class="bk-body"><span class="bk-t">{html.escape(host)}</span>'
            f'<span class="bk-u">{html.escape(path[:90] or url)}</span></span></a>')


def render(body: str, resolve) -> tuple[str, list[str], list[str]]:
    """resolve(title) -> slug|None. Returns (html, link_targets, embed_names).

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

    text, embed_used = _embed_runs(body, stash)
    used.extend(embed_used)

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

    # inline, so it must survive markdown; stash these too
    text = WIKI_RE.sub(lambda m: stash(on_wiki(m)), text)
    text = URL_LINE_RE.sub(lambda m: "\n\n" + stash(_bookmark_html(m.group(1))) + "\n\n",
                           text)

    out = _EXTERNAL_LINK_RE.sub(_open_externally, md.render(text))

    # Unwrap the <p> markdown puts around a block-level placeholder before
    # substituting, while the token is still a single predictable word.
    out = re.sub(r"<p>\s*(" + PLACEHOLDER.replace("{}", r"\d+") + r")\s*</p>",
                 r"\1", out)
    for i, frag in enumerate(blocks):
        out = out.replace(PLACEHOLDER.format(i), frag)
    return out, targets, used
