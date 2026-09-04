"""Session persistence across a restart.

Sessions used to live only in app/sessions.py's module dict, so a container
restart silently moved every browser back to the default vault and lost any
in-flight view state. app/sessions.py now writes sessions.json into the same
platform config dir settings.py uses, and reloads it in main.py's lifespan.

"Restart" here means: clear the module-level _sessions dict, then enter a
second `TestClient(app)` lifespan in this same process. Clearing is the part
that makes the assertion mean anything -- without it the old dict is still
populated and a passing test would prove nothing about load() at all.
"""
import json, os, shutil, time
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
os.environ.setdefault("TEPHRA_CONFIG_DIR",
                      os.path.join(os.path.realpath("/tmp"), "tephra-test-sessions-cfg", "Tephra"))
BASE = os.path.join(os.path.realpath("/tmp"), "tephra-test-sessions")
shutil.rmtree(BASE, ignore_errors=True)
shutil.rmtree(os.environ["TEPHRA_CONFIG_DIR"], ignore_errors=True)
A = os.path.join(BASE, "vault-a")
B = os.path.join(BASE, "vault-b")
os.makedirs(A, exist_ok=True)
# B needs notes/ up front: /api/vault/open refuses a path that is not
# already a vault (looks_like_vault), so creating only the parent gets a 404.
os.makedirs(os.path.join(B, "notes"), exist_ok=True)
os.environ.setdefault("TEPHRA_VAULT", A)

from fastapi.testclient import TestClient
from app.main import app
from app import sessions as S

CFG = Path(os.environ["TEPHRA_CONFIG_DIR"])
SFILE = CFG / "sessions.json"

ok = fail = 0
def ck(l, c, x=""):
    global ok, fail
    if c: ok += 1; print(f"  PASS  {l} {x}")
    else: fail += 1; print(f"  FAIL  {l} {x}")

def restart():
    """Drop every trace of live session state, the way a new process would."""
    with S._sessions_lock:
        S._sessions.clear()
    S._last_write = 0.0

def rows():
    return json.loads(SFILE.read_text())["sessions"]

def clear_progress():
    """Wipe every vault's .sessions/ dir.

    Needed by any section asserting an exact session count, because the
    lifespan reconciles stranded progress on startup: a progress file an
    earlier section left behind is correctly *adopted* as a session, which
    is right for the app and fatal for a count assertion here.
    """
    for v in (A, B):
        d = Path(v, ".sessions")
        if d.is_dir():
            for f in d.glob("*"):
                f.unlink()


print("── a session is written to disk once it holds something ──")
with TestClient(app) as c:
    c.get("/api/vault/info")
    sid = c.cookies.get(S.SESSION_COOKIE)
    ck("a cookie was issued", bool(sid), sid)
    # Not on disk yet, on purpose: an untouched session is identical to one
    # minted free on the next request. See "a session with nothing in it is
    # never persisted" below for why writing them was actively harmful.
    ck("a bare session is not written yet", not SFILE.exists(), SFILE.exists())

    print("\n── vault switch and prefs are persisted ──")
    r = c.post("/api/vault/open", json={"path": B})
    ck("opened vault B", r.status_code == 200, r.text[:120])
    c.put("/api/theme", json={"note_sort": "title", "note_tag": "fabric",
                              "media_open": {"x": True}})
    ck("sessions.json lives in the config dir, not in a vault",
       SFILE.is_file() and not Path(A, "sessions.json").exists(), str(SFILE))
    ck("the session is now in the file", any(r["id"] == sid for r in rows()),
       [r["id"][:6] for r in rows()])
    row = next(r for r in rows() if r["id"] == sid)
    ck("file records vault B", row["vault"] == B, row["vault"])
    ck("file records note_sort", row["prefs"]["note_sort"] == "title", row["prefs"])
    ck("file records note_tag", row["prefs"]["note_tag"] == "fabric", row["prefs"])
    ck("file records media_open", row["prefs"]["media_open"] == {"x": True}, row["prefs"])

