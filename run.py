#!/usr/bin/env python3
"""
Tephra launcher.

    python3 run.py

First run builds a private virtualenv in .venv/ and installs dependencies
into it, then re-launches itself inside that venv. Subsequent runs skip
straight to launching. Nothing is installed into your system Python.

    python3 run.py --vault ~/Notes     use a different vault
    python3 run.py --browser           open a browser tab instead of a window
    python3 run.py --headless          server only, no UI
    python3 run.py --reinstall         rebuild the venv from scratch
    python3 run.py --no-venv           use the current interpreter as-is

This file deliberately imports nothing outside the standard library. It has
to run on a bare Python before any dependency exists.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)          # modern union syntax in the app's annotations
ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements-run.txt"
STAMP = VENV / ".tephra-deps"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def inside_our_venv() -> bool:
    """Compare sys.prefix, not sys.executable.

    A venv's bin/python is a symlink to the system interpreter, so resolving
    executables makes the two compare equal and the check silently passes
    while running *outside* the venv. sys.prefix is the venv directory when
    and only when we are actually inside it.
    """
    try:
        return VENV.is_dir() and Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def requirements_fingerprint() -> str:
    """Hash every requirements file that feeds the install, so editing any of
    them triggers a reinstall and editing none of them doesn't."""
    h = hashlib.sha256()
    for name in ("requirements-run.txt", "requirements.txt"):
        f = ROOT / name
        if f.is_file():
            h.update(f.read_bytes())
    h.update(sys.version.encode())        # a Python upgrade invalidates the venv
    return h.hexdigest()


def die(msg: str, hint: str = "") -> None:
    print(f"\n  {msg}", file=sys.stderr)
    if hint:
        print(f"  {hint}", file=sys.stderr)
    print(file=sys.stderr)
    raise SystemExit(1)


def create_venv() -> None:
    print(f"  Creating virtualenv in {VENV.relative_to(ROOT)}/ …", flush=True)
    import venv as venv_mod
    try:
        venv_mod.EnvBuilder(with_pip=True, clear=False,
                            symlinks=os.name != "nt").create(VENV)
    except Exception as exc:
        # Debian and Ubuntu ship venv without ensurepip in the base package,
        # which is the single most common failure here.
        die(f"Could not create the virtualenv: {exc}",
            "On Debian/Ubuntu: sudo apt install python3-venv\n"
            "  Or run with --no-venv and manage dependencies yourself.")
    if not venv_python().exists():
        die("Virtualenv was created but has no interpreter.",
            "Delete .venv/ and try again, or use --no-venv.")


def install_deps() -> None:
    py = str(venv_python())
    print("  Installing dependencies (first run only, ~30s) …", flush=True)
    try:
        subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip", "-q"],
                       check=True)
        subprocess.run([py, "-m", "pip", "install", "-q", "-r", str(REQ)],
                       check=True)
    except subprocess.CalledProcessError:
        die("Dependency install failed.",
            "Usually no network, or a proxy blocking PyPI.\n"
            "  Retry, or install by hand:\n"
            f"  {py} -m pip install -r {REQ}")
    STAMP.write_text(requirements_fingerprint())


def bootstrap_and_reexec(argv: list[str]) -> None:
    if not REQ.is_file():
        die(f"{REQ.name} is missing.", "Run this from inside the project folder.")
    if not venv_python().exists():
        create_venv()
        install_deps()
    elif not STAMP.is_file() or STAMP.read_text().strip() != requirements_fingerprint():
        install_deps()

    # Re-exec rather than importing: packages installed a moment ago aren't
    # reliably importable in the interpreter that installed them.
    py = str(venv_python())
    os.execv(py, [py, str(Path(__file__).resolve()), *argv])


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        die(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
            f"found {sys.version_info.major}.{sys.version_info.minor}.")

    argv = sys.argv[1:]
    use_venv = "--no-venv" not in argv
    argv = [a for a in argv if a != "--no-venv"]

    if "--reinstall" in argv:
        argv.remove("--reinstall")
        import shutil
        if VENV.exists():
            print(f"  Removing {VENV.relative_to(ROOT)}/ …")
            shutil.rmtree(VENV, ignore_errors=True)

    if use_venv and not inside_our_venv():
        bootstrap_and_reexec(argv)      # never returns

    sys.path.insert(0, str(ROOT))
    try:
        from desktop.launcher import main as launch
    except ImportError as exc:
        die(f"Could not load the app: {exc}",
            "Try: python3 run.py --reinstall")

    sys.argv = [sys.argv[0], *argv]
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
