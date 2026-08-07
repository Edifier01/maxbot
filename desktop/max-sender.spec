# PyInstaller spec — сборка: build.bat
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

pymax_datas, pymax_binaries, pymax_hidden = collect_all("pymax")
crypto_datas, crypto_binaries, crypto_hidden = collect_all("cryptography")

hiddenimports = collect_submodules("uvicorn") + collect_submodules("pymax")
hiddenimports += pymax_hidden + crypto_hidden
hiddenimports += [
    "multipart",
    "email.mime.multipart",
    "email.mime.text",
    "antiban_core",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=pymax_binaries + crypto_binaries,
    datas=[("static", "static")] + pymax_datas + crypto_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MAX-Sender",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
