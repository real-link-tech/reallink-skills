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
rem Optional integer quality overrides: CVar=Value;CVar=Value. Empty keeps the current default quality.
set "QualityCVars="
rem apt没办法应用默认推荐设置，所以这里用本地配置应用
set "ExtraArgs=-NLPEnable -NLPRef=local -NLPLocalIP=localhost -VTPoolReport -StreamingPoolReport"

rem Insights Trace is opt-in. Enable it only in a temporary config for an explicit Trace run.
set "DoInsightsTrace=false"
set "DoCSVProfiler=false"
set "DoFPSChart=true"
set "DoLLM=true"
set "DoGPUPerf=false"
set "DoGPUReshape=false"
set "DoVideoCapture=false"

rem Pause replay playback until the replay world and ProjectPBZ loading flow are stable.
set "WaitForReplayReady=true"
set "ReplayReadyCVar=gq.Ind.Loading"
set "ReplayReadyValue=0"
set "ReplayReadySettleSeconds=1.0"
set "ReplayReadyTimeoutSeconds=60.0"
set "ReplayReadyForceExitOnTimeout=true"
set "ReplayReadyWatchdog=true"
set "ReplayReadyWatchdogGraceSeconds=10.0"
set "ReplayReadyPrimeFrames=1"

rem PSO policy for local replay runs. Auto warms once per build/replay/GPU-driver key.
set "PSOWarmupMode=Auto"
set "PSOWarmupCacheRoot=%WorkRoot%\PSOWarmup"
set "PSOWarmupRequireCompletion=true"
set "PSOWarmupBatchSize=100"
set "PSOWarmupBatchTime=200"
set "PSOWarmupExecCmds=Reallink.ProfileMatrix.AddCustomizedCVar r.ShaderPipelineCache.BatchMode 1,Reallink.ProfileMatrix.AddCustomizedCVar r.ShaderPipelineCache.BatchSize %PSOWarmupBatchSize%,Reallink.ProfileMatrix.AddCustomizedCVar r.ShaderPipelineCache.BatchTime %PSOWarmupBatchTime%,r.ShaderPipelineCache.SetBatchMode Fast"
set "PSOCaptureExecCmds=Reallink.ProfileMatrix.AddCustomizedCVar r.PSOPrecaching 0,r.ShaderPipelineCache.SetBatchMode Pause"

rem GPUPerf settings applied by the direct PC runner.
set "GPUPerfExecCmds=r.StencilLODMode 1,r.VolumetricRenderTarget.PreferAsyncCompute 0,r.LumenScene.Lighting.AsyncCompute 0,r.Lumen.DiffuseIndirect.AsyncCompute 0,r.Bloom.AsyncCompute 0,r.nanite.asyncrasterization.shadowdepths 1,r.TSR.AsyncCompute 0,r.RayTracing.AsyncBuild 0,r.DFShadowAsyncCompute 0,r.AmbientOcclusion.Compute 1,r.LocalFogVolume.TileCullingUseAsync 0,r.SkyAtmosphereASyncCompute 0,r.Substrate.AsyncClassification 0"

rem GPUReshape direct-launch settings.
set "GPUReshapeExe=%EnginePath%\Engine\Binaries\ThirdParty\GPUReshape\Win64\Raytracing\GPUReshape.exe"
set "GPUReshapeWorkspace=BasicWorkspace"
set "GPUReshapeWorkspacePath=%EnginePath%\Engine\Source\Programs\GPUReshape\Resources\Workspaces\%GPUReshapeWorkspace%.json"
set "GPUReshapeSymbolPath=%ProjectPath%\Saved\ShaderSymbols"
set "GPUReshapeTimeout=7200"
set "GPUReshapeTargetArgs=-nothreadtimeout -noheartbeatthread"

set "ArchiveRoot=D:\APTReport"
set "PCSourceProfiling=%WorkRoot%\UserDir\Saved\Profiling"
