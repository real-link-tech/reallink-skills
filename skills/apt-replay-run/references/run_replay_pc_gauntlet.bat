@echo off
setlocal
set "RunMode=PC"
if "%~1"=="" (
  call "%~dp0run_replay_batch.bat" "%~dp0apt.pc.config.cmd"
) else (
  call "%~dp0run_replay_batch.bat" %*
)
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
