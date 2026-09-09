"""The ```sheets fence: rendering, and the column widths in its delimiter row.

The fence had no suite of its own -- it shipped covered only incidentally,
by api_dedupe.py happening to use one as fixture text. This covers the part
that actually has rules: a cell's markdown goes through the same wikilink and
embed pass as the rest of the note (that's the whole reason render.py renders
these tables rather than handing them to the frontend), and a column's width
is the dash count in the delimiter row.

The width format is deliberately invisible to other markdown renderers --
dash count carries no meaning in GFM beyond "at least one" -- so the tests
that matter most are the ones proving an ordinary `| --- |` table still
renders exactly as it did before widths existed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from app.render import _colgroup, _sheet_widths, _split_row  # noqa: E402
from app import render  # noqa: E402

ok = fail = 0


def ck(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


def d(n):
    return "-" * n


def html(body, known=("some-note",)):
    """The note body rendered the way main.py renders it: render() takes a
    resolve(title) -> slug|None and returns (html, link_targets, embeds)."""
    def resolve(title):
        slug = title.strip().lower().replace(" ", "-")
        return slug if slug in known else None
    return render.render(body, resolve)[0]


print("── splitting a delimiter row ──")
ck("a plain row splits on pipes", _split_row("| a | b |") == ["a", "b"], _split_row("| a | b |"))
ck("outer pipes are optional", _split_row("a | b") == ["a", "b"])
ck("an escaped pipe stays inside its cell",
   _split_row(r"| [[Note\|shown]] | b |") == ["[[Note|shown]]", "b"],
   _split_row(r"| [[Note\|shown]] | b |"))
ck("an empty cell is preserved, not dropped",
   _split_row("| a |  | c |") == ["a", "", "c"], _split_row("| a |  | c |"))

print("\n── widths come off the delimiter row ──")
ck("the canonical three-dash form means unset",
   _sheet_widths("| A | B |\n| --- | --- |") == [None, None])
ck("a dash count above the unset threshold is a width",
   _sheet_widths(f"| A | B |\n| --- | {d(30)} |") == [None, 30],
   _sheet_widths(f"| A | B |\n| --- | {d(30)} |"))
ck("alignment colons do not count toward the width",
   _sheet_widths(f"| A |\n| :{d(24)}: |") == [24])
ck("a width under the floor clamps up", _sheet_widths(f"| A |\n| {d(4)} |") == [6])
ck("a width over the ceiling clamps down, so it cannot restore the old scroll",
   _sheet_widths(f"| A |\n| {d(400)} |") == [60])
ck("no table at all yields no widths", _sheet_widths("just prose") == [])
ck("prose above the table does not confuse the row search",
   _sheet_widths(f"Some text.\n\n| A |\n| {d(20)} |\n| 1 |") == [20])
ck("only the first delimiter row is read",
   _sheet_widths(f"| A |\n| {d(20)} |\n| 1 |\n\n| B |\n| {d(50)} |") == [20])

print("\n── the colgroup that carries them ──")
ck("an all-default table gets no colgroup at all", _colgroup([None, None]) == "")
ck("an empty width list gets no colgroup", _colgroup([]) == "")
ck("a set width becomes a ch-sized col",
   _colgroup([None, 30]) == '<colgroup><col><col style="width:30ch"></colgroup>',
   _colgroup([None, 30]))
ck("width is expressed in ch, not px -- the stored unit is characters",
   "ch" in _colgroup([20]) and "px" not in _colgroup([20]))

print("\n── rendering: an ordinary sheet is unchanged by any of this ──")
h = html("```sheets\n## Week 1\n\n| Day | Topic |\n| --- | --- |\n| Mon | Intro |\n```\n")
ck("the card renders", 'class="sheets' in h)
ck("the tab renders with the sheet name", "Week 1" in h and "sheet-tab" in h)
ck("a table is emitted", "<table>" in h)
ck("no colgroup is emitted for a default table", "<colgroup>" not in h, )
ck("the pane is left on auto layout", "sheet-fixed" not in h)

print("\n── rendering: a sheet with widths ──")
h2 = html(f"```sheets\n## W\n\n| Day | Topic |\n| --- | {d(30)} |\n| Mon | Intro |\n```\n")
ck("a colgroup is emitted", "<colgroup>" in h2)
ck("the colgroup sits immediately inside the table",
   "<table><colgroup>" in h2, h2[h2.find("<table>"):h2.find("<table>") + 60])
ck("the width lands on the right column",
   '<col><col style="width:30ch">' in h2)
ck("the pane is switched to fixed layout so the width actually holds",
   "sheet-fixed" in h2)
ck("cell text is unaffected", ">Mon<" in h2 and ">Intro<" in h2)

print("\n── a wikilink in a cell still reaches the link pass ──")
h3 = html("```sheets\n## W\n\n| Day | Topic |\n| --- | "
          + d(30) + " |\n| Mon | [[Some Note]] |\n```\n")
ck("the wikilink in a cell became a link, not literal brackets",
   "[[Some Note]]" not in h3 and "<a" in h3, )
ck("widths did not interfere with it", "<colgroup>" in h3)

print("\n── a multi-line cell, the shape every report generator emits ──")
# The reported case: a tool that writes one `<br>`-separated block per cell.
# The cell has to break onto several lines and still render its markdown.
h4 = html("```sheets\n## W\n\n| Check | Details |\n| --- | --- |\n"
          "| CatalystJobs | 3 jobs.<br><br>**ID** · **Start**<br>1 · 2026 |\n```\n")
ck("the <br>s became real line breaks inside the cell",
   "3 jobs.<br />" in h4 and "&lt;br&gt;" not in h4)
ck("markdown either side of a <br> still renders",
   "<strong>ID</strong>" in h4)

print(f"\n  {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
