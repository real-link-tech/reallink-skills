@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "ConfigFile=%SCRIPT_DIR%apt.pc.config.cmd"
if not "%~1"=="" set "ConfigFile=%~1"
set "RuntimeExtraArgs=%~3"

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
if defined APT_QUALITY_CVARS set "QualityCVars=!APT_QUALITY_CVARS!"
if not defined QualityCVars set "QualityCVars="
if not defined ExtraArgs set "ExtraArgs="
if defined RuntimeExtraArgs if defined ExtraArgs set "ExtraArgs=!ExtraArgs! !RuntimeExtraArgs!"
if defined RuntimeExtraArgs if not defined ExtraArgs set "ExtraArgs=!RuntimeExtraArgs!"
if not defined ArchiveRoot set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
if not defined PCSourceProfiling set "PCSourceProfiling=%WorkRoot%\UserDir\Saved\Profiling"
if not defined DoInsightsTrace set "DoInsightsTrace=false"
if not defined DoCSVProfiler set "DoCSVProfiler=false"
if not defined DoFPSChart set "DoFPSChart=false"
if not defined DoLLM set "DoLLM=false"
if not defined DoGPUPerf set "DoGPUPerf=false"
if not defined DoGPUReshape set "DoGPUReshape=false"
if not defined DoVideoCapture set "DoVideoCapture=false"
if not defined WaitForReplayReady set "WaitForReplayReady=false"
if not defined ReplayReadyValue set "ReplayReadyValue=0"
if not defined ReplayReadySettleSeconds set "ReplayReadySettleSeconds=1.0"
if not defined ReplayReadyTimeoutSeconds set "ReplayReadyTimeoutSeconds=60.0"
if not defined ReplayReadyForceExitOnTimeout set "ReplayReadyForceExitOnTimeout=true"
if not defined ReplayReadyWatchdog set "ReplayReadyWatchdog=true"
if not defined ReplayReadyWatchdogGraceSeconds set "ReplayReadyWatchdogGraceSeconds=10.0"
if not defined ReplayReadyWatchdogPollMilliseconds set "ReplayReadyWatchdogPollMilliseconds=500"
if not defined ReplayReadyWatchdogProcessStartTimeoutSeconds set "ReplayReadyWatchdogProcessStartTimeoutSeconds=30.0"
if not defined ReplayReadyPrimeFrames set "ReplayReadyPrimeFrames=1"
if not defined PSOWarmupMode set "PSOWarmupMode=Auto"
if not defined PSOWarmupCacheRoot set "PSOWarmupCacheRoot=%WorkRoot%\PSOWarmup"
if not defined PSOWarmupRequireCompletion set "PSOWarmupRequireCompletion=true"
if not defined PSOWarmupBatchSize set "PSOWarmupBatchSize=100"
if not defined PSOWarmupBatchTime set "PSOWarmupBatchTime=200"
if not defined PSOWarmupExecCmds set "PSOWarmupExecCmds=Reallink.ProfileMatrix.AddCustomizedCVar r.ShaderPipelineCache.BatchMode 1,Reallink.ProfileMatrix.AddCustomizedCVar r.ShaderPipelineCache.BatchSize %PSOWarmupBatchSize%,Reallink.ProfileMatrix.AddCustomizedCVar r.ShaderPipelineCache.BatchTime %PSOWarmupBatchTime%,r.ShaderPipelineCache.SetBatchMode Fast"
if not defined PSOCaptureExecCmds set "PSOCaptureExecCmds=Reallink.ProfileMatrix.AddCustomizedCVar r.PSOPrecaching 0,r.ShaderPipelineCache.SetBatchMode Pause"
if not defined GPUPerfExecCmds set "GPUPerfExecCmds=r.StencilLODMode 1,r.VolumetricRenderTarget.PreferAsyncCompute 0,r.LumenScene.Lighting.AsyncCompute 0,r.Lumen.DiffuseIndirect.AsyncCompute 0,r.Bloom.AsyncCompute 0,r.nanite.asyncrasterization.shadowdepths 1,r.TSR.AsyncCompute 0,r.RayTracing.AsyncBuild 0,r.DFShadowAsyncCompute 0,r.AmbientOcclusion.Compute 1,r.LocalFogVolume.TileCullingUseAsync 0,r.SkyAtmosphereASyncCompute 0,r.Substrate.AsyncClassification 0"

