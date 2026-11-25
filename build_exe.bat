@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
)
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean AutoVideo.spec
if errorlevel 1 (
  echo ビルドに失敗しました。
  pause
  exit /b 1
)
echo.
echo 完成しました: dist\AutoVideo\AutoVideo.exe
pause
