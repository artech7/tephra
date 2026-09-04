"""
Per-browser sessions, without login.

Tephra was built single-user: one running process, one vault, one SQLite
connection, all held as plain module globals. That's fine on a laptop. It
falls over the moment two browsers hit the same server -- there was no
notion of "whose" vault, "whose" current note, or "whose" quiz progress a
request was even about, so one person's navigation or quiz answer bled
into everyone else's view.

This module doesn't add accounts. There's still no password, no identity,
nothing to log in to (that's a separate, later piece -- LDAP or otherwise).
What it adds is an anonymous session: a random id in a cookie, set the
first time a browser shows up, used only to answer "is this the same
browser as last time" -- never "who is this."

A session owns:
  - which vault path it's currently pointed at (switchable independently
    of every other session)
  - its own view preferences (sort order, tag filter, media-panel state)
    that used to live in a shared theme.json and clash across browsers
  - (via study.py) its own quiz/flashcard progress per vault

A session does NOT own:
  - the notes, media, or index of a vault -- those stay exactly as shared
    as they were, which is the point: people looking at the same vault see
    the same content, just from independent seats.
  - the admin edit-lock -- that remains one shared install-wide toggle
    (auth.py), unrelated to identity.

VaultRegistry holds one SQLite connection per distinct *resolved vault
path*, not one per session -- two sessions pointed at the same vault share
one connection (exactly like today, safe: index.Conn already serialises
access with its own lock), while two sessions pointed at different vaults
each get their own, fully independent connection.
"""
from __future__ import annotations

import contextvars
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fastapi import Request

from . import index as idx
from . import settings as cfg
from . import vault

SESSION_COOKIE = "tephra_sid"
# ~13 months -- past the point where cookies are session-only in most
# browsers, so "keep coming back to the vault I had open" survives a
# browser restart, not just a tab refresh.
SESSION_MAX_AGE = 400 * 24 * 3600

# Sessions live in the platform config dir, next to config.json, for the
# same reason config.json does: a session says *which vault* it is pointed
# at, so it cannot live inside a vault without becoming unreadable the
# moment someone switches away from that vault.
SESSIONS_FILE = "sessions.json"

# Every request touches its session's last_seen. Rewriting the file for a
# timestamp bump on every request would be a write per request forever, so
# a plain touch is throttled to this; anything that actually *changes* what
# a session is (born, vault switched, prefs edited) writes immediately.
TOUCH_THROTTLE = 3600

# Ceiling on what we keep, most-recently-seen first. Pruning on load only
# bounds a process that restarts; a container that stays up for months
# would otherwise grow this file without limit.
MAX_SESSIONS = 500

# Requests that must never mint a session. The container healthcheck hits
# /api/health every 30s with no cookie jar, so before this each probe was a
# brand-new session, force-written to disk: ~2,880 a day, which filled
# MAX_SESSIONS in about four hours and then began *evicting real people*,
# since save() keeps the most-recently-seen. Someone away for an afternoon
# would come back to a fresh default session -- precisely the data loss
# persisting sessions was meant to prevent. These still get a working vault
# context (health calls db()); they just stay anonymous and unrecorded.
NO_SESSION_PATHS = frozenset({"/api/health"})


# ── vault registry ──────────────────────────────────────────────────────────

@dataclass
class VaultHandle:
    path: Path
    con: "idx.Conn"
    # What the self-heal pass fixed the moment this vault was first opened
    # by *any* session -- shown once as a toast, then cleared. Lives on the
    # vault handle rather than per-session: the repair happens once for the
    # vault, not once per browser that happens to look at it.
    last_repair: dict | None = None
    # Set when this vault was first opened by a caller not allowed to write
    # to it (a locked, read-only session). The link repair is a *markdown
    # rewrite*, so a viewer must not trigger one -- but get_or_create only
    # runs its body once per path, so skipping it outright would mean the
    # vault silently never got repaired for the rest of the process, just
    # because a viewer happened to look at it first. Remember instead, and
    # let the first writable caller do it.
    repair_pending: bool = False