set "PSOWarmupModeNormalized="
if /I "%PSOWarmupMode%"=="Auto" set "PSOWarmupModeNormalized=Auto"
if /I "%PSOWarmupMode%"=="Always" set "PSOWarmupModeNormalized=Always"
if /I "%PSOWarmupMode%"=="Never" set "PSOWarmupModeNormalized=Never"
if not defined PSOWarmupModeNormalized (
  echo [ERROR] Invalid PSOWarmupMode "%PSOWarmupMode%". Expected Auto, Always, or Never.
  endlocal & exit /b 2
)

for %%I in ("%SCRIPT_DIR%..\scripts\apt_pso_tools.ps1") do set "PSOTools=%%~fI"
if not exist "%PSOTools%" (
  echo [ERROR] PSO helper script not found: "%PSOTools%"
  endlocal & exit /b 2
)
for %%I in ("%SCRIPT_DIR%..\scripts\apt_replay_watchdog.ps1") do set "ReplayWatchdogScript=%%~fI"

call :BuildQualityExecCmds
if errorlevel 1 exit /b !ERRORLEVEL!

set "GPUPerfEnabled=false"
if /I "%DoGPUPerf%"=="true" set "GPUPerfEnabled=true"
if "%DoGPUPerf%"=="1" set "GPUPerfEnabled=true"

set "GPUReshapeEnabled=false"
if /I "%DoGPUReshape%"=="true" set "GPUReshapeEnabled=true"
if "%DoGPUReshape%"=="1" set "GPUReshapeEnabled=true"

if /I "!GPUReshapeEnabled!"=="true" (
  if not defined GPUReshapeExe if defined EnginePath set "GPUReshapeExe=!EnginePath!\Engine\Binaries\ThirdParty\GPUReshape\Win64\Raytracing\GPUReshape.exe"
  if not defined GPUReshapeWorkspace set "GPUReshapeWorkspace=BasicWorkspace"
  if not defined GPUReshapeWorkspacePath if defined EnginePath set "GPUReshapeWorkspacePath=!EnginePath!\Engine\Source\Programs\GPUReshape\Resources\Workspaces\!GPUReshapeWorkspace!.json"
  if not defined GPUReshapeSymbolPath if defined ProjectPath set "GPUReshapeSymbolPath=!ProjectPath!\Saved\ShaderSymbols"
  if not defined GPUReshapeTimeout set "GPUReshapeTimeout=7200"
  if not defined GPUReshapeTargetArgs set "GPUReshapeTargetArgs=-nothreadtimeout -noheartbeatthread"

  if not exist "!GPUReshapeExe!" (
    echo [ERROR] GPUReshape executable not found: "!GPUReshapeExe!"
    endlocal & exit /b 2
  )
  if not exist "!GPUReshapeWorkspacePath!" (
    echo [ERROR] GPUReshape workspace not found: "!GPUReshapeWorkspacePath!"
    endlocal & exit /b 2
  )
  if not exist "!GPUReshapeSymbolPath!" echo [WARN] GPUReshape shader symbol path not found. Running without symbols: "!GPUReshapeSymbolPath!"
)

for %%I in ("%PCExe%") do set "PCExeDir=%%~dpI"

set "AptDoArgs="
if /I "%DoInsightsTrace%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoInsightsTrace"
if "%DoInsightsTrace%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoInsightsTrace"
if /I "%DoCSVProfiler%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoCSVProfiler -csvGpuStats"
if "%DoCSVProfiler%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoCSVProfiler -csvGpuStats"
if /I "%DoFPSChart%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoFPSChart"
if "%DoFPSChart%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoFPSChart"
if /I "%DoLLM%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoLLM -llm -llmcsv"
if "%DoLLM%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoLLM -llm -llmcsv"
if /I "!GPUPerfEnabled!"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoGPUPerf -AutomatedPerfTest.LockDynamicRes"
if /I "!GPUReshapeEnabled!"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoGPUReshape !GPUReshapeTargetArgs!"
if /I "%DoVideoCapture%"=="true" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoVideoCapture"
if "%DoVideoCapture%"=="1" set "AptDoArgs=!AptDoArgs! -AutomatedPerfTest.DoVideoCapture"

