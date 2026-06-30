@echo off
REM ============================================================================
REM  Bernie Studio - ONE-CLICK.  Double-click this file (after downloading the
REM  repo to your PC - you cannot run it from the GitHub website).
REM  First run: installs EVERYTHING, then opens the app in your browser.
REM ============================================================================
setlocal enabledelayedexpansion
title Bernie Studio
cd /d "%~dp0"

if "%BERNIE_HOME%"=="" ( set "HOMEDIR=%~dp0BernieStudioData" ) else ( set "HOMEDIR=%BERNIE_HOME%" )
if not exist "%HOMEDIR%" mkdir "%HOMEDIR%" 2>nul

REM --- Guard: if an install is already running (this window or another), DON'T start a 2nd one ---
if exist "%HOMEDIR%\.installing" (
  echo.
  echo  An install is already running in another window.
  echo  Please WAIT for it to finish ^(it says "SETUP COMPLETE" when done^),
  echo  then double-click run.bat again.
  echo.
  echo  ^(If you are 100%% sure nothing is installing, delete this file and retry:^)
  echo     "%HOMEDIR%\.installing"
  echo.
  pause
  exit /b 0
)

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
  echo  Leave this window OPEN until it says SETUP COMPLETE.
  echo.
  >"%HOMEDIR%\.installing" echo running
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  del "%HOMEDIR%\.installing" 2>nul
  if errorlevel 1 ( echo. & echo  *** Setup hit a problem - see messages above. *** & echo. & pause & exit /b 1 )
)

REM ALWAYS use the bundled, torch-compatible Python (NEVER the system one - that's
REM what caused "python is too new / can't install torch" on Python 3.14 machines).
set "PYEXE=%HOMEDIR%\python_embeded\python.exe"
if not exist "%PYEXE%" (
  echo.
  echo  Bundled Python is missing - setup did not finish. Re-running setup...
  echo.
  >"%HOMEDIR%\.installing" echo running
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  del "%HOMEDIR%\.installing" 2>nul
)
if not exist "%PYEXE%" (
  echo.
  echo  *** Could not create the bundled Python. See the messages above.       ***
  echo  *** Usual fixes: install "Git for Windows", make sure you are online,   ***
  echo  *** then double-click run.bat again. Nothing else needs installing.     ***
  echo.
  pause & exit /b 1
)

echo.
echo ============================================================
echo    Launching BERNIE STUDIO - opening the app in your browser
echo    (Create episodes, watch renders live, start the season.)
echo ============================================================
echo.
echo    If your browser doesn't open, go to:  http://127.0.0.1:8787
echo.
REM  No args  -> launch the desktop GUI (the front door).
REM  Any args -> pass straight to make.py (e.g. run.bat --series).
if "%~1"=="" ( "%PYEXE%" "%~dp0bernie\gui.py" ) else ( "%PYEXE%" "%~dp0make.py" %* )

echo.
echo ============================================================
echo    Bernie Studio has stopped. See messages above.
echo    (Any renders you started keep running in the background.)
echo ============================================================
pause
