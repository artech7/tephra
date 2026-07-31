# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec, shared by all three platforms.

onedir rather than onefile on purpose: onefile unpacks the whole bundle to a
temp directory on every launch, which is slow and trips antivirus heuristics
on Windows. Installers want a directory anyway.
"""
import sys
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("markdown_it")
    + [
        "anyio._backends._asyncio",
        "fastapi", "starlette", "pydantic",
        "multipart", "python_multipart",
        "sqlite3",
    ]
)

a = Analysis(
    ["desktop/launcher.py"],
    pathex=["."],
    binaries=[],
    # The web UI is data, not code — it must be collected explicitly or the
    # frozen app boots to a blank window.
    datas=[("app/static", "app/static")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Tephra",
    debug=False,
    strip=False,
    upx=False,                    # UPX + macOS signing do not get along
    console=False,                # no terminal window behind the app
    icon="packaging/icon.ico" if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="Tephra",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Tephra.app",
        icon="packaging/icon.icns",
        bundle_identifier="dev.tephra.app",
        info_plist={
            "CFBundleName": "Tephra",
            "CFBundleDisplayName": "Tephra",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # Notes live in ~/Documents, so Sonoma+ will prompt for access.
            "NSDocumentsFolderUsageDescription":
                "Tephra stores your notes as markdown files in this folder.",
        },
    )
