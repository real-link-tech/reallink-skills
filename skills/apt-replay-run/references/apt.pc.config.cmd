@echo off
rem Local PC APT config for run_replay_pc.bat.
rem Keep this file CRLF.

set "EnginePath=D:\UnrealEngine"
set "ProjectPath=E:\PBZ\ProjectPBZ"
set "RunMode=PC"
set "Replay_Path=\\192.168.0.7\store\APT\ReplayFiles\"
set "REPLAY_LIST=%Replay_Path%xuesesinlin\xuesesenlin_1.replay"
set "REPLAY_LIST=%Replay_Path%xuesesinlin\xuesesenlin_2.replay"
set "REPLAY_LIST=%Replay_Path%xuesesinlin\xuesesenlin_3.replay"
set "REPLAY_LIST=%Replay_Path%xuesesinlin\xuesesenlin_4.replay"

set "Configuration=Test"
set "MaxDuration=1800"
set "PCBuildDir=E:\PBZ_PC_Package\196505-10133"
set "PCExe=E:\PBZ_PC_Package\196505-10133\Windows\ProjectPBZ\Binaries\Win64\ProjectPBZ-Win64-Test.exe"
set "PCBuildName=196505-10133"
set "WorkRoot=D:\APTWork"
set "MapPath=/Game/Maps/B02/PBZ_Xigu_WP"
set "WindowMode=-windowed"
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
set "PCSourceProfiling=%WorkRoot%\UserDir\Saved\Profiling"
