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


print("── a session is written to disk as soon as it exists ──")
with TestClient(app) as c:
    c.get("/api/vault/info")
    sid = c.cookies.get(S.SESSION_COOKIE)
    ck("a cookie was issued", bool(sid), sid)
    ck("sessions.json lives in the config dir, not in a vault",
       SFILE.is_file() and not Path(A, "sessions.json").exists(), str(SFILE))
    ck("the new session is in the file", any(r["id"] == sid for r in rows()), rows())

    print("\n── vault switch and prefs are persisted ──")
    r = c.post("/api/vault/open", json={"path": B})
    ck("opened vault B", r.status_code == 200, r.text[:120])
    c.put("/api/theme", json={"note_sort": "title", "note_tag": "fabric",
                              "media_open": {"x": True}})
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
