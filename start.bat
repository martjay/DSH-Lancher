@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo [error] uv is not on PATH. Install it from https://docs.astral.sh/uv/
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [start] venv missing, running install first...
  call "%~dp0install.bat"
  if errorlevel 1 exit /b 1
)

uv run dsh-launcher
exit /b %ERRORLEVEL%