print("\n── the actual regression: that all survives a restart ──")
restart()
ck("in-memory state really was cleared", not S._sessions, S._sessions)
with TestClient(app) as c2:
    c2.cookies.set(S.SESSION_COOKIE, sid)
    info = c2.get("/api/vault/info").json()
    ck("returning browser lands back on vault B, not the default",
       info["vault"] == B, info["vault"])
    th = c2.get("/api/theme").json()
    ck("note_sort survived", th["note_sort"] == "title", th["note_sort"])
    ck("note_tag survived", th["note_tag"] == "fabric", th["note_tag"])
    ck("media_open survived", th["media_open"] == {"x": True}, th["media_open"])
    ck("no second session was minted for the same cookie",
       len(S._sessions) == 1, list(S._sessions))
    ck("appearance is still shared per-vault, not per-session",
       th["acc"] == "63,224,173", th["acc"])

print("\n── in-flight quiz progress reconnects across a restart ──")
# study.py keys progress at <vault>/.sessions/<session-id>-study-progress.json.
# That file was always on disk; what a restart used to break was the *id*
# needed to find it again, so a new session read an empty history while the
# old answers sat there unreachable. This is the "lost in-flight quiz
# progress" half of persisting sessions, and it is only true if the id is
# stable -- so assert on the id, not just on the numbers.
restart()
with TestClient(app) as cq:
    cq.cookies.set(S.SESSION_COOKIE, sid)
    cq.post("/api/study/flag", json={"qid": "q-restart-probe", "flagged": True})
    pfile = Path(B, ".sessions", f"{sid}-study-progress.json")
    ck("progress is namespaced under the session id", pfile.is_file(), str(pfile))

restart()
with TestClient(app) as cq2:
    cq2.cookies.set(S.SESSION_COOKIE, sid)
    flagged = json.loads(pfile.read_text())["flagged"]
    ck("the flag is still on disk after restart", "q-restart-probe" in flagged, flagged)
    live = next(iter(S._sessions.values()))
    ck("and the restored session still resolves to that same file",
       live.id == sid, (live.id, sid))
    ck("so nothing was orphaned under a fresh id",
       len(list(Path(B, ".sessions").glob("*-study-progress.json"))) == 1,
       [x.name for x in Path(B, ".sessions").glob("*")])

print("\n── a session whose vault is gone is pruned, not resurrected broken ──")
restart()
shutil.rmtree(B, ignore_errors=True)
with TestClient(app) as c3:
    c3.cookies.set(S.SESSION_COOKIE, sid)
    info = c3.get("/api/vault/info").json()
    ck("lands on the default vault instead of a missing path",
       info["vault"] == A, info["vault"])
    ck("and still serves requests", c3.get("/api/health").json()["ok"] is True)

print("\n── a session past the cookie's own Max-Age is pruned ──")
os.makedirs(B, exist_ok=True)
Path(B, "notes").mkdir(exist_ok=True)
SFILE.write_text(json.dumps({"sessions": [
    {"id": "staleoldsession", "vault": B, "prefs": {},
     "last_seen": time.time() - (S.SESSION_MAX_AGE + 60)},
    {"id": "freshsession", "vault": B, "prefs": {},
     "last_seen": time.time()},
]}))
restart()
ck("only the fresh one is restored", S.load() == 1, list(S._sessions))
ck("the expired id is gone", "staleoldsession" not in S._sessions, list(S._sessions))
ck("the fresh id is kept", "freshsession" in S._sessions, list(S._sessions))

print("\n── a corrupt or truncated sessions.json must not break boot ──")
restart()
SFILE.write_text("{ this is not json")
ck("load() reports nothing restored rather than raising", S.load() == 0)
with TestClient(app) as c4:
    ck("the app still boots and serves", c4.get("/api/health").json()["ok"] is True)
    # Not /api/health for the cookie check: that path deliberately issues
    # none (NO_SESSION_PATHS). Any normal endpoint still does.
    c4.get("/api/vault/info")
    ck("and issues a fresh session", bool(c4.cookies.get(S.SESSION_COOKIE)))

