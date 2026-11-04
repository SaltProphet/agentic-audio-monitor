@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0preflight.ps1" -Install
if errorlevel 1 pause
