# 远程 PC APT 怎么配和怎么跑

## 这个模式是干什么的

远程 PC 模式适合这种情况：

- 远端电脑只有 Win64 包体。
- 远端不需要 UnrealEngine。
- 远端不需要 ProjectPBZ 工程。
- 本机只负责触发，游戏窗口在远端登录桌面里打开。

## 改哪个配置

改这个文件：

```bat
references\apt.remote-pc.config.cmd
```

远程 PC 不会读取本地 PC 的配置文件：

```bat
references\apt.pc.config.cmd
```

但是远程 PC 仍然是在跑 Win64 PC 包体，所以它会用到同一类 PC 包体字段，比如 `PCBuildDir`、`PCExe`、`REPLAY_LIST`。这些字段需要在 `apt.remote-pc.config.cmd` 里单独写一份。

简单说：

- 本地 PC 跑法用 `apt.pc.config.cmd`
- 远程 PC 跑法用 `apt.remote-pc.config.cmd`
- 两个配置文件互不读取
- 两边都可能需要配置 `PCBuildDir`，但含义不同：本地 PC 是本机路径，远程 PC 是远端电脑上的路径

## 配置文件里有哪些区块

`apt.remote-pc.config.cmd` 是完整模板，主要分这些区块：

- 远程触发设置：`RemotePC`、`RemoteUser`、`RemoteDeployDir`、`RemoteTaskName` 等。
- PC 包体设置：`PCBuildDir`、`PCExe`、`PCBuildName`、`REPLAY_LIST`。
- 游戏启动设置：`MapPath`、`WindowMode`、`ExecCmds`、`ExtraArgs`。
- APT capture 开关：`DoInsightsTrace`、`DoCSVProfiler`、`DoFPSChart`、`DoLLM`、`DoGPUPerf`、`DoGPUReshape`、`DoVideoCapture`。
- 输出设置：`ArchiveRoot`、`WorkRoot`、`PCSourceProfiling`。

注意：远程 PC 是直接启动 packaged exe，不走 RunUAT，所以不配置 `Configuration`、`MaxDuration`、`Iterations`。

## 最少要重点确认这些

```bat
set "RemotePC=192.168.103.33"
set "RemoteUser=192.168.103.33\a"

set "PCBuildDir=D:\PBZ_PC\Win64_189198-9493\189198-9493"
set "PCExe=D:\PBZ_PC\Win64_189198-9493\189198-9493\Windows\ProjectPBZ\Binaries\Win64\ProjectPBZ-Win64-Test.exe"
set "PCBuildName=189198-9493"
set "REPLAY_LIST=\\192.168.0.7\store\APT\ReplayFiles"
set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "WorkRoot=D:\APTWork"
```

这是最小包体信息，不是全部配置。远程 PC 跑的是 PC 包体，所以启动参数也在 `apt.remote-pc.config.cmd` 里配。

## 字段是什么意思

- `RemotePC`: 远端电脑 IP 或机器名。
- `RemoteUser`: 远端登录账号。如果当前 Windows 用户已经有权限，可以不配。
- `PCBuildDir`: 远端电脑上的 Win64 包体目录。注意不是本机路径。
- `PCExe`: 远端电脑上的游戏 exe 完整路径。
- `PCBuildName`: 归档目录里显示的包名。
- `REPLAY_LIST`: 远端电脑能访问到的 replay 输入。默认共享目录会递归查找所有子目录中的 `.replay` 并按完整路径排序；也可以指定单个文件、分号列表或 `.txt/.list` 清单。
- `ArchiveRoot`: 远端电脑能写入的报告归档目录。
- `WorkRoot`: 远端电脑本地工作目录。

## 也必须明确配置这些

`run_replay_remote.bat --target` 不提供默认启动参数。下面这些都应该写在 `apt.remote-pc.config.cmd` 里：