set "ReplayReadyArgs="
if /I "%WaitForReplayReady%"=="true" set "ReplayReadyArgs=-AutomatedPerfTest.ReplayPerfTest.WaitForReady"
if "%WaitForReplayReady%"=="1" set "ReplayReadyArgs=-AutomatedPerfTest.ReplayPerfTest.WaitForReady"
if defined ReplayReadyArgs (
  if defined ReplayReadyCVar set "ReplayReadyArgs=!ReplayReadyArgs! -AutomatedPerfTest.ReplayPerfTest.ReadyCVar=!ReplayReadyCVar!"
  set "ReplayReadyArgs=!ReplayReadyArgs! -AutomatedPerfTest.ReplayPerfTest.ReadyValue=!ReplayReadyValue!"
  set "ReplayReadyArgs=!ReplayReadyArgs! -AutomatedPerfTest.ReplayPerfTest.SettleSeconds=!ReplayReadySettleSeconds!"
  set "ReplayReadyArgs=!ReplayReadyArgs! -AutomatedPerfTest.ReplayPerfTest.ReadyTimeoutSeconds=!ReplayReadyTimeoutSeconds!"
  if /I "!ReplayReadyForceExitOnTimeout!"=="true" set "ReplayReadyArgs=!ReplayReadyArgs! -AutomatedPerfTest.ReplayPerfTest.ForceExitOnReadyTimeout"
  if "!ReplayReadyForceExitOnTimeout!"=="1" set "ReplayReadyArgs=!ReplayReadyArgs! -AutomatedPerfTest.ReplayPerfTest.ForceExitOnReadyTimeout"
  set "ReplayReadyArgs=!ReplayReadyArgs! -AutomatedPerfTest.ReplayPerfTest.PrimeFrames=!ReplayReadyPrimeFrames!"
)

set "ReplayReadyWatchdogEnabled=false"
if defined ReplayReadyArgs if /I "!ReplayReadyWatchdog!"=="true" set "ReplayReadyWatchdogEnabled=true"
if defined ReplayReadyArgs if "!ReplayReadyWatchdog!"=="1" set "ReplayReadyWatchdogEnabled=true"
if /I "!ReplayReadyWatchdogEnabled!"=="true" if not exist "!ReplayWatchdogScript!" (
  echo [ERROR] Replay ready watchdog script not found: "!ReplayWatchdogScript!"
  endlocal & exit /b 2
)

if /I "!GPUPerfEnabled!"=="true" (
  if defined ExecCmds (
    set "ExecCmds=!ExecCmds!,!GPUPerfExecCmds!"
  ) else (
    set "ExecCmds=!GPUPerfExecCmds!"
  )
)

set "ReplayListArg=%REPLAY_LIST%"
if not "%~2"=="" set "ReplayListArg=%~2"

