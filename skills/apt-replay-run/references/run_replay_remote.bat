@echo off
setlocal EnableExtensions EnableDelayedExpansion

if /I "%~1"=="--target" (
  set "ConfigFile=%~2"
  if not defined ConfigFile set "ConfigFile=%~dp0apt.remote-pc.config.cmd"
  goto TargetMain
)

rem Controller mode. Copies this bat plus config to RemotePC, then starts the
rem same bat in --target mode through an interactive scheduled task.

set "SCRIPT_DIR=%~dp0"
set "ConfigFile=%SCRIPT_DIR%apt.remote-pc.config.cmd"
if not "%~1"=="" set "ConfigFile=%~1"

if exist "%ConfigFile%" (
  echo [INFO] Loading config from "%ConfigFile%"
  call "%ConfigFile%"
) else (
  echo [ERROR] Config file not found: "%ConfigFile%"
  endlocal & exit /b 2
)

if not defined RemotePC (
  echo [ERROR] RemotePC is empty. Set RemotePC in config.
  endlocal & exit /b 2
)
if not defined RemoteDeployScripts set "RemoteDeployScripts=true"
if not defined RemoteDeployDir set "RemoteDeployDir=D:\APT"
if not defined RemoteBat set "RemoteBat=%RemoteDeployDir%\run_replay_remote.bat"
if not defined RemoteConfig set "RemoteConfig=%RemoteDeployDir%\apt.remote-pc.config.cmd"
if not defined RemoteTaskName set "RemoteTaskName=APT_Remote_Run"
if not defined RemoteTaskLog set "RemoteTaskLog=%RemoteDeployDir%\remote_task.log"
if not defined RemoteTaskPollSeconds set "RemoteTaskPollSeconds=5"
if not defined RemoteCredentialFile set "RemoteCredentialFile=%USERPROFILE%\.apt\remote_%RemotePC%.credential.xml"
if not defined RemoteSaveCredential set "RemoteSaveCredential=true"

set "LocalRemoteBat=%~f0"

echo [INFO] RemotePC="%RemotePC%"
echo [INFO] RemoteBat="%RemoteBat%"
echo [INFO] RemoteConfig="%RemoteConfig%"
echo [INFO] RemoteDeployScripts="%RemoteDeployScripts%"
if /I "%RemoteDeployScripts%"=="true" echo [INFO] RemoteDeployDir="%RemoteDeployDir%"
echo [INFO] RemoteTaskName="%RemoteTaskName%"
echo [INFO] RemoteTaskLog="%RemoteTaskLog%"
if defined RemoteUser echo [INFO] RemoteUser="%RemoteUser%"
if defined RemoteCredentialFile echo [INFO] RemoteCredentialFile="%RemoteCredentialFile%"
echo [INFO] RemoteSaveCredential="%RemoteSaveCredential%"
echo.

powershell -NoProfile -ExecutionPolicy Bypass ^
  -Command "$ErrorActionPreference='Stop';" ^
  "$remotePc=$env:RemotePC; $remoteBat=$env:RemoteBat; $remoteConfig=$env:RemoteConfig; $remoteUser=$env:RemoteUser; $credentialFile=$env:RemoteCredentialFile; $saveCredential=$env:RemoteSaveCredential; $deploy=$env:RemoteDeployScripts; $deployDir=$env:RemoteDeployDir; $localRemoteBat=$env:LocalRemoteBat; $localConfig=$env:ConfigFile; $taskName=$env:RemoteTaskName; $taskLog=$env:RemoteTaskLog; $poll=[int]$env:RemoteTaskPollSeconds;" ^
  "$script={ param($bat,$cfg,$taskName,$taskLog,$poll) if(-not (Test-Path -LiteralPath $bat)){ throw ('Remote bat not found: ' + $bat) }; if(-not (Test-Path -LiteralPath $cfg)){ throw ('Remote config not found: ' + $cfg) }; $taskDir=Split-Path -Parent $taskLog; if($taskDir){ New-Item -ItemType Directory -Force -Path $taskDir | Out-Null }; $cmd='/d /c ""' + $bat + '"" --target ""' + $cfg + '"" 1>""' + $taskLog + '"" 2>&1'; $action=New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $cmd; $principal=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest; $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 12) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null; Start-ScheduledTask -TaskName $taskName; do { Start-Sleep -Seconds $poll; $task=Get-ScheduledTask -TaskName $taskName } while($task.State -ne 'Ready' -and $task.State -ne 'Disabled'); $info=Get-ScheduledTaskInfo -TaskName $taskName; if(Test-Path -LiteralPath $taskLog){ Get-Content -LiteralPath $taskLog -Tail 80 | ForEach-Object { '[REMOTE] ' + $_ } }; Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; return $info.LastTaskResult };" ^
  "$cred=$null; if(-not [string]::IsNullOrWhiteSpace($credentialFile) -and (Test-Path -LiteralPath $credentialFile)){ $cred=Import-Clixml -LiteralPath $credentialFile } elseif(-not [string]::IsNullOrWhiteSpace($remoteUser)){ $cred=Get-Credential -UserName $remoteUser -Message ('Credential for ' + $remotePc); if(-not [string]::IsNullOrWhiteSpace($credentialFile) -and ($saveCredential -ieq 'true' -or $saveCredential -eq '1')){ $credDir=Split-Path -Parent $credentialFile; if($credDir){ New-Item -ItemType Directory -Force -Path $credDir | Out-Null }; $cred | Export-Clixml -LiteralPath $credentialFile } }; if($cred){ $session=New-PSSession -ComputerName $remotePc -Credential $cred } else { $session=New-PSSession -ComputerName $remotePc };" ^
  "try { if($deploy -ieq 'true' -or $deploy -eq '1'){ if(-not (Test-Path -LiteralPath $localRemoteBat)){ throw ('Local run_replay_remote.bat not found: ' + $localRemoteBat) }; if(-not (Test-Path -LiteralPath $localConfig)){ throw ('Local config not found: ' + $localConfig) }; Invoke-Command -Session $session -ScriptBlock { param($dir) New-Item -ItemType Directory -Force -Path $dir | Out-Null } -ArgumentList $deployDir; $remoteBat=Join-Path $deployDir 'run_replay_remote.bat'; $remoteConfig=Join-Path $deployDir 'apt.remote-pc.config.cmd'; Copy-Item -ToSession $session -LiteralPath $localRemoteBat -Destination $remoteBat -Force; Copy-Item -ToSession $session -LiteralPath $localConfig -Destination $remoteConfig -Force }; $rc=Invoke-Command -Session $session -ScriptBlock $script -ArgumentList $remoteBat,$remoteConfig,$taskName,$taskLog,$poll; if($rc -is [array]){ $rc=$rc[-1] }; exit ([int]$rc) } finally { if($session){ Remove-PSSession $session } }"

