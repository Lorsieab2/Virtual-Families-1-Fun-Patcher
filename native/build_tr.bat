@echo off
rem Build vf1tr.dll (32-bit, static CRT) into build\: the Translations setting's companion DLL.
rem Regenerate native\vf1tr\vf1tr_limits.h with tools\build_vf1_translation_limits.py first if the limits changed.
rem The tests run this same DLL under emulation: there is no separate test build.
rem
rem Set VF1_BUILD_DIR to build somewhere other than build\ (the tests give each run its own folder).
setlocal
set ROOT=%~dp0..
set "BUILD=%ROOT%\build"
if not "%VF1_BUILD_DIR%"=="" set "BUILD=%VF1_BUILD_DIR%"
if not exist "%BUILD%" mkdir "%BUILD%"
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1
cl /nologo /O2 /MT /W4 /WX /LD /GS- "%ROOT%\native\vf1tr\vf1tr.c" /Fo"%BUILD%\vf1tr.obj" /Fe"%BUILD%\vf1tr.dll" /link kernel32.lib /NXCOMPAT /SAFESEH:NO || exit /b 1
if not exist "%BUILD%\vf1tr.dll" exit /b 1
