# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['buscar_piezas.py'],
    pathex=[],
    binaries=[],
    datas=[('ALSI_BUSCADOR.ico', '.'), ('ALSI_ISOTIPO_naranja.png', '.'),
           ('ALSI_IMAGOTIPO_naranja.png', '.'), ('docs', 'docs'), ('CHANGELOG.md', '.'),
           ('SwPropExtractor.exe', '.'), ('SolidWorks.Interop.swdocumentmgr.dll', '.'),
           # V2.0.0 - Rediseño UI: fuentes de marca, iconos SVG y hoja de estilo
           ('fonts', 'fonts'), ('icons', 'icons'), ('alsi_buscador.qss', '.')],
    hiddenimports=['PyQt5.QtSvg', 'xlrd', 'openpyxl'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BuscadorPiezas',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ALSI_BUSCADOR.ico'],
)