class VaultRegistry:
    """One VaultHandle per resolved vault path, shared by every session
    pointed at that path."""

    def __init__(self) -> None:
        self._by_path: dict[str, VaultHandle] = {}
        self._lock = threading.Lock()

    def get_or_create(self, path: Path,
                       on_create: Callable[[Path, "idx.Conn"], None] | None = None,
                       repair: bool = True,
                       ) -> VaultHandle:
        key = str(path)
        with self._lock:
            handle = self._by_path.get(key)
            if handle is not None:
                # A writable caller arriving after a read-only one settles
                # the repair that was deferred above.
                if repair and handle.repair_pending:
                    fixed = idx.repair_links(handle.con)
                    if fixed["changed"]:
                        idx.rebuild(handle.con)
                        handle.last_repair = fixed
                    handle.repair_pending = False
                return handle
            # Only the thread that finds nothing builds the connection --
            # ensure_dirs/connect/init/seed/rebuild/repair all happen once
            # per vault path, not once per session that happens to open it.
            vault.set_current(path)
            con = idx.connect()
            idx.init(con)
            if on_create:
                on_create(path, con)          # e.g. seed example notes if empty
            idx.rebuild(con)
            fixed = {"changed": 0}
            if repair:
                fixed = idx.repair_links(con)
                if fixed["changed"]:
                    idx.rebuild(con)
            handle = VaultHandle(path=path, con=con,
                                  last_repair=fixed if fixed["changed"] else None,
                                  repair_pending=not repair)
            self._by_path[key] = handle
            return handle

    def existing(self, path: Path) -> VaultHandle | None:
        with self._lock:
            return self._by_path.get(str(path))

    def drop(self, path: Path) -> None:
        """Remove a path's registry entry without closing its connection --
        the caller closes it first (see vault_rename in main.py, which has
        to retire exactly one path's entry mid-rename without disturbing
        any other vault's connection)."""
        with self._lock:
            self._by_path.pop(str(path), None)

    def sessions_using(self, path: Path) -> int:
        """How many live sessions currently point at this vault -- used to
        refuse a folder rename/trash while more than the requester has it
        open, since renaming the directory out from under another session's
        open connection is the kind of thing that should require everyone
        else to switch away first, not happen invisibly underneath them."""
        key = str(Path(path).expanduser().resolve())
        with _sessions_lock:
            return sum(1 for s in _sessions.values() if str(s.vault_path) == key)

    def paths(self) -> list[str]:
        with self._lock:
            return list(self._by_path.keys())


REGISTRY = VaultRegistry()


# ── per-session state ────────────────────────────────────────────────────────

@dataclass
class SessionPrefs:
    """UI view-state that used to live in a shared theme.json -- per
    session now, and persisted (see save()/load() below) rather than held
    only in memory.

    In-memory was the original call here, on the grounds that this state is
    disposable. That reasoning came from the laptop case, where a restart
    is something you did to yourself and the vault you land back on is the
    only one you had. Under Docker a restart is someone else's deploy: it
    silently moved every browser back to the default vault, which for a
    person whose own vault was not the default read as their notes being
    gone."""
    note_sort: str = "updated"
    note_tag: str = ""
    media_open: dict = field(default_factory=dict)


@dataclass
class Session:
    id: str
    vault_path: Path
    prefs: SessionPrefs = field(default_factory=SessionPrefs)
    # Wall-clock of the last request on this session. Only used to decide
    # what to prune on load -- never shown, never compared between
    # sessions, so clock skew across a restart is harmless.
    last_seen: float = field(default_factory=time.time)
    # Whether this session holds anything a restart would actually lose:
    # a vault it switched to, prefs it set, quiz progress it recorded.
    # Until then it is identical to one we would mint for free on the next
    # request, so persisting it is pure noise -- and worse than noise once
    # MAX_SESSIONS starts evicting real sessions to make room for probes.
    notable: bool = False

    def as_row(self) -> dict:
        return {
            "id": self.id,
            "vault": str(self.vault_path),
            "last_seen": self.last_seen,
            "prefs": {
                "note_sort": self.prefs.note_sort,
                "note_tag": self.prefs.note_tag,
                "media_open": self.prefs.media_open,
            },
        }


_sessions: dict[str, Session] = {}
_sessions_lock = threading.Lock()

# Set once per incoming request by session_middleware, read by db()/current
# session lookups anywhere downstream in that same request -- including
# inside the threadpool FastAPI runs sync endpoints in, since anyio copies
# the calling context into the worker thread.
_current_session: contextvars.ContextVar[Session] = contextvars.ContextVar("tephra_session")
_current_con: contextvars.ContextVar["idx.Conn"] = contextvars.ContextVar("tephra_con")


def current_session() -> Session:
    return _current_session.get()


def current_con() -> "idx.Conn":
    return _current_con.get()


# ── persistence ─────────────────────────────────────────────────────────────

_last_write = 0.0
_write_lock = threading.Lock()


def _sessions_file() -> Path:
    # Resolved per call, not cached: tests point TEPHRA_CONFIG_DIR somewhere
    # throwaway, and config_dir() already reads that env var every time.
    return cfg.config_dir() / SESSIONS_FILE


