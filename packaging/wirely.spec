# PyInstaller recipe for Wirely.   Build with:  build_exe.bat  (Windows),  packaging/mac/build_mac.sh  (Mac),
# packaging/linux/build_appimage.sh  (Linux)  — or:  pyinstaller packaging/wirely.spec
# Produces dist/Wirely/Wirely(.exe) plus its support files (a folder build starts much faster than one big exe).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import wirely  # noqa: E402

VERSION, REV = wirely.__version__, wirely.__revision__
ASSETS = os.path.join(ROOT, "wirely", "assets")

datas = [(ASSETS, os.path.join("wirely", "assets")), (os.path.join(ROOT, "examples"), "examples"),
         (os.path.join(ROOT, "wirely", "locale"), os.path.join("wirely", "locale"))]   # the language catalogues
for f in ("README.md", "CHANGES.md", "LICENSE", "THIRD-PARTY-NOTICES.txt"):
    datas.append((os.path.join(ROOT, f), "."))

hidden = collect_submodules("wirely") + ["PySide6.QtSvg", "PySide6.QtMultimedia", "numpy"]

# Windows: version details shown in the exe's Properties > Details
version_file = None
if sys.platform == "win32":
    nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    version_file = os.path.join(ROOT, "build", "version_info.txt")
    os.makedirs(os.path.dirname(version_file), exist_ok=True)
    with open(version_file, "w", encoding="utf-8") as fh:
        fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('080904B0', [
      StringStruct('CompanyName', 'Wirely'),
      StringStruct('FileDescription', 'Wirely - circuit design and simulation'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'Wirely'),
      StringStruct('LegalCopyright', 'Wirely contributors, GPL-3.0-or-later'),
      StringStruct('OriginalFilename', 'Wirely.exe'),
      StringStruct('ProductName', 'Wirely'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [2057, 1200])])])
""")

if sys.platform == "darwin":
    doc_icns = os.path.join(ROOT, "build", "WirelyDoc.icns")
    if os.path.exists(doc_icns):
        datas.append((doc_icns, "."))

a = Analysis(
    [os.path.join(HERE, "launcher.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "scipy", "pytest", "IPython", "PIL",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
              "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick3D", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
              "PySide6.QtBluetooth", "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtSensors",
              "PySide6.QtSerialPort", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtTextToSpeech",
              "PySide6.QtWebSockets", "PySide6.QtNfc", "PySide6.QtDesigner", "PySide6.QtHelp"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Wirely",
    icon=os.path.join(ASSETS, "wirely.ico") if sys.platform == "win32" else None,
    version=version_file,
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Wirely")

if sys.platform == "darwin":
    icns = os.path.join(ROOT, "build", "Wirely.icns")
    app = BUNDLE(
        coll,
        name="Wirely.app",
        icon=icns if os.path.exists(icns) else None,
        bundle_identifier="io.github.richiewillmott.wirely",
        info_plist={
            "CFBundleName": "Wirely",
            "CFBundleDisplayName": "Wirely",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "GPL-3.0-or-later",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Wirely circuit",
                "CFBundleTypeExtensions": ["wirely", "spark"],
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "CFBundleTypeIconFile": "WirelyDoc.icns",
                "LSItemContentTypes": ["io.github.richiewillmott.wirely.circuit"],
            }],
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": "io.github.richiewillmott.wirely.circuit",
                "UTTypeDescription": "Wirely circuit",
                "UTTypeConformsTo": ["public.data", "public.content"],
                "UTTypeIconFile": "WirelyDoc.icns",
                "UTTypeTagSpecification": {"public.filename-extension": ["wirely", "spark"]},
            }],
        },
    )
