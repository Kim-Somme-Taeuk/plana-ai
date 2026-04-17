param(
    [string]$PythonLauncher = "py -3.12",
    [string]$VenvDir = ".collector-build-venv"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $RepoRoot $VenvDir
$RequirementsPath = Join-Path $RepoRoot ".requirements.collector-build.txt"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Push-Location $RepoRoot
    try {
        Invoke-Expression "$PythonLauncher -m venv `"$VenvPath`""
    }
    finally {
        Pop-Location
    }
}

$WindowsRequirements = Get-Content (Join-Path $RepoRoot "backend\requirements.txt") |
    Where-Object { $_ -notmatch '^uvloop==' }
$WindowsRequirements + "pyinstaller==6.16.0" | Set-Content $RequirementsPath

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r $RequirementsPath

Push-Location $RepoRoot
try {
    & $PythonExe -m PyInstaller --clean --noconfirm collector\plana_collector.spec
}
finally {
    Pop-Location
}

Write-Host "Build complete: dist\plana-collector.exe"