print("\n── two browsers on different vaults persist independently ──")
restart()
SFILE.unlink(missing_ok=True)
with TestClient(app) as one, TestClient(app) as two:
    one.get("/api/vault/info"); two.get("/api/vault/info")
    sid1 = one.cookies.get(S.SESSION_COOKIE)
    sid2 = two.cookies.get(S.SESSION_COOKIE)
    ck("two distinct sessions", sid1 != sid2, (sid1, sid2))
    one.post("/api/vault/open", json={"path": B})
    one.put("/api/theme", json={"note_sort": "title"})
    two.put("/api/theme", json={"note_sort": "created"})
    by_id = {r["id"]: r for r in rows()}
    ck("browser one persisted vault B", by_id[sid1]["vault"] == B, by_id[sid1]["vault"])
    ck("browser two stayed on vault A", by_id[sid2]["vault"] == A, by_id[sid2]["vault"])
    ck("their prefs did not clobber each other",
       (by_id[sid1]["prefs"]["note_sort"], by_id[sid2]["prefs"]["note_sort"])
       == ("title", "created"),
       (by_id[sid1]["prefs"], by_id[sid2]["prefs"]))

print("\n── a session with nothing in it is never persisted ──")
# The regression this missed. The container healthcheck hits /api/health
# every 30s with no cookie jar; each probe used to mint a session and force
# a write, ~2,880 a day. That filled MAX_SESSIONS in about four hours and
# then evicted *real* sessions, since save() keeps the most-recently-seen --
# so someone away for an afternoon lost the vault and quiz progress that
# persisting sessions exists to protect.
restart()
clear_progress()
SFILE.unlink(missing_ok=True)
with TestClient(app) as cp:
    for _ in range(25):
        cp.cookies.clear()                      # a fresh cookieless probe
        ck_status = cp.get("/api/health").status_code
    ck("health probes still answer", ck_status == 200, ck_status)
    ck("...and are not even given a session cookie",
       not cp.cookies.get(S.SESSION_COOKIE), dict(cp.cookies))
    ck("...and never reach the session table", not S._sessions, len(S._sessions))
    ck("...so sessions.json is never even created", not SFILE.exists())

restart()
with TestClient(app) as cb:
    cb.get("/api/vault/info")                   # a real browser: gets a cookie
    ck("a real request does get a session", len(S._sessions) == 1, len(S._sessions))
    ck("...but an untouched one is still not written to disk",
       not SFILE.exists() or not rows(), SFILE.exists())
    ck("...and is not yet notable",
       next(iter(S._sessions.values())).notable is False)
    # Any one of the three things worth restoring commits it.
    cb.put("/api/theme", json={"note_sort": "title"})
    ck("setting a pref commits it", bool(rows()), rows())
    ck("...and marks it notable", next(iter(S._sessions.values())).notable is True)

restart()
SFILE.unlink(missing_ok=True)
with TestClient(app) as cq3:
    cq3.get("/api/vault/info")
    ck("still not persisted before any quiz activity", not SFILE.exists())
    cq3.post("/api/study/flag", json={"qid": "notable-probe", "flagged": True})
    ck("recording quiz progress commits the session too", bool(rows()), rows())
    ck("...because the progress file is only findable by that id",
       next(iter(S._sessions.values())).notable is True)

print("\n── junk already on disk is cleaned out, not grandfathered in ──")
# The first cut trusted the file: a restored row was marked notable because
# it had been persisted, so every junk session written before probes stopped
# creating them was restored and written straight back out -- immortal.
# Observed live: 161 restored, 160 of them at the default vault with default
# prefs, and the file grew rather than shrank across the fix's own deploy.
restart()
clear_progress()
SFILE.unlink(missing_ok=True)
with TestClient(app) as cd:
    cd.put("/api/theme", json={"note_tag": "real-user"})
    keeper = cd.cookies.get(S.SESSION_COOKIE)
# Hand-write the shape the old bug produced: many default rows beside it.
existing = rows()
junk = [{"id": f"junkjunkjunk{i:04d}", "vault": A, "last_seen": time.time(),
         "prefs": {"note_sort": "updated", "note_tag": "", "media_open": {}}}
        for i in range(40)]
SFILE.write_text(json.dumps({"sessions": existing + junk}))
restart()
n = S.load()
ck("the default-vault, default-pref rows are dropped on load", n == 1, n)
ck("...and the real session is the one kept", keeper in S._sessions, list(S._sessions))
S.flush()
ck("...so one restart shrinks the file instead of preserving the junk",
   len(rows()) == 1, len(rows()))

