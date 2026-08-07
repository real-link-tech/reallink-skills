[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProcessPath,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeLogPath,

    [Parameter(Mandatory = $true)]
    [string]$StatusPath,

    [Parameter(Mandatory = $true)]
    [string]$StopPath,

    [Parameter(Mandatory = $true)]
    [string]$WatchdogLogPath,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1.0, 86400.0)]
    [double]$ReadyTimeoutSeconds,

    [ValidateRange(0.0, 600.0)]
    [double]$GraceSeconds = 10.0,

    [ValidateRange(100, 5000)]
    [int]$PollMilliseconds = 500,

    [ValidateRange(1.0, 300.0)]
    [double]$ProcessStartTimeoutSeconds = 30.0
)

$ErrorActionPreference = 'Stop'
$ReadyWaitMarker = 'Replay ready task installed.'
$ProfilingStartedMarker = 'Replay is ready. Profiling started'
$ReadyTimeoutMarker = 'waiting for replay readiness'
$TargetProcessPath = [IO.Path]::GetFullPath($ProcessPath)
$TargetProcessName = [IO.Path]::GetFileNameWithoutExtension($TargetProcessPath)
$TargetRuntimeLogPath = [IO.Path]::GetFullPath($RuntimeLogPath)
$WatchdogStartedUtc = [DateTime]::UtcNow
$LogOffset = 0L
$ScanBuffer = ''

