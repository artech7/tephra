#!/usr/bin/env python3
"""
Rename back a vault stranded mid-rename.

    python3 tools/recover_vaults.py              # report only
    python3 tools/recover_vaults.py --recover     # rename strays back into view

A case-only rename needs two moves on a case-insensitive filesystem, and the
halfway state is a dot-prefixed folder (`.something.tephra-renaming`) that
Finder does not display — so "my vault disappeared" usually means "my vault
is sitting right there with a dot in front of its name". Tephra recovers any
stray it finds on the next start, so this script is for the harder case: a
vault broken badly enough that the app will not start. It stays a script
rather than an endpoint for exactly that reason — `docker compose exec`
still works when uvicorn is crash-looping. General vault discovery lives in
the app itself now (`GET /api/vault/browse`), so this only searches for the
one thing that needs a filesystem-level tool to fix.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.vault import walk  # noqa: E402

SEARCH_ROOTS = [Path.home() / "Documents", Path.home() / "Desktop",
                Path.home(), Path.cwd()]


def config_path() -> Path:
    override = os.environ.get("TEPHRA_CONFIG_DIR")
    if override:
        return Path(override).expanduser() / "config.json"
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Tephra" / "config.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recover", action="store_true",
                    help="rename hidden .tephra-renaming folders back")
    ap.add_argument("--root", action="append", type=Path,
                    help="extra folder to search")
    args = ap.parse_args()

    cfgp = config_path()
    print(f"\n  config: {cfgp}")
    if cfgp.is_file():
        try:
            cfg = json.loads(cfgp.read_text())
            print(f"  the app expects its vault at: {cfg.get('vault', '(not recorded)')}")
        except Exception as exc:
            print(f"  (could not read it: {exc})")
    else:
        print("  (no config yet)")

    roots, seen_roots = [], set()
    for r in (args.root or []) + SEARCH_ROOTS:
        rp = r.expanduser().resolve()
        if rp not in seen_roots and rp.is_dir():
            seen_roots.add(rp)
            roots.append(rp)

    hidden, seen = [], set()
    print("\n  searching…")
    for root in roots:
        for v in walk(root):
            if v in seen or not v.name.startswith("."):
                continue
            seen.add(v)
            hidden.append(v)

    if not hidden:
        print("\n  no stray hidden vaults found\n")
        return 0

    def describe(p: Path) -> str:
        n = len(list((p / "notes").glob("*.md")))
        return f"{p}  ({n} note{'s' if n != 1 else ''})"

    print(f"\n  HIDDEN vaults: {len(hidden)}  <- Finder does not show these")
    for v in sorted(hidden):
        print(f"    {describe(v)}")

    if args.recover:
        for v in sorted(hidden):
            name = v.name.lstrip(".")
            if name.endswith(".tephra-renaming"):
                name = name[: -len(".tephra-renaming")]
            target = v.parent / name
            if target.exists():
                print(f"    skipped {v.name}: {target} already exists")
                continue
            v.rename(target)
            print(f"    recovered -> {target}")
    else:
        print("\n    Re-run with --recover to rename them back into view.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
