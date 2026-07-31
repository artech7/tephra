"""
Content integrity: detecting and repairing malformed links.

Note the ordering: the app repairs on open, so damage has to be planted *after*
the client starts and picked up with a reindex. Writing the files first meant
startup healed them before the first assertion ran.
"""
import os, shutil

V = os.environ.setdefault("TEPHRA_VAULT", "/tmp/tephra-test-repair")
shutil.rmtree(V, ignore_errors=True)
os.makedirs(f"{V}/notes", exist_ok=True)

from fastapi.testclient import TestClient
from app.main import app

ok = fail = 0
def ck(l, c, x=""):
    global ok, fail
    if c: ok += 1; print(f"  PASS  {l} {x}")
    else: fail += 1; print(f"  FAIL  {l} {x}")

body = lambda n: open(f"{V}/notes/{n}").read()
write = lambda n, t: open(f"{V}/notes/{n}", "w").write(t)

# The exact damage reported in the field.
DAMAGED = """---
title: ICMP
tags: [study, nf]
study: true
category: Networking Fundamentals
question: What is [[ICMP]] and what does [[Answer [[Ping]]|answer ping]] mean?
---

**ICMP** is used by [[Answer [[Ping]]|answer ping]] tooling, twice: [[Answer [[Ping]]|answer ping]].

## Quiz

Q: A host does not [[Answer [[Ping]]|answer ping]], but its web service on 443 responds normally. What is the most likely explanation?
- [x] A firewall drops [[ICMP]] but permits tcp/443
- The host is [[Down]]
Why: [[ICMP]] and tcp/443 are filtered independently.
"""
DEEP = """---
title: Deep
tags: []
---

Nested three deep: [[A [[B [[C]]]]|shown]] plus an empty husk [[]].
"""
CLEAN = """---
title: Clean
tags: []
---

A real alias [[Ping|pinging]] and a plain [[Ping]] link.

An embed: ![[diagram.png]]

Inline code `[[Ping]]` and a fence:

```
[[Ping]] inside a fence
```
"""

with TestClient(app) as c:
    print("── plant damage in a running vault ──")
    write("icmp.md", DAMAGED)
    write("deep.md", DEEP)
    write("clean.md", CLEAN)
    clean_before = body("clean.md")
    c.post("/api/reindex")

    a = c.get("/api/audit").json()
    ck("audit reports damage", a["clean"] is False)
    slugs = {i["slug"] for i in a["issues"]}
    ck("finds both damaged notes", {"icmp", "deep"} <= slugs, sorted(slugs))
    ck("leaves the clean note out", "clean" not in slugs)
    ck("counts nesting", any(i["nested"] for i in a["issues"]))
    ck("flags links in quiz blocks", any(i["quiz_links"] for i in a["issues"]))
    ck("flags empty husks", any(i["empty"] for i in a["issues"]))
    ck("audit itself writes nothing", body("clean.md") == clean_before)

    print("\n── display is already clean, before any repair ──")
    it = c.get("/api/study/item/icmp").json()
    ck("quiz question shows plain text",
       it["quiz"][0]["question"].startswith("A host does not answer ping,"),
       it["quiz"][0]["question"][:52])
    ck("options plain", all("[[" not in o for o in it["quiz"][0]["options"]), it["quiz"][0]["options"])
    ck("explanation plain", "[[" not in it["quiz"][0]["why"])
    ck("flashcard question plain", "[[" not in (it["question"] or ""), it["question"])
    ck("rendered prose has no bracket soup", "[[" not in it["html"])

    print("\n── dry run previews without writing ──")
    snapshot = {n: body(n) for n in ("icmp.md", "deep.md", "clean.md")}
    d = c.post("/api/repair", params={"dry_run": "true"}).json()
    ck("reports dry_run", d["dry_run"] is True)
    ck("counts what it would change", d["changed"] == 2, d["changed"])
    ck("supplies a before/after preview",
       any(x.get("preview", {}).get("before") for x in d["notes"]))
    ck("wrote nothing", all(body(n) == snapshot[n] for n in snapshot))

    print("\n── repair the files ──")
    r = c.post("/api/repair").json()
    ck("rewrote both damaged notes", r["changed"] == 2, r["changed"])
    icmp = body("icmp.md")
    ck("the reported string is gone", "[[Answer [[Ping]]" not in icmp)
    ck("prose kept a single real link", icmp.count("[[Answer Ping|answer ping]]") == 2,
       icmp.count("[[Answer Ping|answer ping]]"))
    ck("quiz question is plain in the file",
       "Q: A host does not answer ping, but its web service on 443" in icmp)
    ck("frontmatter question repaired",
       "question: What is ICMP and what does answer ping mean?" in icmp,
       [l for l in icmp.splitlines() if l.startswith("question:")])
    ck("three-deep nesting flattened", "[[A B C|shown]]" in body("deep.md"))
    ck("empty husk removed", "[[]]" not in body("deep.md"))

    print("\n── quiz structure survives the rewrite ──")
    quiz = icmp.split("## Quiz", 1)[1]
    ck("no links left in the quiz block", "[[" not in quiz)
    ck("answer marker intact", "- [x] A firewall drops ICMP but permits tcp/443" in quiz)
    ck("why text intact", "ICMP and tcp/443 are filtered independently." in quiz)
    item = c.get("/api/study/item/icmp").json()
    ck("still parses as one question", len(item["quiz"]) == 1)
    ck("options preserved",
       item["quiz"][0]["options"] == ["A firewall drops ICMP but permits tcp/443", "The host is Down"],
       item["quiz"][0]["options"])
    ck("correct answer preserved", item["quiz"][0]["answer"] == 0)

    print("\n── legitimate content is byte-identical ──")
    ck("clean note untouched", body("clean.md") == clean_before)
    for frag in ("[[Ping|pinging]]", "![[diagram.png]]", "`[[Ping]]`", "[[Ping]] inside a fence"):
        ck(f"survived: {frag}", frag in body("clean.md"))

    print("\n── idempotent ──")
    ck("second repair is a no-op", c.post("/api/repair").json()["changed"] == 0)
    ck("audit now clean", c.get("/api/audit").json()["clean"] is True)

    print("\n── the auto-linker cannot recreate it ──")
    s = c.post("/api/notes", json={"title": "Fresh"}).json()["slug"]
    c.put(f"/api/notes/{s}", json={"body": "You should answer ping quickly and answer ping often."})
    for term in ("answer ping", "Ping", "answer", "ping"):
        c.post("/api/suggestions/apply", json={"term": term, "target": None})
    after = c.get("/api/audit").json()
    ck("no nesting after repeated linking", after["clean"] is True,
       str(after.get("issues"))[:110])
    ck("quiz blocks were never touched",
       "[[" not in body("icmp.md").split("## Quiz", 1)[1])

print("\n── and repair runs automatically on the next open ──")
write("relapse.md", DEEP.replace("title: Deep", "title: Relapse"))
with TestClient(app) as c:
    ck("startup healed the new damage", c.get("/api/audit").json()["clean"] is True)
    ck("file rewritten on disk", "[[]]" not in body("relapse.md"))

print(f"\n{'='*46}\n  {ok} passed, {fail} failed\n{'='*46}")
raise SystemExit(1 if fail else 0)
