@echo off
REM ============================================================================
REM  Bernie Studio - ONE-CLICK. Double-click this file.
REM  First run: guides setup, auto-installs EVERYTHING (engine, models, LLMs),
REM  then starts the FULLY AUTONOMOUS series - making the whole season by itself.
REM ============================================================================
setlocal enabledelayedexpansion
title Bernie Studio
cd /d "%~dp0"

if not exist "BernieStudioData\.installed" (
  echo.
  echo ============================================================
  echo    BERNIE STUDIO  -  first-time setup
  echo ============================================================
  echo.
  echo  The image model ^(FLUX.1-dev^) needs a FREE HuggingFace token.
  echo    1^) get one:    https://huggingface.co/settings/tokens
  echo    2^) accept license: https://huggingface.co/black-forest-labs/FLUX.1-dev
  echo.
  if not exist "keys.env" (
    set /p HFTOK="  Paste your HuggingFace token (or press Enter to skip): "
    > keys.env echo HF_TOKEN=!HFTOK!
    >> keys.env echo CEREBRAS_API_KEY=
    >> keys.env echo GROQ_API_KEY=
    if not "!HFTOK!"=="" set "HF_TOKEN=!HFTOK!"
  ) else (
    for /f "tokens=2 delims==" %%T in ('findstr /b "HF_TOKEN=" keys.env') do set "HF_TOKEN=%%T"
  )
  echo.
  echo  Installing engine, models and LLMs (~50 GB, one time). Grab a coffee...
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 ( echo Setup hit a problem - see messages above. & pause & exit /b 1 )
)

if "%~1"=="" (
  echo.
  echo ============================================================
  echo    Starting the AUTONOMOUS SERIES - making the whole season!
  echo    ^(It will keep building the next episode by itself.^)
  echo ============================================================
  echo.
  python "%~dp0make.py" --series
) else (
  python "%~dp0make.py" %*
)
pause
