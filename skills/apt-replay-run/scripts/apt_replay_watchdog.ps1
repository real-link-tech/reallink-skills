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

    [string]$DiagnosticPath = '',

    [Parameter(Mandatory = $true)]
    [ValidateRange(1.0, 86400.0)]
    [double]$ReadyTimeoutSeconds,

    [ValidateRange(0.0, 600.0)]
    [double]$GraceSeconds = 10.0,

    [ValidateRange(1.0, 86400.0)]
    [double]$ReplayProgressTimeoutSeconds = 120.0,

    [ValidateRange(1.0, 3600.0)]
    [double]$ExitTimeoutSeconds = 90.0,

    [ValidateRange(0.1, 30.0)]
    [double]$CpuSampleSeconds = 3.0,

    [ValidateRange(100, 5000)]
    [int]$PollMilliseconds = 500,

    [ValidateRange(1.0, 300.0)]
    [double]$ProcessStartTimeoutSeconds = 30.0,

    [switch]$DisableReadyWatchdog,

    [switch]$DisableReplayProgressWatchdog,

    [switch]$DisableExitWatchdog
)

$ErrorActionPreference = 'Stop'
$ReadyWaitMarker = 'Replay ready task installed.'
$ProfilingStartedMarker = 'Replay is ready. Profiling started'
$ReadyTimeoutMarker = 'waiting for replay readiness'
$TeardownMarker = 'AutomatedReplayPerfTest::TeardownTest'
$RequestExitMarker = 'completed, requesting exit'
$PSOExitMarker = '[PBZTrace] PSO: Exit flush'
$ChunkPattern = 'FLocalFileNetworkReplayStreamer::ConditionallyLoadNextChunk\.\s*Index:\s*(\d+)'
$TargetProcessPath = [IO.Path]::GetFullPath($ProcessPath)
$TargetProcessName = [IO.Path]::GetFileNameWithoutExtension($TargetProcessPath)
$TargetRuntimeLogPath = [IO.Path]::GetFullPath($RuntimeLogPath)
$WatchdogStartedUtc = [DateTime]::UtcNow
$LogOffset = 0L
$PartialLogLine = ''
$Phase = 'WAIT_FOR_READY_ARM'
$ReadyDeadline = $null
$ReplayLastProgressUtc = $null
$ExitDeadline = $null
$LastChunkIndex = $null
$LogTail = New-Object 'System.Collections.Generic.Queue[string]'
$LogTailLimit = 200

if ([string]::IsNullOrWhiteSpace($DiagnosticPath)) {
    $DiagnosticPath = Join-Path (Split-Path -Parent $StatusPath) 'ReplayWatchdog.json'
}
$DiagnosticPath = [IO.Path]::GetFullPath($DiagnosticPath)
$DiagnosticTailPath = [IO.Path]::ChangeExtension($DiagnosticPath, '.tail.log')

