@echo off
rem Editable APT config (pure bat). Keep this file ANSI/ASCII to avoid cmd encoding issues.

set "EnginePath=D:\UnrealEngine"
set "ProjectPath=E:\PBZ\ProjectPBZ"
set "RunMode=Packaged"
set "REPLAY_PATH=\\192.168.0.7\store\APT\ReplayFiles\到少年左殇进seq前.replay"
set "MapName=PBZ_WP_ZhuLinGuWu"
set "PS5Target=192.168.103.108"
set "PS5DeviceIp=PS5:192.168.103.108"

set "Configuration=Test"
set "MaxDuration=3600"
set "BuildDir=\\192.168.103.61\builds_ps\PS5\Test\页游包\CL-175803_JKS-8330"
set "Iterations=1"
set "ExecCmds=Reallink.ProfileMatrix.SuspendCVarsRefresh 1;r.DynamicRes.OperationMode 0;"
set "TestID=APT"
set "DoInsightsTrace=true"
set "DoCSVProfiler=false"
set "DoFPSChart=false"
set "DoLLM=false"
set "DoGPUPerf=false"
set "DoGPUReshape=false"
set "DoVideoCapture=false"

set "SourceProfiling=P:\192.168.103.108\devlog\app\projectpbz\projectpbz\saved\profiling"
set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "EditorExe=D:\UnrealEngine\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
set "EditorTestName=AutomatedPerfTest.ReplayTest"
