@echo off
REM ============================================================================
REM  Bernie Studio - ONE-CLICK.  Double-click this file (after downloading the
REM  repo to your PC - you cannot run it from the GitHub website).
REM  First run: installs EVERYTHING, then starts the autonomous series.
REM ============================================================================
setlocal enabledelayedexpansion
title Bernie Studio
cd /d "%~dp0"

if "%BERNIE_HOME%"=="" ( set "HOMEDIR=%~dp0BernieStudioData" ) else ( set "HOMEDIR=%BERNIE_HOME%" )

if not exist "%HOMEDIR%\.installed" (
  echo.
  echo ============================================================
  echo    BERNIE STUDIO  -  first-time setup
  echo ============================================================
  echo.
  echo  The image model ^(FLUX.1-dev^) needs a FREE HuggingFace token.
  echo    1^) get one:        https://huggingface.co/settings/tokens
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
  if errorlevel 1 ( echo. & echo  *** Setup hit a problem - see messages above. *** & echo. & pause & exit /b 1 )
)

REM use the bundled Python from setup (falls back to system python if missing)
set "PYEXE=%HOMEDIR%\python_embeded\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo.
echo ============================================================
echo    Starting the AUTONOMOUS SERIES - making the whole season!
echo    (It keeps building the next episode by itself.)
echo ============================================================
echo.
if "%~1"=="" ( "%PYEXE%" "%~dp0make.py" --series ) else ( "%PYEXE%" "%~dp0make.py" %* )

echo.
echo ============================================================
echo    Bernie Studio has stopped. See messages above.
echo ============================================================
pause
