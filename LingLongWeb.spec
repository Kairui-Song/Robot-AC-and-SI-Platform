# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("dns")
    + collect_submodules("engineio")
    + collect_submodules("socketio")
    + collect_submodules("flask_socketio")
    + collect_submodules("reportlab")
    + [
        "pytest",
        "serial",
    ]
)

a = Analysis(
    ["portable_launcher.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates", "templates"),
        ("static", "static"),
        ("test_case", "test_case"),
        ("tests", "tests"),
        ("controller", "controller"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="启动LingLong自检系统",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LingLong网页程序",
)
