# -*- mode: python ; coding: utf-8 -*-

import os

datas = []


def add_tree(source_root, target_root):
    if not os.path.exists(source_root):
        return
    for root, _dirs, files in os.walk(source_root):
        for filename in files:
            src = os.path.join(root, filename)
            rel_dir = os.path.relpath(root, source_root)
            dest = target_root if rel_dir == "." else os.path.join(target_root, rel_dir)
            datas.append((src, dest))


add_tree("web/dist", "web/dist")
add_tree("tools", "tools")
add_tree("assets", "assets")
if os.path.exists("require.txt"):
    datas.append(("require.txt", "."))

hiddenimports = [
    "fitz",
    "pytesseract",
    "PIL.Image",
    "openpyxl",
    "pypdf",
    "zxingcpp",
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pandas",
        "sqlalchemy",
        "sqlite3",
        "psycopg2",
        "pytest",
        "pygments",
        "matplotlib",
        "IPython",
        "numpy",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EcoInvoiceRecon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="assets/app-icon.ico",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EcoInvoiceRecon",
)