# ...but not if something is actually attached to that id.
prog = Path(A, ".sessions")
prog.mkdir(parents=True, exist_ok=True)
(prog / "junkjunkjunk0007-study-progress.json").write_text(
    json.dumps({"answers": {"q1": {"seen": 1, "right": 1}}, "flagged": [], "settings": {}}))
SFILE.write_text(json.dumps({"sessions": existing + junk}))
restart()
S.load()
ck("a default-looking session with quiz progress behind it is kept",
   "junkjunkjunk0007" in S._sessions, sorted(S._sessions))
ck("...because dropping the id would orphan that progress file",
   (prog / "junkjunkjunk0007-study-progress.json").is_file())

print("\n── probe traffic cannot evict a real session ──")
restart()
clear_progress()
SFILE.unlink(missing_ok=True)
with TestClient(app) as real:
    real.put("/api/theme", json={"note_tag": "keepme"})
    keeper = real.cookies.get(S.SESSION_COOKIE)
    ck("the real session is on disk", any(r["id"] == keeper for r in rows()))
    with TestClient(app) as probe:
        for _ in range(S.MAX_SESSIONS + 50):
            probe.cookies.clear()
            probe.get("/api/health")
    ck("far more probes than MAX_SESSIONS did not grow the file",
       len(rows()) == 1, len(rows()))
    ck("...and the real session is still there",
       any(r["id"] == keeper for r in rows()), [r["id"][:6] for r in rows()])
    ck("...with its pref intact",
       next(r for r in rows() if r["id"] == keeper)["prefs"]["note_tag"] == "keepme")

print("\n── quiz progress with no session pointing at it ──")
# Found in a real vault: a progress file with 13 answers and 3 flagged
# questions, four days old, and no session in sessions.json naming it --
# stranded because sessions only started persisting after it was written.
# The browser holding that cookie would be handed a fresh id and read an
# empty history with its own answers sitting right beside it.
restart()
SFILE.unlink(missing_ok=True)
sdir = Path(B, ".sessions")
sdir.mkdir(parents=True, exist_ok=True)
for f in sdir.glob("*"):
    f.unlink()

real = sdir / ("stranded000000000000000000000001" + S.PROGRESS_SUFFIX)
real.write_text(json.dumps({"answers": {"q1": {"seen": 3, "right": 2}},
                            "flagged": ["q7"], "settings": {"quiz_count": 50}}))
bare = sdir / ("emptyprogress00000000000000000002" + S.PROGRESS_SUFFIX)
bare.write_text(json.dumps({"answers": {}, "flagged": [], "settings": {"quiz_count": 1}}))
stale = sdir / ("longexpired000000000000000000003" + S.PROGRESS_SUFFIX)
stale.write_text(json.dumps({"answers": {"old": {"seen": 1, "right": 1}}, "flagged": []}))
old_mtime = time.time() - (S.SESSION_MAX_AGE + 86400)
os.utime(stale, (old_mtime, old_mtime))

r = S.reconcile_progress([B])
ck("the file with real progress is adopted back", r["adopted"] == 1, r)
ck("...under its original id, which is what makes the cookie resolve",
   "stranded000000000000000000000001" in S._sessions, sorted(S._sessions))
ck("...pointing at the vault it was found in",
   str(S._sessions["stranded000000000000000000000001"].vault_path) == B)
ck("...and is persisted, so the next restart keeps it",
   any(x["id"] == "stranded000000000000000000000001" for x in rows()))
ck("the expired file is deleted -- no cookie can name it any more",
   r["reaped"] == 1 and not stale.exists(), (r, stale.exists()))
ck("a file holding only a quiz_count is neither adopted nor deleted",
   bare.exists() and "emptyprogress00000000000000000002" not in S._sessions)
ck("the adopted file itself is never touched",
   json.loads(real.read_text())["answers"] == {"q1": {"seen": 3, "right": 2}})

