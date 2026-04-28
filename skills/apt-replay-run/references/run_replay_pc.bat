@echo off
setlocal
set "RunMode=PC"
call "%~dp0run_replay_batch.bat" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
