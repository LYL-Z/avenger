# -*- mode: python ; coding: utf-8 -*-
# Avenger Desktop 打包配置 — python -m PyInstaller avenger_desktop.spec
a = Analysis(
    ['avenger_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('avenger_server.py', '.'),
        ('avenger_studio.py', '.'),
        ('avenger_agent.py', '.'),
        ('avenger_core.py', '.'),
        ('avenger_hud.py', '.'),
        ('avenger_mcp_server.py', '.'),
        ('avenger.html', '.'),
        ('PRODUCT.md', '.'),
        ('使用说明.md', '.'),
        ('README.md', '.'),
        ('vendor', 'vendor'),
    ],
    hiddenimports=['webview', 'avenger_server', 'avenger_studio', 'avenger_agent', 'avenger_core'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PyQt5', 'PyQt6', 'torch'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Avenger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Avenger',
)
