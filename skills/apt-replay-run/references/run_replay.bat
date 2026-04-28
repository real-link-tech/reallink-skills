@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "ConfigFile=%SCRIPT_DIR%apt.config.cmd"
set "RequestedRunMode=%RunMode%"
if not "%~1"=="" set "ConfigFile=%~1"
if exist "%ConfigFile%" echo [INFO] Loading config from "%ConfigFile%"
if exist "%ConfigFile%" call "%ConfigFile%"
if not exist "%ConfigFile%" echo [WARN] Config file not found: "%ConfigFile%". Using inline defaults.
if defined RequestedRunMode set "RunMode=%RequestedRunMode%"

if not defined EnginePath set "EnginePath=D:\UnrealEngine"
if not defined ProjectPath set "ProjectPath=E:\PBZ\ProjectPBZ"
if not defined REPLAY_PATH set "REPLAY_PATH=\\192.168.0.7\store\APT\ReplayFiles\sample.replay"
if not defined PS5Target set "PS5Target=192.168.103.108"
if not defined Configuration set "Configuration=Test"
if not defined MaxDuration set "MaxDuration=3600"
if not defined PS5BuildDir set "PS5BuildDir=\\192.168.103.61\builds_ps\PS5\Test\BuildName\CL-123456_JKS-0000"
if not defined PCBuildDir set "PCBuildDir=%ProjectPath%\Saved\StagedBuilds\Windows"
if not defined Iterations set "Iterations=1"
if not defined ExecCmds set "ExecCmds=Reallink.ProfileMatrix.SuspendCVarsRefresh 1;r.DynamicRes.OperationMode 0;"
if not defined DoInsightsTrace set "DoInsightsTrace=true"
if not defined DoCSVProfiler set "DoCSVProfiler=false"
if not defined DoFPSChart set "DoFPSChart=false"
if not defined DoLLM set "DoLLM=false"
if not defined DoGPUPerf set "DoGPUPerf=false"
if not defined DoGPUReshape set "DoGPUReshape=false"
if not defined DoVideoCapture set "DoVideoCapture=false"
if not defined PS5SourceProfiling set "PS5SourceProfiling=P:\%PS5Target%\devlog\app\projectpbz\projectpbz\saved\profiling"
if not defined PCSourceProfiling set "PCSourceProfiling=%ProjectPath%\Saved\Profiling"
if not defined ArchiveRoot set "ArchiveRoot=\\192.168.0.7\store\APT\Report"

set "AptConfiguration=%Configuration%"
set "AptTestID=APT"

set "Configuration="

set "EnginePath=%EnginePath:"=%"
set "RunMode=%RunMode:"=%"
if "%EnginePath%"=="" set "EnginePath=D:\UnrealEngine"

if not defined RunMode set "RunMode=PS5"
if /I "%RunMode%"=="PS5" (
  set "AptPlatform=PS5"
  set "AptTargetName=ProjectPBZ"
  set "AptBuildDir=%PS5BuildDir%"
  set "AptSourceProfiling=%PS5SourceProfiling%"
)
if /I "%RunMode%"=="PC" (
  set "AptPlatform=Win64"
  set "AptTargetName=ProjectPBZ"
  set "AptBuildDir=%PCBuildDir%"
  set "AptSourceProfiling=%PCSourceProfiling%"
)
if not defined AptPlatform (
  echo [ERROR] Invalid RunMode: "%RunMode%". Use PS5 or PC.
  endlocal & exit /b 2
)

set "MSBUILDDISABLENODEREUSE=1"
set "DOTNET_CLI_TELEMETRY_OPTOUT=1"
set "DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1"
call "%EnginePath%\Engine\Build\BatchFiles\GetDotnetPath.bat" >nul 2>&1
dotnet build-server shutdown >nul 2>&1

echo [INFO] RunMode="%RunMode%"
echo [INFO] EnginePath="%EnginePath%"
echo [INFO] Platform="%AptPlatform%"
echo [INFO] TargetName="%AptTargetName%"
if /I "%AptPlatform%"=="PS5" echo [INFO] PS5Target="%PS5Target%"
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-Date -Format o"') do set "AptRunStartIso=%%I"
echo [INFO] Run start="%AptRunStartIso%"

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
echo [INFO] APT Do args:%AptDoArgs%
set "DeviceArg="
if /I "%AptPlatform%"=="PS5" if not "%PS5Target%"=="" set "DeviceArg=-devices=PS5:%PS5Target%"
if defined DeviceArg echo [INFO] DeviceArg="%DeviceArg%"

if /I "%RunMode%"=="PS5" goto RunPS5
if /I "%RunMode%"=="PC" goto RunPC

