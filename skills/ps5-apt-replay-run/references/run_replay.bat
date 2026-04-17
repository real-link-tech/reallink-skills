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
if not defined RunMode set "RunMode=Packaged"
if not defined REPLAY_PATH set "REPLAY_PATH=\\192.168.0.7\store\APT\ReplayFiles\sample.replay"
if not defined MapName set "MapName=PBZ_WP_ZhuLinGuWu"
if not defined PS5Target set "PS5Target=192.168.103.108"
if not defined PS5DeviceIp set "PS5DeviceIp=PS5:%PS5Target%"
if not defined Configuration set "Configuration=Test"
if not defined MaxDuration set "MaxDuration=3600"
if not defined BuildDir set "BuildDir=\\192.168.103.61\builds_ps\PS5\Test\BuildName\CL-123456_JKS-0000"
if not defined Iterations set "Iterations=1"
if not defined ExecCmds set "ExecCmds=Reallink.ProfileMatrix.SuspendCVarsRefresh 1;r.DynamicRes.OperationMode 0;"
if not defined TestID set "TestID=APT"
if not defined DoInsightsTrace set "DoInsightsTrace=true"
if not defined DoCSVProfiler set "DoCSVProfiler=false"
if not defined DoFPSChart set "DoFPSChart=false"
if not defined DoLLM set "DoLLM=false"
if not defined DoGPUPerf set "DoGPUPerf=false"
if not defined DoGPUReshape set "DoGPUReshape=false"
if not defined DoVideoCapture set "DoVideoCapture=false"
if not defined SourceProfiling set "SourceProfiling=%ProjectPath%\Saved\Profiling"
if not defined ArchiveRoot set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
if not defined EditorExe set "EditorExe=%EnginePath%\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
if not defined EditorTestName set "EditorTestName=AutomatedPerfTest.ReplayTest"

set "EnginePath=%EnginePath:"=%"
set "RunMode=%RunMode:"=%"
if "%EnginePath%"=="" set "EnginePath=D:\UnrealEngine"

echo [INFO] RunMode="%RunMode%"
echo [INFO] EnginePath="%EnginePath%"

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

if /I "%RunMode%"=="Packaged" goto RunPackaged
if /I "%RunMode%"=="Editor" goto RunEditor
echo [ERROR] Invalid RunMode: "%RunMode%". Use Packaged or Editor.
endlocal & exit /b 2

:RunPackaged
set "RunUATBat=%EnginePath%\Engine\Build\BatchFiles\RunUAT.bat"
if not exist "%RunUATBat%" (
  echo [ERROR] RunUAT.bat not found: "%RunUATBat%"
  endlocal & exit /b 1
)
echo [INFO] Running Packaged APT with strict -skipdeploy (no retry).
call "%RunUATBat%" RunUnreal ^
  -project="%ProjectPath%\ProjectPBZ.uproject" ^
  -build="%BuildDir%" ^
  -skipdeploy ^
  -configuration="%Configuration%" ^
  -platform=PS5 ^
  -target="ProjectPBZ" ^
  -devices=%PS5DeviceIp% ^
  -maxduration=%MaxDuration% ^
  -unattended ^
  -verbose ^
  -ResumeOnCriticalFailure ^
  -Test="AutomatedPerfTest.ReplayTest" ^
  -AutomatedPerfTest.ReplayPerfTest.ReplayName="%REPLAY_PATH%" ^
  -AutomatedPerfTest.ReplayPerfTest.MapName="%MapName%" ^
  -AutomatedPerfTest.UseShippingInsights="false" ^
  -AutomatedPerfTest.TestID="%TestID%" ^
  -AutomatedPerfTest.IgnoreTestBuildLogging ^
  !AptDoArgs! ^
  -LocalReports ^
  -iterations=%Iterations% ^
  -map=%MapName% ^
  -Args="" ^
  -ExecCmds="%ExecCmds%" ^
  -log
set "RUN_EXIT=%ERRORLEVEL%"
echo [INFO] Packaged RunUAT exit code: %RUN_EXIT%
if not "%RUN_EXIT%"=="0" (
  echo [ERROR] Packaged APT failed. Exit directly.
  endlocal & exit /b %RUN_EXIT%
)
goto CopyProfiling

:RunEditor
if not exist "%EditorExe%" (
  echo [ERROR] UnrealEditor-Cmd.exe not found: "%EditorExe%"
  endlocal & exit /b 1
)
echo [INFO] Running Editor APT (no deploy/install path).
call "%EditorExe%" "%ProjectPath%\ProjectPBZ.uproject" ^
  -unattended ^
  -nop4 ^
  -nosplash ^
  -nullrhi ^
  -stdout ^
  -FullStdOutLogOutput ^
  -AutomatedPerfTest.ReplayPerfTest.ReplayName="%REPLAY_PATH%" ^
  -AutomatedPerfTest.ReplayPerfTest.MapName="%MapName%" ^
  -AutomatedPerfTest.UseShippingInsights="false" ^
  -AutomatedPerfTest.TestID="%TestID%" ^
  -AutomatedPerfTest.IgnoreTestBuildLogging ^
  !AptDoArgs! ^
  -iterations=%Iterations% ^
  -ExecCmds="Automation RunTests %EditorTestName%;Quit" ^
  -log
set "RUN_EXIT=%ERRORLEVEL%"
echo [INFO] Editor run exit code: %RUN_EXIT%
if not "%RUN_EXIT%"=="0" (
  echo [ERROR] Editor APT failed. Exit directly.
  endlocal & exit /b %RUN_EXIT%
)
goto CopyProfiling

:CopyProfiling
if not exist "%SourceProfiling%" (
  echo [WARN] SourceProfiling not found: "%SourceProfiling%"
  endlocal & exit /b %RUN_EXIT%
)

for /f %%I in ('powershell -NoProfile -Command Get-Date -Format yyyy-M-d-HHmm') do set "ArchiveStamp=%%I"
if not defined ArchiveStamp (
  echo [WARN] Failed to generate archive timestamp. Skip copy.
  endlocal & exit /b %RUN_EXIT%
)

set "ArchiveTarget=%ArchiveRoot%\%ArchiveStamp%\profiling"
echo [INFO] Copy profiling -> "%ArchiveTarget%"
mkdir "%ArchiveTarget%" 2>nul
robocopy "%SourceProfiling%" "%ArchiveTarget%" /E /R:2 /W:2
set "ROBO_EXIT=%ERRORLEVEL%"
if %ROBO_EXIT% GEQ 8 (
  echo [ERROR] Robocopy failed with exit code: %ROBO_EXIT%
  endlocal & exit /b %ROBO_EXIT%
)
echo [INFO] Profiling archived. Robocopy exit code: %ROBO_EXIT%

endlocal & exit /b %RUN_EXIT%
