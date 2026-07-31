"""
App-level settings that must live *outside* any vault.

Which vault to open cannot be stored in a vault, so this is the one piece of
state kept in the platform config directory. Everything else — theme, study
progress, notes — belongs to the vault and travels with it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "Tephra"
MAX_RECENT = 8


def config_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


def load() -> dict:
    f = config_file()
    if f.is_file():
        try:
            data = json.loads(f.read_text())
            data.setdefault("recent", [])
            return data
        except Exception:
            pass
    return {"recent": []}


def save(cfg: dict) -> dict:
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        config_file().write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass          # a read-only config dir must not break the app
    return cfg


def remember_vault(path: str | Path) -> dict:
    cfg = load()
    p = str(Path(path).expanduser().resolve())
    cfg["vault"] = p
    cfg["recent"] = [p] + [r for r in cfg.get("recent", []) if r != p]
    cfg["recent"] = cfg["recent"][:MAX_RECENT]
    return save(cfg)


def rename_vault(old: str | Path, new: str | Path) -> dict:
    """Point config at a moved vault, keeping its place in the recents list."""
    cfg = load()
    old_s, new_s = str(Path(old).resolve()), str(Path(new).resolve())
    cfg["recent"] = [new_s if r == old_s else r for r in cfg.get("recent", [])]
    # Only ever called for the vault in use, and on a first run the config may
    # not name a vault at all yet — so set it rather than only updating a match.
    cfg["vault"] = new_s
    if new_s not in cfg["recent"]:
        cfg["recent"].insert(0, new_s)
    cfg["recent"] = cfg["recent"][:MAX_RECENT]
    return save(cfg)


def default_vault() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / APP_NAME
