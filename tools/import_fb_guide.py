#!/usr/bin/env python3
"""
Import the standalone FB Study Guide from the command line.

Prefer importing from inside Tephra (Study tab -> Import study guide): the
running app knows its own vault, so it cannot write to the wrong place. Use
this only for scripted or headless setups.

    TEPHRA_VAULT=~/Documents/Tephra python3 tools/import_fb_guide.py guide.py
    python3 tools/import_fb_guide.py guide.py --vault ~/Documents/Tephra
    python3 tools/import_fb_guide.py guide.py --vault ./vault --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CANDIDATES = [
    ("desktop / run.py", Path.home() / "Documents" / "Tephra"),
    ("docker compose", Path.cwd() / "vault"),
    ("container default", Path("/vault")),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--vault", help="target vault directory (required unless TEPHRA_VAULT is set)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"no such file: {args.source}")

    target = args.vault or os.environ.get("TEPHRA_VAULT")
    if not target:
        # Guessing here is how notes end up in a directory the app never
        # reads, which is indistinguishable from the import doing nothing.
        print("\n  Refusing to guess which vault to write to.\n")
        print("  Pass --vault, or set TEPHRA_VAULT. Likely candidates:\n")
        for label, path in CANDIDATES:
            mark = "exists" if (path / "notes").is_dir() else "not found"
            print(f"    {str(path):42} {mark:10} ({label})")
        print("\n  Easier: start Tephra and use Study -> Import study guide.\n")
        return 2

    os.environ["TEPHRA_VAULT"] = str(Path(target).expanduser())
    from app import fb_import, vault

    summary = fb_import.run_import(args.source.read_text(encoding="utf-8"),
                                   dry_run=args.dry_run)
    verb = "would import" if args.dry_run else "imported"
    print(f"\n  vault:   {summary['vault']}")
    print(f"  source:  {summary['topics']} topics, {summary['questions']} questions")
    print(f"  {verb}: {summary['created']} new, {summary['updated']} updated, "
          f"{summary['categories']} category indexes + 1 root note")
    if summary["manual_overrides_kept"]:
        print(f"  kept {summary['manual_overrides_kept']} manual category override(s)")
    if not args.dry_run:
        print(f"\n  Now reindex so a running app picks them up:")
        print(f"    curl -X POST http://127.0.0.1:<port>/api/reindex")
        print(f"  or just restart Tephra.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
