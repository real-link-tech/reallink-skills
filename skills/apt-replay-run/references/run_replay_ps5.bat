@echo off
setlocal
set "RunMode=PS5"
call "%~dp0run_replay_batch.bat" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
