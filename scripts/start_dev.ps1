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
$probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
try { $probe.Start() } catch { throw "Port $Port is occupied. Choose another port; existing apps were left running." } finally { $probe.Stop() }
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run scripts/setup_dev_env.ps1 first.' }
Push-Location $projectRoot
try {
    & $pythonExe scripts/check_dev_environment.py
    if ($LASTEXITCODE -ne 0) { throw 'Environment check failed; launch stopped.' }
    if ($CheckOnly) { Write-Host "Ready to launch LegalPDF Honorarios at http://127.0.0.1:$Port/"; return }
    $launchArgs = @('-m', 'honorarios_app.web', '--host', '127.0.0.1', '--port', "$Port")
    if ($runtimeAbsolute) { $launchArgs += @('--runtime-root', $runtimeAbsolute) }
    if ($Synthetic) { $launchArgs += '--init-synthetic-runtime' }
    Write-Host "LegalPDF Honorarios: http://127.0.0.1:$Port/ (Ctrl+C to stop)"
    & $pythonExe @launchArgs
    if ($LASTEXITCODE -ne 0) { throw "Server exited with code $LASTEXITCODE." }
} finally { Pop-Location }
