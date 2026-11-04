@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo The project .venv was not found. Run setup.bat first.
  exit /b 1
)
".venv\Scripts\python.exe" "cc\companion.py"
