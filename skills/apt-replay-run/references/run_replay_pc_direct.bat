@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "ConfigFile=%SCRIPT_DIR%apt.pc.config.cmd"
if not "%~1"=="" set "ConfigFile=%~1"

if exist "%ConfigFile%" (
  echo [INFO] Loading config from "%ConfigFile%"
  call "%ConfigFile%"
) else (
  echo [ERROR] Config file not found: "%ConfigFile%"
  endlocal & exit /b 2
)

if not defined PCBuildDir (
  echo [ERROR] PCBuildDir is empty. Set PCBuildDir in config.
  endlocal & exit /b 2
)
if not defined PCExe set "PCExe=%PCBuildDir%\Windows\ProjectPBZ\Binaries\Win64\ProjectPBZ-Win64-Test.exe"
if not exist "%PCExe%" (
  echo [ERROR] PC exe not found: "%PCExe%"
  endlocal & exit /b 2
)
if not defined REPLAY_LIST (
  echo [ERROR] REPLAY_LIST is empty. Set REPLAY_LIST in config.
  endlocal & exit /b 2
)

if not defined PCBuildName (
  for %%I in ("%PCBuildDir%") do set "PCBuildName=%%~nxI"
)
if not defined WorkRoot set "WorkRoot=D:\APTWork"
if not defined MapPath set "MapPath=/Game/Maps/B02/PBZ_Xigu_WP"
if not defined WindowMode set "WindowMode=-windowed"
if not defined ExecCmds set "ExecCmds="
if not defined ExtraArgs set "ExtraArgs="
if not defined ArchiveRoot set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
if not defined PCSourceProfiling set "PCSourceProfiling=%WorkRoot%\UserDir\Saved\Profiling"
if not defined DoInsightsTrace set "DoInsightsTrace=true"
if not defined DoCSVProfiler set "DoCSVProfiler=false"
if not defined DoFPSChart set "DoFPSChart=false"
if not defined DoLLM set "DoLLM=false"
if not defined DoGPUPerf set "DoGPUPerf=false"
if not defined DoGPUReshape set "DoGPUReshape=false"
if not defined DoVideoCapture set "DoVideoCapture=false"

for %%I in ("%PCExe%") do set "PCExeDir=%%~dpI"

set "AptDoArgs="
if /I "%DoInsightsTrace%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoInsightsTrace"
if "%DoInsightsTrace%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoInsightsTrace"
if /I "%DoCSVProfiler%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoCSVProfiler"
if "%DoCSVProfiler%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoCSVProfiler"
if /I "%DoFPSChart%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoFPSChart"
if "%DoFPSChart%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoFPSChart"
if /I "%DoLLM%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoLLM"
if "%DoLLM%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoLLM"
if /I "%DoGPUPerf%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoGPUPerf"
if "%DoGPUPerf%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoGPUPerf"
if /I "%DoGPUReshape%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoGPUReshape"
if "%DoGPUReshape%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoGPUReshape"
if /I "%DoVideoCapture%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoVideoCapture"
if "%DoVideoCapture%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoVideoCapture"

set "ReplayListArg=%REPLAY_LIST%"
if not "%~2"=="" set "ReplayListArg=%~2"

set "ReplayInputFile="
for %%I in ("%ReplayListArg%") do set "ReplayInputExt=%%~xI"
if exist "%ReplayListArg%" if /I "%ReplayInputExt%"==".txt" set "ReplayInputFile=%ReplayListArg%"
if exist "%ReplayListArg%" if /I "%ReplayInputExt%"==".list" set "ReplayInputFile=%ReplayListArg%"

set /a Total=0
set /a Failed=0
set "SummaryFile=%WorkRoot%\pc_direct_summary.txt"
mkdir "%WorkRoot%" >nul 2>&1
del /q "%SummaryFile%" >nul 2>&1

echo [INFO] PCExe="%PCExe%"
echo [INFO] PCBuildName="%PCBuildName%"
echo [INFO] MapPath="%MapPath%"
echo [INFO] WindowMode="%WindowMode%"
echo [INFO] APT Do args:%AptDoArgs%
echo [INFO] ExtraArgs="%ExtraArgs%"
echo [INFO] Replay input="%ReplayListArg%"
echo [INFO] WorkRoot="%WorkRoot%"
echo [INFO] ArchiveRoot="%ArchiveRoot%"
echo.

if defined ReplayInputFile (
  echo [INFO] Replay input file="%ReplayInputFile%"
  for /f "usebackq delims=" %%R in ("%ReplayInputFile%") do (
    set "ReplayLine=%%R"
    if not "!ReplayLine!"=="" if not "!ReplayLine:~0,1!"=="#" (
      set /a Total+=1
      call :RunOneReplay "!ReplayLine!" !Total!
      if errorlevel 1 set /a Failed+=1
    )
  )
) else (
  set "RemainingReplayList=%ReplayListArg%"
  call :RunInlineReplayList
)

