@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
rem The patcher's own files sit in this folder, beside this file.
set "VF1_FILES=%SCRIPT_DIR%Virtual Families 1 Fun Patcher Files\"
if not exist "%VF1_FILES%vf1_patcher.py" (
  echo Could not find the "Virtual Families 1 Fun Patcher Files" folder next to this file.
  echo Unzip the whole patcher download and keep that folder beside this file.
  pause
  exit /b 1
)
echo.
echo Virtual Families 1 Fun Patcher - {VERSION}
echo This creates a separate modded game folder next to the vanilla folder
echo (or in your Games folder if the game is installed under Program Files).
echo Enter or drag the original "Virtual Families.exe" here.
set /p VF1_EXE=EXE path:
set "VF1_EXE=%VF1_EXE:"=%"
if not exist "%VF1_EXE%" (
  echo File not found: "%VF1_EXE%"
  pause
  exit /b 1
)
rem py.exe existing does not mean it has a Python 3 registered, so try it and
rem fall back on failure rather than committing to a branch up front.
set "VF1_PY="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
  if not errorlevel 1 set "VF1_PY=py -3"
)
if not defined VF1_PY (
  rem `where python` succeeding proves nothing: it also matches Python 2 and
  rem the Windows Store execution alias, which exits without running anything.
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
    if not errorlevel 1 set "VF1_PY=python"
  )
)
if not defined VF1_PY (
  echo Could not find Python 3.9 or newer. Install it from https://www.python.org/downloads/
  echo and keep the "tcl/tk and IDLE" component ticked.
  pause
  exit /b 1
)
%VF1_PY% "%VF1_FILES%vf1_patcher.py" apply --exe "%VF1_EXE%" --manifest "%VF1_FILES%manifest.json"
echo.
pause
