@echo off
chcp 65001 > nul
cd /d "%~dp0"
where python > nul 2>&1
if errorlevel 1 (
  echo Python が見つかりません。https://www.python.org/ から Python 3.10 以上をインストールしてください。
  echo インストール時に「Add python.exe to PATH」にチェックを入れてください。
  pause
  exit /b 1
)
if not exist .venv (
  echo 初回セットアップ中です。数分かかります…
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo インストールに失敗しました。
    pause
    exit /b 1
  )
)
start "" .venv\Scripts\pythonw main.py %*
