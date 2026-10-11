# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

wvlib = r"C:\Users\miroz\AppData\Roaming\Python\Python314\site-packages\webview\lib"

datas = []
binaries = []
hiddenimports = []

for pkg in ("pythonnet", "clr_loader"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# WebView2: managed-сборки + нативный загрузчик (кладём как данные, чтобы PyInstaller
# не пытался анализировать их зависимости). Путь сохраняем: webview/lib/...
wv_items = [
    ("Microsoft.Web.WebView2.Core.dll", "webview/lib"),
    ("Microsoft.Web.WebView2.WinForms.dll", "webview/lib"),
    (os.path.join("runtimes", "win-x64", "native", "WebView2Loader.dll"),
     "webview/lib/runtimes/win-x64/native"),
]
for rel, dest in wv_items:
    src = os.path.join(wvlib, rel)
    if os.path.exists(src):
        datas.append((src, dest))

if os.path.exists("jektor.ico"):
    datas.append(("jektor.ico", "."))

a = Analysis(
    ["native_browser.py"],
    pathex=[os.path.abspath(os.getcwd())],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["clr", "System", "Microsoft.VisualBasic"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["webview", "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6",
              "matplotlib", "numpy", "PIL", "scipy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jektor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="jektor.ico" if os.path.exists("jektor.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Jektor",
)
