@echo off
rem Editable APT config (pure bat). Keep this file ANSI/ASCII to avoid cmd encoding issues.

set "EnginePath=D:\UnrealEngine"
set "ProjectPath=E:\PBZ\ProjectPBZ"
set "REPLAY_PATH=\\192.168.0.7\store\APT\ReplayFiles\test1.replay"
set "PS5Target=192.168.103.108"

set "Configuration=Test"
set "MaxDuration=1800"
set "PS5BuildDir=\\192.168.103.61\builds_ps\PS5\Test\页游包\CL-179700_JKS-8799"
set "PCBuildDir=D:\PBZ_Release\178669-8704"
set "Iterations=1"
set "ExecCmds="
set "DoInsightsTrace=true"
set "DoCSVProfiler=false"
set "DoFPSChart=false"
set "DoLLM=false"
set "DoGPUPerf=false"
set "DoGPUReshape=false"
set "DoVideoCapture=false"

set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "PS5SourceProfiling=P:\%PS5Target%\devlog\app\projectpbz\projectpbz\saved\profiling"
set "PCSourceProfiling=%ProjectPath%\Saved\Profiling"
