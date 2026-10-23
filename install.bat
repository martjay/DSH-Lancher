@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo [error] uv is not on PATH. Install it from https://docs.astral.sh/uv/
  exit /b 1
)

echo [install] syncing runtime + build extras...
uv sync --extra build
if errorlevel 1 (
  echo [error] uv sync failed
  exit /b 1
)

echo [install] done. Use start.bat to launch, or build-exe.bat to pack an exe.
exit /b 0
