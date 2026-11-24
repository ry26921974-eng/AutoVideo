# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 設定: build_exe.bat から使います。
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("imageio_ffmpeg")  # FFmpeg 本体を同梱
datas += [("サンプル", "サンプル")]  # サンプルプロジェクト

a = Analysis(
    ["main.py"],
    pathex=[],
    datas=datas,
    hiddenimports=["PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"],
    excludes=["tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AutoVideo", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="AutoVideo")
