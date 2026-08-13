#!/usr/bin/env python3
"""
Clear a forgotten admin password.

    python3 tools/reset_admin_password.py            # report only
    python3 tools/reset_admin_password.py --clear     # remove the lock

There is no "forgot password" flow in the app -- the admin password is the
only thing gating edits, and there's no email or second factor to recover it
through (see the Admin drawer / app/auth.py). Losing it means clearing it
from wherever config.json actually lives:

    docker compose exec tephra python3 tools/reset_admin_password.py --clear

Clearing removes the "admin" key entirely, which restores the pre-lock,
fully-open behaviour -- require_admin() in app/main.py no-ops with no admin
key present, so notes are editable from any browser again until a new
password is set from the Admin drawer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.settings import config_file, load, save  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true",
                    help="remove the admin password lock")
    args = ap.parse_args()

    cfgp = config_file()
    print(f"\n  config: {cfgp}")
    cfg = load()
    if not cfg.get("admin"):
        print("  no admin password is set -- nothing to do\n")
        return 0

    print("  an admin password is set and locking edits")
    if not args.clear:
        print("\n    Re-run with --clear to remove it -- notes reopen for anyone"
              " who can reach the app until a new password is set.\n")
        return 0

    del cfg["admin"]
    save(cfg)
    print("  cleared -- notes are unlocked and open until a new password is set\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
