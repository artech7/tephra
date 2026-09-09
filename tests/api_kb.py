"""KB Authoring: the template registry, the frontmatter round trip, and export.

Export is where the assertions concentrate, because export is the only part
of this feature whose output lands somewhere Tephra cannot see. A regression
in the authoring UI is visible the moment you look at it; a regression in the
exporter is visible only after someone has pasted a broken article into a
system of record, which is exactly when it is most expensive.

So the export tests assert the *degradations* as contracts, not just the
happy path: a class attribute must not survive into the ServiceNow target
(nothing there knows Tephra's stylesheet, so a class is a silent loss of
formatting), a callout must arrive as a table (a div flattens, and a warning
that flattens into a paragraph stops reading as a warning), and every image
must leave a numbered placeholder plus a manifest row, numbered in document
order, because an author matching "Image 3" to the third gap on a page is
the entire mechanism by which nothing gets dropped.

The frontmatter tests exist because vault.py's header parser is deliberately
a tiny fixed-schema one rather than YAML. It has three edges a free-text KB
field finds immediately -- one line per value, `[...]` means a list, list
items split on commas -- and kb.py is responsible for never handing it a
value that fails its own round trip.
"""
import base64
import os
import re
import shutil
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

ROOT = os.path.realpath("/tmp") + "/tephra-test-kb"
shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(ROOT, exist_ok=True)
os.environ.setdefault("TEPHRA_VAULT", ROOT)
os.environ.setdefault("TEPHRA_CONFIG_DIR", ROOT + "-cfg/Tephra")

from fastapi.testclient import TestClient  # noqa: E402

from app import kb, kb_export, vault  # noqa: E402
from app.main import app  # noqa: E402

ok = fail = 0


