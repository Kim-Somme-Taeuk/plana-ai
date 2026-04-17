# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


REPO_ROOT = Path(__file__).resolve().parents[1]

hiddenimports = collect_submodules("collector") + collect_submodules("app")


a = Analysis(
    [str(REPO_ROOT / "collector" / "launcher.py")],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "backend")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="plana-collector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
)
