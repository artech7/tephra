#!/usr/bin/env python3
"""
Check and repair link damage in a vault, from the command line.

    TEPHRA_VAULT=~/Documents/Tephra python3 tools/repair.py            # report only
    TEPHRA_VAULT=~/Documents/Tephra python3 tools/repair.py --fix      # rewrite

Prefer the in-app control (Vaults -> Content check) — it knows which vault is
open. This exists for headless or scripted use.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", help="vault directory (or set TEPHRA_VAULT)")
    ap.add_argument("--fix", action="store_true", help="write the repairs")
    args = ap.parse_args()

    target = args.vault or os.environ.get("TEPHRA_VAULT")
    if not target:
        print("\n  Set --vault or TEPHRA_VAULT.\n", file=sys.stderr)
        return 2
    os.environ["TEPHRA_VAULT"] = str(Path(target).expanduser())

    from app import index as idx, vault
    con = idx.connect()
    idx.init(con)
    idx.rebuild(con)

    report = idx.repair_links(con, dry_run=not args.fix)
    print(f"\n  vault:   {vault.VAULT}")
    print(f"  scanned: {report['scanned']} notes")
    if not report["changed"]:
        print("  result:  no malformed links found\n")
        return 0

    verb = "would rewrite" if not args.fix else "rewrote"
    print(f"  result:  {verb} {report['changed']} note(s)\n")
    for d in report["notes"][:40]:
        bits = [f"{k}={d[k]}" for k in ("nested", "quiz_links", "empty") if d.get(k)]
        print(f"    {d['title']}  ({', '.join(bits)})")
        p = d.get("preview") or {}
        if p.get("before"):
            print(f"      -  {p['before']}")
            print(f"      +  {p['after']}")
    if len(report["notes"]) > 40:
        print(f"    … and {len(report['notes']) - 40} more")
    if not args.fix:
        print("\n  Re-run with --fix to apply.\n")
    else:
        idx.rebuild(con)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