function Ensure-ParentDirectory {
    param([string]$Path)

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Write-WatchdogLog {
    param([string]$Message)

    $line = '{0:O} {1}' -f [DateTime]::UtcNow, $Message
    Add-Content -LiteralPath $WatchdogLogPath -Value $line -Encoding UTF8
}

function Set-WatchdogStatus {
    param([string]$Status)

    $temporaryPath = "$StatusPath.tmp"
    Set-Content -LiteralPath $temporaryPath -Value $Status -Encoding ASCII
    Move-Item -LiteralPath $temporaryPath -Destination $StatusPath -Force
}

function Stop-Requested {
    if (-not (Test-Path -LiteralPath $StopPath)) {
        return $false
    }

    Remove-Item -LiteralPath $StopPath -Force -ErrorAction SilentlyContinue
    return $true
}

function Find-TargetProcess {
    $candidates = Get-Process -Name $TargetProcessName -ErrorAction SilentlyContinue

    foreach ($candidate in ($candidates | Sort-Object StartTime)) {
        try {
            if (-not [string]::Equals([IO.Path]::GetFullPath($candidate.Path), $TargetProcessPath, [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }

            if ($candidate.StartTime.ToUniversalTime() -lt $WatchdogStartedUtc.AddSeconds(-2.0)) {
                continue
            }

            return $candidate
        }
        catch {
            continue
        }
    }

    return $null
}

function Read-NewRuntimeLogText {
    if (-not (Test-Path -LiteralPath $TargetRuntimeLogPath)) {
        return ''
    }

    $stream = $null
    $reader = $null
    try {
        $stream = [IO.File]::Open(
            $TargetRuntimeLogPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)

        if ($stream.Length -lt $script:LogOffset) {
            $script:LogOffset = 0L
        }

        [void]$stream.Seek($script:LogOffset, [IO.SeekOrigin]::Begin)
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $script:LogOffset -eq 0L, 4096, $true)
        $text = $reader.ReadToEnd()
        $script:LogOffset = $stream.Length
        return $text
    }
    catch [IO.IOException] {
        return ''
    }
    finally {
        if ($reader) {
            $reader.Dispose()
        }
        if ($stream) {
            $stream.Dispose()
        }
    }
}

function Target-ProcessIsRunning {
    param([int]$ProcessId)

    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Kill-TargetProcessTree {
    param([int]$ProcessId)

    Set-WatchdogStatus 'KILLED'
    Write-WatchdogLog "Ready timeout exceeded. Killing process tree rooted at PID $ProcessId."

    $taskKillPath = Join-Path $env:SystemRoot 'System32\taskkill.exe'
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $taskKillOutput = & $taskKillPath /PID $ProcessId /T /F 2>&1
        $taskKillExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        foreach ($line in $taskKillOutput) {
            Write-WatchdogLog "taskkill: $line"
        }

        if ($taskKillExitCode -ne 0) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }

        Start-Sleep -Milliseconds 500
        if (-not (Target-ProcessIsRunning $ProcessId)) {
            Write-WatchdogLog 'Target process tree exited.'
            return $true
        }
    }

    Set-WatchdogStatus 'KILL_FAILED'
    Write-WatchdogLog "Unable to terminate process tree rooted at PID $ProcessId."
    return $false
}

try {
    Ensure-ParentDirectory $StatusPath
    Ensure-ParentDirectory $StopPath
    Ensure-ParentDirectory $WatchdogLogPath
    Remove-Item -LiteralPath $StatusPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$StatusPath.tmp" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $WatchdogLogPath -Force -ErrorAction SilentlyContinue

    Write-WatchdogLog (
        "Starting. Process='$TargetProcessPath' RuntimeLog='$TargetRuntimeLogPath' " +
        "ReadyTimeout=${ReadyTimeoutSeconds}s Grace=${GraceSeconds}s Poll=${PollMilliseconds}ms")

    $processStartDeadline = [DateTime]::UtcNow.AddSeconds($ProcessStartTimeoutSeconds)
    $targetProcess = $null
    while (-not $targetProcess) {
        if (Stop-Requested) {
            Set-WatchdogStatus 'STOPPED'
            Write-WatchdogLog 'Stopped before the target process was discovered.'
            exit 0
        }

        $targetProcess = Find-TargetProcess
        if ($targetProcess) {
            break
        }

        if ([DateTime]::UtcNow -ge $processStartDeadline) {
            Set-WatchdogStatus 'PROCESS_NOT_FOUND'
            Write-WatchdogLog "Target process was not found within ${ProcessStartTimeoutSeconds}s."
            exit 0
        }

        Start-Sleep -Milliseconds $PollMilliseconds
    }

    $targetProcessId = [int]$targetProcess.Id
    Write-WatchdogLog "Attached to PID $targetProcessId. Waiting for replay readiness to arm."

    $readyDeadline = $null
    while ($true) {
        if (Stop-Requested) {
            Set-WatchdogStatus 'STOPPED'
            Write-WatchdogLog 'Stopped by the runner.'
            exit 0
        }

        $newText = Read-NewRuntimeLogText
        if ($newText) {
            $ScanBuffer = $ScanBuffer + $newText
            if ($ScanBuffer.Length -gt 16384) {
                $ScanBuffer = $ScanBuffer.Substring($ScanBuffer.Length - 16384)
            }

            if ($ScanBuffer.IndexOf($ProfilingStartedMarker, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                Set-WatchdogStatus 'READY'
                Write-WatchdogLog 'Profiling start detected. Watchdog disarmed.'
                exit 0
            }

            if (-not $readyDeadline -and
                $ScanBuffer.IndexOf($ReadyWaitMarker, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $readyDeadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds + $GraceSeconds)
                Write-WatchdogLog "Replay ready wait armed. External deadline is $($readyDeadline.ToString('O'))."
            }

            if ($ScanBuffer.IndexOf($ReadyTimeoutMarker, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $ScanBuffer.IndexOf('Timed out after', [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $graceDeadline = [DateTime]::UtcNow.AddSeconds($GraceSeconds)
                if (-not $readyDeadline -or $graceDeadline -lt $readyDeadline) {
                    $readyDeadline = $graceDeadline
                    Write-WatchdogLog "In-process ready timeout detected. Grace deadline is $($readyDeadline.ToString('O'))."
                }
            }
        }

        if (-not (Target-ProcessIsRunning $targetProcessId)) {
            Set-WatchdogStatus 'PROCESS_EXITED'
            Write-WatchdogLog 'Target process exited before the watchdog fired.'
            exit 0
        }

        if ($readyDeadline -and [DateTime]::UtcNow -ge $readyDeadline) {
            if (Kill-TargetProcessTree $targetProcessId) {
                exit 124
            }
            exit 125
        }

        Start-Sleep -Milliseconds $PollMilliseconds
    }
}
catch {
    try {
        Set-WatchdogStatus 'ERROR'
        Write-WatchdogLog "ERROR: $($_.Exception.Message)"
    }
    catch {
        # The runner will still receive the target process exit code if status reporting fails.
    }
    exit 2
}
