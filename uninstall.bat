@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
echo.
echo To remove the install, logs, or model weights, run uninstall.ps1 -Yes from this folder.
pause
