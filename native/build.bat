@echo off
rem Build vf1fun.dll (32-bit, static CRT) into build\.
setlocal
set ROOT=%~dp0..
if not exist "%ROOT%\build" mkdir "%ROOT%\build"
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1
cl /nologo /O2 /MT /EHsc /W3 /LD "%ROOT%\native\vf1fun\vf1fun.cpp" /Fo"%ROOT%\build\\" /Fe"%ROOT%\build\vf1fun.dll" /link user32.lib kernel32.lib /MANIFEST:EMBED /MANIFESTDEPENDENCY:"type='win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' processorArchitecture='x86' publicKeyToken='6595b64144ccf1df' language='*'" || exit /b 1
