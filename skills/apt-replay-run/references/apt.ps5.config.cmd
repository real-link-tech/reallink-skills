@echo off
rem PS5 APT config for run_replay_ps5.bat.
rem Keep this file CRLF.

set "EnginePath=D:\UnrealEngine"
set "ProjectPath=E:\PBZ\ProjectPBZ"
set "RunMode=PS5"
set "Replay_Path=\\192.168.0.7\store\APT\ReplayFiles\"
set "REPLAY_LIST=%Replay_Path%zxrzhulin.replay"

set "PS5Target=192.168.103.108"
set "Configuration=Test"
set "MaxDuration=1800"
set "PS5BuildDir=\\192.168.103.61\builds_ps\PS5\Test\页游包\CL-179700_JKS-8799"
set "Iterations=1"
set "ExecCmds="
rem apt没办法应用默认推荐设置，所以这里用本地配置应用
set "ExtraArgs=-NLPEnable -NLPRef=local -NLPLocalIP=localhost -VTPoolReport -StreamingPoolReport"

set "DoInsightsTrace=true"
set "DoCSVProfiler=false"
set "DoFPSChart=false"
set "DoLLM=false"
set "DoGPUPerf=false"
set "DoGPUReshape=false"
set "DoVideoCapture=false"

set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "PS5SourceProfiling=P:\%PS5Target%\devlog\app\projectpbz\projectpbz\saved\profiling"
