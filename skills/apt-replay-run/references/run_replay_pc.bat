@echo off
setlocal
set "RunMode=PC"
if /I "%~1"=="--extra-args" (
  if "%~2"=="" (
    echo [ERROR] --extra-args requires a quoted game command-line argument string.
    endlocal & exit /b 2
  )
  call "%~dp0run_replay_pc_direct.bat" "%~dp0apt.pc.config.cmd" "" "%~2"
) else if /I "%~1"=="--quality" (
  if "%~2"=="" (
    echo [ERROR] --quality requires "CVar=Value;CVar=Value".
    endlocal & exit /b 2
  )
  set "APT_QUALITY_CVARS=%~2"
  call "%~dp0run_replay_pc_direct.bat" "%~dp0apt.pc.config.cmd"
) else if "%~1"=="" (
  call "%~dp0run_replay_pc_direct.bat" "%~dp0apt.pc.config.cmd"
) else (
  call "%~dp0run_replay_pc_direct.bat" %*
)
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
