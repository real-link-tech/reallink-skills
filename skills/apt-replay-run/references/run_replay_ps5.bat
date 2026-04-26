@echo off
setlocal
set "RunMode=PS5"
call "%~dp0run_replay.bat" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
