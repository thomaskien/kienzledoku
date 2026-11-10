@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
set "RECORD_BUILD_STATUS=%ERRORLEVEL%"
pause
exit /b %RECORD_BUILD_STATUS%