def check_writable() -> str | None:
    """Probe the config dir once at startup. Returns a complaint, or None.

    save() and settings.save() both swallow OSError on purpose -- a config
    dir we cannot write must not fail requests. The cost is that the whole
    persistence layer degrades *silently*, and its failure mode (everyone
    back on the default vault after a restart) is indistinguishable from
    the bug persisting sessions was meant to fix.

    The realistic trigger is a container: if the host side of the
    ./config:/config bind mount does not exist yet, Docker creates it
    root-owned, and the non-root image user cannot write it. Same story if
    the image was built without matching UID/GID. Both deserve a line in
    the log rather than months of quietly forgotten preferences.
    """
    d = cfg.config_dir()
    probe = d / ".write-probe"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe.write_text("")
        probe.unlink()
        return None
    except OSError as e:
        return (f"config dir {d} is not writable ({e.strerror}) -- vault "
                f"choice and sessions will reset on every restart. If this "
                f"is Docker, check the ./config mount exists and is owned "
                f"by the image's UID.")


def save(force: bool = False) -> None:
    """Write every live session to disk.

    `force` for anything that changed what a session *is*; the default
    throttles, so the last_seen touch every request performs does not turn
    into a file write every request.
    """
    global _last_write
    now = time.time()
    with _write_lock:
        if not force and now - _last_write < TOUCH_THROTTLE:
            return
        with _sessions_lock:
            live = sorted((x for x in _sessions.values() if x.notable),
                          key=lambda x: x.last_seen, reverse=True)
        rows = [x.as_row() for x in live[:MAX_SESSIONS]]
        f = _sessions_file()
        tmp = f.parent / (f.name + ".tmp")
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"sessions": rows}, indent=2))
            # Atomic swap. A half-written sessions.json is worse than none:
            # it would parse as garbage on the next boot and drop everyone
            # to the default vault, which is the exact failure persisting
            # this was meant to remove.
            os.replace(tmp, f)
            _last_write = now
        except OSError:
            # Same posture as settings.save(): a read-only or full config
            # dir degrades to "sessions don't survive restart", which is
            # where we started. It must never fail a request.
            try:
                tmp.unlink()
            except OSError:
                pass


def load() -> int:
    """Restore sessions from disk. Returns how many survived pruning."""
    f = _sessions_file()
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return 0

    now = time.time()
    restored: dict[str, Session] = {}
    for row in (data.get("sessions") if isinstance(data, dict) else None) or []:
        if not isinstance(row, dict):
            continue
        sid = row.get("id")
        raw_vault = row.get("vault")
        if not isinstance(sid, str) or not isinstance(raw_vault, str):
            continue
        try:
            last_seen = float(row.get("last_seen") or 0)
        except (TypeError, ValueError):
            continue
        # Past the cookie's own Max-Age no browser can still present this
        # id, so the record is unreachable by definition.
        if now - last_seen > SESSION_MAX_AGE:
            continue
        # The vault moved, was deleted, or (under Docker) its volume is not
        # mounted this time. Dropping the session lands that browser on the
        # default vault -- the old behaviour -- instead of pointing it at a
        # path that would fail on every request.
        if not vault.looks_like_vault(raw_vault):
            continue
        prefs_in = row.get("prefs")
        prefs_in = prefs_in if isinstance(prefs_in, dict) else {}
        media_open = prefs_in.get("media_open")
        restored[sid] = Session(
            id=sid,
            vault_path=Path(raw_vault).expanduser().resolve(),
            last_seen=last_seen,
            prefs=SessionPrefs(
                note_sort=str(prefs_in.get("note_sort") or "updated"),
                note_tag=str(prefs_in.get("note_tag") or ""),
                media_open=media_open if isinstance(media_open, dict) else {},
            ),
            notable=True,   # it was on disk, so it earned its place already
        )

    with _sessions_lock:
        _sessions.update(restored)
    return len(restored)


def mark_notable(sess: "Session | None" = None) -> None:
    """Record that this session now holds something worth restoring, and
    persist it. Called on vault switch, pref change, and quiz progress."""
    sess = sess if sess is not None else current_session()
    sess.notable = True
    save(force=True)


def flush() -> None:
    """Persist unconditionally -- called on shutdown, where the throttle
    would otherwise discard up to an hour of last_seen touches."""
    save(force=True)


def update_prefs(**changes) -> SessionPrefs:
    """Apply view-pref changes to the current session and persist at once.

    Keyword-per-pref with a None sentinel rather than a dict merge, so
    clearing a pref (note_tag="") is expressible and an unknown key is a
    TypeError here instead of a silently ignored no-op at the caller.
    """
    sess = current_session()
    prefs = sess.prefs
    note_sort = changes.pop("note_sort", None)
    note_tag = changes.pop("note_tag", None)
    media_open = changes.pop("media_open", None)
    if changes:
        raise TypeError(f"unknown pref(s): {', '.join(sorted(changes))}")
    if note_sort is not None:
        prefs.note_sort = str(note_sort)
    if note_tag is not None:
        prefs.note_tag = str(note_tag)
    if isinstance(media_open, dict):
        prefs.media_open = media_open
    mark_notable(sess)
    return prefs


