[CmdletBinding()]
param([ValidatePattern('^\.venv[0-9A-Za-z_-]*$')][string]$VenvName = '.venv311', [string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Environment setup failed (exit $LASTEXITCODE)." }
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $VenvName))
if ([IO.Path]::GetDirectoryName($envPath) -ne $projectRoot) { throw 'Environment must belong to this checkout.' }
$uvCommand = Get-Command uv -CommandType Application -ErrorAction Stop | Select-Object -First 1
$uvExe = $uvCommand.Source
$projectText = Get-Content -LiteralPath (Join-Path $projectRoot 'pyproject.toml') -Raw
$uvPin = [regex]::Match($projectText, 'required-version\s*=\s*"==([0-9.]+)"').Groups[1].Value
$uvVersion = (& $uvExe --version).Split(' ')[1]
if ($LASTEXITCODE -ne 0 -or -not $uvPin -or $uvVersion -ne $uvPin) { throw "Install the project's pinned uv $uvPin before setup." }
$nodePin = (Get-Content -LiteralPath (Join-Path $projectRoot '.node-version') -Raw).Trim()
$nodeCommand = Get-Command node -CommandType Application -ErrorAction Stop | Select-Object -First 1
$nodeVersion = (& $nodeCommand.Source --version).Trim().TrimStart('v')
if ($LASTEXITCODE -ne 0 -or $nodeVersion -ne $nodePin) { throw "Install the project's pinned Node $nodePin before setup." }
$pythonPin = (Get-Content -LiteralPath (Join-Path $projectRoot '.python-version') -Raw).Trim()
if ($pythonPin -notmatch '^3\.11\.\d+$') { throw 'Expected an exact Python 3.11 pin.' }
$oldEnv = [Environment]::GetEnvironmentVariable('UV_PROJECT_ENVIRONMENT', 'Process')
Push-Location $projectRoot
try {
    if ($PythonExecutable) {
        $pythonExe = (Resolve-Path -LiteralPath $PythonExecutable).Path
    } else {
        $pythonOutput = @(Invoke-Checked $uvExe @('python', 'find', $pythonPin, '--no-project', '--no-python-downloads'))
        $pythonExe = ($pythonOutput | Select-Object -Last 1).ToString().Trim()
    }
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw 'Pinned Python is not installed.' }
    Invoke-Checked $pythonExe @('-I', '-c', "import sys,xml.dom.minidom,html.entities,ssl,sqlite3,venv; assert sys.version.split()[0] == '$pythonPin'; print('Pinned Python and standard library: ready')")
    Invoke-Checked $uvExe @('lock', '--check', '--offline', '--python', $pythonExe, '--no-python-downloads')
    if (Test-Path -LiteralPath $envPath) {
        $envItem = Get-Item -LiteralPath $envPath -Force
        if (-not $envItem.PSIsContainer -or ($envItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Existing environment must be a regular directory.' }
        $envPython = Join-Path $envPath 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath (Join-Path $envPath 'pyvenv.cfg')) -or -not (Test-Path -LiteralPath $envPython)) { throw 'Existing directory is not a supported environment; it has been preserved.' }
        # Refuse to repair/replace any mismatching existing environment.
        Invoke-Checked $envPython @('scripts/check_dev_environment.py')
    }
    [Environment]::SetEnvironmentVariable('UV_PROJECT_ENVIRONMENT', $envPath, 'Process')
    Invoke-Checked $uvExe @('sync', '--locked', '--extra', 'dev', '--inexact', '--python', $pythonExe, '--no-python-downloads')
    $envPython = Join-Path $envPath 'Scripts\python.exe'
    Invoke-Checked $uvExe @('pip', 'check', '--python', $envPython, '--offline', '--no-python-downloads')
    Invoke-Checked $envPython @('scripts/check_dev_environment.py')
    Write-Host "Setup complete. Use .\$VenvName\Scripts\python.exe for this project."
} finally {
    [Environment]::SetEnvironmentVariable('UV_PROJECT_ENVIRONMENT', $oldEnv, 'Process')
    Pop-Location
}