set "ReplayInputFile="
set "ReplayInputDirectory="
if exist "%ReplayListArg%\*" set "ReplayInputDirectory=%ReplayListArg%"
for %%I in ("%ReplayListArg%") do set "ReplayInputExt=%%~xI"
if not defined ReplayInputDirectory if exist "%ReplayListArg%" if /I "%ReplayInputExt%"==".txt" set "ReplayInputFile=%ReplayListArg%"
if not defined ReplayInputDirectory if exist "%ReplayListArg%" if /I "%ReplayInputExt%"==".list" set "ReplayInputFile=%ReplayListArg%"

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
echo [INFO] Replay ready args:%ReplayReadyArgs%
echo [INFO] Replay ready watchdog=!ReplayReadyWatchdogEnabled! grace=!ReplayReadyWatchdogGraceSeconds!s
echo [INFO] PSO warmup mode=%PSOWarmupModeNormalized% cache="%PSOWarmupCacheRoot%"
echo [INFO] ExtraArgs="%ExtraArgs%"
if defined QualityCVars (echo [INFO] Quality overrides="!QualityCVars!") else echo [INFO] Quality overrides=default
echo [INFO] Replay input="%ReplayListArg%"
echo [INFO] WorkRoot="%WorkRoot%"
echo [INFO] ArchiveRoot="%ArchiveRoot%"
if /I "!GPUPerfEnabled!"=="true" echo [INFO] GPUPerf mode enabled: dynamic resolution locked and GPU async work reduced.
if /I "!GPUReshapeEnabled!"=="true" echo [INFO] GPUReshape mode enabled: executable="!GPUReshapeExe!" workspace="!GPUReshapeWorkspacePath!"
if /I "!GPUPerfEnabled!"=="true" if /I "!GPUReshapeEnabled!"=="true" echo [WARN] GPUReshape instrumentation affects GPU timings. Treat GPUPerf numbers from this combined run as diagnostic only.
echo.

