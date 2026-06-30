@echo off
REM ============================================================================
REM  Bernie Studio - open the desktop app (GUI).
REM  Use this once you've already run the first-time setup (run.bat).
REM  It just launches the app and opens it in your browser.
REM ============================================================================
setlocal
title Bernie Studio
cd /d "%~dp0"

if "%BERNIE_HOME%"=="" ( set "HOMEDIR=%~dp0BernieStudioData" ) else ( set "HOMEDIR=%BERNIE_HOME%" )

REM Not installed yet?  Hand off to the first-run installer.
if not exist "%HOMEDIR%\.installed" (
  echo  First-time setup hasn't run yet - starting it now...
  call "%~dp0run.bat"
  exit /b
)

set "PYEXE=%HOMEDIR%\python_embeded\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo.
echo  Opening Bernie Studio at  http://127.0.0.1:8787  ...
echo  (Leave this window open while you use the app. Renders keep running if you close it.)
echo.
"%PYEXE%" "%~dp0bernie\gui.py"
pause
