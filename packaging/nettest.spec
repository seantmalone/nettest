# packaging/nettest.spec
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

a = Analysis(
    ["../src/nettest/cli/__main__.py"],
    pathex=["../src"],
    binaries=[],
    datas=[
        ("../src/nettest/web/static", "nettest/web/static"),
        ("../examples/nettest.yaml", "nettest"),
    ],
    hiddenimports=[
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.loops.auto",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    [],
    name="nettest",
    debug=False, strip=False, upx=False,
    console=True,
    target_arch=None,
)
