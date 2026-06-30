@echo off
REM ============================================================================
REM  Bernie Studio - ONE-CLICK.  Double-click this file (after downloading the
REM  repo to your PC - you cannot run it from the GitHub website).
REM  First run installs EVERYTHING, then opens the app in your browser.
REM  (goto-label structure - avoids fragile parenthesized blocks.)
REM ============================================================================
setlocal enabledelayedexpansion
title Bernie Studio
cd /d "%~dp0"

if "%BERNIE_HOME%"=="" (set "HOMEDIR=%~dp0BernieStudioData") else (set "HOMEDIR=%BERNIE_HOME%")
if not exist "%HOMEDIR%" mkdir "%HOMEDIR%" 2>nul

REM --- guard: an install already running in another window? ---
if exist "%HOMEDIR%\.installing" goto installing

REM --- first-time setup needed? ---
if not exist "%HOMEDIR%\.installed" goto firstrun
goto launch


:installing
echo.
echo  An install is already running in another window.
echo  Please WAIT for it to finish, then double-click run.bat again.
echo.
echo  If you are sure nothing is installing, delete this file and retry:
echo     "%HOMEDIR%\.installing"
echo.
pause
exit /b 0


:firstrun
echo.
echo ============================================================
echo    BERNIE STUDIO  -  first-time setup
echo ============================================================
echo.
echo  The image model FLUX.1-dev needs a FREE HuggingFace token.
echo    1. get one:        https://huggingface.co/settings/tokens
echo    2. accept license: https://huggingface.co/black-forest-labs/FLUX.1-dev
echo.
if exist "keys.env" goto haskeys
set /p "HFTOK=  Paste your HuggingFace token (or press Enter to skip): "
> keys.env echo HF_TOKEN=!HFTOK!
>> keys.env echo CEREBRAS_API_KEY=
>> keys.env echo GROQ_API_KEY=
:haskeys
REM load HF_TOKEN from keys.env so setup can fetch the gated FLUX model
for /f "usebackq tokens=1,* delims==" %%A in ("keys.env") do if /i "%%A"=="HF_TOKEN" set "HF_TOKEN=%%B"
echo.
echo  Installing engine, models and LLMs (about 50 GB, one time). Grab a coffee...
echo  Leave this window OPEN until it says SETUP COMPLETE.
echo.
> "%HOMEDIR%\.installing" echo running
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
del "%HOMEDIR%\.installing" 2>nul
if errorlevel 1 goto setupfail
goto launch


:setupfail
echo.
echo  *** Setup hit a problem - see the messages above.   ***
echo  *** Fix it, then double-click run.bat again.         ***
echo.
pause
exit /b 1


:launch
set "PYEXE=%HOMEDIR%\python_embeded\python.exe"
if not exist "%PYEXE%" goto nopython
echo.
echo ============================================================
echo    Launching BERNIE STUDIO - opening in your browser...
echo ============================================================
echo.
echo    If your browser does not open, go to:  http://127.0.0.1:8787
echo.
echo    Keep THIS window open while you use the app.
echo.
if "%~1"=="" ("%PYEXE%" "%~dp0bernie\gui.py") else ("%PYEXE%" "%~dp0make.py" %*)
echo.
echo ============================================================
echo    Bernie Studio has stopped. (Renders keep running in the background.)
echo ============================================================
pause
exit /b 0


:nopython
echo.
echo  Bundled Python missing - setup did not finish. Re-running setup...
echo.
> "%HOMEDIR%\.installing" echo running
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
del "%HOMEDIR%\.installing" 2>nul
if exist "%PYEXE%" goto launch
echo.
echo  *** Could not create the bundled Python. Install "Git for Windows",   ***
echo  *** make sure you are online, then double-click run.bat again.         ***
echo.
pause
exit /b 1
