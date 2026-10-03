[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port = 8878, [string]$RuntimeRoot, [switch]$Synthetic, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $projectRoot '.venv311\Scripts\python.exe'
if ($Synthetic -and -not $RuntimeRoot) { throw 'Synthetic mode requires an explicit disposable RuntimeRoot.' }
$runtimeAbsolute = $null
if ($RuntimeRoot) {
    if ([IO.Path]::IsPathRooted($RuntimeRoot)) { $runtimeAbsolute = [IO.Path]::GetFullPath($RuntimeRoot) }
    else { $runtimeAbsolute = [IO.Path]::GetFullPath((Join-Path $projectRoot $RuntimeRoot)) }
}
if ($Synthetic) {
    # Fixture initialization must never replace an existing runtime.
    $ancestorPath = $runtimeAbsolute
    while ($ancestorPath) {
        if (Test-Path -LiteralPath $ancestorPath) {
            $ancestorItem = Get-Item -LiteralPath $ancestorPath -Force
            if (-not $ancestorItem.PSIsContainer -or ($ancestorItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Synthetic runtime path must use regular directories, with no links.' }
        }
        $ancestorPath = [IO.Path]::GetDirectoryName($ancestorPath)
    }
    if ((Test-Path -LiteralPath $runtimeAbsolute) -and @(Get-ChildItem -LiteralPath $runtimeAbsolute -Force).Count -gt 0) { throw 'Synthetic runtime must be new or empty. Existing files were preserved.' }
}
$isolateProviderEnvironment = [bool]$Synthetic
if ($runtimeAbsolute -and -not $Synthetic) {
    $markerPath = Join-Path $runtimeAbsolute 'config/synthetic-runtime.local.json'
    if (Test-Path -LiteralPath $markerPath) {
        $markerItem = Get-Item -LiteralPath $markerPath -Force
        if ($markerItem.PSIsContainer -or ($markerItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Synthetic runtime marker must be a regular JSON file.' }
        try { $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json }
        catch { throw 'Synthetic runtime marker is unreadable; launch stopped.' }
        if ($marker.attestation -cne 'honorarios_synthetic_runtime_v1' -or $marker.runtime -cne 'synthetic_isolated' -or
            $marker.isolated_runtime -isnot [bool] -or -not $marker.isolated_runtime -or
            $marker.synthetic_runtime -isnot [bool] -or -not $marker.synthetic_runtime -or
            $marker.send_allowed -isnot [bool] -or $marker.send_allowed -or
            $marker.write_allowed -isnot [bool] -or $marker.write_allowed) { throw 'Synthetic runtime marker is invalid; launch stopped.' }
        $isolateProviderEnvironment = $true
    }
}
$probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
try { $probe.Start() } catch { throw "Port $Port is occupied. Choose another port; existing apps were left running." } finally { $probe.Stop() }
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run scripts/setup_dev_env.ps1 first.' }
Push-Location $projectRoot
$savedEnvironment = @{}
try {
    if ($isolateProviderEnvironment) {
        # Match the portable runner's child boundary. A reopened synthetic
        # runtime must be isolated just like its initial -Synthetic launch.
        foreach ($entry in @(Get-ChildItem Env:)) {
            $name = $entry.Name
            if ($name -in @('OPENAI_API_KEY', 'PYTHONPATH', 'PYTHONHOME') -or
                ($name -match '^(GMAIL_|GOOGLE_|HONORARIOS_)' -and $name -ne 'HONORARIOS_UV_EXECUTABLE')) {
                $savedEnvironment[$name] = $entry.Value
                [Environment]::SetEnvironmentVariable($name, $null, 'Process')
            }
        }
    }
    & $pythonExe scripts/check_dev_environment.py
    if ($LASTEXITCODE -ne 0) { throw 'Environment check failed; launch stopped.' }
    if ($CheckOnly) { Write-Host "Ready to launch LegalPDF Honorarios at http://127.0.0.1:$Port/"; return }
    $launchArgs = @('-m', 'honorarios_app.web', '--host', '127.0.0.1', '--port', "$Port")
    if ($runtimeAbsolute) { $launchArgs += @('--runtime-root', $runtimeAbsolute) }
    if ($Synthetic) { $launchArgs += '--init-synthetic-runtime' }
    Write-Host "LegalPDF Honorarios: http://127.0.0.1:$Port/ (Ctrl+C to stop)"
    & $pythonExe @launchArgs
    if ($LASTEXITCODE -ne 0) { throw "Server exited with code $LASTEXITCODE." }
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    Pop-Location
}