```bat
set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "WorkRoot=D:\APTWork"
set "MapPath=/Game/Maps/B02/PBZ_Xigu_WP"
set "WindowMode=-windowed"
set "ExecCmds=Reallink.ProfileMatrix.SuspendCVarsRefresh 1;r.DynamicRes.OperationMode 0;"
set "DoInsightsTrace=false"
set "DoCSVProfiler=false"
set "DoFPSChart=false"
set "DoLLM=false"
set "DoGPUPerf=false"
set "DoGPUReshape=false"
set "DoVideoCapture=false"
```

如果缺了这些字段，脚本会直接报错。

## 远程触发相关字段

```bat
set "RemoteDeployDir=D:\APT"
set "RemoteCredentialFile=%USERPROFILE%\.apt\remote_192.168.103.33.credential.xml"
set "RemoteSaveCredential=true"
```

这些是 `run_replay_remote.bat` 的触发配置。可以不写，不写时 launcher 会用自己的默认值。它们不属于游戏启动参数。

## 启动参数怎么加

常用启动参数直接在 `apt.remote-pc.config.cmd` 里写这些字段：

```bat
set "MapPath=/Game/Maps/B02/PBZ_Xigu_WP"
set "WindowMode=-windowed"
set "ExecCmds=Reallink.ProfileMatrix.SuspendCVarsRefresh 1;r.DynamicRes.OperationMode 0;"
```

这些会被拼进远端游戏启动命令。缺了会报错。

如果要加临时 UE/game 参数，用 `ExtraArgs`：

```bat
set "ExtraArgs=-ResX=1920 -ResY=1080 -ForceRes -NoVSync"
```

`ExtraArgs` 会原样追加到 `ProjectPBZ-Win64-Test.exe` 命令最后。适合放那些不常用、不想单独做字段的参数。

不要把这些参数写到 `apt.pc.config.cmd`。远程 PC 只读：

```bat
references\apt.remote-pc.config.cmd
```

## 怎么让 Codex 跑

直接说：

```text
跑远程PC APT
```

或者：

```text
跑远程PC
```

skill 应该使用：

```bat
references\run_replay_remote.bat
```

## 手动命令

```bat
references\run_replay_remote.bat
```

## 密码怎么处理

第一次如果配置了 `RemoteUser`，PowerShell 可能会弹密码。

默认会保存凭据到：

```bat
%USERPROFILE%\.apt\remote_%RemotePC%.credential.xml
```

以后同一台本机、同一个 Windows 用户再跑，会自动读取，不用每次输密码。

## 常见问题

### 远程能连，但没有游戏窗口

现在默认会通过远端交互式计划任务启动游戏。远端必须有同一个用户登录在桌面上，否则窗口不会正常显示。

### 报 DXGI_ERROR_NOT_CURRENTLY_AVAILABLE

通常是游戏被直接放进 WinRM 非交互 session 启动了。

现在 `run_replay_remote.bat` 默认不会这么做。确认你跑的是：

```bat
references\run_replay_remote.bat
```

不要手动用 `Invoke-Command` 直接启动游戏 exe。

### AccessDenied

说明远程账号没有权限。

检查：

```bat
set "RemoteUser=..."
```

这个账号需要能 PowerShell Remoting 到远端，并且通常要有管理员权限。

### 远程连不上

远端管理员 PowerShell 执行：

```powershell
Enable-PSRemoting -Force
Start-Service WinRM
Enable-NetFirewallRule -DisplayGroup "Windows Remote Management"
```

本机如果提示 TrustedHosts，管理员 PowerShell 执行：

```powershell
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "192.168.103.33" -Force
```

### 找不到 exe

检查：

```bat
set "PCExe=..."
```

确认远端电脑上这个文件存在。`PCExe` 现在必须明确配置。

### 找不到 replay 或没法写报告

远端电脑必须能访问这些共享路径：

```bat
set "REPLAY_LIST=\\192.168.0.7\store\APT\ReplayFiles"
set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
```

注意是远端电脑要能访问，不是只有本机能访问。
