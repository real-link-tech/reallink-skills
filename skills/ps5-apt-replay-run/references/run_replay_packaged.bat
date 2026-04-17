@echo off
setlocal
set "RunMode=Packaged"
call "%~dp0run_replay.bat" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
