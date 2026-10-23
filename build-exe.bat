@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo [error] uv is not on PATH. Install it from https://docs.astral.sh/uv/
  exit /b 1
)

if not exist "assets\dsh.ico" (
  echo [error] missing assets\dsh.ico
  exit /b 1
)

echo [build] syncing extras...
uv sync --extra build
if errorlevel 1 exit /b 1

echo [build] pyinstaller onefile...
uv run python scripts\build_exe.py
if errorlevel 1 exit /b 1

echo [build] exe: "%~dp0dist\DeepSeek Harness.exe"
exit /b 0
