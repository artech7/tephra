"""
Markdown -> HTML, with the three syntaxes that make this a wiki rather than
a folder of documents:

    [[Note Title]]          a link; renders orange if the note doesn't exist
    [[Note Title|shown]]    same, with display text
    ![[picture.png]]        an embed, resolved to img/video/audio/file by extension

A bare URL alone on a line becomes a bookmark card. That is deliberate:
pasting a link is the most common thing anyone does in a notes app, and it
should not require syntax.
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


def _embed_html(name: str, caption: str | None) -> str:
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
    return (f'<figure class="embed g2" data-kind="{kind}">'
            f'<div class="embed-media">{inner}</div>'
            f'<figcaption class="embed-cap"><span class="kind">{kind.upper()}</span>'
            f'{html.escape(name)}</figcaption></figure>')


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

    def on_embed(m):
        name = m.group(1).strip()
        used.append(name)
        return "\n\n" + stash(_embed_html(name, m.group(2))) + "\n\n"

    text = EMBED_RE.sub(on_embed, body)

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

    out = md.render(text)

    # Unwrap the <p> markdown puts around a block-level placeholder before
    # substituting, while the token is still a single predictable word.
    out = re.sub(r"<p>\s*(" + PLACEHOLDER.replace("{}", r"\d+") + r")\s*</p>",
                 r"\1", out)
    for i, frag in enumerate(blocks):
        out = out.replace(PLACEHOLDER.format(i), frag)
    return out, targets, used
