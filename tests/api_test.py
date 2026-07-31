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
