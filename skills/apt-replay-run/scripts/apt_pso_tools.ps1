param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('BuildQualityExecCmds', 'Key', 'ValidateWarmup', 'ValidateCapture')]
    [string]$Action,

    [string]$ExePath,
    [string]$ReplayPath,
    [string]$BuildName,
    [string]$MapPath,
    [string]$QualityCVars,
    [string]$LogPath,
    [switch]$RequireCompletion
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Exit-Failure {
    param(
        [int]$Code,
        [string]$Message
    )

    Write-Host "[ERROR] $Message"
    exit $Code
}

function Read-RunLog {
    if (-not $LogPath -or -not (Test-Path -LiteralPath $LogPath -PathType Leaf)) {
        Exit-Failure 10 "PSO validation log was not found: $LogPath"
    }

    $logText = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $LogPath))
    if ([string]::IsNullOrWhiteSpace($logText)) {
        Exit-Failure 11 "PSO validation log is empty: $LogPath"
    }

    return $logText
}

function Get-QualityCVarOverrides {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return
    }

    $seenNames = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($rawEntry in $Text.Split(';')) {
        $entry = $rawEntry.Trim()
        if (-not $entry) {
            continue
        }

        $separator = $entry.IndexOf('=')
        if ($separator -le 0 -or $separator -ge $entry.Length - 1) {
            Exit-Failure 20 "Invalid quality override '$entry'. Expected CVar=integer."
        }

        $name = $entry.Substring(0, $separator).Trim()
        $value = $entry.Substring($separator + 1).Trim()
        if ($name -notmatch '^(?:gq\.(?:Ind\.)?[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*|r\.GraphicsQuality)$') {
            Exit-Failure 20 "Unsupported quality CVar '$name'. Use gq.*, gq.Ind.*, or r.GraphicsQuality."
        }
        if ($value -notmatch '^-?\d+$') {
            Exit-Failure 20 "Quality CVar '$name' requires an integer value."
        }
        if (-not $seenNames.Add($name)) {
            Exit-Failure 20 "Duplicate quality CVar '$name'."
        }

        [pscustomobject]@{ Name = $name; Value = $value }
    }
}

