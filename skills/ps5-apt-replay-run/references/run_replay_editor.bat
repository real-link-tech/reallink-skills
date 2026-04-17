@echo off
setlocal
set "RunMode=Editor"
call "%~dp0run_replay.bat" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
