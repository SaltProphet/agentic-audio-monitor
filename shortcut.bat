@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0shortcut.ps1"
if errorlevel 1 pause
echo.
pause
