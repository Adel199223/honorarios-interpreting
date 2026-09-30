[CmdletBinding()]
param([switch]$Full)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $projectRoot '.venv311\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run scripts/setup_dev_env.ps1 first.' }
function Invoke-Check {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Validation failed (exit $LASTEXITCODE)." }
}
Push-Location $projectRoot
try {
    Invoke-Check $pythonExe @('scripts/check_dev_environment.py')
    Invoke-Check uv @('lock', '--check', '--offline', '--python', $pythonExe, '--no-python-downloads')
    Invoke-Check uv @('pip', 'check', '--python', $pythonExe, '--offline', '--no-python-downloads')
    $expectedExport = (& uv export --locked --no-emit-project --no-header --format requirements-txt --quiet | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Locked requirements export check failed.' }
    $actualExport = (Get-Content -LiteralPath 'requirements.txt' -Raw).Trim()
    if (($actualExport -replace "`r`n", "`n") -ne ($expectedExport -replace "`r`n", "`n")) { throw 'requirements.txt does not match the tracked lock export.' }
    Invoke-Check $pythonExe @('scripts/check_project_docs.py')
    Invoke-Check node @('--check', 'honorarios_app/static/app.js')
    Invoke-Check node @('--check', 'scripts/browser_iab_smoke.mjs')
    # Includes an actual offline installed-wheel test, outside the checkout.
    Invoke-Check $pythonExe @('scripts/run_portable_tests.py')
    if ($Full) {
        foreach ($smokeFlag in @('--source-upload-checks', '--supporting-attachment-checks', '--adapter-contract-checks', '--gmail-api-checks')) {
            Invoke-Check $pythonExe @('scripts/isolated_app_smoke.py', $smokeFlag)
        }
    }
    Write-Host 'Development validation passed.'
} finally { Pop-Location }
