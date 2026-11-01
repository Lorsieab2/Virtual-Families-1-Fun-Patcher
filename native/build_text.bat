@echo off
rem Build vf1text.dll (32-bit, static CRT) into build\: Render Unicode with In-Game Fonts' companion DLL.
rem Regenerate native\vf1text\extenders.inc with scripts\build_vf1_text_tables.py first if vf1_text.py changed.
rem The tests run this same DLL under emulation and through rundll32: there is no separate test build.
rem
rem Set VF1_BUILD_DIR to build somewhere other than build\ (the tests give each run its own folder).
setlocal
set ROOT=%~dp0..
set "BUILD=%ROOT%\build"
if not "%VF1_BUILD_DIR%"=="" set "BUILD=%VF1_BUILD_DIR%"
if not exist "%BUILD%" mkdir "%BUILD%"
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1
cl /nologo /O2 /MT /EHsc /W4 /WX /LD /GS- "%ROOT%\native\vf1text\vf1text.cpp" /Fo"%BUILD%\vf1text.obj" /Fe"%BUILD%\vf1text.dll" /link kernel32.lib gdi32.lib /NXCOMPAT /SAFESEH:NO || exit /b 1
if not exist "%BUILD%\vf1text.dll" exit /b 1
rem The same source as vf1font.dll: Use Unicode Font (overrides in-game fonts).
cl /nologo /O2 /MT /EHsc /W4 /WX /LD /GS- /DVF1_FONT_MODE "%ROOT%\native\vf1text\vf1text.cpp" /Fo"%BUILD%\vf1font.obj" /Fe"%BUILD%\vf1font.dll" /link kernel32.lib gdi32.lib /NXCOMPAT /SAFESEH:NO || exit /b 1
if not exist "%BUILD%\vf1font.dll" exit /b 1
