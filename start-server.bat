@echo off
setlocal
cd /d "%~dp0"

echo Starting Server Video Service...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-server.ps1" %*

if errorlevel 1 (
  echo.
  echo Server failed to start. Review the error above.
  pause
)
endlocal
