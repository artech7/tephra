"""Admin password lock: open by default, gates writes once set, session
cookies survive/invalidate the way require_admin and auth.py intend."""
import os, shutil
os.environ.setdefault("TEPHRA_CONFIG_DIR", os.path.realpath("/tmp") + "/tephra-test-admin-cfg/Tephra")
ROOT = os.path.realpath("/tmp") + "/tephra-test-admin-vault"
shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(os.environ["TEPHRA_CONFIG_DIR"], ignore_errors=True)
os.makedirs(ROOT, exist_ok=True)
os.environ.setdefault("TEPHRA_VAULT", ROOT)
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app import sessions as sess

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
    # Appearance is stored per vault, so it is shared -- one browser setting
    # the accent repaints it for everyone else on that vault. It is an edit.
    # The request is still accepted rather than 401'd, because the frontend
    # debounces appearance and the private session prefs into a single PUT;
    # rejecting it would drop a viewer's sort order too.
    was = c.get("/api/theme").json()["acc"]
    r = c.put("/api/theme", json={"acc": "1,1,1", "note_sort": "title"})
    ck("theme PUT is still accepted while locked", r.status_code == 200, r.status_code)
    ck("but the shared appearance is ignored", r.json()["acc"] == was,
       (r.json()["acc"], was))
    ck("...and never reaches the vault's theme.json",
       "1,1,1" not in (open(f"{ROOT}/theme.json").read()
                       if os.path.isfile(f"{ROOT}/theme.json") else ""))
    ck("...while the caller's own session prefs in the same PUT do apply",
       r.json()["note_sort"] == "title", r.json()["note_sort"])
    ck("...which a reread confirms, so nothing silently reverts",
       c.get("/api/theme").json() == {**r.json()}, c.get("/api/theme").json()["acc"])
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

    print("\n── unlocked: appearance writes through to the shared theme.json ──")
    c.post("/api/admin/login", json={"password": "correct horse battery"})
    r = c.put("/api/theme", json={"acc": "2,2,2"})
    ck("accepted while unlocked", r.status_code == 200, r.status_code)
    ck("and applied", r.json()["acc"] == "2,2,2", r.json()["acc"])
    ck("and on disk in the vault", "2,2,2" in open(f"{ROOT}/theme.json").read())

    print("\n── locked: switching vaults is allowed, but writes nothing ──")
    # Reading notes and taking quizzes is open while locked, so gating
    # /api/vault/open left a locked install able to read exactly one vault.
    # It is navigation -- it repoints only the requesting session.
    import json as _json
    OTHER = ROOT + "-other"
    shutil.rmtree(OTHER, ignore_errors=True)
    os.makedirs(OTHER + "/notes", exist_ok=True)
    with open(OTHER + "/notes/only-note.md", "w") as fh:
        fh.write("---\ntitle: Only Note\ntags: []\n---\n\nBody.\n")
    cfg_before = _json.load(open(os.environ["TEPHRA_CONFIG_DIR"] + "/config.json"))

    c.post("/api/admin/logout")
    ck("confirmed locked for this check", c.get("/api/admin/status").json()["unlocked"] is False)
    r = c.post("/api/vault/open", json={"path": OTHER})
    ck("a locked session may switch vaults", r.status_code == 200, r.text[:160])
    ck("and actually lands there", c.get("/api/vault/info").json()["vault"] == OTHER,
       c.get("/api/vault/info").json()["vault"])
    ck("...and can read its notes", any(n["slug"] == "only-note"
                                       for n in c.get("/api/notes").json()))
    ck("...and can take its quiz", c.get("/api/study/quiz").status_code == 200)

    # The three writes opening a vault would otherwise perform.
    ck("no example notes were seeded into it",
       sorted(os.listdir(OTHER + "/notes")) == ["only-note.md"],
       sorted(os.listdir(OTHER + "/notes")))
    ck("the install-wide default vault was not moved",
       _json.load(open(os.environ["TEPHRA_CONFIG_DIR"] + "/config.json"))["vault"]
       == cfg_before["vault"])
    ck("and it was not added to the shared recents list",
       OTHER not in _json.load(open(os.environ["TEPHRA_CONFIG_DIR"]
                                    + "/config.json"))["recent"])
    # Still pending after several later requests: the session middleware
    # resolves this vault on every one of them, and must not settle the
    # repair on a locked session's behalf.
    c.get("/api/notes"); c.get("/api/vault/info")
    ck("the repair was deferred, not silently skipped forever",
       sess.REGISTRY.existing(Path(OTHER)).repair_pending is True)

    print("\n── locked: creating, renaming and forgetting vaults stay gated ──")
    ck("create is refused", c.post("/api/vault/create",
                                   json={"path": ROOT + "-nope"}).status_code == 401)
    ck("...and created nothing on disk", not os.path.exists(ROOT + "-nope"))
    ck("rename is refused", c.post("/api/vault/rename",
                                   json={"name": "Renamed"}).status_code == 401)
    ck("forget is refused", c.post("/api/vault/forget",
                                   json={"path": ROOT}).status_code == 401)
    ck("editing a note in the opened vault is still refused",
       c.post("/api/notes", json={"title": "Nope"}).status_code == 401)

    print("\n── unlocking then reopening settles the deferred repair ──")
    c.post("/api/admin/login", json={"password": "third correct horse"})
    r = c.post("/api/vault/open", json={"path": OTHER})
    ck("reopen succeeds while unlocked", r.status_code == 200, r.text[:120])
    ck("the deferred repair has now run",
       sess.REGISTRY.existing(Path(OTHER)).repair_pending is False)
    ck("and an unlocked open does record it in recents",
       OTHER in _json.load(open(os.environ["TEPHRA_CONFIG_DIR"]
                                + "/config.json"))["recent"])
    c.post("/api/vault/open", json={"path": ROOT})

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