if defined ReplayInputDirectory (
  echo [INFO] Replay input directory="%ReplayInputDirectory%"
  for /f "delims=" %%R in ('dir /b /s /a-d "!ReplayInputDirectory!\*.replay" 2^>nul ^| sort') do (
    set /a Total+=1
    call :RunOneReplay "%%R" !Total!
    if errorlevel 1 set /a Failed+=1
  )
) else if defined ReplayInputFile (
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

:BuildQualityExecCmds
set "QualityExecCmds="
if not defined QualityCVars exit /b 0

set "QualityCommandFile=!TEMP!\apt_quality_!RANDOM!_!RANDOM!.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PSOTools%" -Action BuildQualityExecCmds -QualityCVars "!QualityCVars!" > "!QualityCommandFile!"
set "QUALITY_PARSE_EXIT=!ERRORLEVEL!"
if not "!QUALITY_PARSE_EXIT!"=="0" (
  type "!QualityCommandFile!"
  del /q "!QualityCommandFile!" >nul 2>&1
  exit /b !QUALITY_PARSE_EXIT!
)

set /p "QualityExecCmds="<"!QualityCommandFile!"
del /q "!QualityCommandFile!" >nul 2>&1
if not defined QualityExecCmds (
  echo [ERROR] QualityCVars did not produce any startup commands.
  exit /b 20
)
exit /b 0

:RunOneReplay
set "ReplayPath=%~1"
set "ReplayIndex=%~2"
for %%I in ("%ReplayPath%") do set "ReplayName=%%~nI"
if not defined ReplayName set "ReplayName=Replay%ReplayIndex%"

if not exist "!ReplayPath!" (
  echo [ERROR] [!ReplayIndex!] Replay file not found: "!ReplayPath!"
  echo FAIL [!ReplayIndex!] replay_not_found "!ReplayPath!" >> "!SummaryFile!"
  exit /b 2
)

for /f %%I in ('powershell -NoProfile -Command Get-Date -Format yyyyMMdd-HHmmss') do set "ArchiveDate=%%I"
set "UserDir=%WorkRoot%\UserDir"
set "ProfilingDir=%PCSourceProfiling%"
set "LogDir=%UserDir%\Saved\Logs"
set "ArchiveTarget=%ArchiveRoot%\%PCBuildName%_%ArchiveDate%_%ReplayName%"
set "PSOWarmupKey="

for /f "usebackq delims=" %%K in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%PSOTools%" -Action Key -ExePath "%PCExe%" -ReplayPath "!ReplayPath!" -BuildName "%PCBuildName%" -MapPath "%MapPath%" -QualityCVars "!QualityCVars!"`) do set "PSOWarmupKey=%%K"
if not defined PSOWarmupKey (
  echo [ERROR] [!ReplayIndex!] Could not generate the PSO warmup key.
  echo FAIL [!ReplayIndex!] pso_key_failed "!ReplayPath!" >> "!SummaryFile!"
  exit /b 2
)

set "PSOWarmupStampDir=%PSOWarmupCacheRoot%\stamps"
set "PSOWarmupLogDir=%PSOWarmupCacheRoot%\logs"
set "PSOWarmupTempDir=%PSOWarmupCacheRoot%\temp"
set "PSOWarmupStamp=!PSOWarmupStampDir!\!PSOWarmupKey!.done"
set "PSOWarmupLog=!PSOWarmupLogDir!\!PSOWarmupKey!.log"
set "PSOWarmupCVarIni=!PSOWarmupTempDir!\!PSOWarmupKey!-warmup.ini"
set "PSOCaptureCVarIni=!PSOWarmupTempDir!\!PSOWarmupKey!-capture.ini"

set "WarmupRunExecCmds=!ExecCmds!"
if defined QualityExecCmds if defined WarmupRunExecCmds set "WarmupRunExecCmds=!WarmupRunExecCmds!,!QualityExecCmds!"
if defined QualityExecCmds if not defined WarmupRunExecCmds set "WarmupRunExecCmds=!QualityExecCmds!"
if defined WarmupRunExecCmds if defined PSOWarmupExecCmds set "WarmupRunExecCmds=!WarmupRunExecCmds!,!PSOWarmupExecCmds!"
if not defined WarmupRunExecCmds set "WarmupRunExecCmds=!PSOWarmupExecCmds!"
set "CaptureRunExecCmds=!ExecCmds!"
if defined QualityExecCmds if defined CaptureRunExecCmds set "CaptureRunExecCmds=!CaptureRunExecCmds!,!QualityExecCmds!"
if defined QualityExecCmds if not defined CaptureRunExecCmds set "CaptureRunExecCmds=!QualityExecCmds!"
if defined CaptureRunExecCmds if defined PSOCaptureExecCmds set "CaptureRunExecCmds=!CaptureRunExecCmds!,!PSOCaptureExecCmds!"
if not defined CaptureRunExecCmds set "CaptureRunExecCmds=!PSOCaptureExecCmds!"

mkdir "!ArchiveTarget!" >nul 2>&1
if defined QualityCVars (> "!ArchiveTarget!\quality_cvars.txt" echo !QualityCVars!) else (> "!ArchiveTarget!\quality_cvars.txt" echo DEFAULT)
mkdir "!PSOWarmupStampDir!" >nul 2>&1
mkdir "!PSOWarmupLogDir!" >nul 2>&1
mkdir "!PSOWarmupTempDir!" >nul 2>&1

echo [INFO] [!ReplayIndex!] Running replay: "%ReplayPath%"
echo [INFO] [!ReplayIndex!] UserDir="%UserDir%"
echo [INFO] [!ReplayIndex!] PSO warmup key=!PSOWarmupKey!

set "RunPSOWarmup=false"
if /I "!PSOWarmupModeNormalized!"=="Always" set "RunPSOWarmup=true"
if /I "!PSOWarmupModeNormalized!"=="Auto" if not exist "!PSOWarmupStamp!" set "RunPSOWarmup=true"

if /I "!RunPSOWarmup!"=="true" (
  call :RunPSOWarmup
  set "PSO_WARMUP_RC=!ERRORLEVEL!"
  if not "!PSO_WARMUP_RC!"=="0" (
    echo FAIL [!ReplayIndex!] pso_warmup_rc=!PSO_WARMUP_RC! "!ReplayPath!" >> "!SummaryFile!"
    echo [ERROR] [!ReplayIndex!] PSO warmup failed rc=!PSO_WARMUP_RC!
    exit /b !PSO_WARMUP_RC!
  )
) else (
  if /I "!PSOWarmupModeNormalized!"=="Auto" echo [INFO] [!ReplayIndex!] PSO warmup cache hit. Skipping warmup.
  if /I "!PSOWarmupModeNormalized!"=="Never" echo [WARN] [!ReplayIndex!] PSO warmup disabled by configuration.
)

call :RunCapture
set "RUN_EXIT=!ERRORLEVEL!"

mkdir "!ArchiveTarget!\profiling" >nul 2>&1
mkdir "!ArchiveTarget!\logs" >nul 2>&1

if exist "!ProfilingDir!" (
  robocopy "!ProfilingDir!" "!ArchiveTarget!\profiling" /E /R:2 /W:2 >nul
  set "ROBO_PROFILE=!ERRORLEVEL!"
) else (
  echo [WARN] [!ReplayIndex!] Profiling dir not found: "!ProfilingDir!"
  set "ROBO_PROFILE=8"
)

if exist "!LogDir!" (
  robocopy "!LogDir!" "!ArchiveTarget!\logs" /E /R:2 /W:2 >nul
)

if not "!RUN_EXIT!"=="0" (
  echo FAIL [!ReplayIndex!] rc=!RUN_EXIT! "!ReplayPath!" >> "!SummaryFile!"
  echo [ERROR] [!ReplayIndex!] FAIL rc=!RUN_EXIT!
  exit /b !RUN_EXIT!
)
if !ROBO_PROFILE! GEQ 8 (
  echo FAIL [!ReplayIndex!] profiling_copy_rc=!ROBO_PROFILE! "!ReplayPath!" >> "!SummaryFile!"
  echo [ERROR] [!ReplayIndex!] Profiling copy failed rc=!ROBO_PROFILE!
  exit /b !ROBO_PROFILE!
)

echo PASS [!ReplayIndex!] "!ReplayPath!" archive="!ArchiveTarget!" >> "!SummaryFile!"
echo [INFO] [!ReplayIndex!] PASS archive="!ArchiveTarget!"
echo.
exit /b 0

:RunPSOWarmup
echo [INFO] [!ReplayIndex!] Starting PSO warmup pass. Performance collectors are disabled.

rmdir /s /q "!ProfilingDir!" >nul 2>&1
rmdir /s /q "!LogDir!" >nul 2>&1
mkdir "!ProfilingDir!" >nul 2>&1
mkdir "!LogDir!" >nul 2>&1
del /q "!PSOWarmupLog!" >nul 2>&1
call :WritePSOCVarIni "!PSOWarmupCVarIni!" Warmup
set "PSOWarmupWatchdogStatus=!PSOWarmupLog!.watchdog.status"
set "PSOWarmupWatchdogStop=!PSOWarmupLog!.watchdog.stop"
set "PSOWarmupWatchdogLog=!PSOWarmupLog!.watchdog.log"
call :StartReplayReadyWatchdog "%PCExe%" "!PSOWarmupLog!" "!PSOWarmupWatchdogStatus!" "!PSOWarmupWatchdogStop!" "!PSOWarmupWatchdogLog!"

pushd "%PCExeDir%" >nul
call "%PCExe%" "%MapPath%" ^
  -keepscreenawake ^
  -AutomatedPerfTest.TestID="APT_PSO_Warmup" ^
  !ReplayReadyArgs! ^
  -AutomatedPerfTest.ReplayPerfTest.ReplayName="!ReplayPath!" ^
  -ExecCmds="!WarmupRunExecCmds!" ^
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
  -userdir="!UserDir!" ^
  -abslog="!PSOWarmupLog!" ^
  -cvarsini="!PSOWarmupCVarIni!" ^
  %ExtraArgs%
set "PSO_WARMUP_EXIT=!ERRORLEVEL!"
popd >nul
call :FinalizeReplayReadyWatchdog "!PSOWarmupWatchdogStatus!" "!PSOWarmupWatchdogStop!" PSO_WARMUP_EXIT
del /q "!PSOWarmupCVarIni!" >nul 2>&1

mkdir "!ArchiveTarget!\warmup_logs" >nul 2>&1
if exist "!PSOWarmupLog!" copy /y "!PSOWarmupLog!" "!ArchiveTarget!\warmup_logs\ProjectPBZ-PSOWarmup.log" >nul
if exist "!PSOWarmupWatchdogLog!" copy /y "!PSOWarmupWatchdogLog!" "!ArchiveTarget!\warmup_logs\ReplayReadyWatchdog.log" >nul
if exist "!PSOWarmupWatchdogStatus!" copy /y "!PSOWarmupWatchdogStatus!" "!ArchiveTarget!\warmup_logs\ReplayReadyWatchdog.status" >nul

if not "!PSO_WARMUP_EXIT!"=="0" exit /b !PSO_WARMUP_EXIT!

set "PSOWarmupValidationArgs="
if /I "%PSOWarmupRequireCompletion%"=="true" set "PSOWarmupValidationArgs=-RequireCompletion"
if "%PSOWarmupRequireCompletion%"=="1" set "PSOWarmupValidationArgs=-RequireCompletion"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PSOTools%" -Action ValidateWarmup -LogPath "!PSOWarmupLog!" -QualityCVars "!QualityCVars!" !PSOWarmupValidationArgs!
set "PSO_WARMUP_VALIDATION_EXIT=!ERRORLEVEL!"
if not "!PSO_WARMUP_VALIDATION_EXIT!"=="0" exit /b !PSO_WARMUP_VALIDATION_EXIT!

> "!PSOWarmupStamp!" echo !PSOWarmupKey!
echo [INFO] [!ReplayIndex!] PSO warmup completed and cached.
exit /b 0

:RunCapture
echo [INFO] [!ReplayIndex!] Starting measured replay pass with runtime PSO precaching disabled and bundled batching paused.

rmdir /s /q "!ProfilingDir!" >nul 2>&1
rmdir /s /q "!LogDir!" >nul 2>&1
mkdir "!ProfilingDir!" >nul 2>&1
mkdir "!LogDir!" >nul 2>&1
call :WritePSOCVarIni "!PSOCaptureCVarIni!" Capture

set "LaunchExe=%PCExe%"
set "LaunchPrefixArgs="
set "GPUReshapeReport="
if /I "!GPUReshapeEnabled!"=="true" (
  set "GPUReshapeDir=%ProfilingDir%\GPUReshape"
  mkdir "!GPUReshapeDir!" >nul 2>&1
  set "GPUReshapeReport=!GPUReshapeDir!\!ReplayName!.GRS.Report.json"
  set "LaunchExe=!GPUReshapeExe!"
  set "LaunchPrefixArgs=launch -report "!GPUReshapeReport!" -workspace "!GPUReshapeWorkspacePath!" -timeout !GPUReshapeTimeout!"
  if exist "!GPUReshapeSymbolPath!" set "LaunchPrefixArgs=!LaunchPrefixArgs! -symbol "!GPUReshapeSymbolPath!""
  set "LaunchPrefixArgs=!LaunchPrefixArgs! -app "!PCExe!""
  echo [INFO] [!ReplayIndex!] GPUReshape report="!GPUReshapeReport!"
)

set "CaptureLogPath=!LogDir!\ProjectPBZ.log"
set "CaptureWatchdogStatus=!LogDir!\ReplayReadyWatchdog.status"
set "CaptureWatchdogStop=!LogDir!\ReplayReadyWatchdog.stop"
set "CaptureWatchdogLog=!LogDir!\ReplayReadyWatchdog.log"
call :StartReplayReadyWatchdog "!LaunchExe!" "!CaptureLogPath!" "!CaptureWatchdogStatus!" "!CaptureWatchdogStop!" "!CaptureWatchdogLog!"

pushd "%PCExeDir%" >nul
call "!LaunchExe!" !LaunchPrefixArgs! "%MapPath%" ^
  -keepscreenawake ^
  -AutomatedPerfTest.TestID="APT" ^
  -statnamedevents ^
  !AptDoArgs! ^
  !ReplayReadyArgs! ^
  -AutomatedPerfTest.ReplayPerfTest.ReplayName="!ReplayPath!" ^
  -ExecCmds="!CaptureRunExecCmds!" ^
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
  -abslog="!CaptureLogPath!" ^
  -cvarsini="!PSOCaptureCVarIni!" ^
  %ExtraArgs%
set "CAPTURE_EXIT=!ERRORLEVEL!"
popd >nul
call :FinalizeReplayReadyWatchdog "!CaptureWatchdogStatus!" "!CaptureWatchdogStop!" CAPTURE_EXIT
del /q "!PSOCaptureCVarIni!" >nul 2>&1

if /I "!GPUReshapeEnabled!"=="true" if "!CAPTURE_EXIT!"=="0" if not exist "!GPUReshapeReport!" (
  echo [ERROR] [!ReplayIndex!] GPUReshape exited without producing a report: "!GPUReshapeReport!"
  set "CAPTURE_EXIT=3"
)

if "!CAPTURE_EXIT!"=="0" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%PSOTools%" -Action ValidateCapture -LogPath "!CaptureLogPath!" -QualityCVars "!QualityCVars!"
  set "PSO_CAPTURE_VALIDATION_EXIT=!ERRORLEVEL!"
  if not "!PSO_CAPTURE_VALIDATION_EXIT!"=="0" set "CAPTURE_EXIT=!PSO_CAPTURE_VALIDATION_EXIT!"
)

