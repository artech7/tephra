"""Vault switching and multi-format import."""
import io, json, os, shutil, sys
from pathlib import Path
os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/tephra-test-cfg")
# Everything under one parent that gets wiped: rename creates sibling folders,
# and a leftover target from a previous run made the rename fail with a 409
# that surfaced as a confusing KeyError.
ROOT = "/tmp/tephra-test-vaults"
shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(os.environ["XDG_CONFIG_HOME"], ignore_errors=True)
os.makedirs(ROOT, exist_ok=True)
A = os.environ.setdefault("TEPHRA_VAULT", f"{ROOT}/vault-a")
B = f"{ROOT}/vault-b"
from fastapi.testclient import TestClient
from app.main import app
from app import importers as I

ok = fail = 0
def ck(l, c, x=""):
    global ok, fail
    if c: ok += 1; print(f"  PASS  {l} {x}")
    else: fail += 1; print(f"  FAIL  {l} {x}")

print("── answer resolution, the part that silently drops questions ──")
opts = ["RAID 0", "RAID 1", "RAID 5"]
ck("option text beats index reading", I._resolve_answer("9000", ["1500", "9000"]) == 1)
ck("letter", I._resolve_answer("B", opts) == 1)
ck("exact text", I._resolve_answer("RAID 1", opts) == 1)
ck("json 0-based", I._resolve_answer(1, opts) == 1)
ck("csv 1-based", I._resolve_answer(2, opts, one_based=True) == 1)
ck("out-of-range falls back to the other base", I._resolve_answer(3, opts, one_based=True) == 2)
for bad in ("", None, True, "nope"):
    try: I._resolve_answer(bad, opts); ck(f"rejects {bad!r}", False)
    except I.ImportError_: ck(f"rejects {bad!r}", True)

print("\n── each format parses to the same shape ──")
py = 'TOPICS=[dict(id="r",cat="Storage",title="RAID",q="Levels?",a="body")]\nQUIZ=[dict(t="r",q="Q?",o=["a","b"],a=1,why="w")]'
js = json.dumps({"topics": [{"id": "r", "category": "Storage", "title": "RAID", "question": "Levels?",
    "answer": "body", "quiz": [{"question": "Q?", "options": ["a", "b"], "answer": 1, "why": "w"}]}]})
cs = "category,title,answer,question,option_a,option_b,correct,why\nStorage,RAID,body,Q?,a,b,b,w\n"
shapes = []
for name, src in (("g.py", py), ("g.json", js), ("g.csv", cs)):
    t = I.parse(name, src)
    shapes.append((t[0]["title"], t[0]["category"], len(t[0]["quiz"]), t[0]["quiz"][0]["answer"]))
    ck(f"{name} parses", t[0]["title"] == "RAID" and len(t[0]["quiz"]) == 1, shapes[-1])
ck("all three agree", len(set(shapes)) == 1, shapes)

print("\n── content sniffing when the extension lies ──")
ck("json without .json", I.parse("mystery", js)[0]["title"] == "RAID")
ck("python without .py", I.parse("mystery", py)[0]["title"] == "RAID")

