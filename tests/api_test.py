import os, io, json, shutil
VAULT = os.environ.setdefault("TEPHRA_VAULT", "/tmp/tephra-test")
shutil.rmtree(VAULT, ignore_errors=True)
from fastapi.testclient import TestClient
from app.main import app

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
    c.put(f"/api/notes/{new['slug']}", json={"body": body + "\n![[busbar-layout.png]]\n\nhttps://victronenergy.com/inverters\n"})
    emb = c.get(f"/api/notes/{new['slug']}").json()["html"]
    check("image embedded", '<img src="/media/busbar-layout.png"' in emb)
    check("bare url -> bookmark", 'class="bookmark' in emb)
    check("media served", c.get("/media/busbar-layout.png").status_code == 200)

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
    check("per-note suggestions honour it too",
          all(x["term"] != term for n in c.get("/api/notes").json()[:6]
              for x in c.get(f"/api/notes/{n['slug']}").json()["suggestions"]))

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

    print("\n── seed dismissal ──")
    before = c.get("/api/study").json()
    check("starter categories start visible", "OSI Model" in before["known_categories"],
       before["known_categories"])
    check("and listed as unused", "OSI Model" in before["unused_seeds"])
    d = c.post("/api/study/seeds", json={"category": "OSI Model", "dismissed": True}).json()
    check("dismiss records it", "OSI Model" in d["dismissed_seeds"])
    after = c.get("/api/study").json()
    check("dismissed seed drops out of known_categories",
       "OSI Model" not in after["known_categories"])
    check("dismissed seed drops out of unused_seeds",
       "OSI Model" not in after["unused_seeds"])
    restore = c.post("/api/study/seeds",
                     json={"category": "OSI Model", "dismissed": False}).json()
    check("restoring un-hides it", "OSI Model" not in restore["dismissed_seeds"])
    check("back in known_categories",
       "OSI Model" in c.get("/api/study").json()["known_categories"])
    check("rejects a non-seed name",
       c.post("/api/study/seeds", json={"category": "Not A Real Seed"}).status_code == 400)

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
