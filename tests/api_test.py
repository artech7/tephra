import os, io, json, re, shutil
VAULT = os.environ.setdefault("TEPHRA_VAULT", "/tmp/tephra-test")
shutil.rmtree(VAULT, ignore_errors=True)
from fastapi.testclient import TestClient
from app.main import app
from app import study as st

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  PASS  {label} {extra}")
    else:    fail += 1; print(f"  FAIL  {label} {extra}")

with TestClient(app) as c:
    print("\n── boot & seed ──")
    h = c.get("/api/health").json()
    check("health", h["ok"] and h["notes"] == 3, h)
    notes = c.get("/api/notes").json()
    check("seeded 3 notes", len(notes) == 3, [n["slug"] for n in notes])

    print("\n── render ──")
    n = c.get("/api/notes/welcome-to-tephra").json()
    check("wikilink resolved", 'class="wl" data-slug="linking-and-the-auto-wiki"' in n["html"])
    check("headings render", "<h2>" in n["html"])
    check("links_out counted", n["links_out"] >= 1, n["links_out"])

    print("\n── backlinks ──")
    b = c.get("/api/notes/linking-and-the-auto-wiki").json()["backlinks"]
    check("backlinks found", any(x["slug"] == "welcome-to-tephra" for x in b), [x["slug"] for x in b])
    check("excerpt present", all(x["excerpt"] for x in b))

    print("\n── create / autosave / persistence ──")
    new = c.post("/api/notes", json={"title": "Victron MultiPlus-II"}).json()
    check("created", new["slug"] == "victron-multiplus-ii", new["slug"])
    body = "Inverter notes. Ties into [[Welcome to Tephra]] and a missing [[Shunt Calibration]].\n"
    c.put(f"/api/notes/{new['slug']}", json={"body": body})
    disk = open(f"{VAULT}/notes/victron-multiplus-ii.md").read()
    check("written to disk", "Inverter notes" in disk)
    check("frontmatter intact", disk.startswith("---\ntitle: Victron MultiPlus-II"))
    re_read = c.get(f"/api/notes/{new['slug']}").json()
    check("pending link is amber", 'class="wl pending"' in re_read["html"])

    print("\n── stub resolution ──")
    r = c.post(f"/api/notes/{new['slug']}/resolve", json={"title": "Shunt Calibration"}).json()
    check("stub created", r["created"] and r["slug"] == "shunt-calibration", r)
    again = c.get(f"/api/notes/{new['slug']}").json()
    check("link now resolves", 'data-slug="shunt-calibration"' in again["html"])

    print("\n── rename repoints links ──")
    c.put("/api/notes/shunt-calibration", json={"title": "Shunt Wiring"})
    src = open(f"{VAULT}/notes/victron-multiplus-ii.md").read()
    check("wikilink rewritten in other note", "[[Shunt Wiring]]" in src, src.split("\n")[-2][:70])

    print("\n── media ──")
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000100" + "0" * 10)
    up = c.post("/api/media", files={"file": ("Busbar Layout.png", io.BytesIO(png), "image/png")}).json()
    check("uploaded + slugged", up["name"] == "busbar-layout.png" and up["kind"] == "image", up["name"])
    check("file on disk", os.path.isfile(f"{VAULT}/media/busbar-layout.png"))
    c.put(f"/api/notes/{new['slug']}", json={"body": body +
          "\n![[busbar-layout.png]]\n\nhttps://victronenergy.com/inverters\n\n"
          "See the [install guide](https://victronenergy.com/install) first.\n"})
    emb = c.get(f"/api/notes/{new['slug']}").json()["html"]
    check("image embedded", '<img src="/media/busbar-layout.png"' in emb)
    check("bare url -> bookmark", 'class="bookmark' in emb)
    check("media served", c.get("/media/busbar-layout.png").status_code == 200)

    print("\n── external links never trap navigation inside the app window ──")
    # No back button in the desktop build (one pywebview window, no browser
    # chrome) and no address bar in a kiosk-style browser tab either -- an
    # external link that navigates the app's own window away is a dead end
    # the user can only escape by closing Tephra. Every clickable external
    # link needs target="_blank" so it opens elsewhere instead.
    check("bookmark card opens in a new tab", re.search(
        r'class="bookmark[^"]*"[^>]*target="_blank"', emb), emb)
    check("inline markdown link also opens in a new tab", re.search(
        r'<a href="https://victronenergy\.com/install" target="_blank" rel="noopener', emb), emb)

    print("\n── image sizing and rows ──")
    up2 = c.post("/api/media", files={"file": ("Shunt Photo.png", io.BytesIO(png), "image/png")}).json()
    check("second image uploaded", up2["name"] == "shunt-photo.png", up2["name"])
    sizing_note = c.post("/api/notes", json={"title": "Sizing Scratch"}).json()["slug"]

    def rendered(md_body):
        c.put(f"/api/notes/{sizing_note}", json={"body": md_body})
        return c.get(f"/api/notes/{sizing_note}").json()["html"]

    h = rendered("![[busbar-layout.png|400]]")
    check("bare number sizes the figure (px, Obsidian's own convention)",
          'style="width:400px"' in h and 'class="embed g2 sized"' in h, h)

    h = rendered("![[busbar-layout.png|50%]]")
    check("percent size also works", 'style="width:50%"' in h, h)

    h = rendered("![[busbar-layout.png|A caption]]")
    check("a lone non-numeric field stays a caption, not a size",
          'alt="A caption"' in h and "sized" not in h, h)
    check("the caption is visible text under the embed, not just alt",
          'data-caption="A caption"' in h and ">A caption</span>" in h, h)

    h = rendered("![[busbar-layout.png|A caption|300]]")
    check("caption and size together",
          'alt="A caption"' in h and 'style="width:300px"' in h, h)
    check("caption still shown alongside a size",
          'data-caption="A caption"' in h and ">A caption</span>" in h, h)

    h = rendered("![[busbar-layout.png]]")
    check("an image embed gets a view-full-size link, opened in-app rather than a new tab",
          '<a class="embed-view" href="/media/busbar-layout.png"' in h and 'target="_blank"' not in h, h)
    check("the caption span carries the full text as a title, even though CSS truncates it visually",
          'title="busbar-layout.png"' in h, h)

    c.post("/api/media", files={"file": ("clip.mp4", io.BytesIO(b"not really a video"), "video/mp4")})
    h = rendered("![[clip.mp4]]")
    check("a non-image embed (video) gets no view-full-size link -- there's already a native player",
          "embed-view" not in h, h)

    h = rendered("![[busbar-layout.png|before|after]]")
    check("a caption containing a literal | stays a caption verbatim (backcompat)",
          'alt="before|after"' in h and "style=" not in h, h)

    h = rendered("![[busbar-layout.png]]")
    check("no caption falls back to the filename, shown as empty data-caption",
          'data-caption=""' in h and ">busbar-layout.png</span>" in h, h)

    h = rendered("![[busbar-layout.png]]\n![[shunt-photo.png]]")
    check("adjacent embeds (no blank line) become one row",
          h.count('class="embed-row"') == 1 and h.count("data-embed-index") == 2, h)

    h = rendered("![[busbar-layout.png]]\n\n![[shunt-photo.png]]")
    check("a blank line between them keeps them stacked, not a row",
          "embed-row" not in h and h.count("data-embed-index") == 2, h)

    h = rendered("![[busbar-layout.png]]\n![[shunt-photo.png]]\n\n![[busbar-layout.png]]")
    check("indices run in document order across a mixed row+stack layout",
          'data-embed-index="0"' in h and 'data-embed-index="1"' in h and 'data-embed-index="2"' in h, h)

    print("\n── callout / note boxes (GitHub and Obsidian [!TYPE] syntax) ──")
    h = rendered("> [!NOTE]\n> Plain callout, no title.")
    check("renders a callout div, not a bare blockquote",
          '<div class="callout callout-note">' in h and "<blockquote>" not in h, h)
    check("no title falls back to the type name",
          '<div class="callout-h">NOTE</div>' in h, h)

    h = rendered("> [!WARNING] Careful now\n> Danger ahead.")
    check("a custom title is used instead of the type name",
          '<div class="callout-h">Careful now</div>' in h, h)
    check("recognised type maps to its own visual variant",
          'class="callout callout-warning"' in h, h)

    h = rendered("> [!some-made-up-type]\n> Still boxed, not left as broken bracket text.")
    check("an unrecognised type still renders as a box (falls back to the note variant)",
          'class="callout callout-note">' in h and "[!some-made-up-type]" not in h, h)

    h = rendered("> [!TIP]+\n> Obsidian's fold marker doesn't break parsing.")
    check("a trailing +/- fold marker is accepted, not left dangling in the title",
          '<div class="callout-h">TIP</div>' in h, h)

    h = rendered("> [!NOTE]\n> Links to [[Shunt Wiring]] still resolve inside a callout.")
    check("a wikilink inside a callout still gets resolved, not left as raw brackets",
          'class="wl"' in h and 'data-slug="shunt-wiring"' in h, h)

    h = rendered("> [!NOTE]\n> Before.\n> ![[busbar-layout.png]]\n> After.")
    check("a block embed inside a callout stays inside the callout box",
          re.search(r'callout-b">.*Before.*embed g2.*After', h, re.S), h)
    check("it's still tracked as used media, not just visually present",
          'src="/media/busbar-layout.png"' in h, h)

    h = rendered("> Just a normal quote, no [!TYPE] marker.")
    check("an ordinary blockquote is untouched", "<blockquote>" in h and "callout" not in h, h)

    print("\n── mermaid: a ```mermaid fence renders as a diagram container, not a code block ──")
    h = rendered("```mermaid\ngraph TD\n    A[Start] --> B{Decision}\n```")
    check('renders as <pre class="mermaid">, not <pre><code class="language-mermaid">',
          '<pre class="mermaid">' in h and "language-mermaid" not in h, h)
    check("the raw diagram source is preserved (escaped) inside it",
          "graph TD" in h and "A[Start]" in h and "B{Decision}" in h, h)

    h = rendered("```python\ndef hello():\n    return \"hi\"\n```")
    check('an ordinary fence is unaffected -- still <pre><code class="language-python">',
          '<pre><code class="language-python">' in h, h)

    print("\n── mermaid: fence content is protected from the wikilink/citation/bookmark substitutions ──")
    h = rendered("```mermaid\ngraph TD\n    A --> B[[Subroutine]]\n```")
    check("a Mermaid [[Subroutine]] node shape survives literally, not rewritten into a wikilink",
          "B[[Subroutine]]" in h and 'class="wl' not in h, h)

    h = rendered("```text\nFootnote-looking text: item[^1] appears here.\n```")
    check("a [^N]-looking token inside a fence stays literal text, not a citation link",
          "item[^1]" in h and 'class="cite-link' not in h, h)

    h = rendered("```text\nSee also:\nhttps://example.com/whitepaper\n```")
    check("a bare URL alone on its own line inside a fence stays code, not a bookmark card",
          'class="bookmark' not in h and "https://example.com/whitepaper" in h, h)

    print("\n── search ──")
    s = c.get("/api/search", params={"q": "inverter"}).json()
    check("fts finds note", any(x["slug"] == new["slug"] for x in s), [x["slug"] for x in s])

    print("\n── the auto-wiki ──")
    for i, t in enumerate(["Solar Array", "Battery Bank", "Cable Sizing"]):
        cr = c.post("/api/notes", json={"title": t}).json()
        c.put(f"/api/notes/{cr['slug']}", json={"body": "Every run needs correct cable sizing and a voltage drop check. Voltage drop matters."})
    sug = c.get("/api/suggestions").json()
    kinds = {x["kind"] for x in sug}
    check("suggestions produced", len(sug) > 0, f"{len(sug)} found: {[x['term'] for x in sug][:5]}")
    check("emerging terms detected", "emerging" in kinds, kinds)
    target = next((x for x in sug if x["kind"] == "emerging"), None)
    if target:
        res = c.post("/api/suggestions/apply", json={"term": target["term"], "target": None}).json()
        check("applied across vault", res["notes_updated"] >= 3, res)
        anyfile = open(f"{VAULT}/notes/cable-sizing.md").read()
        check("markdown rewritten on disk", "[[" in anyfile, anyfile.strip().split("\n")[-1][:80])

    print("\n── a coincidental n-gram must not swallow the real phrase ──")
    # Regression for a real bug report: "Test Bed" typed into three notes with
    # different surrounding wording never surfaced as its own suggestion,
    # because a 3-word window landing on it by coincidence (e.g. "on Test
    # Bed") happened to also clear the MIN_DOCS threshold and, under the old
    # substring-based suppression, swallowed the shorter, actually-useful
    # phrase. Deliberately varied phrasing here, since identical wording in
    # every note would make the longer window a genuine fixed phrase too --
    # the bug is specifically that ordinary phrasing variation lost the
    # short phrase to an accidental long one.
    tb_notes = []
    for i, body in enumerate([
        "We ran diagnostics on Test Bed yesterday and it passed.",
        "The Test Bed needs a firmware update before next week.",
        "Results from Test Bed look consistent with the last run.",
    ]):
        sl = c.post("/api/notes", json={"title": f"Bench Note {i}"}).json()["slug"]
        c.put(f"/api/notes/{sl}", json={"body": body})
        tb_notes.append(sl)
    sugg = c.get("/api/suggestions", params={"limit": 100}).json()
    tb = next((s for s in sugg if s["term"].lower() == "test bed"), None)
    check("the real phrase surfaces, not just a coincidental n-gram around it",
          tb is not None, [s["term"] for s in sugg])
    if tb:
        res = c.post("/api/suggestions/apply", json={"term": tb["term"], "target": tb["target"]}).json()
        check("linked across all three notes it actually appears in",
              res["notes_updated"] == 3, res)
        for sl in tb_notes:
            body = c.get(f"/api/notes/{sl}").json()["body"]
            check(f"{sl}: linked, not left as manual work", "[[Test Bed]]" in body, body)

    print("\n── a single significant word can be a phrase too ──")
    # "Actuation" alone -- previously never a candidate at all, since only
    # 2- and 3-word windows were extracted. A lone word needs a stricter bar
    # than a multi-word phrase (any common noun would otherwise clear
    # MIN_DOCS in any vault about anything), so this also checks that an
    # ordinary lowercase word recurring just as often is NOT suggested.
    act_notes = []
    for i, body in enumerate([
        "The Actuation happened faster than expected today.",
        "We need better Actuation across the whole system.",
        "Actuation was logged at 3ms this run.",
    ]):
        sl = c.post("/api/notes", json={"title": f"Bench Log {i}"}).json()["slug"]
        c.put(f"/api/notes/{sl}", json={"body": body})
        act_notes.append(sl)
    for i in range(3):
        sl = c.post("/api/notes", json={"title": f"Chatter {i}"}).json()["slug"]
        c.put(f"/api/notes/{sl}", json={"body": "The system handles this data process well."})

    sugg = c.get("/api/suggestions", params={"limit": 100}).json()
    act = next((s for s in sugg if s["term"].lower() == "actuation"), None)
    check("a consistently-capitalized single word surfaces", act is not None,
          [s["term"] for s in sugg])
    noisy = [s["term"] for s in sugg if s["term"].lower() in ("system", "process", "data", "handles")]
    check("but an ordinary lowercase word recurring just as often does not",
          not noisy, noisy)
    if act:
        res = c.post("/api/suggestions/apply", json={"term": act["term"], "target": act["target"]}).json()
        check("linked across all three notes", res["notes_updated"] == 3, res)
        for sl in act_notes:
            body = c.get(f"/api/notes/{sl}").json()["body"]
            check(f"{sl}: linked", "[[Actuation]]" in body, body)

    print("\n── a short acronym with its own page is still suggested ──")
    # Regression: RPO/RTO -- real 3-letter titles a user had already created
    # pages for -- never showed up as "unlinked" suggestions no matter how
    # often they were typed as plain text elsewhere. The floor guarding
    # *this* loop (existing titles) used to match the emerging-phrase
    # miner's floor below, but the two aren't the same risk: this one only
    # ever matches a title someone deliberately gave a real note, not a
    # guessed n-gram, so a short acronym is exactly the high-confidence case
    # worth catching -- unlike a guessed phrase, there's already a concrete
    # page to point at. 1-2 character titles ("RP" here) stay excluded --
    # too close to bare letters/common short words to be useful signal even
    # with a word-boundary match.
    rpo_slug = c.post("/api/notes", json={"title": "RPO"}).json()["slug"]
    c.post("/api/notes", json={"title": "RP"})
    mention_notes = []
    for i, body in enumerate([
        "Our RPO target is under 15 minutes for this tier.",
        "RPO and RTO both factor into the DR runbook.",
        "Snapshot cadence is tuned to the RPO we committed to.",
    ]):
        sl = c.post("/api/notes", json={"title": f"DR Note {i}"}).json()["slug"]
        c.put(f"/api/notes/{sl}", json={"body": body})
        mention_notes.append(sl)
    sugg = c.get("/api/suggestions", params={"limit": 100}).json()
    rpo = next((s for s in sugg if s["kind"] == "unlinked" and s["term"] == "RPO"), None)
    check("the 3-letter title surfaces as an existing-page suggestion",
          rpo is not None, [s["term"] for s in sugg if s["kind"] == "unlinked"])
    if rpo:
        check("points at the actual RPO note, not a guess", rpo["target"] == rpo_slug, rpo)
        check("counted in all three notes that mention it", rpo["notes"] == 3, rpo)
        res = c.post("/api/suggestions/apply", json={"term": "RPO", "target": rpo_slug}).json()
        check("applied across all three mentions", res["notes_updated"] == 3, res)
        for sl in mention_notes:
            body = c.get(f"/api/notes/{sl}").json()["body"]
            check(f"{sl}: linked, not left as plain text", "[[RPO]]" in body, body)
    check("a 1-2 character title stays excluded even so",
          not any(s["term"] == "RP" for s in sugg), [s["term"] for s in sugg])

    print("\n── apply_suggestion is not fooled by a stale index ──")
    # Regression for a real bug report: a suggestion's toast said "Linked
    # across 1 note" when 4 notes actually had the phrase. The index is
    # supposed to always track disk (reindex_note runs on every save), but
    # "supposed to" is not a guarantee, and this is the one place a gap
    # between them is not an acceptable tradeoff -- so simulate one directly
    # (delete rows the app itself never asked to delete) rather than trying
    # to reproduce whatever caused it upstream, and confirm the endpoint
    # heals itself before doing the bulk rewrite.
    drift_notes = []
    for i in range(4):
        sl = c.post("/api/notes", json={"title": f"Drift {i}"}).json()["slug"]
        c.put(f"/api/notes/{sl}", json={"body": f"Findings mention Coolant Loop clearly in note {i}."})
        drift_notes.append(sl)
    con = app.state.db
    for sl in drift_notes[1:]:
        con.execute("DELETE FROM notes WHERE slug=?", (sl,))
    con.commit()
    still_indexed = {r["slug"] for r in con.execute("SELECT slug FROM notes").fetchall()}
    check("drift actually simulated (3 of 4 no longer in the index)",
          len(still_indexed & set(drift_notes)) == 1, still_indexed & set(drift_notes))

    r = c.post("/api/suggestions/apply", json={"term": "coolant loop", "target": None})
    check("apply succeeds", r.status_code == 200, r.text[:120])
    res = r.json()
    check("all four notes touched despite the stale index", res["notes_updated"] == 4, res)
    for sl in drift_notes:
        body = c.get(f"/api/notes/{sl}").json()["body"]
        check(f"{sl}: linked despite having fallen out of the index", "[[Coolant Loop]]" in body, body)

    print("\n── dismissing a suggestion sticks ──")
    for i, body in enumerate([
        "The remote host answers on tcp 443 every time.",
        "A remote host may drop icmp while serving tcp 443.",
        "Check whether the remote host is filtering.",
    ]):
        sl = c.post("/api/notes", json={"title": f"Host Note {i}"}).json()["slug"]
        c.put(f"/api/notes/{sl}", json={"body": body})
    sugg = c.get("/api/suggestions", params={"limit": 20}).json()
    check("suggestions offered", len(sugg) > 0, [x["term"] for x in sugg][:4])
    term = sugg[0]["term"]
    check("each names the notes it affects", bool(sugg[0]["where"]), sugg[0]["where"][:2])

    c.post("/api/suggestions/dismiss", json={"term": term})
    after = [x["term"] for x in c.get("/api/suggestions", params={"limit": 20}).json()]
    check("dismissed term is gone", term not in after, after[:4])
    check("recorded in the vault", os.path.isfile(f"{VAULT}/link-suggestions.json"))
    check("listed as dismissed",
          term in [d["term"] for d in c.get("/api/suggestions/dismissed").json()])
    # the actual bug: it used to reappear on the next read
    again = [x["term"] for x in c.get("/api/suggestions", params={"limit": 20}).json()]
    check("still gone on a fresh read", term not in again)

    c.post("/api/suggestions/restore", json={"term": term})
    check("restoring brings it back",
          term in [x["term"] for x in c.get("/api/suggestions", params={"limit": 20}).json()])

    applied = c.get("/api/suggestions", params={"limit": 20}).json()[0]
    c.post("/api/suggestions/apply", json={"term": applied["term"], "target": applied["target"]})
    check("an applied term is not re-suggested",
          applied["term"] not in [x["term"] for x in c.get("/api/suggestions", params={"limit": 20}).json()])
    check("and is marked as linked, not dismissed",
          any(d["term"] == applied["term"] and d.get("note") == "applied"
              for d in c.get("/api/suggestions/dismissed").json()))

    print("\n── category history ──")
    cr = c.post("/api/notes", json={"title": "Zoning"}).json()["slug"]
    c.put(f"/api/notes/{cr}", json={"body": "Soft zoning by WWPN in the fabric."})
    c.post(f"/api/study/{cr}/enable", json={"category": "SAN & Fibre Channel"})
    check("no history on first assignment",
       c.get(f"/api/notes/{cr}").json()["category_history"] == [])
    r1 = c.post(f"/api/study/{cr}/category", json={"category": "File Protocols"}).json()
    check("records where it came from", [e["category"] for e in r1["history"]] == ["SAN & Fibre Channel"],
       [e["category"] for e in r1["history"]])
    check("reports both ends", r1["from"] == "SAN & Fibre Channel" and r1["changed"], r1.get("from"))
    r2 = c.post(f"/api/study/{cr}/category", json={"category": "Linux Commands"}).json()
    check("newest first", [e["category"] for e in r2["history"]][0] == "File Protocols")
    same = c.post(f"/api/study/{cr}/category", json={"category": "Linux Commands"}).json()
    check("a no-op change is not recorded", same["changed"] is False and len(same["history"]) == 2,
       len(same["history"]))
    check("stored in the note itself",
       "category_history:" in open(f"{VAULT}/notes/{cr}.md").read())

    rv = c.post(f"/api/study/{cr}/revert", json={}).json()
    check("revert moves it back", rv["category"] == "File Protocols", rv["category"])
    check("the undone value is itself revertible",
       [e["category"] for e in rv["history"]][0] == "Linux Commands")
    rv2 = c.post(f"/api/study/{cr}/revert", json={"category": "SAN & Fibre Channel"}).json()
    check("can jump to any earlier point", rv2["category"] == "SAN & Fibre Channel")
    check("unknown category refused",
       c.post(f"/api/study/{cr}/revert", json={"category": "Nope"}).status_code == 404)
    fresh = c.post("/api/notes", json={"title": "No History"}).json()["slug"]
    c.post(f"/api/study/{fresh}/enable", json={"category": "Windows"})
    check("nothing to revert is refused clearly",
       c.post(f"/api/study/{fresh}/revert", json={}).status_code == 400)

    print("\n── tags ──")
    tg = c.post("/api/notes", json={"title": "Tag Test"}).json()["slug"]
    c.put(f"/api/notes/{tg}", json={"tags": ["gear", "solar"]})
    check("tags round-trip", c.get(f"/api/notes/{tg}").json()["tags"] == ["gear", "solar"])
    c.put(f"/api/notes/{tg}", json={"tags": ["solar"]})
    check("tag removed", c.get(f"/api/notes/{tg}").json()["tags"] == ["solar"])
    check("tag cloud reflects it",
       "solar" in {t for n in c.get("/api/notes").json() for t in n["tags"]})

    print("\n── favorites ──")
    fav = c.post("/api/notes", json={"title": "Favorite Me"}).json()
    check("starts unfavorited", fav["favorite"] is False, fav)
    check("list agrees", next(n for n in c.get("/api/notes").json()
                              if n["slug"] == fav["slug"])["favorite"] is False)
    r = c.post(f"/api/notes/{fav['slug']}/favorite").json()
    check("toggle turns it on", r["favorite"] is True, r)
    check("reflected on the note", c.get(f"/api/notes/{fav['slug']}").json()["favorite"] is True)
    check("reflected in the list", next(n for n in c.get("/api/notes").json()
                                        if n["slug"] == fav["slug"])["favorite"] is True)
    check("never leaks into the tag list", "favorite" not in c.get(f"/api/notes/{fav['slug']}").json()["tags"])
    check("stored as a plain tag on disk (no schema change)",
       "favorite" in open(f"{VAULT}/notes/{fav['slug']}.md").read())
    r2 = c.post(f"/api/notes/{fav['slug']}/favorite").json()
    check("toggling again turns it off", r2["favorite"] is False, r2)

    print("\n── editing other tags never unfavorites a note (the actual bug: PUT .../notes\n"
          "   overwrites the whole tags array, and 'favorite' is hidden from every client-facing list) ──")
    c.post(f"/api/notes/{fav['slug']}/favorite")   # back on
    c.put(f"/api/notes/{fav['slug']}", json={"tags": ["gear"]})
    after = c.get(f"/api/notes/{fav['slug']}").json()
    check("favorite survives an unrelated tag edit", after["favorite"] is True, after)
    check("the new tag still lands", after["tags"] == ["gear"], after["tags"])
    check("and 'favorite' still never leaks out as a visible tag", "favorite" not in after["tags"])

    print("\n── manual study-group creation ──")
    ng = c.post("/api/notes", json={"title": "Freeform Group Note"}).json()["slug"]
    c.put(f"/api/notes/{ng}", json={"body": "Anything goes here."})
    r = c.post(f"/api/study/{ng}/enable",
               json={"category": "Brand New Study Group"}).json()
    check("arbitrary category accepted on enable",
       r["item"]["category"] == "Brand New Study Group", r["item"]["category"])
    check("becomes ground truth, not a guess", r["item"]["source"] == "manual",
       r["item"]["source"])
    check("shows up in known_categories",
       "Brand New Study Group" in c.get("/api/study").json()["known_categories"])

    print("\n── cold-start suggestion is topic-agnostic ──")
    # A fresh Classifier with nothing fitted, exercised directly — this is
    # the same "before any labelled items exist" state a brand-new vault (or
    # a vault about a topic with no confirmed categories yet) starts from.
    # There is no built-in topic lexicon: a vault can be about anything, so
    # every cold-start guess is derived straight from the note's own words.
    clf = st.Classifier()
    beekeeping = st.feature_text("Hive Inspection — Spring Check", None,
        "Checked the brood frames today. The queen is laying well and the hive "
        "looks healthy. Added a new super since the bees are running out of room "
        "in the hive. Next hive inspection in two weeks.")
    guess = clf.predict(beekeeping)
    check("falls back to a name derived from the note's own words",
       guess["method"] == "content" and guess["category"] is not None and
       any(w in guess["category"].lower() for w in ("hive", "inspection", "spring", "check", "bee")),
       guess)

    # Even a note on a topic the old built-in IT lexicon used to recognise
    # (DNS, in this case) gets the same content-derived treatment now — no
    # hardcoded category is waiting to claim it.
    dns_note = st.feature_text("DNS Resolver Behaviour", None,
        "Notes on how a dns resolver walks a zone from the root down. A resolver "
        "caches each record it gets until its ttl expires, then asks again.")
    guess2 = clf.predict(dns_note)
    check("no built-in category exists to claim an on-topic-for-IT note either",
       guess2["method"] == "content" and "dns" in guess2["category"].lower(), guess2)

    blank = clf.predict(st.feature_text("Untitled", None, ""))
    check("an empty note has nothing to guess and says so plainly, not oddly",
       blank["category"] == "Untitled", blank)

    print("\n── trained k-NN also refuses to force an unrelated category ──")
    # Once a vault has confirmed categories, predict() moves past the seed
    # tier into k-NN — which had the identical bug: a note with nothing in
    # common with any trained example still got forced onto whichever one
    # happened to be least distant (a whaling note landing on "Windows"
    # because that's the vault's least-unrelated IT category).
    trained = st.Classifier()
    trained.fit([
        (st.feature_text("Zoning Basics", None,
            "Soft zoning by WWPN in the fibre channel fabric, unlike hard zoning by port."),
         "SAN & Fibre Channel"),
        (st.feature_text("LUN Masking", None,
            "Masking a lun to a specific initiator wwpn keeps other hosts from seeing it."),
         "SAN & Fibre Channel"),
        (st.feature_text("Grep Basics", None,
            "Using grep and awk to filter log output from the command line shell."),
         "Linux Commands"),
        (st.feature_text("Systemctl Cheatsheet", None,
            "systemctl start, stop, and restart a service, journalctl to read its log."),
         "Linux Commands"),
    ])
    whale_note = st.feature_text("Whaling History", None,
        "Whaling is the hunting of whales for their products such as meat and blubber, "
        "which was turned into oil important to the Industrial Revolution.")
    guess4 = trained.predict(whale_note)
    check("an unrelated note is not forced into the nearest existing category",
       guess4["method"] == "content", guess4)
    check("and gets a name derived from its own words instead",
       guess4["category"] is not None and "whal" in guess4["category"].lower(), guess4)

    san_note = st.feature_text("Fabric Zoning Notes", None,
        "Reviewed the fibre channel fabric zoning config, WWPN based, soft zoning throughout.")
    guess5 = trained.predict(san_note)
    check("a genuinely on-topic note in a trained vault still matches",
       guess5["category"] == "SAN & Fibre Channel" and guess5["method"] == "knn", guess5)

    # A live report against a real 94-note vault: a note titled "Whaling
    # History" landed on "Windows" at 53% confidence, low_confidence=False —
    # sim_top alone (0.259) cleared MIN_SIM. The entire similarity turned out
    # to come from exactly one shared word, "history", coincidentally
    # prominent in an unrelated Windows note too. Short notes produce sparse
    # vectors, and cosine similarity between two sparse vectors can be
    # dominated by a single shared dimension — an aggregate threshold on its
    # own can't tell that apart from genuine relatedness.
    history_collision = st.Classifier()
    history_collision.fit([
        (st.feature_text("Windows Update History", None,
            "The update history log shows recent patches applied to this machine automatically."),
         "Windows"),
        (st.feature_text("Grep Basics", None,
            "Using grep and awk to filter log output from the command line shell."),
         "Linux Commands"),
    ])
    guess6 = history_collision.predict(whale_note)
    check("one coincidentally shared word does not out-vote real unrelatedness",
       guess6["category"] != "Windows" and guess6["method"] == "content", guess6)

    print("\n── near-duplicate detection on import ──")
    # The bug this fixes: title matching alone lets the *same* content back
    # in under a different title, from a different guide, or reworded --
    # exactly what a re-merged export produces. These three answers are
    # verified (via app.dedupe directly) to land in three different bands:
    # a title-only reword stays >= AUTO_SKIP_THRESHOLD, two single-word
    # substitutions land between REPORT_THRESHOLD and AUTO_SKIP_THRESHOLD,
    # and an unrelated topic stays well under REPORT_THRESHOLD.
    subnet_answer = (
        "Subnetting divides a network into smaller pieces using a subnet mask. "
        "Each subnet has its own range of usable host addresses bounded by the "
        "network and broadcast address. CIDR notation expresses the mask as a "
        "slash and a bit count, such as slash 24 for a class C sized network. "
        "Subnetting improves routing efficiency and limits broadcast domains "
        "within an organization network.")
    subnet_answer_tweaked = subnet_answer.replace("divides", "splits").replace("improves", "helps")

    guide1 = json.dumps({"topics": [
        {"title": "Subnetting Basics", "category": "Networking",
         "question": "What is subnetting?", "answer": subnet_answer},
    ]})
    c.post("/api/study/import", files={"file": ("net-guide-1.json", io.BytesIO(guide1.encode()), "application/json")})
    baseline = next(n for n in c.get("/api/notes").json() if n["title"] == "Subnetting Basics")

    route_answer = ("Static routes are configured by hand rather than learned from a "
        "routing protocol. Each entry names a destination network and the next "
        "hop to reach it. They are simple and predictable but do not adapt "
        "automatically when the topology changes, so they suit small or stable "
        "networks better than large dynamic ones.")
    guide2 = json.dumps({"topics": [
        # near-certain duplicate of the note guide1 already created: same
        # answer, reworded title only -- must be skipped, not created.
        {"title": "Subnetting Basics Overview", "category": "Networking",
         "question": "What is subnetting?", "answer": subnet_answer},
        # a real but lighter rewrite: reported, not auto-skipped, so real
        # content is never dropped on a guess.
        {"title": "Subnetting Fundamentals", "category": "Networking",
         "question": "What is subnetting?", "answer": subnet_answer_tweaked},
        # genuinely unrelated -- must not be flagged at all.
        {"title": "DHCP Overview", "category": "Networking",
         "question": "What does DHCP do?",
         "answer": "DHCP automatically assigns IP addresses and other network "
                   "configuration to hosts on a network via a lease process."},
        # two near-identical topics *within the same file*, neither of which
        # exists in the vault yet -- the within-batch case the user hit.
        {"title": "Static Routing", "category": "Networking",
         "question": "What is static routing?", "answer": route_answer},
        {"title": "Static Routes Explained", "category": "Networking",
         "question": "What is static routing?", "answer": route_answer},
    ]})
    r = c.post("/api/study/import",
               files={"file": ("net-guide-2.json", io.BytesIO(guide2.encode()), "application/json")}).json()

    check("near-certain reword is skipped, not created",
       r["skipped_duplicates"] >= 1, r["skipped_duplicates"])
    dup_titles = {d["title"]: d for d in r["duplicates"]}
    check("the skipped one is reported and marked skipped",
       dup_titles.get("Subnetting Basics Overview", {}).get("skipped") is True, dup_titles)
    check("the lighter rewrite is reported but NOT skipped",
       dup_titles.get("Subnetting Fundamentals", {}).get("skipped") is False, dup_titles)
    check("an unrelated topic is never flagged", "DHCP Overview" not in dup_titles, dup_titles)
    check("a within-batch duplicate is caught too (neither existed before this import)",
       dup_titles.get("Static Routes Explained", {}).get("skipped") is True, dup_titles)

    notes_after = {n["title"] for n in c.get("/api/notes").json()}
    check("the skipped duplicate never became a note",
       "Subnetting Basics Overview" not in notes_after, sorted(notes_after))
    check("the reported (not skipped) rewrite WAS created -- flagging never withholds content",
       "Subnetting Fundamentals" in notes_after, sorted(notes_after))
    check("the unrelated topic was created normally", "DHCP Overview" in notes_after)
    check("only one of the two within-batch near-duplicates was created",
       ("Static Routing" in notes_after) != ("Static Routes Explained" in notes_after),
       sorted(t for t in notes_after if t.startswith("Static")))
    check("the original note is untouched", baseline["slug"] in
       {n["slug"] for n in c.get("/api/notes").json()})

    print("\n── vault-wide duplicate scan ──")
    scan = c.get("/api/duplicates").json()["pairs"]
    check("finds the real duplicate left on disk (reported rewrite vs the original)",
       any({p["a_title"], p["b_title"]} == {"Subnetting Basics", "Subnetting Fundamentals"}
           for p in scan), scan)
    check("sorted highest-similarity first",
       all(scan[i]["similarity"] >= scan[i + 1]["similarity"] for i in range(len(scan) - 1)))
    check("unrelated notes are not paired up",
       not any({p["a_title"], p["b_title"]} & {"DHCP Overview"} for p in scan), scan)

    print("\n── quiz editor: structured save ──")
    qnote = c.post("/api/notes", json={"title": "Quiz Editor Note",
                                        "body": "Some prose about the topic.\n"}).json()
    qslug = qnote["slug"]
    saved = c.put(f"/api/notes/{qslug}/quiz", json={"items": [
        {"question": "Single-answer question?", "options": ["Right", "Wrong"],
         "answers": [0], "why": "Because."},
        {"question": "Multi-answer question?", "options": ["A", "B", "C"],
         "answers": [0, 2], "why": ""},
        # No options marked correct -- unanswerable, must not be persisted.
        {"question": "Half-finished question", "options": ["Only one so far"],
         "answers": [], "why": ""},
    ]}).json()
    check("response reports only the two answerable questions",
       len(saved["quiz"]) == 2, [q["question"] for q in saved["quiz"]])
    single = next(q for q in saved["quiz"] if q["question"] == "Single-answer question?")
    multi = next(q for q in saved["quiz"] if q["question"] == "Multi-answer question?")
    check("single answer round-trips as a one-element list", single["answers"] == [0], single["answers"])
    check("multi answer keeps both indices", sorted(multi["answers"]) == [0, 2], multi["answers"])

    on_disk = open(f"{VAULT}/notes/{qslug}.md").read()
    check("prose is untouched", "Some prose about the topic." in on_disk)
    check("multi-answer question has two [x] marks in the file",
       on_disk.count("- [x] A") == 1 and on_disk.count("- [x] C") == 1, on_disk)
    check("the half-finished question was never written",
       "Half-finished" not in on_disk)

    refetched = c.get(f"/api/notes/{qslug}").json()
    check("GET agrees with the save response", len(refetched["quiz"]) == 2,
       [q["question"] for q in refetched["quiz"]])
    check("the note's displayed html is prose only, not the quiz text a second time",
       "Multi-answer question?" not in refetched["html"] and "Some prose" in refetched["html"],
       refetched["html"])

    print("\n── quiz editor: hand-edited markdown round-trips back through the same parser ──")
    hand = c.put(f"/api/notes/{qslug}", json={
        "body": "Rewritten prose.\n\n## Quiz\n\nQ: Hand-written?\n- [x] Yes\n- No\nWhy: because.\n"}).json()
    check("save_note also reports the quiz array", len(hand["quiz"]) == 1, hand["quiz"])
    check("hand-written question parsed correctly",
       hand["quiz"][0]["question"] == "Hand-written?" and hand["quiz"][0]["answers"] == [0],
       hand["quiz"][0])

    print("\n── sources section: parsed out of prose, alongside a quiz block ──")
    snote = c.post("/api/notes", json={"title": "Sources Note", "body": (
        "Some prose about the topic.\n\n"
        "## Sources\n"
        "* [Wikipedia](https://en.wikipedia.org/wiki/Example)\n"
        "- https://bare.example.com/paper\n"
        "* Baker et al. -- https://mixed.example.com/paper.\n"
        "- Baker et al., a plain-text citation with no link\n\n"
        "## Quiz\n\n"
        "Q: A question?\n- [x] Right\n- Wrong\nWhy: because.\n"
    )}).json()
    sslug = snote["slug"]
    fetched = c.get(f"/api/notes/{sslug}").json()
    check("four sources parsed", len(fetched["sources"]) == 4, fetched["sources"])
    check("a `*` bulleted link becomes {text, url}, same as `-`",
       fetched["sources"][0] == {"text": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Example"},
       fetched["sources"][0])
    check("a bare-URL bullet is still clickable",
       fetched["sources"][1] == {"text": "https://bare.example.com/paper",
                                 "url": "https://bare.example.com/paper"},
       fetched["sources"][1])
    check("a `*` bullet with an embedded URL is still clickable, trailing period trimmed off the href",
       fetched["sources"][2] == {"text": "Baker et al. -- https://mixed.example.com/paper.",
                                 "url": "https://mixed.example.com/paper"},
       fetched["sources"][2])
    check("plain bullet with no url at all becomes {text, url: null}",
       fetched["sources"][3] == {"text": "Baker et al., a plain-text citation with no link", "url": None},
       fetched["sources"][3])
    check("the quiz section after it still parses on its own",
       len(fetched["quiz"]) == 1 and fetched["quiz"][0]["question"] == "A question?", fetched["quiz"])
    check("displayed html has the prose but neither the Sources heading nor the quiz text",
       "Some prose about the topic" in fetched["html"]
       and "Sources" not in fetched["html"] and "Wikipedia" not in fetched["html"]
       and "A question?" not in fetched["html"], fetched["html"])

    print("\n── sources: no ## Sources heading at all is just an empty list ──")
    plain = c.post("/api/notes", json={"title": "No Sources Here",
                                        "body": "Nothing but prose.\n"}).json()
    check("empty sources list, not an error",
       c.get(f"/api/notes/{plain['slug']}").json()["sources"] == [])

    print("\n── sources: hand-edited markdown round-trips through save_note too ──")
    resaved = c.put(f"/api/notes/{plain['slug']}", json={
        "body": "Prose.\n\n## Sources\n- [Only](https://only.example)\n"}).json()
    check("save_note's own response reports the new sources",
       resaved["sources"] == [{"text": "Only", "url": "https://only.example"}], resaved["sources"])

    print("\n── citations: [^N] markers index into the note's own Sources list ──")
    cnote = c.post("/api/notes", json={"title": "Citations Note", "body": (
        "Caffeine improves alertness[^1]. A wider claim[^2] needs more evidence[^5].\n\n"
        "## Sources\n"
        "- [Caffeine study](https://example.com/caffeine)\n"
        "- Baker et al., a plain-text citation with no link\n"
    )}).json()
    chtml = c.get(f"/api/notes/{cnote['slug']}").json()["html"]
    check("[^1] renders as a resolved citation link, numbered and anchored",
       '<sup class="cite-ref"><a class="cite-link" href="#src-1" data-idx="1"' in chtml, chtml)
    check("[^1]'s data attributes carry its source's text and url",
       'data-text="Caffeine study" data-url="https://example.com/caffeine"' in chtml, chtml)
    check("[^2] resolves against the second source, with no url to carry",
       'href="#src-2" data-idx="2" data-text="Baker et al., a plain-text citation with no link" data-url=""'
       in chtml, chtml)
    check("[^5], past the end of a two-item Sources list, is flagged instead of silently wrong",
       'class="cite-link missing" data-idx="5"' in chtml, chtml)

    print("\n── citations: [^N] with no Sources block at all is flagged, not a crash ──")
    nosrc = c.post("/api/notes", json={"title": "No Sources Citation",
                                        "body": "A claim with nothing to back it[^1].\n"}).json()
    nchtml = c.get(f"/api/notes/{nosrc['slug']}").json()["html"]
    check("flagged the same way an out-of-range citation is",
       'class="cite-link missing" data-idx="1"' in nchtml, nchtml)

    print("\n── graph ──")
    g = c.get("/api/graph").json()
    check("graph nodes", len(g["nodes"]) >= 7, len(g["nodes"]))
    check("graph edges", len(g["links"]) >= 2, len(g["links"]))

    print("\n── theme persistence ──")
    c.put("/api/theme", json={"acc": "255,143,177", "blur": 44, "wall": "ember"})
    t = c.get("/api/theme").json()
    check("theme persisted", t["acc"] == "255,143,177" and t["blur"] == 44)
    check("theme.json on disk", os.path.isfile(f"{VAULT}/theme.json"))

    print("\n── index is disposable ──")
    os.remove(f"{VAULT}/.index/index.db")
    check("rebuild from files", c.post("/api/reindex").json()["notes"] >= 7)

    print("\n── delete goes to trash ──")
    c.delete("/api/notes/battery-bank")
    check("gone from api", c.get("/api/notes/battery-bank").status_code == 404)
    check("recoverable in .trash", len(os.listdir(f"{VAULT}/.trash")) == 1)

print(f"\n{'='*46}\n  {ok} passed, {fail} failed\n{'='*46}")
raise SystemExit(1 if fail else 0)
