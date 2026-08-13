"""Admin password lock: open by default, gates writes once set, session
cookies survive/invalidate the way require_admin and auth.py intend."""
import os, shutil
os.environ.setdefault("TEPHRA_CONFIG_DIR", os.path.realpath("/tmp") + "/tephra-test-admin-cfg/Tephra")
ROOT = os.path.realpath("/tmp") + "/tephra-test-admin-vault"
shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(os.environ["TEPHRA_CONFIG_DIR"], ignore_errors=True)
os.makedirs(ROOT, exist_ok=True)
os.environ.setdefault("TEPHRA_VAULT", ROOT)
from fastapi.testclient import TestClient
from app.main import app

ok = fail = 0
def ck(l, c, x=""):
    global ok, fail
    if c: ok += 1; print(f"  PASS  {l} {x}")
    else: fail += 1; print(f"  FAIL  {l} {x}")

with TestClient(app) as c:
    print("── no password ever set: fully open, matching pre-lock behaviour ──")
    s = c.get("/api/admin/status").json()
    ck("not configured", s == {"configured": False, "unlocked": False}, s)
    r = c.post("/api/notes", json={"title": "Before Lock"})
    ck("writes work with no admin password set", r.status_code == 200, r.text[:120])
    ck("theme writes work too (never gated)", c.put("/api/theme", json={"acc": "9,9,9"}).status_code == 200)

    print("\n── setting the password the first time needs no current_password ──")
    r = c.post("/api/admin/password", json={"password": "short"})
    ck("rejects an under-length password", r.status_code == 400, r.text[:100])
    r = c.post("/api/admin/password", json={"password": "correct horse battery"})
    ck("first-time set accepted", r.status_code == 200, r.text[:120])
    token_v1 = c.cookies.get("tephra_admin")
    ck("session cookie issued", bool(token_v1))
    s = c.get("/api/admin/status").json()
    ck("now configured and this session is unlocked", s == {"configured": True, "unlocked": True}, s)

    print("\n── locked: writes refused, reads and quiz-taking still work ──")
    c.post("/api/admin/logout")
    s = c.get("/api/admin/status").json()
    ck("logged out -> configured but not unlocked", s == {"configured": True, "unlocked": False}, s)
    r = c.post("/api/notes", json={"title": "Should Fail"})
    ck("note creation refused while locked", r.status_code == 401, r.status_code)
    ck("note is not actually on disk",
       not os.path.isfile(f"{ROOT}/notes/should-fail.md"))
    ck("reading notes still works locked", c.get("/api/notes").status_code == 200)
    ck("theme PUT still open while locked (left ungated on purpose)",
       c.put("/api/theme", json={"acc": "1,1,1"}).status_code == 200)
    ck("vault list still open while locked",
       c.get("/api/vault/list").status_code == 200)

    print("\n── wrong password refused, correct one unlocks ──")
    r = c.post("/api/admin/login", json={"password": "not it"})
    ck("wrong password rejected", r.status_code == 401, r.status_code)
    ck("still locked", c.get("/api/admin/status").json()["unlocked"] is False)
    r = c.post("/api/admin/login", json={"password": "correct horse battery"})
    ck("correct password unlocks", r.status_code == 200, r.text[:120])
    ck("status reflects it", c.get("/api/admin/status").json()["unlocked"] is True)
    r = c.post("/api/notes", json={"title": "After Unlock"})
    ck("writes work again once unlocked", r.status_code == 200, r.text[:120])
    ck("note actually landed on disk", os.path.isfile(f"{ROOT}/notes/after-unlock.md"))

    print("\n── changing the password always needs current_password, even while unlocked,\n"
          "   and invalidates every session signed under the old one ──")
    stray = TestClient(app)
    stray.cookies.set("tephra_admin", token_v1)
    ck("a second browser holding the original session is still valid pre-rotation",
       stray.get("/api/admin/status").json()["unlocked"] is True)
    r = c.post("/api/admin/password", json={"password": "second correct horse"})
    ck("refused with no current_password, even from an unlocked session", r.status_code == 401, r.status_code)
    r = c.post("/api/admin/password",
               json={"password": "second correct horse", "current_password": "wrong"})
    ck("refused with a wrong current_password too", r.status_code == 401, r.status_code)
    r = c.post("/api/admin/password",
               json={"password": "second correct horse", "current_password": "correct horse battery"})
    ck("accepted with the right current_password", r.status_code == 200, r.text[:120])
    token_v2 = c.cookies.get("tephra_admin")
    ck("rotation issues a fresh cookie", token_v2 and token_v2 != token_v1)
    ck("this session (the one that rotated it) stays unlocked",
       c.get("/api/admin/status").json()["unlocked"] is True)
    ck("the stray session on the old password is now locked out",
       stray.get("/api/admin/status").json()["unlocked"] is False)
    r = stray.post("/api/notes", json={"title": "Via Stray"})
    ck("...and can no longer write", r.status_code == 401, r.status_code)

    print("\n── changing the password locked-out (not unlocked) needs current_password ──")
    locked_client = TestClient(app)
    r = locked_client.post("/api/admin/password", json={"password": "third correct horse"})
    ck("refused with no current_password and no session", r.status_code == 401, r.status_code)
    r = locked_client.post("/api/admin/password",
                           json={"password": "third correct horse", "current_password": "wrong"})
    ck("refused with a wrong current_password", r.status_code == 401, r.status_code)
    r = locked_client.post("/api/admin/password",
                           json={"password": "third correct horse", "current_password": "second correct horse"})
    ck("accepted with the right current_password", r.status_code == 200, r.text[:120])
    ck("that browser is now unlocked too", locked_client.get("/api/admin/status").json()["unlocked"] is True)
    # c is still on the previous password's session token, but that token's
    # signature was made against the *previous* hash -- rotating from
    # locked_client just invalidated it exactly like the first rotation did.
    ck("meanwhile the original admin session (c) was invalidated by this rotation too",
       c.get("/api/admin/status").json()["unlocked"] is False)
    c.post("/api/admin/login", json={"password": "third correct horse"})

    print("\n── quiz-taking is intentionally left open regardless of lock state ──")
    c.post("/api/admin/logout")
    ck("confirmed locked for this check", c.get("/api/admin/status").json()["unlocked"] is False)
    quiz_before = c.get("/api/study").json()
    r = c.post("/api/study/prefs", json={"quiz_count": 7})
    ck("quiz prefs still writable while locked (left ungated on purpose)",
       r.status_code == 200, r.text[:120])
    c.post("/api/admin/login", json={"password": "third correct horse"})

    print("\n── login throttling: a burst of wrong guesses gets rate-limited ──")
    # TestClient's requests all share the same synthetic client host, so the
    # per-IP throttle bucket is really shared across every client used above
    # -- clear it explicitly rather than trying to account for every prior
    # login attempt in this file.
    from app import main as _main
    _main._login_attempts.clear()
    fresh = TestClient(app)
    codes = [fresh.post("/api/admin/login", json={"password": f"nope-{i}"}).status_code
             for i in range(9)]
    ck("first eight guesses are each just a plain 401",
       codes[:8] == [401] * 8, codes[:8])
    ck("ninth guess in the same window is throttled instead", codes[8] == 429, codes)

print(f"\n{'='*46}\n  {ok} passed, {fail} failed\n{'='*46}")
raise SystemExit(1 if fail else 0)