echo [INFO] [!ReplayIndex!] Game exit code: !CAPTURE_EXIT!
exit /b !CAPTURE_EXIT!

:StartReplayReadyWatchdog
if /I not "!ReplayReadyWatchdogEnabled!"=="true" exit /b 0
set "WatchdogProcessPath=%~1"
set "WatchdogRuntimeLogPath=%~2"
set "WatchdogStatusPath=%~3"
set "WatchdogStopPath=%~4"
set "WatchdogLogPath=%~5"
del /q "!WatchdogStatusPath!" "!WatchdogStopPath!" "!WatchdogLogPath!" >nul 2>&1
start "" /b "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" ^
  -NoProfile ^
  -NonInteractive ^
  -ExecutionPolicy Bypass ^
  -WindowStyle Hidden ^
  -File "!ReplayWatchdogScript!" ^
  -ProcessPath "!WatchdogProcessPath!" ^
  -RuntimeLogPath "!WatchdogRuntimeLogPath!" ^
  -StatusPath "!WatchdogStatusPath!" ^
  -StopPath "!WatchdogStopPath!" ^
  -WatchdogLogPath "!WatchdogLogPath!" ^
  -ReadyTimeoutSeconds !ReplayReadyTimeoutSeconds! ^
  -GraceSeconds !ReplayReadyWatchdogGraceSeconds! ^
  -PollMilliseconds !ReplayReadyWatchdogPollMilliseconds! ^
  -ProcessStartTimeoutSeconds !ReplayReadyWatchdogProcessStartTimeoutSeconds! >nul 2>&1
