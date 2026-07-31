"""Link integrity: the auto-linker must never damage a note, and existing
damage must be repairable."""
import io, os, re, shutil
V = os.environ.setdefault("TEPHRA_VAULT", "/tmp/tephra-test-links")
shutil.rmtree(V, ignore_errors=True)
from fastapi.testclient import TestClient
from app.main import app
from app.index import flatten_nested_links, unlink

ok = fail = 0
def ck(l, c, x=""):
    global ok, fail
    if c: ok += 1; print(f"  PASS  {l} {x}")
    else: fail += 1; print(f"  FAIL  {l} {x}")

body_of = lambda slug: open(f"{V}/notes/{slug}.md").read().split("---", 2)[2]

print("── flattening, unit level ──")
for src, want in [
    ("[[Answer [[Ping]]|answer ping]]", "[[Answer Ping|answer ping]]"),
    ("[[Deep [[A]] [[B]]|d]]", "[[Deep A B|d]]"),
    ("[[a [[b [[c]] d]] e]]", "[[a b c d e]]"),
    ("[[Normal]] and [[Piped|shown]]", "[[Normal]] and [[Piped|shown]]"),
    ("![[image.png]]", "![[image.png]]"),
]:
    got, _ = flatten_nested_links(src)
    ck(f"{src[:30]:32}", got == want, f"-> {got}")
ck("unlink keeps display text", unlink("see [[ICMP|icmp]] and [[DNS]]") == "see icmp and DNS")
ck("unlink leaves embeds", unlink("![[a.png]]") == "![[a.png]]")

with TestClient(app) as c:
    print("\n── the linker cannot nest, whatever the order ──")
    n = c.post("/api/notes", json={"title": "Host checks"}).json()["slug"]
    c.put(f"/api/notes/{n}", json={"body":
        "A host does not answer ping, but responds to TCP.\n\n"
        "## Quiz\n\nQ: Host does not answer ping — next?\n- [x] Check filtering\n- Reboot\n"
        "Why: answer ping is often filtered.\n"})
    for t in ("Answer Ping", "Ping", "Host"):
        c.post("/api/notes", json={"title": t})
    for term in ("answer ping", "Ping", "Host", "answer ping"):
        c.post("/api/suggestions/apply", json={"term": term, "target": None})
    txt = body_of(n)
    ck("no nested links", not re.search(r"!?\[\[[^\[\]]*\[\[", txt),
       re.findall(r"!?\[\[[^\]]*\[\[[^\]]*\]\][^\]]*\]\]", txt))
    ck("prose was still linked", "[[" in txt.split("## Quiz")[0])
    ck("quiz block has no markup", "[[" not in txt.split("## Quiz")[1],
       txt.split("## Quiz")[1].strip()[:60])
    ck("audit clean after linking", c.get("/api/audit").json()["clean"],
       c.get("/api/audit").json()["issues"][:2])

    print("\n── the real guide survives repeated auto-linking ──")
    c.post("/api/study/import", files={"file": ("g.py", io.BytesIO(
        open(os.path.join(os.path.dirname(__file__), "fixtures/fb_study_guide.py"), "rb").read()), "text/x-python")})
    before = c.get("/api/study").json()["totals"]["questions"]
    for _ in range(3):
        for s in c.get("/api/suggestions").json()[:4]:
            c.post("/api/suggestions/apply", json={"term": s["term"], "target": s["target"]})
    a = c.get("/api/audit").json()
    ck("no damage across 3 rounds", a["clean"], [i["sample"] for i in a["issues"]][:3])
    ck("every quiz question survived",
       c.get("/api/study").json()["totals"]["questions"] == before,
       f"{before} -> {c.get('/api/study').json()['totals']['questions']}")
    ck("no quiz option contains markup", all(
        "[[" not in o for it in c.get("/api/study").json()["items"]
        for q in c.get(f"/api/study/item/{it['slug']}").json()["quiz"] for o in q["options"]))

    print("\n── repairing pre-existing damage ──")
    d = c.post("/api/notes", json={"title": "Damaged"}).json()["slug"]
    c.put(f"/api/notes/{d}", json={"body":
        "Bad: [[Answer [[Ping]]|answer ping]] and [[Deep [[A]] [[B]]|d]] and [[]] husk.\n\n"
        "## Quiz\n\nQ: What is [[ICMP|icmp]]?\n- [x] A [[Protocol|protocol]]\n- No\n"
        "Why: see [[ICMP]].\n"})
    a = c.get("/api/audit").json()
    hit = [x for x in a["issues"] if x["slug"] == d]
    ck("audit finds it", bool(hit), [x["slug"] for x in a["issues"]])
    ck("counts both nested links", hit and hit[0]["nested"] == 6, hit[0] if hit else None)
    r = c.post("/api/repair").json()
    ck("repair reports it", r["changed"] >= 1, f"{r['changed']}/{r['scanned']}")
    fixed = body_of(d)
    ck("all nesting gone", not re.search(r"!?\[\[[^\[\]]*\[\[", fixed))
    ck("outer links kept", "[[Answer Ping|answer ping]]" in fixed and "[[Deep A B|d]]" in fixed,
       fixed.strip().splitlines()[0])
    ck("husk gone", "[[]]" not in fixed)
    ck("quiz is plain text again", "[[" not in fixed.split("## Quiz")[1])
    ck("display text preserved in quiz",
       "icmp" in fixed.split("## Quiz")[1] and "protocol" in fixed.split("## Quiz")[1])
    ck("audit clean", c.get("/api/audit").json()["clean"])
    ck("idempotent", c.post("/api/repair").json()["changed"] == 0)

    print("\n── junk phrase no longer proposed ──")
    for i in range(3):
        s2 = c.post("/api/notes", json={"title": f"Filler {i}"}).json()["slug"]
        c.put(f"/api/notes/{s2}", json={"body": "The host does not answer ping when filtered."})
    terms = [x["term"] for x in c.get("/api/suggestions").json()]
    ck("'answer ping' not suggested", "answer ping" not in terms, terms[:6])

print(f"\n{'='*46}\n  {ok} passed, {fail} failed\n{'='*46}")
raise SystemExit(1 if fail else 0)