def _default_vault_path() -> Path:
    """Where a brand-new session lands: whatever vault was last remembered
    process-wide (the same "last vault wins" default the app has always
    used), falling back to the launch default. This is a *starting point*
    for a new browser only -- switching it afterwards never affects any
    other session."""
    from . import settings as cfg
    saved = (cfg.load() or {}).get("vault")
    if saved:
        return Path(saved).expanduser().resolve()
    return vault.current().vault


def _new_session(request: Request) -> Session:
    sid = secrets.token_hex(16)
    sess = Session(id=sid, vault_path=_default_vault_path())
    with _sessions_lock:
        _sessions[sid] = sess
    # Deliberately no save() here: a fresh session is indistinguishable from
    # one we would mint on the next request, so there is nothing to lose yet.
    # mark_notable() is what commits it, once it holds something real.
    return sess


def get_or_create_session(request: Request) -> tuple[Session, bool]:
    """(session, is_new). is_new tells the caller whether a cookie needs
    setting on the response."""
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        with _sessions_lock:
            sess = _sessions.get(sid)
        if sess is not None:
            return sess, False
    return _new_session(request), True


def switch_vault(path: str | Path,
                  on_create: Callable[[Path, "idx.Conn"], None] | None = None,
                  repair: bool = True,
                  ) -> VaultHandle:
    """Point the *current session only* at a different vault. Creates or
    joins that vault's connection in the registry; every other session
    keeps whatever it already had open, untouched."""
    sess = current_session()
    resolved = Path(path).expanduser().resolve()
    handle = REGISTRY.get_or_create(resolved, on_create=on_create, repair=repair)
    sess.vault_path = resolved
    vault.set_current(resolved)
    _current_con.set(handle.con)
    mark_notable(sess)   # the whole point: come back to the vault I had open
    return handle


class SessionMiddleware:
    """Plain ASGI middleware -- deliberately *not* Starlette's
    BaseHTTPMiddleware.

    BaseHTTPMiddleware runs the downstream app via a separately-spawned
    task (it has to, to stream the request body and response concurrently),
    and relying on a contextvar set just before `call_next()` to still be
    visible inside that spawned task is the kind of thing that has bitten
    other projects before, even though asyncio tasks normally copy the
    parent context at creation. A plain ASGI middleware has no such
    boundary: it just awaits the inner app directly, in the same task, so
    the contextvars set below are unambiguously visible to every route
    handler and everything it calls -- including vault.py's own contextvar,
    and including sync endpoints FastAPI runs in a threadpool, since anyio's
    to_thread.run_sync copies the calling context into the worker thread.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        if (scope.get("path") in NO_SESSION_PATHS
                and not request.cookies.get(SESSION_COOKIE)):
            # Ephemeral: never registered, never persisted, no cookie set.
            this_session, is_new = Session(id="", vault_path=_default_vault_path()), False
        else:
            this_session, is_new = get_or_create_session(request)
        if not is_new and this_session.notable:
            # A brand-new session was already force-saved by _new_session;
            # this is the returning-browser case, where all that changed is
            # "still here", so it rides the throttle.
            this_session.last_seen = time.time()
            save()
        # repair=False: resolving which vault a request belongs to is not
        # someone asking for a repair. The link repair rewrites markdown, so
        # letting the middleware trigger it would hand every locked,
        # read-only session a note-rewriting side effect on its next
        # request -- which is exactly what vault_open is careful not to do.
        # An explicit unlocked open settles it (see VaultHandle.
        # repair_pending); boot still repairs the default vault.
        handle = REGISTRY.get_or_create(this_session.vault_path, repair=False)

        tok_sess = _current_session.set(this_session)
        tok_con = _current_con.set(handle.con)
        vault.set_current(this_session.vault_path)

        send_out = send
        if is_new:
            cookie = (f"{SESSION_COOKIE}={this_session.id}; Path=/; "
                      f"Max-Age={SESSION_MAX_AGE}; HttpOnly; SameSite=lax")

            async def send_out(message):  # noqa: FURB -- shadow is deliberate
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers") or [])
                    headers.append((b"set-cookie", cookie.encode("latin-1")))
                    message = {**message, "headers": headers}
                await send(message)

        try:
            await self.app(scope, receive, send_out)
        finally:
            _current_session.reset(tok_sess)
            _current_con.reset(tok_con)