function Ensure-ParentDirectory {
    param([string]$Path)

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Write-Utf8NoBomText {
    param(
        [string]$Path,
        [string]$Text
    )

    $encoding = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($Path, $Text, $encoding)
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

function Contains-Text {
    param(
        [string]$Text,
        [string]$Value
    )

    return $Text.IndexOf($Value, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Find-TargetProcess {
    $candidates = Get-Process -Name $TargetProcessName -ErrorAction SilentlyContinue

    foreach ($candidate in ($candidates | Sort-Object StartTime)) {
        try {
            if (-not [string]::Equals(
                    [IO.Path]::GetFullPath($candidate.Path),
                    $TargetProcessPath,
                    [StringComparison]::OrdinalIgnoreCase)) {
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

function Get-VerifiedTargetProcess {
    param(
        [int]$ProcessId,
        [DateTime]$ExpectedStartUtc
    )

    $candidate = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $candidate) {
        return $null
    }

    try {
        if (-not [string]::Equals(
                [IO.Path]::GetFullPath($candidate.Path),
                $TargetProcessPath,
                [StringComparison]::OrdinalIgnoreCase)) {
            return $null
        }

        $startDifference = [Math]::Abs(
            ($candidate.StartTime.ToUniversalTime() - $ExpectedStartUtc).TotalSeconds)
        if ($startDifference -gt 1.0) {
            return $null
        }

        return $candidate
    }
    catch {
        return $null
    }
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
            $script:PartialLogLine = ''
        }

        [void]$stream.Seek($script:LogOffset, [IO.SeekOrigin]::Begin)
        $reader = [IO.StreamReader]::new(
            $stream,
            [Text.Encoding]::UTF8,
            ($script:LogOffset -eq 0L),
            4096,
            $true)
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

function Add-LogTailLine {
    param([string]$Line)

    $script:LogTail.Enqueue($Line)
    while ($script:LogTail.Count -gt $LogTailLimit) {
        [void]$script:LogTail.Dequeue()
    }
}

function Enter-ReplayActivePhase {
    param([string]$Reason)

    if ($script:Phase -eq 'EXITING') {
        return
    }

    $script:Phase = 'REPLAY_ACTIVE'
    $script:ReplayLastProgressUtc = [DateTime]::UtcNow
    Write-WatchdogLog "Replay progress monitoring armed: $Reason"
}

function Enter-ExitPhase {
    param([string]$Reason)

    if ($script:Phase -eq 'EXITING') {
        return
    }

    $script:Phase = 'EXITING'
    $script:ExitDeadline = [DateTime]::UtcNow.AddSeconds($ExitTimeoutSeconds)
    Write-WatchdogLog (
        "Exit phase detected: $Reason. Exit deadline is " +
        $script:ExitDeadline.ToString('O'))
}

function Process-LogLine {
    param([string]$Line)

    Add-LogTailLine $Line

    if (Contains-Text $Line $TeardownMarker) {
        Enter-ExitPhase 'TeardownTest'
    }
    elseif (Contains-Text $Line $RequestExitMarker) {
        Enter-ExitPhase 'requesting exit'
    }
    elseif (Contains-Text $Line $PSOExitMarker) {
        Enter-ExitPhase 'PSO exit flush'
    }

    if (Contains-Text $Line $ProfilingStartedMarker) {
        Enter-ReplayActivePhase 'profiling start detected'
    }

    if (Contains-Text $Line $ReadyWaitMarker) {
        $script:Phase = 'WAIT_READY'
        if (-not $DisableReadyWatchdog) {
            $script:ReadyDeadline = [DateTime]::UtcNow.AddSeconds(
                $ReadyTimeoutSeconds + $GraceSeconds)
            Write-WatchdogLog (
                'Replay ready wait armed. External deadline is ' +
                $script:ReadyDeadline.ToString('O'))
        }
        else {
            Write-WatchdogLog 'Replay ready marker detected; ready timeout monitoring is disabled.'
        }
    }

    if (-not $DisableReadyWatchdog -and
        (Contains-Text $Line $ReadyTimeoutMarker) -and
        (Contains-Text $Line 'Timed out after')) {
        $graceDeadline = [DateTime]::UtcNow.AddSeconds($GraceSeconds)
        if (-not $script:ReadyDeadline -or $graceDeadline -lt $script:ReadyDeadline) {
            $script:ReadyDeadline = $graceDeadline
            Write-WatchdogLog (
                'In-process ready timeout detected. Grace deadline is ' +
                $script:ReadyDeadline.ToString('O'))
        }
    }

    $chunkMatch = [Text.RegularExpressions.Regex]::Match(
        $Line,
        $ChunkPattern,
        [Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if ($chunkMatch.Success) {
        $chunkIndex = [int]$chunkMatch.Groups[1].Value
        if ($null -eq $script:LastChunkIndex -or $chunkIndex -ne $script:LastChunkIndex) {
            $previousChunkIndex = $script:LastChunkIndex
            $script:LastChunkIndex = $chunkIndex
            $script:ReplayLastProgressUtc = [DateTime]::UtcNow

            if ($script:Phase -eq 'WAIT_FOR_READY_ARM') {
                Enter-ReplayActivePhase 'chunk marker detected before a ready marker'
            }
            elseif ($script:Phase -eq 'REPLAY_ACTIVE') {
                Write-WatchdogLog (
                    'Replay progressed from chunk {0} to chunk {1}.' -f
                    $previousChunkIndex,
                    $chunkIndex)
            }
        }
    }
}

function Process-NewRuntimeLogText {
    param([string]$Text)

    if ([string]::IsNullOrEmpty($Text)) {
        return
    }

    $combined = $script:PartialLogLine + $Text
    $parts = [Text.RegularExpressions.Regex]::Split($combined, '\r\n|\n|\r')
    $endsWithNewLine = [Text.RegularExpressions.Regex]::IsMatch(
        $combined,
        '(\r\n|\n|\r)$')

    if ($endsWithNewLine) {
        $script:PartialLogLine = ''
        $completeCount = $parts.Count
    }
    else {
        $script:PartialLogLine = $parts[$parts.Count - 1]
        $completeCount = $parts.Count - 1
    }

    for ($index = 0; $index -lt $completeCount; $index++) {
        Process-LogLine $parts[$index]
    }
}

function Get-ProcessSnapshot {
    param(
        [int]$ProcessId,
        [DateTime]$ExpectedStartUtc
    )

    $before = Get-VerifiedTargetProcess $ProcessId $ExpectedStartUtc
    if (-not $before) {
        return [pscustomobject][ordered]@{
            Exited = $true
            Pid = $ProcessId
            SampleSeconds = 0.0
        }
    }

    $beforeCpu = if ($null -ne $before.CPU) { [double]$before.CPU } else { 0.0 }
    Start-Sleep -Milliseconds ([int][Math]::Round($CpuSampleSeconds * 1000.0))

    $after = Get-VerifiedTargetProcess $ProcessId $ExpectedStartUtc
    if (-not $after) {
        return [pscustomobject][ordered]@{
            Exited = $true
            Pid = $ProcessId
            SampleSeconds = $CpuSampleSeconds
        }
    }

    $afterCpu = if ($null -ne $after.CPU) { [double]$after.CPU } else { $beforeCpu }
    $cpuDelta = [Math]::Max(0.0, $afterCpu - $beforeCpu)
    $threadCount = 0
    try {
        $threadCount = @($after.Threads).Count
    }
    catch {
        $threadCount = -1
    }

    $responding = $true
    try {
        $responding = [bool]$after.Responding
    }
    catch {
        $responding = $true
    }

    return [pscustomobject][ordered]@{
        Exited = $false
        Pid = $ProcessId
        Path = $after.Path
        StartTimeUtc = $after.StartTime.ToUniversalTime().ToString('O')
        Responding = $responding
        CpuSecondsBefore = [Math]::Round($beforeCpu, 3)
        CpuSecondsAfter = [Math]::Round($afterCpu, 3)
        CpuDeltaSeconds = [Math]::Round($cpuDelta, 3)
        AverageActiveCores = [Math]::Round($cpuDelta / $CpuSampleSeconds, 3)
        SampleSeconds = $CpuSampleSeconds
        ThreadCount = $threadCount
        WorkingSetBytes = [int64]$after.WorkingSet64
        MainWindowTitle = [string]$after.MainWindowTitle
    }
}

function Write-Diagnostic {
    param(
        [string]$Status,
        [string]$Reason,
        [object]$ProcessSnapshot
    )

    $now = [DateTime]::UtcNow
    $noProgressSeconds = $null
    if ($null -ne $script:ReplayLastProgressUtc) {
        $noProgressSeconds = [Math]::Round(
            ($now - $script:ReplayLastProgressUtc).TotalSeconds,
            3)
    }

    $lastProgressText = $null
    if ($null -ne $script:ReplayLastProgressUtc) {
        $lastProgressText = $script:ReplayLastProgressUtc.ToString('O')
    }

    $diagnostic = [ordered]@{
        SchemaVersion = 1
        Status = $Status
        Reason = $Reason
        Phase = $script:Phase
        ObservedUtc = $now.ToString('O')
        WatchdogStartedUtc = $WatchdogStartedUtc.ToString('O')
        ProcessPath = $TargetProcessPath
        RuntimeLogPath = $TargetRuntimeLogPath
        LastChunkIndex = $script:LastChunkIndex
        ReplayLastProgressUtc = $lastProgressText
        NoProgressSeconds = $noProgressSeconds
        ReadyTimeoutSeconds = $ReadyTimeoutSeconds
        ReadyGraceSeconds = $GraceSeconds
        ReplayProgressTimeoutSeconds = $ReplayProgressTimeoutSeconds
        ExitTimeoutSeconds = $ExitTimeoutSeconds
        Process = $ProcessSnapshot
        LogTail = @($script:LogTail.ToArray())
    }

    $json = $diagnostic | ConvertTo-Json -Depth 8
    $temporaryPath = "$DiagnosticPath.tmp"
    Write-Utf8NoBomText $temporaryPath $json
    Move-Item -LiteralPath $temporaryPath -Destination $DiagnosticPath -Force

    $tailText = [string]::Join([Environment]::NewLine, @($script:LogTail.ToArray()))
    Write-Utf8NoBomText $DiagnosticTailPath $tailText
}

function Stop-TargetProcessTree {
    param(
        [int]$ProcessId,
        [DateTime]$ExpectedStartUtc
    )

    $verifiedProcess = Get-VerifiedTargetProcess $ProcessId $ExpectedStartUtc
    if (-not $verifiedProcess) {
        $processWithSameId = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($processWithSameId) {
            Write-WatchdogLog (
                "PID $ProcessId no longer matches the attached path/start time. Refusing to kill it.")
            return 'CHANGED'
        }

        Write-WatchdogLog 'Target process exited before process-tree termination.'
        return 'EXITED'
    }

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
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            Write-WatchdogLog 'Target process tree exited.'
            return 'KILLED'
        }
    }

    Write-WatchdogLog "Unable to terminate process tree rooted at PID $ProcessId."
    return 'FAILED'
}

function Invoke-TimeoutTermination {
    param(
        [string]$Status,
        [string]$Reason,
        [int]$ExitCode,
        [int]$ProcessId,
        [DateTime]$ExpectedStartUtc
    )

    $snapshot = Get-ProcessSnapshot $ProcessId $ExpectedStartUtc
    if ($snapshot.Exited) {
        Set-WatchdogStatus 'PROCESS_EXITED'
        Write-WatchdogLog 'Target process exited while collecting the timeout diagnostic sample.'
        Write-Diagnostic 'PROCESS_EXITED' $Reason $snapshot
        exit 0
    }

    Write-WatchdogLog "$Reason Terminating process tree rooted at PID $ProcessId."
    Write-Diagnostic $Status $Reason $snapshot

    $terminationResult = Stop-TargetProcessTree $ProcessId $ExpectedStartUtc
    if ($terminationResult -eq 'CHANGED') {
        Set-WatchdogStatus 'TARGET_PROCESS_CHANGED'
        Write-Diagnostic 'TARGET_PROCESS_CHANGED' $Reason $snapshot
        exit 126
    }
    if ($terminationResult -eq 'FAILED') {
        $failedStatus = '{0}_KILL_FAILED' -f $Status
        Set-WatchdogStatus $failedStatus
        Write-Diagnostic $failedStatus $Reason $snapshot
        exit 125
    }

    Set-WatchdogStatus $Status
    exit $ExitCode
}

try {
    Ensure-ParentDirectory $StatusPath
    Ensure-ParentDirectory $StopPath
    Ensure-ParentDirectory $WatchdogLogPath
    Ensure-ParentDirectory $DiagnosticPath
    Ensure-ParentDirectory $DiagnosticTailPath
    Remove-Item -LiteralPath $StatusPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$StatusPath.tmp" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StopPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $WatchdogLogPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $DiagnosticPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$DiagnosticPath.tmp" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $DiagnosticTailPath -Force -ErrorAction SilentlyContinue

    Write-WatchdogLog (
        "Starting lifecycle watchdog. Process='$TargetProcessPath' " +
        "RuntimeLog='$TargetRuntimeLogPath' ReadyTimeout=$ReadyTimeoutSeconds s " +
        "Grace=$GraceSeconds s ReplayProgressTimeout=$ReplayProgressTimeoutSeconds s " +
        "ExitTimeout=$ExitTimeoutSeconds s CpuSample=$CpuSampleSeconds s " +
        "ReadyEnabled=$(-not $DisableReadyWatchdog) " +
        "ReplayProgressEnabled=$(-not $DisableReplayProgressWatchdog) " +
        "ExitEnabled=$(-not $DisableExitWatchdog)")

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
            Write-WatchdogLog (
                "Target process was not found within $ProcessStartTimeoutSeconds seconds.")
            exit 0
        }

        Start-Sleep -Milliseconds $PollMilliseconds
    }

    $targetProcessId = [int]$targetProcess.Id
    $targetProcessStartUtc = $targetProcess.StartTime.ToUniversalTime()
    Write-WatchdogLog (
        "Attached to PID $targetProcessId started $($targetProcessStartUtc.ToString('O')).")

    while ($true) {
        if (Stop-Requested) {
            Set-WatchdogStatus 'STOPPED'
            Write-WatchdogLog 'Stopped by the runner.'
            exit 0
        }

        $newText = Read-NewRuntimeLogText
        if ($newText) {
            Process-NewRuntimeLogText $newText
        }

        if (-not (Get-VerifiedTargetProcess $targetProcessId $targetProcessStartUtc)) {
            Set-WatchdogStatus 'PROCESS_EXITED'
            Write-WatchdogLog 'Target process exited before the watchdog fired.'
            exit 0
        }

        $now = [DateTime]::UtcNow
        if (-not $DisableReadyWatchdog -and
            $script:Phase -eq 'WAIT_READY' -and
            $script:ReadyDeadline -and
            $now -ge $script:ReadyDeadline) {
            $reason = (
                'Replay readiness made no transition to profiling before the external deadline.')
            Invoke-TimeoutTermination 'READY_TIMEOUT' $reason 124 $targetProcessId $targetProcessStartUtc
        }

        if (-not $DisableReplayProgressWatchdog -and
            $script:Phase -eq 'REPLAY_ACTIVE' -and
            $script:ReplayLastProgressUtc) {
            $noProgressSeconds = ($now - $script:ReplayLastProgressUtc).TotalSeconds
            if ($noProgressSeconds -ge $ReplayProgressTimeoutSeconds) {
                $snapshot = Get-ProcessSnapshot $targetProcessId $targetProcessStartUtc
                if ($snapshot.Exited) {
                    Set-WatchdogStatus 'PROCESS_EXITED'
                    Write-WatchdogLog (
                        'Target process exited while collecting the replay progress sample.')
                    Write-Diagnostic 'PROCESS_EXITED' 'Replay progress timeout sample.' $snapshot
                    exit 0
                }

                if (-not $snapshot.Responding -and $snapshot.CpuDeltaSeconds -le 0.05) {
                    $status = 'PROCESS_HUNG'
                }
                elseif ($snapshot.CpuDeltaSeconds -gt 0.05) {
                    $status = 'REPLAY_STALLED_BUSY'
                }
                else {
                    $status = 'REPLAY_STALLED_IDLE'
                }

                $reason = (
                    'Replay produced no new chunk or teardown marker for {0:N1} seconds; last chunk was {1}.' -f
                    $noProgressSeconds,
                    $script:LastChunkIndex)

                Write-WatchdogLog "$reason Status=$status. Terminating PID $targetProcessId."
                Write-Diagnostic $status $reason $snapshot
                $terminationResult = Stop-TargetProcessTree $targetProcessId $targetProcessStartUtc
                if ($terminationResult -eq 'CHANGED') {
                    Set-WatchdogStatus 'TARGET_PROCESS_CHANGED'
                    Write-Diagnostic 'TARGET_PROCESS_CHANGED' $reason $snapshot
                    exit 126
                }
                if ($terminationResult -eq 'FAILED') {
                    $failedStatus = '{0}_KILL_FAILED' -f $status
                    Set-WatchdogStatus $failedStatus
                    Write-Diagnostic $failedStatus $reason $snapshot
                    exit 125
                }
                $statusLine = '{0} last_chunk={1} no_progress={2:N1}s' -f
                    $status,
                    $script:LastChunkIndex,
                    $noProgressSeconds
                Set-WatchdogStatus $statusLine
                exit 127
            }
        }

        if (-not $DisableExitWatchdog -and
            $script:Phase -eq 'EXITING' -and
            $script:ExitDeadline -and
            $now -ge $script:ExitDeadline) {
            $reason = (
                'The process did not exit within {0:N1} seconds after teardown/exit began.' -f
                $ExitTimeoutSeconds)
            Invoke-TimeoutTermination 'EXIT_STALLED' $reason 128 $targetProcessId $targetProcessStartUtc
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
