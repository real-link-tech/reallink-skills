@echo off
setlocal
set "RunMode=PC"
call "%~dp0run_replay.bat" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