print("\n── an adopted session actually reconnects a returning browser ──")
with TestClient(app) as cr:
    cr.cookies.set(S.SESSION_COOKIE, "stranded000000000000000000000001")
    cr.post("/api/vault/open", json={"path": B})
    ck("the returning cookie was not replaced with a fresh id",
       cr.cookies.get(S.SESSION_COOKIE) == "stranded000000000000000000000001",
       cr.cookies.get(S.SESSION_COOKIE))
    # The real proof: a write from this browser has to land in the *same*
    # file, not a new one beside it. Reading it back through the API would
    # pass even if study.py had silently started a fresh history.
    cr.post("/api/study/flag", json={"qid": "q9", "flagged": True})
    after = json.loads(real.read_text())
    ck("...and a new answer lands in that same file",
       after["flagged"] == ["q7", "q9"], after["flagged"])
    ck("...with the pre-existing history still intact",
       after["answers"] == {"q1": {"seen": 3, "right": 2}}, after["answers"])
    ck("...and no second progress file was started for it",
       len(list(sdir.glob("stranded*"))) == 1,
       [f.name for f in sdir.glob("stranded*")])

print("\n── reconciling twice adopts nothing new ──")
r2 = S.reconcile_progress([B])
ck("idempotent", r2 == {"adopted": 0, "reaped": 0}, r2)

print("\n── a live session's progress is never reaped or re-adopted ──")
restart()
with TestClient(app) as cl:
    cl.post("/api/vault/open", json={"path": B})
    cl.post("/api/study/flag", json={"qid": "live-one", "flagged": True})
    sid_live = cl.cookies.get(S.SESSION_COOKIE)
    r3 = S.reconcile_progress([B])
    ck("the live session is left alone", r3["adopted"] == 0, r3)
    ck("...and its file survives",
       (sdir / (sid_live + S.PROGRESS_SUFFIX)).is_file())

print("\n── writes are throttled for a touch, immediate for a change ──")
restart()
with TestClient(app) as c5:
    c5.get("/api/vault/info")          # mints the session -> forced write
    before = SFILE.stat().st_mtime_ns
    time.sleep(0.01)
    for _ in range(5):
        c5.get("/api/vault/info")      # returning browser -> throttled
    ck("a plain request does not rewrite the file",
       SFILE.stat().st_mtime_ns == before)
    c5.put("/api/theme", json={"note_sort": "updated"})
    ck("a pref change rewrites it at once",
       SFILE.stat().st_mtime_ns != before)
    ck("no .tmp file is left behind",
       not list(CFG.glob("sessions.json.tmp")), list(CFG.glob("*.tmp")))

print("\n── an unwritable config dir complains instead of failing quietly ──")
ck("a writable config dir has nothing to say", S.check_writable() is None)
ro = Path(BASE, "readonly-cfg")
ro.mkdir(parents=True, exist_ok=True)
ro.chmod(0o500)                     # r-x: can traverse, cannot create
_saved_cfg = os.environ["TEPHRA_CONFIG_DIR"]
os.environ["TEPHRA_CONFIG_DIR"] = str(ro / "Tephra")
try:
    msg = S.check_writable()
    ck("an unwritable config dir is reported", bool(msg), msg)
    ck("the message names the reset symptom, not just errno",
       msg and "reset on every restart" in msg, msg)
    # The point of the probe: this is what stays silent without it.
    S.save(force=True)
    ck("save() on an unwritable dir still does not raise", True)
    ck("and leaves no .tmp turd behind",
       not list(ro.rglob("*.tmp")), list(ro.rglob("*")))
finally:
    os.environ["TEPHRA_CONFIG_DIR"] = _saved_cfg
    ro.chmod(0o700)

print("\n── unknown prefs are a caller error, not a silent no-op ──")
restart()
with TestClient(app) as c6:
    c6.get("/api/vault/info")
    try:
        S._current_session.set(next(iter(S._sessions.values())))
        S.update_prefs(note_sort="title", bogus_pref=1)
        ck("update_prefs rejected an unknown key", False, "no TypeError raised")
    except TypeError as e:
        ck("update_prefs rejected an unknown key", "bogus_pref" in str(e), str(e))

shutil.rmtree(BASE, ignore_errors=True)
print(f"\n{'='*46}\n  {ok} passed, {fail} failed\n{'='*46}")
raise SystemExit(1 if fail else 0)
