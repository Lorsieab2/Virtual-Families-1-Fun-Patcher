@echo off
rem Opens the Virtual Families 1 Patcher window. Needs Python 3.
where py >nul 2>nul && (start "" pyw -3 "%~dp0patcher\vf1_patcher_gui.py" & exit /b)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0patcher\vf1_patcher_gui.py" & exit /b)
echo Python 3 is needed to run the patcher. Get it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" when installing), then run this again.
pause
