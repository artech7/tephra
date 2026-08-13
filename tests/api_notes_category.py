"""
Stats-page category browsing: GET /api/notes/by-category and
POST /api/notes/category/bulk. Both work over every vault note, not just
Crucible-enabled ones -- the Stats page's category bars count the whole
vault, so the list behind a bar has to match.
"""
import os, shutil

V = os.environ.setdefault("TEPHRA_VAULT", "/tmp/tephra-test-notes-category")
shutil.rmtree(V, ignore_errors=True)
os.makedirs(f"{V}/notes", exist_ok=True)

from fastapi.testclient import TestClient
from app.main import app

ok = fail = 0
def ck(l, c, x=""):
    global ok, fail
    if c: ok += 1; print(f"  PASS  {l} {x}")
    else: fail += 1; print(f"  FAIL  {l} {x}")

write = lambda n, t: open(f"{V}/notes/{n}", "w").write(t)

# A plain note (never enabled for Crucible) with a category, one Crucible
# item sharing that category, and two notes with no category at all.
write("icmp.md", "---\ntitle: ICMP\ntags: []\ncategory: Networking\n---\n\nBody.\n")
write("dns-quiz.md", "---\ntitle: DNS Quiz\ntags: [study]\nstudy: true\n"
                     "category: Networking\ncategory_source: manual\n---\n\n"
                     "Q: what is DNS?\n\n## Quiz\n\nQ: what is DNS?\n- [x] a name system\n")
write("loose-one.md", "---\ntitle: Loose One\ntags: []\n---\n\nNo category.\n")
write("loose-two.md", "---\ntitle: Loose Two\ntags: []\n---\n\nAlso none.\n")

with TestClient(app) as c:
    print("── by-category spans the whole vault, not just study items ──")
    r = c.get("/api/notes/by-category", params={"category": "Networking"}).json()
    slugs = {n["slug"] for n in r["notes"]}
    ck("finds both the plain note and the study item", slugs == {"icmp", "dns-quiz"}, slugs)
    ck("echoes the requested category", r["category"] == "Networking")
    icmp = next(n for n in r["notes"] if n["slug"] == "icmp")
    ck("plain note is not marked as a study item", icmp["study"] is False)
    dq = next(n for n in r["notes"] if n["slug"] == "dns-quiz")
    ck("study item is marked", dq["study"] is True)
    ck("carries category_source through", dq["category_source"] == "manual", dq["category_source"])
    ck("sorted by title", [n["title"] for n in r["notes"]] == ["DNS Quiz", "ICMP"])

    print("\n── empty category means 'no category field at all' ──")
    r = c.get("/api/notes/by-category", params={"category": ""}).json()
    slugs = {n["slug"] for n in r["notes"]}
    ck("finds both uncategorised notes", slugs == {"loose-one", "loose-two"}, slugs)

    print("\n── an unused category name comes back empty, not an error ──")
    r = c.get("/api/notes/by-category", params={"category": "Nope"}).json()
    ck("empty list", r["notes"] == [])

    print("\n── bulk reassignment ──")
    r = c.post("/api/notes/category/bulk",
               json={"slugs": ["loose-one", "loose-two"], "category": "Networking"}).json()
    ck("both updated", set(r["updated"]) == {"loose-one", "loose-two"}, r)

    after_net = {n["slug"] for n in c.get("/api/notes/by-category",
                                           params={"category": "Networking"}).json()["notes"]}
    ck("moved notes now show up under the new category",
       {"loose-one", "loose-two"} <= after_net, after_net)
    after_empty = c.get("/api/notes/by-category", params={"category": ""}).json()["notes"]
    ck("and are gone from Uncategorised", after_empty == [])

    print("\n── bulk skips notes already at the target, no wasted history entry ──")
    before = c.get("/api/notes/icmp").json()["category_history"]
    r2 = c.post("/api/notes/category/bulk", json={"slugs": ["icmp"], "category": "Networking"}).json()
    ck("nothing reported as updated", r2["updated"] == [], r2)
    after = c.get("/api/notes/icmp").json()["category_history"]
    ck("history untouched", after == before, (before, after))

    print("\n── bulk-moved notes are reachable via history like any manual move ──")
    # loose-one had no category before the bulk move, so there's nothing to
    # record -- push_history is a no-op from an unset category, same as the
    # single-note endpoint. A note that *had* a category is the real check.
    c.post("/api/notes/category/bulk", json={"slugs": ["icmp"], "category": "Archived"})
    hist = c.get("/api/notes/icmp").json()["category_history"]
    ck("records where it came from", hist and hist[0]["category"] == "Networking", hist)
    # icmp's fixture never set category_source, so it defaults to "auto" --
    # push_history records *that* prior source, not "manual" for this move.
    ck("prior source carried through unchanged", hist[0]["source"] == "auto", hist)

    print("\n── a slug that doesn't exist is skipped, not a hard failure ──")
    r3 = c.post("/api/notes/category/bulk", json={"slugs": ["ghost", "icmp-x-not-real"], "category": "Whatever"}).json()
    ck("nothing updated, no error", r3["updated"] == [])

    print("\n── an empty category clears it, on the single-note endpoint ──")
    # icmp is "Archived" at this point (moved there a few steps up).
    r4 = c.post("/api/study/icmp/category", json={"category": ""}).json()
    ck("reports the change", r4["changed"] is True and r4["category"] == "", r4)
    ck("icmp is gone from Archived",
       "icmp" not in {n["slug"] for n in c.get("/api/notes/by-category",
                                                params={"category": "Archived"}).json()["notes"]})
    ck("and back in Uncategorised",
       "icmp" in {n["slug"] for n in c.get("/api/notes/by-category",
                                            params={"category": ""}).json()["notes"]})
    ck("history remembers where it came from",
       r4["history"] and r4["history"][0]["category"] == "Archived", r4["history"])
    ck("clearing an already-clear note is a no-op",
       c.post("/api/study/icmp/category", json={"category": ""}).json()["changed"] is False)

    print("\n── a missing category field is still rejected (not the same as an empty one) ──")
    resp = c.post("/api/study/icmp/category", json={})
    ck("400", resp.status_code == 400, resp.status_code)

    print("\n── an empty category clears everyone selected, on the bulk endpoint ──")
    c.post("/api/notes/category/bulk", json={"slugs": ["loose-one", "loose-two"], "category": "Networking"})
    r5 = c.post("/api/notes/category/bulk", json={"slugs": ["loose-one", "loose-two"], "category": ""}).json()
    ck("both cleared", set(r5["updated"]) == {"loose-one", "loose-two"}, r5)
    uncategorised = {n["slug"] for n in c.get("/api/notes/by-category", params={"category": ""}).json()["notes"]}
    ck("both back in Uncategorised", {"loose-one", "loose-two"} <= uncategorised, uncategorised)

print(f"\n{'='*46}\n  {ok} passed, {fail} failed\n{'='*46}")
raise SystemExit(1 if fail else 0)
