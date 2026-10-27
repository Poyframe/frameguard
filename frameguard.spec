# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: genera dist\Frameguard\Frameguard.exe (carpeta, sin consola). Se usa desde build.ps1.
import os
import re
from pathlib import Path

ROOT = Path(SPECPATH)
# Edición interna (build.ps1 -SinGitHub): el .exe se compila SIN el módulo que habla con GitHub
SIN_GITHUB = os.environ.get("FRAMEGUARD_SIN_GITHUB_BUILD") == "1"
GITHUB_MODULE = "frameguard.github_updates"
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "frameguard" / "__init__.py").read_text()).group(1)
nums = [int(x) for x in VERSION.split(".")] + [0]

version_file = ROOT / "build" / "version_info.txt"
version_file.parent.mkdir(exist_ok=True)
version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums[0]}, {nums[1]}, {nums[2]}, 0), prodvers=({nums[0]}, {nums[1]}, {nums[2]}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040A04B0', [
    StringStruct('CompanyName', 'Frameguard'),
    StringStruct('FileDescription', 'Frameguard - gestor de colas de render para Blender'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('InternalName', 'Frameguard'),
    StringStruct('OriginalFilename', 'Frameguard.exe'),
    StringStruct('ProductName', 'Frameguard'),
    StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [0x040A, 1200])])]
)""", encoding="utf-8")

a = Analysis(
    ["frameguard_main.py"],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "frameguard" / "blender_scripts"), "frameguard/blender_scripts"),
           (str(ROOT / "frameguard" / "ui" / "logo.png"), "frameguard/ui")],
    hiddenimports=["frameguard.engine", "frameguard.ui.app"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner"]
             + ([GITHUB_MODULE] if SIN_GITHUB else []),
    noarchive=False,
)
if SIN_GITHUB:
    a.pure = [m for m in a.pure if m[0] != GITHUB_MODULE]
    assert not any(m[0] == GITHUB_MODULE for m in a.pure), "el módulo de GitHub se coló en la edición interna"
    print("Edición interna: compilada SIN", GITHUB_MODULE)
# Fuera lo que una ventana Qt Widgets no usa (OpenGL por software, Quick/QML, PDF, formatos de imagen extra).
DROP = ("opengl32sw.dll", "qt6quick", "qt6qml", "qt6pdf", "qdirect2d", "qtiff", "qwebp", "qpdf",
        "qt6virtualkeyboard", "qtvirtualkeyboard", "qt6opengl.dll", "qt6openglwidgets")
a.binaries = [b for b in a.binaries if not any(d in b[0].lower() for d in DROP)]
a.datas = [d for d in a.datas if "translations" not in d[0].lower() or "_es." in d[0].lower()]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Frameguard", console=False,
          icon=str(ROOT / "assets" / "frameguard.ico"), version=str(version_file), upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Frameguard", upx=False)
