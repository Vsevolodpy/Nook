# -*- mode: python ; coding: utf-8 -*-
"""Сборка Nook: PyInstaller --onedir.

    .\\venv\\Scripts\\python.exe -m PyInstaller nook.spec

Результат: ``dist\\Nook\\Nook.exe``.  Папка ``nook/view`` кладётся внутрь
сборки как ``view/`` — ``controller.main.view_dir()`` ищет её в ``sys._MEIPASS``.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve()

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "nook" / "view"), "view")],
    hiddenimports=["webview.platforms.edgechromium", "webview.platforms.winforms"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Nook",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Nook",
)
