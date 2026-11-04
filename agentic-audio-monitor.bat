@echo off
setlocal
cd /d "%~dp0"

set "ACTION=%~1"
if not defined ACTION set "ACTION=start"

if /I "%ACTION%"=="start" goto start_monitor
if /I "%ACTION%"=="stop" goto stop_monitor
if /I "%ACTION%"=="restart" goto restart_monitor
if /I "%ACTION%"=="status" goto status_monitor

echo Usage: agentic-audio-monitor.bat [start^|stop^|restart^|status]
exit /b 2

:start_monitor
start "Agentic Audio Monitor" "%~dp0run.bat"
echo Agentic Audio Monitor start requested.
echo Closed Captions are managed from the Audio Monitor web UI.
exit /b 0

:stop_monitor
call "%~dp0stop.bat"
exit /b %ERRORLEVEL%

:restart_monitor
call "%~dp0stop.bat"
timeout /t 1 /nobreak >nul
goto start_monitor

:status_monitor
if not exist "%~dp0monitor.pid" (
  echo Agentic Audio Monitor is not running.
  exit /b 0
)
for /f "usebackq tokens=1" %%P in ("%~dp0monitor.pid") do set "MONITOR_PID=%%P"
if not defined MONITOR_PID (
  echo monitor.pid is invalid.
  exit /b 1
)
powershell -NoProfile -Command "$p = Get-Process -Id %MONITOR_PID% -ErrorAction SilentlyContinue; if ($p) { Write-Output ('Agentic Audio Monitor is running (pid {0}).' -f $p.Id); exit 0 } else { Write-Output 'Agentic Audio Monitor is not running.'; exit 1 }"
exit /b %ERRORLEVEL%
