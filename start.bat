@echo off
rem ============================================================
rem  SEN-Kaleido one-click launcher
rem  Starts the unified server (web UI + API) on port 8080.
rem  Double-click to run. First run installs deps and seeds data.
rem  Note: kept ASCII-only because cmd.exe parses .bat files
rem  using the system OEM codepage, which corrupts UTF-8 text.
rem ============================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---- pick interpreter: prefer project venv ----
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem ---- first run: install deps if kaleido is not importable ----
"%PY%" -c "import kaleido" >nul 2>nul
if errorlevel 1 (
  echo [setup] installing dependencies: pip install -e .
  "%PY%" -m pip install -e .
  if errorlevel 1 (
    echo [error] dependency installation failed.
    pause
    exit /b 1
  )
)

rem ---- fall back to offline stub when no API key is present ----
if "%SEN_KALEIDO_LLM_PROVIDER%"=="" if "%DEEPSEEK_API_KEY%"=="" (
  set "SEN_KALEIDO_LLM_PROVIDER=stub"
  echo [info] DEEPSEEK_API_KEY not set, using offline stub client.
)

rem ---- first run: seed sample data (skip if it already exists) ----
if not exist "data\students\index.json" (
  echo [setup] seeding sample data...
  "%PY%" scripts\seed_data.py
)

echo.
echo   SEN-Kaleido server is starting...
echo   Web UI : http://127.0.0.1:8080/
echo   LAN    : http://YOUR-IP:8080/
echo   Press Ctrl+C to stop.
echo.

rem ---- start unified server (Bottle + waitress) ----
"%PY%" -m kaleido.api.app
endlocal
