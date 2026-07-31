#!/usr/bin/env python3
"""
Find Tephra vaults on this machine, including ones Finder hides.

    python3 tools/find_vaults.py
    python3 tools/find_vaults.py --recover     # rename hidden strays back

A vault is any folder containing a `notes/` directory with markdown in it. An
interrupted rename could leave one named `.something.tephra-renaming`, which
Finder does not show — so "my vault disappeared" usually means "my vault is
sitting right there with a dot in front of its name".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SEARCH_ROOTS = [Path.home() / "Documents", Path.home() / "Desktop",
                Path.home(), Path.cwd()]
MAX_DEPTH = 4


def is_vault(p: Path) -> bool:
    notes = p / "notes"
    if not notes.is_dir():
        return False
    try:
        return any(notes.glob("*.md")) or (p / ".index").is_dir()
    except OSError:
        return False


def walk(root: Path, depth: int = 0):
    if depth > MAX_DEPTH or not root.is_dir():
        return
    try:
        entries = list(root.iterdir())
    except (OSError, PermissionError):
        return
    for e in entries:
        if not e.is_dir() or e.is_symlink():
            continue
        if e.name in ("node_modules", "Library", ".git", ".venv"):
            continue
        if is_vault(e):
            yield e
            continue                      # do not descend into a vault
        yield from walk(e, depth + 1)


def config_path() -> Path:
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
            for r in cfg.get("recent", [])[1:]:
                print(f"    also remembered: {r}")
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

    found, hidden = [], []
    seen = set()
    print("\n  searching…")
    for root in roots:
        for v in walk(root):
            if v in seen:
                continue
            seen.add(v)
            (hidden if v.name.startswith(".") else found).append(v)

    def describe(p: Path) -> str:
        n = len(list((p / "notes").glob("*.md")))
        return f"{p}  ({n} note{'s' if n != 1 else ''})"

    print(f"\n  vaults found: {len(found)}")
    for v in sorted(found):
        print(f"    {describe(v)}")

    if hidden:
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

    if not found and not hidden:
        print("\n    Nothing found. Try: python3 tools/find_vaults.py --root /Volumes")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