:RunPS5
set "RunUATBat=%EnginePath%\Engine\Build\BatchFiles\RunUAT.bat"
if not exist "%RunUATBat%" (
  echo [ERROR] RunUAT.bat not found: "%RunUATBat%"
  endlocal & exit /b 1
)
echo [INFO] Running PS5 packaged APT with strict -skipdeploy (no retry).
call "%RunUATBat%" RunUnreal ^
  -project="%ProjectPath%\ProjectPBZ.uproject" ^
  -build="%AptBuildDir%" ^
  -skipdeploy ^
  -configuration="%AptConfiguration%" ^
  -platform=%AptPlatform% ^
  -target="%AptTargetName%" ^
  !DeviceArg! ^
  -maxduration=%MaxDuration% ^
  -unattended ^
  -verbose ^
  -ResumeOnCriticalFailure ^
  -Test="AutomatedPerfTest.ReplayTest" ^
  -AutomatedPerfTest.ReplayPerfTest.ReplayName="%REPLAY_PATH%" ^
  -AutomatedPerfTest.UseShippingInsights="false" ^
  -AutomatedPerfTest.TestID="%AptTestID%" ^
  -AutomatedPerfTest.IgnoreTestBuildLogging ^
  !AptDoArgs! ^
  -LocalReports ^
  -iterations=%Iterations% ^
  -Args="" ^
  -ExecCmds="%ExecCmds%" ^
  -log ^
  -map="/Game/Maps/B02/PBZ_Xigu_WP"
set "RUN_EXIT=%ERRORLEVEL%"
echo [INFO] PS5 RunUAT exit code: %RUN_EXIT%
if not "%RUN_EXIT%"=="0" (
  echo [ERROR] PS5 packaged APT failed. Exit directly.
  endlocal & exit /b %RUN_EXIT%
)
goto CopyProfiling

:RunPC
set "RunUATBat=%EnginePath%\Engine\Build\BatchFiles\RunUAT.bat"
if not exist "%RunUATBat%" (
  echo [ERROR] RunUAT.bat not found: "%RunUATBat%"
  endlocal & exit /b 1
)
echo [INFO] Running PC packaged APT.
call "%RunUATBat%" RunUnreal ^
  -project="%ProjectPath%\ProjectPBZ.uproject" ^
  -build="%AptBuildDir%" ^
  -skipdeploy ^
  -configuration="%AptConfiguration%" ^
  -platform=%AptPlatform% ^
  -target="%AptTargetName%" ^
  -maxduration=%MaxDuration% ^
  -unattended ^
  -verbose ^
  -ResumeOnCriticalFailure ^
  -Test="AutomatedPerfTest.ReplayTest" ^
  -AutomatedPerfTest.ReplayPerfTest.ReplayName="%REPLAY_PATH%" ^
  -AutomatedPerfTest.UseShippingInsights="false" ^
  -AutomatedPerfTest.TestID="%AptTestID%" ^
  -AutomatedPerfTest.IgnoreTestBuildLogging ^
  !AptDoArgs! ^
  -LocalReports ^
  -iterations=%Iterations% ^
  -Args="" ^
  -ExecCmds="%ExecCmds%" ^
  -log ^
  -map="/Game/Maps/B02/PBZ_Xigu_WP"
set "RUN_EXIT=%ERRORLEVEL%"
echo [INFO] PC RunUAT exit code: %RUN_EXIT%
if not "%RUN_EXIT%"=="0" (
  echo [ERROR] PC packaged APT failed. Exit directly.
  endlocal & exit /b %RUN_EXIT%
)
goto CopyProfiling

:CopyProfiling
if not exist "%AptSourceProfiling%" (
  echo [WARN] Source profiling not found: "%AptSourceProfiling%"
  endlocal & exit /b %RUN_EXIT%
)

for %%I in ("%AptBuildDir%") do set "ArchiveBuildName=%%~nxI"
for %%I in ("%REPLAY_PATH%") do set "ArchiveReplayName=%%~nI"
for /f %%I in ('powershell -NoProfile -Command Get-Date -Format yyyyMMdd-HHmm') do set "ArchiveDate=%%I"
if not defined ArchiveBuildName (
  echo [WARN] Failed to derive build name from AptBuildDir. Skip copy.
  endlocal & exit /b %RUN_EXIT%
)
if not defined ArchiveReplayName (
  echo [WARN] Failed to derive replay name from REPLAY_PATH. Skip copy.
  endlocal & exit /b %RUN_EXIT%
)
if not defined ArchiveDate (
  echo [WARN] Failed to generate archive date. Skip copy.
  endlocal & exit /b %RUN_EXIT%
)

set "ArchiveName=%ArchiveBuildName%_%ArchiveDate%_%ArchiveReplayName%"
set "ArchiveTarget=%ArchiveRoot%\%ArchiveName%\profiling"
echo [INFO] Copy profiling -> "%ArchiveTarget%"
mkdir "%ArchiveTarget%" 2>nul
robocopy "%AptSourceProfiling%" "%ArchiveTarget%" /E /R:2 /W:2
set "ROBO_EXIT=%ERRORLEVEL%"
if %ROBO_EXIT% GEQ 8 (
  echo [ERROR] Robocopy failed with exit code: %ROBO_EXIT%
  endlocal & exit /b %ROBO_EXIT%
)
echo [INFO] Profiling archived. Robocopy exit code: %ROBO_EXIT%

endlocal & exit /b %RUN_EXIT%
