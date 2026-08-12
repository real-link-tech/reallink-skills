@echo off
rem Remote PC APT config for run_replay_remote.bat.
rem Keep this file CRLF.

rem ---------------------------------------------------------------------------
rem Remote trigger settings. These are used by controller mode on this machine.
rem ---------------------------------------------------------------------------
set "RemotePC=192.168.103.33"
set "RemoteUser=192.168.103.33\a"
set "RemoteDeployScripts=true"
set "RemoteDeployDir=D:\APT"
set "RemoteBat=D:\APT\run_replay_remote.bat"
set "RemoteConfig=D:\APT\apt.remote-pc.config.cmd"
set "RemoteTaskName=APT_Remote_Run"
set "RemoteTaskLog=D:\APT\remote_task.log"
set "RemoteTaskPollSeconds=5"
set "RemoteCredentialFile=%USERPROFILE%\.apt\remote_192.168.103.33.credential.xml"
set "RemoteSaveCredential=true"

rem ---------------------------------------------------------------------------
rem PC package settings. These paths are on the remote PC, not this machine.
rem ---------------------------------------------------------------------------
set "RunMode=RemotePC"
set "PCBuildDir=D:\PBZ_PC\Win64_189198-9493\189198-9493"
set "PCExe=D:\PBZ_PC\Win64_189198-9493\189198-9493\Windows\ProjectPBZ\Binaries\Win64\ProjectPBZ-Win64-Test.exe"
set "PCBuildName=189198-9493"
set "Replay_Path=\\192.168.0.7\store\APT\ReplayFiles"
set "REPLAY_LIST=%Replay_Path%"

rem ---------------------------------------------------------------------------
rem Game launch settings. Target mode does not provide defaults for these.
rem ---------------------------------------------------------------------------
set "MapPath=/Game/Maps/B02/PBZ_Xigu_WP"
set "WindowMode=-windowed"
set "ExecCmds="
rem apt没办法应用默认推荐设置，所以这里用本地配置应用
set "ExtraArgs=-NLPEnable -NLPRef=local -NLPLocalIP=localhost -VTPoolReport -StreamingPoolReport"

rem ---------------------------------------------------------------------------
rem APT capture toggles. Same names as apt.pc.config.cmd.
rem ---------------------------------------------------------------------------
rem Insights Trace is opt-in. Enable it only in a temporary config for an explicit Trace run.
set "DoInsightsTrace=false"
set "DoCSVProfiler=false"
set "DoFPSChart=false"
set "DoLLM=false"
set "DoGPUPerf=false"
set "DoGPUReshape=false"
set "DoVideoCapture=false"

rem ---------------------------------------------------------------------------
rem Output/archive settings. WorkRoot is on the remote PC.
rem ArchiveRoot must be writable from the remote PC.
rem ---------------------------------------------------------------------------
set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "WorkRoot=D:\APTWork"
set "PCSourceProfiling=%WorkRoot%\UserDir\Saved\Profiling"
