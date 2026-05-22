# -*- mode: python ; coding: utf-8 -*-
import sys

# 根据平台选择要打包的原生库
_binaries = []
if sys.platform == 'win32':
    _binaries = [('libs/opus.dll', '.')]
elif sys.platform == 'linux':
    import os
    # 尝试常见路径（CentOS/RHEL 用 lib64，Ubuntu/Debian 用 lib/x86_64-linux-gnu）
    for candidate in ['/usr/lib64/libopus.so.0',
                      '/usr/lib/x86_64-linux-gnu/libopus.so.0',
                      '/usr/lib/libopus.so.0']:
        if os.path.isfile(candidate):
            _binaries = [(candidate, '.')]
            break

# 平台特定的 hidden imports
_platform_imports = []
if sys.platform == 'win32':
    _platform_imports = ['keyboard']
elif sys.platform == 'linux':
    _platform_imports = ['pynput', 'pynput.keyboard', 'pynput.keyboard._xorg']

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_binaries,
    datas=[('app.ico', '.')],
    hiddenimports=[
        'customtkinter',
        'pyaudio',
        'numpy',
        'yaml',
        'PIL.Image',
        'PIL.ImageTk',
        'requests',
        *_platform_imports,
        # 内部模块（确保 PyInstaller 能发现）
        'core',
        'core.protocol',
        'core.codec',
        'core.packet_factory',
        'core.packet_parser',
        'config',
        'config.settings',
        'network',
        'network.udp_client',
        'network.connection_manager',
        'network.api_client',
        'services',
        'services.talk_service',
        'services.room_service',
        'services.location_service',
        'services.mdc1200',
        'services.tail_tone_service',
        'audio',
        'audio.audio_handler',
        'audio.audio_manager',
        'ptt',
        'ptt.hotkey',
        'ui',
        'ui.theme',
        'ui.app',
        'ui.components',
        'ui.components.status_bar',
        'ui.components.ptt_button',
        'ui.components.chat_panel',
        'ui.components.room_selector',
        'ui.components.audio_panel',
        'ui.components.config_dialog',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter.test',
        'unittest',
        'pydoc',
        'distutils',
        'setuptools',
        'pip',
        'lib2to3',
        'test',
    ],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='78HAM',
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
    icon='app.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='78HAM',
)
