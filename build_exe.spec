# -*- mode: python ; coding: utf-8 -*-
# Альтернатива скрипту scripts/build_windows.ps1
# Запуск из корня проекта: pyinstaller build_exe.spec

from pathlib import Path

import PyQt6

_qt_translations = Path(PyQt6.__file__).resolve().parent / "Qt6" / "translations"

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('resources/styles_classic.qss', 'resources'),
        ('resources/styles_glass.qss', 'resources'),
        (str(_qt_translations), 'PyQt6/Qt6/translations'),
    ],
    hiddenimports=[
        'soundcard',
        'soundcard.mediafoundation',
        'numpy',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        # Импорт только из тела функций — PyInstaller не всегда подхватывает сам.
        'ui.image_import_edit_dialog',
        'app.paths',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AudioVisualization',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AudioVisualization',
)
