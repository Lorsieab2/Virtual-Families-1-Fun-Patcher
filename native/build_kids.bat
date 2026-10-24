@echo off
rem Build vf1kids.dll (32-bit, static CRT) into build\: the Up to 28 Children companion DLL.
rem Regenerate native\vf1kids\vf1kids_sites.h with tools\vf1_kids_sites.py first if the pins changed.
rem
rem   build_kids.bat          the shipped DLL
rem   build_kids.bat test     the harness DLL (exports the planning and state test entry points,
rem                           writes build\vf1kids_test.dll)
rem
rem Set VF1_BUILD_DIR to build somewhere other than build\ (the tests give each run its own folder,
rem so parallel test runs never write the same files).
setlocal
set ROOT=%~dp0..
set "BUILD=%ROOT%\build"
if not "%VF1_BUILD_DIR%"=="" set "BUILD=%VF1_BUILD_DIR%"
if not exist "%BUILD%" mkdir "%BUILD%"
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1
set DEFS=
set OUT=vf1kids
if /I "%1"=="test" (
  set DEFS=/DVF1KIDS_TEST
  set OUT=vf1kids_test
)
cl /nologo /O2 /MT /EHsc /W4 /WX %DEFS% /LD /GS "%ROOT%\native\vf1kids\vf1kids.cpp" /Fo"%BUILD%\%OUT%.obj" /Fe"%BUILD%\%OUT%.dll" /link kernel32.lib /NXCOMPAT /SAFESEH:NO || exit /b 1
if not exist "%BUILD%\%OUT%.dll" exit /b 1