with TestClient(app) as c:
    print("\n── vault switching ──")
    ck("starts in A", c.get("/api/vault/info").json()["vault"] == A)
    c.post("/api/study/import", files={"file": ("g.json", io.BytesIO(js.encode()), "application/json")})
    ck("A has the topic", c.get("/api/study").json()["totals"]["topics"] == 1)

    r = c.post("/api/vault/create", json={"path": B})
    ck("created B", r.status_code == 200 and r.json()["created"])
    ck("B is empty of study items", c.get("/api/study").json()["totals"]["topics"] == 0)
    c.post("/api/notes", json={"title": "Only in B"})
    ck("B's note is only in B",
       os.path.isfile(f"{B}/notes/only-in-b.md") and not os.path.isfile(f"{A}/notes/only-in-b.md"))

    ck("theme set in B", c.put("/api/theme", json={"acc": "1,2,3"}).json()["acc"] == "1,2,3")
    ck("theme.json written inside B", os.path.isfile(f"{B}/theme.json"))
    ck("B's index lives in B", os.path.isfile(f"{B}/.index/index.db"))
    c.post("/api/vault/open", json={"path": A})
    ck("A kept its own theme", c.get("/api/theme").json()["acc"] != "1,2,3",
       c.get("/api/theme").json()["acc"])
    ck("A has its own index file", os.path.isfile(f"{A}/.index/index.db"))
    ck("A's content intact", c.get("/api/study").json()["totals"]["topics"] == 1)

    print("\n── refusals leave the current vault alone ──")
    for path, code in ((".", 400), ("/tmp/does-not-exist-x", 404), ("/", 400)):
        ck(f"refuses {path!r}", c.post("/api/vault/open", json={"path": path}).status_code in (code, 400, 404))
    ck("still in A", c.get("/api/vault/info").json()["vault"] == A)
    ck("create over an existing vault refused", c.post("/api/vault/create", json={"path": A}).status_code == 409)

    print("\n── recents live outside every vault ──")
    l = c.get("/api/vault/list").json()
    ck("both listed", {x["path"] for x in l["recent"]} >= {A, B}, [x["path"] for x in l["recent"]])
    ck("config not inside a vault",
       os.path.isfile(f"{os.environ['XDG_CONFIG_HOME']}/Tephra/config.json")
       and not os.path.exists(f"{A}/config.json"))

    print("\n── renaming the vault folder ──")
    import json as _json
    n0 = len(c.get("/api/notes").json())
    resp = c.post("/api/vault/rename", json={"name": "renamed-a"})
    ck("rename accepted", resp.status_code == 200, f"{resp.status_code} {resp.text[:80]}")
    r = resp.json()
    NEW = os.path.join(os.path.dirname(A), "renamed-a")
    ck("renamed", r.get("renamed") and r.get("vault") == NEW, r.get("vault"))
    ck("folder moved", os.path.isdir(NEW) and not os.path.exists(A))
    ck("notes came with it", len(c.get("/api/notes").json()) == n0)
    ck("app serves the new path", c.get("/api/vault/info").json()["vault"] == NEW)
    ck("writes land in the new folder",
       c.post("/api/notes", json={"title": "Post Rename"}).status_code == 200
       and os.path.isfile(f"{NEW}/notes/post-rename.md"))
    cfgf = _json.load(open(f"{os.environ['XDG_CONFIG_HOME']}/Tephra/config.json"))
    ck("config follows", cfgf["vault"] == NEW, cfgf["vault"])
    ck("no dead recents entry", A not in cfgf["recent"], cfgf["recent"])

    # macOS is case-insensitive, so this is the common case, not an edge one
    r = c.post("/api/vault/rename", json={"name": "RENAMED-A"}).json()
    ck("case-only rename works", r["vault"].endswith("RENAMED-A"), r["vault"])
    ck("vault still readable", len(c.get("/api/notes").json()) == n0 + 1)

    os.makedirs(os.path.join(os.path.dirname(A), "occupied"), exist_ok=True)
    for name, code, why in [("", 400, "empty"), ("a/b", 400, "a path"),
                            ("..", 400, "dot-dot"), ("occupied", 409, "an existing folder"),
                            ("x" * 200, 400, "an over-long name")]:
        ck(f"refuses {why}", c.post("/api/vault/rename", json={"name": name}).status_code == code)
    ck("vault intact after refusals", len(c.get("/api/notes").json()) == n0 + 1)
    A = r["vault"]        # later assertions use the current path

    print("\n── a failed rename must not hide the vault ──")
    # The two-step case-only move parks the folder under a dot-prefixed name,
    # which Finder does not show. If step two fails it has to be put back.
    import unittest.mock as _mock
    cur = c.get("/api/vault/info").json()["vault"]
    n_before = len(c.get("/api/notes").json())
    real_rename = os.rename
    calls = {"n": 0}
    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:          # fail the second move only
            raise OSError("simulated failure")
        return real_rename(src, dst)
    base = os.path.basename(cur)
    flipped = base.lower() if base != base.lower() else base.upper()
    ck("test uses a genuinely different name", flipped != base, f"{base} -> {flipped}")
    with _mock.patch("pathlib.Path.rename", autospec=True,
                     side_effect=lambda self, t: flaky(str(self), str(t))):
        resp = c.post("/api/vault/rename", json={"name": flipped})
    ck("failure reported", resp.status_code == 400, f"{resp.status_code} {resp.text[:70]}")
    ck("vault put back where it was", os.path.isdir(cur), cur)
    ck("no hidden folder left behind",
       not list(Path(cur).parent.glob(".*.tephra-renaming")),
       [p.name for p in Path(cur).parent.glob(".*")])
    ck("still serving it", c.get("/api/vault/info").json()["vault"] == cur)
    ck("notes intact", len(c.get("/api/notes").json()) == n_before, len(c.get("/api/notes").json()))

    print("\n── formats endpoint matches the parsers ──")
    f = c.get("/api/study/formats").json()
    ck("advertises what it accepts", set(f["accepted"]) == set(I.ACCEPTED))
    ck("every advertised format has an example", all(x["example"] for x in f["formats"]))
    for fmt in f["formats"]:
        if fmt["id"] == "markdown": continue
        try:
            t = I.parse("x" + fmt["extensions"][0], fmt["example"])
            ck(f"the {fmt['id']} example actually imports", len(t) >= 1, f"{len(t)} topic(s)")
        except I.ImportError_ as e:
            ck(f"the {fmt['id']} example actually imports", False, str(e)[:60])

print(f"\n{'='*46}\n  {ok} passed, {fail} failed\n{'='*46}")
raise SystemExit(1 if fail else 0)