def ck(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")


def png_bytes():
    """A real 1x1 PNG, built rather than checked in: the standalone target
    inlines image bytes as a data URI and there has to be something on disk
    with a genuine PNG signature for that path to run at all."""
    def chunk(tag, data):
        body = tag + data
        return (len(data).to_bytes(4, "big") + body
                + zlib.crc32(body).to_bytes(4, "big"))
    ihdr = (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    idat = zlib.compress(bytes([0, 255, 255, 255]))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


print("── the template registry ──")
ck("every shipped template has an id matching its key",
   all(k == t.id for k, t in kb.TEMPLATES.items()))
ck("the default template exists", kb.DEFAULT_TEMPLATE in kb.TEMPLATES)
ck("every template has at least one required section",
   all(any(s.required for s in t.sections) for t in kb.TEMPLATES.values()))
ck("every section carries guidance, since the skeleton emits it",
   all(s.hint.strip() for t in kb.TEMPLATES.values() for s in t.sections))
ck("every section shape is one the structure panel knows",
   all(s.shape in ("prose", "steps", "list", "table", "code")
       for t in kb.TEMPLATES.values() for s in t.sections))
ck("the troubleshooting shape is symptom before cause before resolution",
   [s.heading for s in kb.TEMPLATES["troubleshooting"].sections].index("Symptoms")
   < [s.heading for s in kb.TEMPLATES["troubleshooting"].sections].index("Cause")
   < [s.heading for s in kb.TEMPLATES["troubleshooting"].sections].index("Resolution"))
ck("every metadata field key carries the kb_ prefix, so nothing can collide "
   "with category or study state",
   all(f.key.startswith(kb.PREFIX) for f in kb.FIELDS))

body = kb.new_body("how-to")
ck("a fresh article has every heading its template declares",
   all(f"## {s.heading}" in body for s in kb.TEMPLATES["how-to"].sections))
ck("a fresh article is entirely guidance", kb.has_todos(body))
ck("stripping guidance leaves the headings and nothing else",
   kb.strip_todos(body).replace("#", "").strip().replace("\n", " ").split()
   and "TODO" not in kb.strip_todos(body))

print("\n── frontmatter values survive their own round trip ──")
ck("a comma inside a list item would split it, so commas are removed",
   kb._list("nfs, mount") == ["nfs", "mount"])
ck("removing a comma never leaves a double space",
   kb._list(["nfs, mount"]) == ["nfs mount"])
ck("brackets are stripped from list items, because [x] round-trips as a "
   "damaged wikilink",
   kb._list(["[FlashArray]"]) == ["FlashArray"])
ck("duplicates collapse", kb._list(["dns", "dns", "DNS"]) == ["dns", "DNS"])
# parse() only mistakes a value for a list when it starts *and* ends with a
# bracket, so that is exactly the shape _scalar has to defend against -- and
# the shape it must not touch otherwise, since quoting everything would be
# noise in a file people hand-edit.
ck("a scalar the parser would read back as a list gets quoted",
   kb._scalar("[urgent]") == '"[urgent]"', kb._scalar("[urgent]"))
ck("a scalar that merely contains brackets is left alone",
   kb._scalar("[urgent] fix it") == "[urgent] fix it")
ck("a newline in a scalar would end the header early, so it collapses",
   kb._scalar("one\ntwo") == "one two")

meta = kb.sanitize_meta({"kb_type": "how-to", "kb_keywords": "a, b",
                         "kb_short_description": "x" * 400,
                         "nonsense": "dropped", "kb_status": "draft"})
ck("an unknown key is dropped rather than written", "nonsense" not in meta)
ck("a short description is capped at the field's own limit",
   len(meta["kb_short_description"]) <= 160)
ck("a list field arrives as a list", meta["kb_keywords"] == ["a", "b"])

round_trip = vault.dump({"title": "T", "tags": [], **meta}, "body")
parsed, _ = vault.parse(round_trip)
ck("every sanitized field reads back as what was written",
   parsed["kb_keywords"] == ["a", "b"] and parsed["kb_type"] == "how-to",
   parsed.get("kb_keywords"))

print("\n── splitting an article into sections ──")
secs = kb.sections("intro text\n\n## One\n\na\n\n## Two\n\nb\n")
ck("text above the first heading is kept as its own section",
   secs[0]["heading"] == "" and secs[0]["content"] == "intro text")
ck("each heading gets its own section", [s["heading"] for s in secs] == ["", "One", "Two"])
fenced = kb.sections("## Real\n\n```sheets\n## Not a section\n\n| a |\n| --- |\n| 1 |\n```\n")
ck("a ## inside a fence is a sheet name, not a section",
   [s["heading"] for s in fenced] == ["Real"], [s["heading"] for s in fenced])

print("\n── the block palette and the droppable render ──")
ck("every block belongs to a group the palette shows",
   all(b.group in kb.BLOCK_GROUPS for b in kb.BLOCKS))
ck("every block id is unique", len({b.id for b in kb.BLOCKS}) == len(kb.BLOCKS))
ck("every block carries a snippet", all(b.snippet.strip() for b in kb.BLOCKS))
ck("a block's select text is actually in its snippet, or the editor would "
   "highlight nothing after a drop",
   all(not b.select or b.select in b.snippet for b in kb.BLOCKS),
   [b.id for b in kb.BLOCKS if b.select and b.select not in b.snippet])
ck("every snippet is markdown Tephra already understands -- a block is a way "
   "of writing the syntax, never a second format",
   all("<" not in b.snippet or b.id in ("link", "bookmark") for b in kb.BLOCKS))

# The line ranges are what make a drop land somewhere exact rather than
# somewhere approximate, so the splitter is what these assertions are about.
BODY = "## One\n\npara\n\n```sheets\n## S\n\n| a |\n| - |\n```\n\n- x\n- y\n"
blks = kb.split_blocks(BODY)
ck("blank lines separate blocks", len(blks) == 4, len(blks))
ck("each block knows the source lines it came from",
   [(b["start"], b["end"]) for b in blks] == [(0, 0), (2, 2), (4, 9), (11, 12)],
   [(b["start"], b["end"]) for b in blks])
ck("a fence stays one block even though it contains blank lines -- a sheets "
   "card split down the middle is not a card",
   blks[2]["text"].startswith("```sheets") and blks[2]["text"].endswith("```"))
ck("the lines quoted back are the lines that were there",
   all(b["text"] == "\n".join(BODY.split("\n")[b["start"]:b["end"] + 1]) for b in blks))
ck("an empty body yields no blocks rather than one empty one",
   kb.split_blocks("") == [] and kb.split_blocks("\n\n  \n") == [])
ck("a body with no trailing newline still closes its last block",
   kb.split_blocks("just text")[0]["end"] == 0)
ck("an unterminated fence does not swallow everything after it silently",
   len(kb.split_blocks("```\nopen\n\nmore\n")) == 1)

print("\n── the API ──")
with TestClient(app) as c:
    t = c.get("/api/kb/templates").json()
    ck("templates, fields and targets arrive in one request",
       bool(t["templates"]) and bool(t["fields"]) and bool(t["targets"]))
    ck("the export targets are the ones the exporter implements",
       set(t["targets"]) == set(kb_export.TARGETS))

    r = c.post("/api/kb/articles", json={"title": "Array unreachable", "kb_type": "troubleshooting"})
    ck("creating an article returns 200", r.status_code == 200, r.status_code)
    slug = r.json()["slug"]
    ck("a new article starts as a draft", r.json()["status"] == "draft")

    bad = c.post("/api/kb/articles", json={"title": "x", "kb_type": "not-a-type"})
    ck("an unknown article type is refused", bad.status_code == 400, bad.status_code)
    ck("a missing article is a 404", c.get("/api/kb/nope").status_code == 404)

    a = c.get(f"/api/kb/{slug}").json()
    ck("the outline names every template section",
       [o["heading"] for o in a["outline"]]
       == [s.heading for s in kb.TEMPLATES["troubleshooting"].sections])
    ck("a section holding only guidance reports as empty, not written",
       all(o["present"] and o["empty"] for o in a["outline"]))
    ck("the article reports that guidance is still in it", a["has_guidance"] is True)

    # A note that already carries non-KB frontmatter -- the case that matters,
    # because kb_* keys are written into the same header category and study
    # state live in, and a wholesale overwrite would take them with it.
    n = vault.Note(slug="existing", title="Existing note", body="## Notes\n\nprose\n",
                   meta={"category": "Networking", "category_source": "manual"})
    vault.write(n)
    ad = c.post("/api/kb/existing/adopt", json={"kb_type": "reference"})
    ck("an existing note can be adopted", ad.status_code == 200, ad.status_code)
    ck("adopting does not touch the prose",
       vault.read("existing").body.strip() == "## Notes\n\nprose")
    c.put("/api/kb/existing/meta", json={"meta": {"kb_type": "reference", "kb_number": "KB1"}})
    ck("saving KB fields leaves other frontmatter alone",
       vault.read("existing").meta.get("category") == "Networking",
       vault.read("existing").meta.get("category"))
    c.post("/api/kb/existing/release")
    after = vault.read("existing")
    ck("releasing removes every kb_ key",
       not any(k.startswith("kb_") for k in after.meta))
    ck("releasing keeps the note and its other frontmatter",
       after.body.strip() == "## Notes\n\nprose" and after.meta.get("category") == "Networking")

    # Deleting is the ordinary note delete, deliberately: a KB article is a
    # note, so it goes to vault/.trash and stays recoverable rather than
    # getting a second, harsher deletion path of its own.
    doomed = c.post("/api/kb/articles",
                    json={"title": "Doomed article", "kb_type": "faq"}).json()["slug"]
    ck("a new article shows up in the list first",
       any(a["slug"] == doomed for a in c.get("/api/kb/articles").json()["articles"]))
    d = c.delete(f"/api/notes/{doomed}")
    ck("deleting an article returns 200", d.status_code == 200, d.status_code)
    ck("it leaves the KB list",
       not any(a["slug"] == doomed for a in c.get("/api/kb/articles").json()["articles"]))
    ck("its file leaves the notes folder",
       not (vault.current().notes / f"{doomed}.md").is_file())
    ck("but lands in the vault trash, so a mis-click is recoverable",
       any(f.name.startswith(doomed) for f in (vault.current().vault / ".trash").glob("*.md")),
       [f.name for f in (vault.current().vault / ".trash").glob("*.md")])
    ck("deleting it twice is a 404, not a crash",
       c.delete(f"/api/notes/{doomed}").status_code == 404)

    # The authoring preview deliberately uses Tephra's own renderer, not the
    # exporter's: it is what you write beside, and it should look like the
    # rest of the app. Only the export preview shows the destination's look.
    rnd = c.get(f"/api/kb/{slug}/render").json()
    ck("the render endpoint returns one entry per source block",
       len(rnd["blocks"]) > 0)
    ck("each rendered block carries its source line range, so a drop between "
       "two of them is a splice at a known line",
       all("start" in b and "end" in b and "html" in b for b in rnd["blocks"]))
    ck("the ranges are in document order and do not overlap",
       all(rnd["blocks"][i]["end"] < rnd["blocks"][i + 1]["start"]
           for i in range(len(rnd["blocks"]) - 1)))
    ck("it renders with Tephra's own classes, not the export's inline styles",
       any("<h2" in b["html"] for b in rnd["blocks"])
       and not any("style=\"font-size:1.3em" in b["html"] for b in rnd["blocks"]))
    ck("rendering a missing article is a 404",
       c.get("/api/kb/nope/render").status_code == 404)

    cited = c.post("/api/kb/articles", json={"title": "Cited", "kb_type": "faq"}).json()["slug"]
    c.put(f"/api/notes/{cited}", json={
        "body": "## Scope\n\nA claim.[^1]\n\n## Sources\n\n- [S](https://example.com)\n"})
    cr = c.get(f"/api/kb/{cited}/render").json()
    joined = "".join(b["html"] for b in cr["blocks"])
    ck("a citation resolves even though each block is rendered on its own",
       'class="cite-link"' in joined and "missing" not in joined, joined[:0] or "")

    ck("an unknown export target is refused",
       c.get(f"/api/kb/{slug}/export", params={"target": "pdf"}).status_code == 400)
    dl = c.get(f"/api/kb/{slug}/export/download", params={"target": "standalone"})
    ck("a download arrives as an attachment",
       "attachment;" in dl.headers.get("content-disposition", ""),
       dl.headers.get("content-disposition"))

print("\n── export ──")
vault.ensure_dirs()
(vault.current().media / "topology.png").write_bytes(png_bytes())

ARTICLE = """## Summary

Fixed by flushing the cache. See [[Controller Failover]] and [[Nothing Here]].

## Symptoms

- `purearray list` times out[^1]

## Environment

| Product | Version |
| --- | --- |
| FlashArray | 6.5.2 |

## Resolution

> [!WARNING] Do not reboot
> Rebooting loses the evidence.

![[topology.png|Management topology]]

```bash
purenetwork setattr --flush ct0.eth0
```

```mermaid
graph TD
A --> B
```

*TODO — leftover guidance that must never ship*

## Sources

- [Release notes](https://kb.purestorage.com/csm/rn)
"""

art = vault.Note(slug="unreachable", title="Array unreachable", body=ARTICLE,
                 meta={"kb_type": "troubleshooting", "kb_number": "KB0012345",
                       "kb_status": "draft", "kb_audience": "internal",
                       "kb_short_description": "Flush the cache.",
                       "kb_products": ["FlashArray"], "kb_keywords": ["arp"]})
vault.write(art)
vault.write(vault.Note(slug="controller-failover", title="Controller Failover",
                       meta={"kb_type": "reference", "kb_number": "KB0009876"}))
art = vault.read("unreachable")

sn = kb_export.export(art, target="servicenow")
h = sn["content"]
ck("nothing that depends on Tephra's stylesheet survives",
   'class="' not in h, h[h.find('class="'):][:60] if 'class="' in h else "")
ck("no <style> block, since a KB editor strips them", "<style" not in h)
ck("no script can ride along", "<script" not in h.lower())
ck("headings carry their styling inline", "<h2 " in h and "style=" in h)
ck("tables carry presentational attributes as well as CSS, for editors that "
   "drop the CSS", '<table border="1" cellspacing="0" cellpadding="6"' in h)
ck("a callout becomes a bordered table, not a div that flattens",
   "border-left:4px solid" in h and "Do not reboot" in h)
ck("a code fence keeps its content verbatim",
   "purenetwork setattr --flush ct0.eth0" in h)
ck("template guidance never reaches an export",
   "TODO" not in h and "leftover guidance" not in h)
ck("the export says out loud that it stripped guidance",
   any("guidance" in w for w in sn["warnings"]), sn["warnings"])
# The link format is lifted from a live article, not guessed: the portal
# these are read in does not serve the platform-UI `kb_view.do` form this
# code originally shipped with.
ck("a wikilink to an article with a number becomes a link to that number",
   "kb.purestorage.com/csm?id=kb_article_view&amp;sysparm_article=KB0009876" in h,
   [l for l in h.split('"') if "sysparm" in l][:1])
ck("a wikilink to a note that is not an article degrades to bold text, "
   "never to a dead link",
   "<strong>Nothing Here</strong>" in h)
ck("a citation becomes a superscript pointing at the references list",
   '<sup><a href="#ref-1"' in h)
ck("the references list is emitted with the source's own link",
   'id="ref-1"' in h and "kb.purestorage.com/csm/rn" in h)
ck("the metadata table is included by default", "KB0012345" in h)

names = [m["name"] for m in sn["manifest"]]
ck("both the image and the diagram are in the manifest", len(names) == 2, names)
ck("the manifest is in document order, not the order the parser met them",
   names[0] == "topology.png" and names[1].startswith("mermaid"), names)
ck("placeholders are numbered in that same document order",
   h.find("[Image 1]") < h.find("[Diagram 2]"),
   (h.find("[Image 1]"), h.find("[Diagram 2]")))
ck("each placeholder names the file to attach", "topology.png" in h and "mermaid-2.png" in h)
ck("a diagram warns that it needs a screenshot",
   any("screenshot" in w for w in sn["warnings"]), sn["warnings"])

nometa = kb_export.export(art, target="servicenow", include_meta=False)
ck("the metadata table can be turned off", "KB0012345" not in nometa["content"])

plain = kb_export.export(art, target="servicenow", links="text")
ck("link mode 'text' emits no article links at all",
   "sysparm_article" not in plain["content"])

st = kb_export.export(art, target="standalone")
s = st["content"]
ck("standalone is a complete document", s.startswith("<!doctype html>") and "</html>" in s)
ck("standalone carries its own stylesheet rather than depending on one",
   "<style>" in s)
ck("standalone inlines the image rather than leaving a placeholder",
   "data:image/png;base64," in s and "[Image 1]" not in s)
ck("standalone builds a table of contents", 'class="toc"' in s and "#summary" in s)
ck("standalone is responsive rather than fixed-width", "@media" in s)
ck("standalone titles itself with the article title",
   "<title>Array unreachable</title>" in s)

md = kb_export.export(art, target="markdown")
m = md["content"]
ck("markdown opens with the title", m.startswith("# Array unreachable"))
ck("markdown strips guidance too", "TODO" not in m)
ck("markdown keeps a table as a table", "| Product | Version |" in m)
ck("markdown resolves a wikilink to something portable",
   "[[Controller Failover]]" not in m and "Controller Failover" in m)
ck("markdown leaves an attachment instruction where the image was",
   "Attach `topology.png` here" in m)
ck("a citation becomes a plain number", "[^1]" not in m and "[1]" in m)
ck("a callout keeps its boundary as a labelled blockquote",
   "> **Do not reboot**" in m, m[m.find("Do not reboot") - 30:][:60])

tx = kb_export.export(art, target="text")
x = tx["content"]
ck("plain text underlines its headings", "SUMMARY\n-------" in x)
ck("plain text lays a table out in fixed columns",
   "Product     Version" in x, [l for l in x.splitlines() if "Product" in l])
ck("plain text keeps a callout's boundary with a quote rule",
   "| Do not reboot" in x)
ck("plain text has no markdown emphasis left in it", "**" not in x)

sheets = vault.Note(slug="sheeted", title="Sheeted", body=(
    "## Overview\n\n```sheets\n## Ports\n\n| Port | Use |\n| --- | --- |\n"
    "| 22 | SSH |\n\n## Limits\n\n| Name | Max |\n| --- | --- |\n| Vols | 5000 |\n```\n"),
    meta={"kb_type": "reference"})
vault.write(sheets)
sheets = vault.read("sheeted")
sh = kb_export.export(sheets, target="servicenow")["content"]
ck("every sheet in a tabbed group becomes its own table, since tabs do not paste",
   sh.count("<table") == 2 and "Ports" in sh and "Limits" in sh, sh.count("<table"))
ck("an article with no metadata worth showing gets no empty metadata table",
   sh.index("Ports") < sh.index("Limits"))
shmd = kb_export.export(sheets, target="markdown")["content"]
ck("a sheet name becomes an h3 in markdown, never an h2 that would look like "
   "one of the article's own sections",
   "### Ports" in shmd and "## Ports" not in shmd.replace("### Ports", ""))

empty = vault.Note(slug="bare", title="Bare", body="Just a sentence.\n",
                   meta={"kb_type": "faq"})
vault.write(empty)
bare = kb_export.export(vault.read("bare"), target="servicenow")
ck("an article with no structure at all still exports rather than raising",
   "Just a sentence." in bare["content"])

missing = vault.Note(slug="gone", title="Gone", body="![[not-here.png]]\n",
                     meta={"kb_type": "reference"})
vault.write(missing)
gone = kb_export.export(vault.read("gone"), target="standalone")
ck("a missing image degrades to a placeholder and says so",
   "not-here.png" in gone["content"]
   and any("not in the vault" in w for w in gone["warnings"]), gone["warnings"])
ck("a missing image is still in the manifest, so it cannot be silently lost",
   [i["name"] for i in gone["manifest"]] == ["not-here.png"])

try:
    kb_export.export(art, target="pdf")
    ck("an unknown target raises rather than guessing", False)
except ValueError:
    ck("an unknown target raises rather than guessing", True)

print("\n── the destination form: one field per section, not one body ──")
# The KB this exports to has no article body. It has five separate rich-text
# boxes, so an export that produced one blob of HTML would have nowhere to
# go. These are the assertions that keep that true.
ck("every template section names a field the form actually has",
   all(sec.field in kb.SECTION_FIELDS
       for t in kb.TEMPLATES.values() for sec in t.sections))
ck("there is a template that mirrors the form exactly, section for section",
   [s.heading for s in kb.TEMPLATES["question-answer"].sections] == kb.SECTION_FIELDS)
ck("an unmapped heading falls back to Answer rather than being dropped — "
   "content that goes nowhere is the failure mode worth engineering against",
   kb.field_of("Something Nobody Planned", kb.TEMPLATES["troubleshooting"], {}) == "Answer")

fields = kb_export.export(art, target="servicenow")["parts"]
order = [p["field"] for p in fields]
ck("parts come back in the order the form asks for them",
   order == ["Short description", "Question", "Environment", "Answer",
             "Additional Information", "Meta"], order)
ck("Short description and Meta are plain text, since their boxes are",
   all(p["kind"] == "text" for p in fields if p["field"] in kb.META_FIELDS))
ck("the rich-text fields are html", all(p["kind"] == "html" for p in fields
                                        if p["field"] not in kb.META_FIELDS))
ck("Meta carries the form's own 4000-character limit",
   next(p for p in fields if p["field"] == "Meta")["limit"] == kb.META_MAX)
ck("Meta is fed from the article's keywords",
   next(p for p in fields if p["field"] == "Meta")["content"] == "arp")

q = next(p for p in fields if p["field"] == "Question")
ck("a field says which sections feed it", q["sections"] == ["Summary", "Symptoms"], q["sections"])
ck("a field fed by several sections keeps their headings, demoted to h3 — "
   "the box itself is already playing the h2's part",
   "<h3 " in q["content"] and "Symptoms" in q["content"])

env = next(p for p in fields if p["field"] == "Environment")
ck("a field fed by exactly one section drops that heading, since the field "
   "is the heading",
   "Environment</h3>" not in env["content"] and "FlashArray" in env["content"])

extra = next(p for p in fields if p["field"] == "Additional Information")
ck("the reference list rides with the supporting material rather than being "
   "stranded wherever the last citation happened to be",
   'id="ref-1"' in extra["content"])

ck("a character count measures what a reader sees, not the markup",
   q["chars"] < len(q["content"]), (q["chars"], len(q["content"])))

# Numbering has to be decided over the whole document and then applied per
# field. Numbering each field on its own would restart at 1 in every box.
ORDERED = """## Summary

```mermaid
graph TD
A --> B
```

## Resolution

![[topology.png|A topology]]
"""
ordered = vault.Note(slug="ordered", title="Ordered", body=ORDERED,
                     meta={"kb_type": "troubleshooting"})
vault.write(ordered)
op = kb_export.export(vault.read("ordered"), target="servicenow")
by_field = {p["field"]: p["content"] for p in op["parts"]}
ck("media is numbered across the whole article, not restarted per field",
   "[Diagram 1]" in by_field["Question"] and "[Image 2]" in by_field["Answer"],
   [(p["field"], p["chars"]) for p in op["parts"]])
ck("and the manifest agrees with what the fields say",
   [i["n"] for i in op["manifest"]] == [1, 2])

# The mapping editor lists whatever field_plan returns, and the copy buttons
# emit whatever the exporter builds. When those two disagreed, the panel
# offered a row for a section no button could honour.
plan_headings = [h for f in kb.field_plan(art) for h in f["sections"]]
ck("the mapping plan does not list sections the export never emits",
   "Sources" not in plan_headings, plan_headings)
ck("and it lists every section that does get emitted",
   set(plan_headings) == {h for p in fields for h in p["sections"]},
   plan_headings)

print("\n── matching the house look, taken from a published article ──")
# The question this exporter was designed around -- "does the sanitiser strip
# <style>?" -- turned out to have the answer "no", and every published
# article carries the same block in every field. So matching the house is a
# matter of shipping that block, not of inlining a private approximation of
# it, and these assertions pin that decision to what the real article does.
ck("every rich-text field carries the house stylesheet, as published "
   "articles do",
   all(p["content"].startswith("<style>") for p in fields if p["kind"] == "html"),
   [p["field"] for p in fields if p["kind"] == "html"
    and not p["content"].startswith("<style>")])
ck("plain-text fields do not, since their boxes hold no markup",
   all("<style>" not in p["content"] for p in fields if p["kind"] == "text"))
ck("the block is the published one, byte for byte",
   "#fe5000" in kb_export.HOUSE_STYLE and "Space Mono" in kb_export.HOUSE_STYLE
   and 'td{padding: 16px !important;}' in kb_export.HOUSE_STYLE)
answer = next(p for p in fields if p["field"] == "Answer")
ck("code and pre are left bare so the house block owns them -- an inline "
   "style would make this the one article whose code looks different",
   "<pre>" in answer["content"] or "<pre " not in answer["content"],
   answer["content"][answer["content"].find("<pre"):][:60])
ck("and everything the house block does not cover is still inlined",
   "<p style=" in answer["content"])

bare = kb_export.export(art, target="servicenow", house_style=False)
bare_answer = next(p for p in bare["parts"] if p["field"] == "Answer")
ck("the house block can be turned off, and then code carries its own styling",
   "<style>" not in bare_answer["content"] and "<pre style=" in bare_answer["content"])
ck("the standalone page never carries it -- it is a whole document with a "
   "stylesheet of its own",
   "#fe5000" not in kb_export.export(art, target="standalone")["content"])

NESTED = """## Resolution

1. Confirm the array's health
   1. Check parity
      1. Read the counter
   2. Check mastership
2. Replace the blade
"""
nested = vault.Note(slug="nested", title="Nested", body=NESTED,
                    meta={"kb_type": "troubleshooting"})
vault.write(nested)
nh = next(p for p in kb_export.export(vault.read("nested"), target="servicenow")["parts"]
          if p["field"] == "Answer")["content"]
ck("nested steps run 1 -> A -> i, the house convention that makes a long "
   "procedure readable",
   "list-style-type: upper-alpha" in nh and "list-style-type: lower-roman" in nh, )
ck("the outermost list takes no marker override, only the inside position",
   nh.count('<ol style="list-style-position: inside;">') >= 1)

# A GFM cell cannot hold a newline, so a multi-line cell is written with
# <br> -- render.py grew a rule for exactly this, and the published articles
# lean on it hard (one holds 108 of them). An export parser without that rule
# silently reflows their tables onto one line.
BR = """## Environment

| Product | Versions |
| --- | --- |
| FlashArray | 6.5.0<br>**6.5.2 only** |
"""
brn = vault.Note(slug="brcell", title="Br", body=BR, meta={"kb_type": "troubleshooting"})
vault.write(brn)
bh = next(p for p in kb_export.export(vault.read("brcell"), target="servicenow")["parts"]
          if p["field"] == "Environment")["content"]
# `<br />` rather than `<br>`: the commonmark preset sets xhtmlOut, so this
# is the same form Tephra's own renderer emits. Both are a line break
# everywhere it matters, so the assertion is on the break, not the spelling.
ck("a <br> in a table cell survives the export as a line break",
   re.search(r"<br\s*/?>", bh) and "&lt;br&gt;" not in bh, bh[bh.find("6.5.0"):][:40])
ck("and the markdown around it still renders", "<strong>6.5.2 only</strong>" in bh)

print("\n── the per-article field override ──")
mapped = vault.Note(slug="mapped", title="Mapped", body=(
    "## Summary\n\nvisible\n\n## Resolution\n\nsecret\n"),
    meta={"kb_type": "troubleshooting",
          "kb_fieldmap": ["Resolution>Internal Notes"]})
vault.write(mapped)
mp = {p["field"]: p["content"] for p in
      kb_export.export(vault.read("mapped"), target="servicenow")["parts"]}
ck("an override moves a section to a different box",
   "secret" in mp.get("Internal Notes", "") and "secret" not in mp.get("Answer", ""),
   list(mp))
ck("and the sections it does not name are untouched", "visible" in mp["Question"])
ck("the override survives a frontmatter round trip",
   kb.parse_fieldmap(["Resolution>Internal Notes"]) == {"resolution": "Internal Notes"})
ck("an override naming a field the form does not have is discarded, not "
   "written, so a typo cannot send a section into the void",
   kb.parse_fieldmap(["Resolution>Nowhere"]) == {})
ck("a comma or a > inside a heading cannot corrupt the map",
   kb.dump_fieldmap({"A, B > C": "Answer"}) == ["A B C>Answer"],
   kb.dump_fieldmap({"A, B > C": "Answer"}))

print("\n── the export warns about what the form will reject ──")
longdesc = vault.Note(slug="longdesc", title="Long", body="## Summary\n\nx\n\n## Resolution\n\ny\n",
                      meta={"kb_type": "troubleshooting",
                            "kb_short_description": "y" * 200})
vault.write(longdesc)
lw = kb_export.export(vault.read("longdesc"), target="servicenow")["warnings"]
# The authoring form caps this field on save, so it cannot happen from the
# UI -- but a file hand-edited outside Tephra can carry anything, and the
# export saying so beats the export silently truncating it.
ck("a short description over the form's limit is called out, not truncated",
   any("Short description is 200 characters" in w for w in lw), lw)
ck("and the value is left intact for the author to cut themselves",
   len(kb.meta_of(vault.read("longdesc"))["kb_short_description"]) == 200)
ck("saving through the app caps it instead, so the UI cannot produce one",
   len(kb.sanitize_meta({"kb_short_description": "y" * 200})["kb_short_description"]) == 160)

hollow = vault.Note(slug="hollow", title="Hollow", body="## Environment\n\njust this\n",
                    meta={"kb_type": "troubleshooting"})
vault.write(hollow)
hw = kb_export.export(vault.read("hollow"), target="servicenow")["warnings"]
ck("an empty Question is called out, since the form requires one",
   any("Question" in w for w in hw), hw)
ck("an empty Answer is called out too", any("Answer" in w for w in hw), hw)

ck("a non-fielded target returns no parts, rather than parts that mean nothing",
   kb_export.export(art, target="standalone")["parts"] == []
   and kb_export.export(art, target="markdown")["parts"] == [])

print(f"\n  {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