function Assert-QualityControlsApplied {
    param([string]$LogText)

    foreach ($override in @(Get-QualityCVarOverrides -Text $QualityCVars)) {
        $rejectedText = "Cannot add customized CVar [$($override.Name)]"
        if ($LogText.IndexOf($rejectedText, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Exit-Failure 19 "The packaged build rejected quality override '$($override.Name)'."
        }

        $assignmentPattern = [regex]::Escape("$($override.Name)=$($override.Value)")
        if ($LogText -notmatch "(?im)Priority:2147483647[^\r\n]*$assignmentPattern(?:\s|$)") {
            Exit-Failure 19 "The log did not confirm quality override '$($override.Name)=$($override.Value)'."
        }
    }
}

function Assert-PSOControlsApplied {
    param(
        [string]$LogText,
        [switch]$RequirePSOPrecachingDisabled
    )

    $unsupportedPatterns = @(
        'Command not recognized: Reallink.ProfileMatrix.AddCustomizedCVar',
        'Wrong arguments. Usage: Reallink.ProfileMatrix.AddCustomizedCVar'
    )

    foreach ($pattern in $unsupportedPatterns) {
        if ($LogText.IndexOf($pattern, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Exit-Failure 12 "The packaged build does not support the required ProfileMatrix PSO override: $pattern"
        }
    }

    if ($LogText -match '(?im)Cannot add customized CVar \[(?:r\.PSOPrecaching|r\.ShaderPipelineCache\.(?:BatchMode|BatchSize|BatchTime))\]') {
        Exit-Failure 12 'The packaged build rejected a required ProfileMatrix PSO override.'
    }

    if ($RequirePSOPrecachingDisabled -and $LogText -notmatch '(?im)Priority:2147483647[^\r\n]*r\.PSOPrecaching=0') {
        Exit-Failure 13 'The log did not confirm the max-priority r.PSOPrecaching=0 override.'
    }
}

switch ($Action) {
    'BuildQualityExecCmds' {
        $overrides = @(Get-QualityCVarOverrides -Text $QualityCVars)
        if ($overrides.Count -eq 0) {
            Exit-Failure 20 'QualityCVars is empty.'
        }

        $commands = $overrides | ForEach-Object {
            "Reallink.ProfileMatrix.AddCustomizedCVar $($_.Name) $($_.Value)"
        }
        Write-Output ($commands -join ',')
        exit 0
    }

    'Key' {
        if (-not $ExePath -or -not $ReplayPath) {
            Exit-Failure 2 'Key generation requires ExePath and ReplayPath.'
        }

        $exe = Get-Item -LiteralPath $ExePath
        $replay = Get-Item -LiteralPath $ReplayPath

        try {
            $displayClass = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*'
            $gpuIdentity = (Get-ItemProperty -Path $displayClass -Name DriverVersion, DriverDesc, MatchingDeviceId -ErrorAction Stop |
                Where-Object DriverVersion |
                Sort-Object MatchingDeviceId |
                ForEach-Object { '{0}:{1}:{2}' -f $_.DriverDesc, $_.MatchingDeviceId, $_.DriverVersion }) -join '|'
            if (-not $gpuIdentity) {
                $gpuIdentity = 'GPU_UNKNOWN'
            }
        }
        catch {
            $gpuIdentity = 'GPU_UNKNOWN'
        }

        $normalizedQuality = @(
            @(Get-QualityCVarOverrides -Text $QualityCVars) | Sort-Object Name |
                ForEach-Object { '{0}={1}' -f $_.Name.ToLowerInvariant(), $_.Value }
        )
        if ($normalizedQuality.Count -eq 0) {
            $normalizedQuality = @('DEFAULT')
        }

        $identity = @(
            'APT_PSO_WARMUP_V4'
            $BuildName
            $exe.FullName.ToLowerInvariant()
            $exe.Length
            $exe.LastWriteTimeUtc.Ticks
            $replay.FullName.ToLowerInvariant()
            $replay.Length
            $replay.LastWriteTimeUtc.Ticks
            $MapPath
            $gpuIdentity
            ($normalizedQuality -join ';')
        ) -join "`n"

        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $bytes = [Text.Encoding]::UTF8.GetBytes($identity)
            $hash = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
        }
        finally {
            $sha.Dispose()
        }

        Write-Output $hash.Substring(0, 32)
        exit 0
    }

    'ValidateWarmup' {
        $logText = Read-RunLog
        Assert-PSOControlsApplied -LogText $logText
        Assert-QualityControlsApplied -LogText $logText

        if ($logText -match '(?im)\[PSO Health\].*unhealthy') {
            Exit-Failure 14 'Warmup reported an unhealthy PSO precompile state.'
        }

        if ($RequireCompletion) {
            $completed =
                $logText.IndexOf('Finished, no jobs remaining.', [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                $logText -match '(?im)\[PSO Health\].*Precompile healthy\..*pending=0'

            if (-not $completed) {
                Exit-Failure 15 'Warmup ended before the bundled PSO queue reported completion.'
            }
        }

        Write-Host '[INFO] PSO warmup validation passed.'
        exit 0
    }

    'ValidateCapture' {
        $logText = Read-RunLog
        Assert-PSOControlsApplied -LogText $logText -RequirePSOPrecachingDisabled
        Assert-QualityControlsApplied -LogText $logText

        $pauseMatches = [regex]::Matches(
            $logText,
            'ShaderPipelineCache: (?:Starting paused|Paused Batching\.)',
            [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($pauseMatches.Count -eq 0) {
            Exit-Failure 16 'The capture log did not confirm that ShaderPipelineCache batching was paused.'
        }

        $profilingMarkers = @(
            'Replay is ready. Profiling started',
            'Started creating FPS charts',
            'CSVProfiler Start requested'
        )
        $profilingStart = -1
        foreach ($marker in $profilingMarkers) {
            $index = $logText.IndexOf($marker, [StringComparison]::OrdinalIgnoreCase)
            if ($index -ge 0 -and ($profilingStart -lt 0 -or $index -lt $profilingStart)) {
                $profilingStart = $index
            }
        }

        if ($profilingStart -lt 0) {
            Write-Host '[WARN] No profiling-start marker was found; post-start PSO activity could not be checked.'
            Write-Host '[INFO] PSO capture validation passed with warnings.'
            exit 0
        }

        $profilingEnd = $logText.Length
        foreach ($marker in @('Stopped creating FPS charts', 'AutomatedReplayPerfTest::TeardownTest')) {
            $index = $logText.IndexOf($marker, $profilingStart, [StringComparison]::OrdinalIgnoreCase)
            if ($index -ge 0 -and $index -lt $profilingEnd) {
                $profilingEnd = $index
            }
        }

        $beforeProfiling = $logText.Substring(0, $profilingStart)
        $lastPause = [regex]::Matches(
            $beforeProfiling,
            'ShaderPipelineCache: (?:Starting paused|Paused Batching\.)',
            [Text.RegularExpressions.RegexOptions]::IgnoreCase) |
            Select-Object -Last 1
        $lastResume = [regex]::Matches(
            $beforeProfiling,
            'ShaderPipelineCache: Batching Resumed\.',
            [Text.RegularExpressions.RegexOptions]::IgnoreCase) |
            Select-Object -Last 1

        if (-not $lastPause -or ($lastResume -and $lastResume.Index -gt $lastPause.Index)) {
            Exit-Failure 17 'ShaderPipelineCache was not paused when profiling started.'
        }

        $profilingText = $logText.Substring($profilingStart, $profilingEnd - $profilingStart)
        if ($profilingText -match '(?im)ShaderPipelineCache: Batching Resumed\.|FShaderPipelineCache::BeginNextPrecompileCacheTask') {
            Exit-Failure 18 'Bundled PSO precompile activity overlapped the profiling window.'
        }

        Write-Host '[INFO] PSO capture validation passed.'
        exit 0
    }
}
