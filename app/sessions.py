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
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fastapi import Request

from . import index as idx
from . import vault

SESSION_COOKIE = "tephra_sid"
# ~13 months -- past the point where cookies are session-only in most
# browsers, so "keep coming back to the vault I had open" survives a
# browser restart, not just a tab refresh.
SESSION_MAX_AGE = 400 * 24 * 3600


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


class VaultRegistry:
    """One VaultHandle per resolved vault path, shared by every session
    pointed at that path."""

    def __init__(self) -> None:
        self._by_path: dict[str, VaultHandle] = {}
        self._lock = threading.Lock()

    def get_or_create(self, path: Path,
                       on_create: Callable[[Path, "idx.Conn"], None] | None = None
                       ) -> VaultHandle:
        key = str(path)
        with self._lock:
            handle = self._by_path.get(key)
            if handle is not None:
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
            fixed = idx.repair_links(con)
            if fixed["changed"]:
                idx.rebuild(con)
            handle = VaultHandle(path=path, con=con,
                                  last_repair=fixed if fixed["changed"] else None)
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
    """UI view-state that used to live in a shared theme.json -- kept in
    memory per session instead. Lost on a server restart, same as the app
    already resets to defaults on restart today; not worth a file per
    session for state this disposable."""
    note_sort: str = "updated"
    note_tag: str = ""
    media_open: dict = field(default_factory=dict)


@dataclass
class Session:
    id: str
    vault_path: Path
    prefs: SessionPrefs = field(default_factory=SessionPrefs)


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


def switch_vault(path: str | Path, on_create: Callable[[Path, "idx.Conn"], None] | None = None
                  ) -> VaultHandle:
    """Point the *current session only* at a different vault. Creates or
    joins that vault's connection in the registry; every other session
    keeps whatever it already had open, untouched."""
    sess = current_session()
    resolved = Path(path).expanduser().resolve()
    handle = REGISTRY.get_or_create(resolved, on_create=on_create)
    sess.vault_path = resolved
    vault.set_current(resolved)
    _current_con.set(handle.con)
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
        this_session, is_new = get_or_create_session(request)
        handle = REGISTRY.get_or_create(this_session.vault_path)

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