if errorlevel 1 echo [WARN] Failed to start replay ready watchdog.
exit /b 0

:FinalizeReplayReadyWatchdog
if /I not "!ReplayReadyWatchdogEnabled!"=="true" exit /b 0
set "WatchdogStatusPath=%~1"
set "WatchdogStopPath=%~2"
set "WatchdogExitVariable=%~3"
if not exist "!WatchdogStatusPath!" (
  > "!WatchdogStopPath!" echo stop
  ping 127.0.0.1 -n 2 -w 1000 >nul
)
if not exist "!WatchdogStatusPath!" (
  echo [WARN] Replay ready watchdog did not produce a status file.
  exit /b 0
)
set "WatchdogResult="
set /p "WatchdogResult="<"!WatchdogStatusPath!"
echo [INFO] Replay ready watchdog result: !WatchdogResult!
if /I "!WatchdogResult!"=="KILLED" set "!WatchdogExitVariable!=124"
if /I "!WatchdogResult!"=="KILL_FAILED" set "!WatchdogExitVariable!=125"
if /I "!WatchdogResult!"=="ERROR" set "!WatchdogExitVariable!=126"
if /I "!WatchdogResult!"=="PROCESS_NOT_FOUND" set "!WatchdogExitVariable!=126"
exit /b 0

:WritePSOCVarIni
> "%~1" (
  echo [Startup]
  if /I "%~2"=="Warmup" (
    echo r.ShaderPipelineCache.StartupMode=1
    echo r.ShaderPipelineCache.BatchMode=1
  ) else (
    echo r.PSOPrecaching=0
    echo r.ShaderPipelineCache.StartupMode=0
  )
)
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
