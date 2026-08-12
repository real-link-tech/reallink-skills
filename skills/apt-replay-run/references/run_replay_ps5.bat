@echo off
setlocal
set "RunMode=PS5"
if /I "%~1"=="--extra-args" (
  if "%~2"=="" (
    echo [ERROR] --extra-args requires a quoted game command-line argument string.
    endlocal & exit /b 2
  )
  call "%~dp0run_replay_batch.bat" "%~dp0apt.ps5.config.cmd" "" "%~2"
) else if "%~1"=="" (
  call "%~dp0run_replay_batch.bat" "%~dp0apt.ps5.config.cmd"
) else (
  call "%~dp0run_replay_batch.bat" %*
)
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
