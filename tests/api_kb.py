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
ck("a wikilink to an article with a number becomes a link to that number",
   "kb_view.do?sysparm_article=KB0009876" in h)
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
   "kb_view.do" not in plain["content"])

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

print(f"\n  {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