set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [ERROR] Remote APT trigger failed. Exit code: %RC%
  endlocal & exit /b %RC%
)

echo [INFO] Remote APT finished successfully.
endlocal & exit /b 0

:TargetMain
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
if not defined PCExe (
  echo [ERROR] PCExe is empty. Set PCExe in config.
  endlocal & exit /b 2
)
if not exist "%PCExe%" (
  echo [ERROR] PC exe not found: "%PCExe%"
  endlocal & exit /b 2
)
if not defined REPLAY_LIST (
  echo [ERROR] REPLAY_LIST is empty. Set replay path/list in config.
  endlocal & exit /b 2
)

call :RequireConfig ArchiveRoot
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig WorkRoot
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig MapPath
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig WindowMode
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig PCBuildName
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig PCSourceProfiling
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig DoInsightsTrace
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig DoCSVProfiler
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig DoFPSChart
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig DoLLM
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig DoGPUPerf
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig DoGPUReshape
if errorlevel 1 endlocal & exit /b 2
call :RequireConfig DoVideoCapture
if errorlevel 1 endlocal & exit /b 2

set "BuildName=%PCBuildName%"
for %%I in ("%PCExe%") do set "PCExeDir=%%~dpI"

set "AptDoArgs="
if /I "%DoInsightsTrace%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoInsightsTrace"
if "%DoInsightsTrace%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoInsightsTrace"
if /I "%DoCSVProfiler%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoCSVProfiler -csvGpuStats"
if "%DoCSVProfiler%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoCSVProfiler -csvGpuStats"
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
if not "%~3"=="" set "ReplayListArg=%~3"

set "ReplayInputFile="
for %%I in ("%ReplayListArg%") do set "ReplayInputExt=%%~xI"
if exist "%ReplayListArg%" if /I "%ReplayInputExt%"==".txt" set "ReplayInputFile=%ReplayListArg%"
if exist "%ReplayListArg%" if /I "%ReplayInputExt%"==".list" set "ReplayInputFile=%ReplayListArg%"

set /a Total=0
set /a Failed=0
set "SummaryFile=%WorkRoot%\remote_summary.txt"
mkdir "%WorkRoot%" >nul 2>&1
del /q "%SummaryFile%" >nul 2>&1

echo [INFO] PCExe="%PCExe%"
echo [INFO] BuildName="%BuildName%"
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
      call :RunOneRemoteReplay "!ReplayLine!" !Total!
      if errorlevel 1 set /a Failed+=1
    )
  )
) else (
  set "RemainingReplayList=%ReplayListArg%"
  call :RunInlineRemoteReplayList
)

echo.
echo [INFO] Remote replay finished. Total=!Total! Failed=!Failed!
echo [INFO] Summary="%SummaryFile%"

if "!Total!"=="0" (
  echo [ERROR] No replay entries found.
  endlocal & exit /b 2
)
if not "!Failed!"=="0" (
  endlocal & exit /b 1
)
endlocal & exit /b 0

:RunOneRemoteReplay
set "ReplayPath=%~1"
set "ReplayIndex=%~2"
for %%I in ("%ReplayPath%") do set "ReplayName=%%~nI"
if not defined ReplayName set "ReplayName=Replay%ReplayIndex%"

for /f %%I in ('powershell -NoProfile -Command Get-Date -Format yyyyMMdd-HHmmss') do set "ArchiveDate=%%I"
set "UserDir=%WorkRoot%\UserDir"
set "ProfilingDir=%PCSourceProfiling%"
set "LogDir=%UserDir%\Saved\Logs"
set "ArchiveTarget=%ArchiveRoot%\%BuildName%_%ArchiveDate%_%ReplayName%"

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

:RunInlineRemoteReplayList
if not defined RemainingReplayList exit /b 0
set "ReplayLine="
for /f "tokens=1* delims=;" %%A in ("!RemainingReplayList!") do (
  set "ReplayLine=%%~A"
  set "RemainingReplayList=%%~B"
)
if not "!ReplayLine!"=="" if not "!ReplayLine:~0,1!"=="#" (
  set /a Total+=1
  call :RunOneRemoteReplay "!ReplayLine!" !Total!
  if errorlevel 1 set /a Failed+=1
)
if defined RemainingReplayList goto RunInlineRemoteReplayList
exit /b 0

:RequireConfig
set "RequiredName=%~1"
if not defined %RequiredName% (
  echo [ERROR] %RequiredName% is empty. Set %RequiredName% in config.
  exit /b 1
)
exit /b 0
