@echo off
REM Bernie Studio - one-click. First run auto-installs everything, then makes an episode.
title Bernie Studio
cd /d "%~dp0"

if not exist "BernieStudioData\.installed" (
  echo ============================================================
  echo   FIRST RUN - installing engine, models, and LLMs.
  echo   This downloads ~50 GB one time. Grab a coffee.
  echo   ^(For gated FLUX.1-dev, set HF_TOKEN first - see README.^)
  echo ============================================================
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
)

echo.
echo Starting Bernie Studio...
python "%~dp0make.py" %*
pause