echo.
echo [INFO] PC direct replay finished. Total=!Total! Failed=!Failed!
echo [INFO] Summary="%SummaryFile%"

if "!Total!"=="0" (
  echo [ERROR] No replay entries found.
  endlocal & exit /b 2
)
if not "!Failed!"=="0" (
  endlocal & exit /b 1
)
endlocal & exit /b 0

:RunOneReplay
set "ReplayPath=%~1"
set "ReplayIndex=%~2"
for %%I in ("%ReplayPath%") do set "ReplayName=%%~nI"
if not defined ReplayName set "ReplayName=Replay%ReplayIndex%"

for /f %%I in ('powershell -NoProfile -Command Get-Date -Format yyyyMMdd-HHmmss') do set "ArchiveDate=%%I"
set "UserDir=%WorkRoot%\UserDir"
set "ProfilingDir=%PCSourceProfiling%"
set "LogDir=%UserDir%\Saved\Logs"
set "ArchiveTarget=%ArchiveRoot%\%PCBuildName%_%ArchiveDate%_%ReplayName%"

echo [INFO] [!ReplayIndex!] Running replay: "%ReplayPath%"
echo [INFO] [!ReplayIndex!] UserDir="%UserDir%"

rmdir /s /q "%ProfilingDir%" >nul 2>&1
rmdir /s /q "%LogDir%" >nul 2>&1
mkdir "%ProfilingDir%" >nul 2>&1
mkdir "%LogDir%" >nul 2>&1

pushd "%PCExeDir%" >nul
call "%PCExe%" "%MapPath%" ^
  -keepscreenawake ^
  -deterministic ^
  -AutomatedPerfTest.TestID="APT" ^
  -statnamedevents ^
  !AptDoArgs! ^
  -AutomatedPerfTest.ReplayPerfTest.ReplayName="%ReplayPath%" ^
  -ExecCmds="%ExecCmds%" ^
  -gauntlet=AutomatedReplayPerfTest ^
  %WindowMode% ^
  -log ^
  -unattended ^
  -nosplash ^
  -stdout ^
  -FullStdOutLogOutput ^
  -nomcp ^
  -notimeouts ^
  -noepicportal ^
  -userdir="%UserDir%" ^
  -abslog="%LogDir%\ProjectPBZ.log" ^
  %ExtraArgs%
set "RUN_EXIT=%ERRORLEVEL%"
popd >nul

echo [INFO] [!ReplayIndex!] Game exit code: %RUN_EXIT%

mkdir "%ArchiveTarget%\profiling" >nul 2>&1
mkdir "%ArchiveTarget%\logs" >nul 2>&1

if exist "%ProfilingDir%" (
  robocopy "%ProfilingDir%" "%ArchiveTarget%\profiling" /E /R:2 /W:2 >nul
  set "ROBO_PROFILE=%ERRORLEVEL%"
) else (
  echo [WARN] [!ReplayIndex!] Profiling dir not found: "%ProfilingDir%"
  set "ROBO_PROFILE=8"
)

if exist "%LogDir%" (
  robocopy "%LogDir%" "%ArchiveTarget%\logs" /E /R:2 /W:2 >nul
)

if not "%RUN_EXIT%"=="0" (
  echo FAIL [%ReplayIndex%] rc=%RUN_EXIT% "%ReplayPath%" >> "%SummaryFile%"
  echo [ERROR] [!ReplayIndex!] FAIL rc=%RUN_EXIT%
  exit /b %RUN_EXIT%
)
if %ROBO_PROFILE% GEQ 8 (
  echo FAIL [%ReplayIndex%] profiling_copy_rc=%ROBO_PROFILE% "%ReplayPath%" >> "%SummaryFile%"
  echo [ERROR] [!ReplayIndex!] Profiling copy failed rc=%ROBO_PROFILE%
  exit /b %ROBO_PROFILE%
)

echo PASS [%ReplayIndex%] "%ReplayPath%" archive="%ArchiveTarget%" >> "%SummaryFile%"
echo [INFO] [!ReplayIndex!] PASS archive="%ArchiveTarget%"
echo.
exit /b 0

:RunInlineReplayList
if not defined RemainingReplayList exit /b 0
set "ReplayLine="
for /f "tokens=1* delims=;" %%A in ("!RemainingReplayList!") do (
  set "ReplayLine=%%~A"
  set "RemainingReplayList=%%~B"
)
if not "!ReplayLine!"=="" if not "!ReplayLine:~0,1!"=="#" (
  set /a Total+=1
  call :RunOneReplay "!ReplayLine!" !Total!
  if errorlevel 1 set /a Failed+=1
)
if defined RemainingReplayList goto RunInlineReplayList
exit /b 0
