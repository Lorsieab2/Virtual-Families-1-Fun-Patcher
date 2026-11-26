@echo off
rem Build vf1skin.dll (32-bit, static CRT) into build\: Skin Tones' companion DLL (PROTOTYPE: the drawing part).
rem Regenerate native\vf1skin\skin_tables.h with tools\vf1_skin_tables.py first if a tone changed.
rem The tests run this same DLL under emulation: there is no separate test build.
rem
rem Set VF1_BUILD_DIR to build somewhere other than build\ (the tests give each run its own folder,
rem so parallel test runs never write the same files).
setlocal
set ROOT=%~dp0..
set "BUILD=%ROOT%\build"
if not "%VF1_BUILD_DIR%"=="" set "BUILD=%VF1_BUILD_DIR%"
if not exist "%BUILD%" mkdir "%BUILD%"
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1
cl /nologo /O2 /MT /EHsc /W4 /WX /LD /GS "%ROOT%\native\vf1skin\vf1skin.cpp" /Fo"%BUILD%\vf1skin.obj" /Fe"%BUILD%\vf1skin.dll" /link kernel32.lib /NXCOMPAT /SAFESEH:NO || exit /b 1
if not exist "%BUILD%\vf1skin.dll" exit /b 1
