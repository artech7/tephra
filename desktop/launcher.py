"""
Tephra desktop launcher.

Runs the same FastAPI app the container runs, on a random loopback port,
inside a native webview window. There is no second implementation of
anything — the desktop build is the server build plus a window.

Design notes that matter for packaging:

* The port is chosen by the OS (bind :0) rather than hardcoded, so two
  copies, or a container already using 8080, never collide.
* It binds 127.0.0.1 explicitly. A desktop app has no business listening
  on all interfaces.
* Cross-origin requests are refused. A web page you have open could
  otherwise fetch() 127.0.0.1 and read the vault; browsers mark those
  requests with Origin / Sec-Fetch-Site, and address-bar navigation does
  not, so the check costs the user nothing.
* The vault defaults to a real documents folder, not inside the app bundle.
  Application bundles get replaced wholesale on update; user data must not
  live where an installer will overwrite it.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Tephra"


# ── platform paths ─────────────────────────────────────────────────────────

def config_dir() -> Path:
    override = os.environ.get("TEPHRA_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def default_vault() -> Path:
    """Documents, not Application Support. These are the user's notes, and
    they should be findable, backup-able and sync-able without spelunking."""
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / APP_NAME


def load_config() -> dict:
    f = config_dir() / "config.json"
    if f.is_file():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "config.json").write_text(json.dumps(cfg, indent=2))


def resource_root() -> Path:
    """Where the bundled `app` package lives. PyInstaller unpacks data files
    to sys._MEIPASS in onefile mode; in onedir and in development the layout
    is just the source tree."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


# ── server ─────────────────────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _same_origin(origin: str, host_header: str) -> bool:
    """Is this Origin the app's own origin?

    127.0.0.1 and localhost are the same server here, and browsers will send
    whichever the user typed, so they are treated as interchangeable when the
    port matches.
    """
    from urllib.parse import urlparse
    try:
        net = urlparse(origin).netloc.lower()
    except ValueError:
        return False
    host = (host_header or "").lower()
    if net and net == host:
        return True
    o_host, _, o_port = net.rpartition(":")
    h_host, _, h_port = host.rpartition(":")
    loopback = {"127.0.0.1", "localhost", "[::1]", "::1"}
    return bool(o_port) and o_port == h_port and o_host in loopback and h_host in loopback


def build_asgi():
    """Import the web app and wrap it in a cross-origin guard.

    An earlier version of this used a per-launch session token in the URL,
    traded for a cookie. That was both fragile and pointless:

    * Fragile — the token is regenerated every launch, so a cookie left by a
      previous session shadowed the fresh token in the URL and locked the app
      out with "bad session token" until browser storage was cleared.
    * Pointless — it was defending the vault from other local processes, which
      can already read ~/Documents/Tephra/notes/*.md directly. It bought
      nothing against the only attacker it could have stopped.

    The real threat is a web page you happen to have open doing fetch() at
    127.0.0.1. Browsers always mark those requests: cross-origin requests
    carry an Origin header, and modern browsers send Sec-Fetch-Site. Typing
    the address yourself sends neither, so checking them blocks the attack
    without any state to go stale.
    """
    sys.path.insert(0, str(resource_root()))
    from app.main import app as fastapi_app          # noqa: E402
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class Guard(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.client and request.client.host not in ("127.0.0.1", "::1"):
                return JSONResponse({"detail": "loopback only"}, status_code=403)

            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "cross-site request blocked"},
                                    status_code=403)

            origin = request.headers.get("origin")
            if origin and origin != "null" and not _same_origin(
                    origin, request.headers.get("host", "")):
                return JSONResponse({"detail": "cross-origin request blocked"},
                                    status_code=403)

            return await call_next(request)

    fastapi_app.add_middleware(Guard)
    return fastapi_app


def serve(asgi, port: int) -> "object":
    import uvicorn
    config = uvicorn.Config(asgi, host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="tephra-server").start()
    return server


def wait_until_up(port: int, timeout: float = 25.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


# ── entry ──────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(prog="tephra")
    ap.add_argument("--vault", help="path to the vault directory")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--headless", action="store_true",
                    help="run the server without opening any UI")
    ap.add_argument("--browser", action="store_true",
                    help="open a browser tab instead of a native window")
    args = ap.parse_args()

    cfg = load_config()
    vault_path = Path(args.vault or cfg.get("vault") or default_vault()).expanduser()
    vault_path.mkdir(parents=True, exist_ok=True)
    if cfg.get("vault") != str(vault_path):
        cfg["vault"] = str(vault_path)
        save_config(cfg)

    # app.vault reads this at import time, so it must be set before build_asgi
    os.environ["TEPHRA_VAULT"] = str(vault_path)

    port = args.port or free_port()
    asgi = build_asgi()
    server = serve(asgi, port)

    if not wait_until_up(port):
        print("tephra: server failed to start", file=sys.stderr, flush=True)
        return 1

    url = f"http://127.0.0.1:{port}/"
    print(f"{APP_NAME} ready\n  vault: {vault_path}\n  url:   {url}", flush=True)

    if args.headless:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0

    def serve_in_browser(reason: str = "") -> int:
        if reason:
            print(f"  {reason}", file=sys.stderr, flush=True)
        import webbrowser
        webbrowser.open(url)
        print("  Serving in your browser. Ctrl+C to stop.", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Stopped.", flush=True)
            return 0

    if args.browser:
        return serve_in_browser()

    try:
        import webview
    except Exception as exc:
        # Not always ImportError: on Linux the backend probe can raise other
        # things. Report what actually happened rather than guessing.
        return serve_in_browser(
            f"Native window unavailable ({type(exc).__name__}: {exc}). Using your browser.")

    window = webview.create_window(
        APP_NAME, url,
        width=cfg.get("w", 1380), height=cfg.get("h", 900),
        min_size=(900, 620),
        background_color="#050C0E",
        text_select=True,
    )

    def on_closing():
        try:
            cfg["w"], cfg["h"] = window.width, window.height
            save_config(cfg)
        except Exception:
            pass
        server.should_exit = True

    window.events.closing += on_closing

    # Edge WebView2 on Windows, WKWebView on macOS, WebKitGTK or Qt on Linux.
    # The first two ship with the OS. Linux does not, and pip cannot install
    # them, so that is the one platform where this can legitimately fail.
    # pywebview logs a full traceback per backend it fails to load, which is
    # noise when we handle the failure ourselves one line later.
    import logging
    logging.getLogger("pywebview").setLevel(logging.CRITICAL)

    try:
        webview.start(private_mode=False,
                      storage_path=str(config_dir() / "webview"))
    except Exception as exc:
        hint = "No native webview backend available"
        if sys.platform.startswith("linux"):
            hint += (" — install one with:\n"
                     "    sudo apt install python3-gi gir1.2-webkit2-4.1\n"
                     "  or re-run with --browser")
        return serve_in_browser(f"{hint}\n  ({type(exc).__name__}: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
