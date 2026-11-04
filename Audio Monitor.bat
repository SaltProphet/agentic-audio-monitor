@echo off
setlocal
cd /d "%~dp0"
call "%~dp0start.bat"
if errorlevel 1 (
  echo.
  echo Audio Monitor could not start. See the message above.
  pause
)
endlocal
