param(
    [string]$DeviceSerial = "emulator-5554",
    [string]$RequestPath = "collector\adb_data\sample_request.json",
    [string]$PythonPath = ".collector-venv\Scripts\python.exe",
    [string]$AdbPath = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
    [string]$TesseractPath = "C:\Program Files\Tesseract-OCR\tesseract.exe",
    [string]$OutputDir = "",
    [switch]$ResumeOnly,
    [switch]$ForceRecapture
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-RepoPath {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $PathValue
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }
    return (Join-Path $RepoRoot $PathValue)
}

$ResolvedPythonPath = Resolve-RepoPath $PythonPath
$ResolvedRequestPath = Resolve-RepoPath $RequestPath
$ResolvedAdbPath = Resolve-RepoPath $AdbPath
$ResolvedTesseractPath = Resolve-RepoPath $TesseractPath

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $ResolvedOutputDir = Join-Path $RepoRoot "collector\capture_runs\win_run_$Timestamp"
} else {
    $ResolvedOutputDir = Resolve-RepoPath $OutputDir
}

foreach ($RequiredPath in @(
    $ResolvedPythonPath,
    $ResolvedRequestPath,
    $ResolvedAdbPath,
    $ResolvedTesseractPath
)) {
    if (-not (Test-Path $RequiredPath)) {
        throw "필수 경로를 찾을 수 없습니다: $RequiredPath"
    }
}

$CommandArgs = @(
    "collector\run_capture_pipeline.py",
    "--output-dir", $ResolvedOutputDir,
    "--device-serial", $DeviceSerial,
    "--adb-command", $ResolvedAdbPath,
    "--ocr-command", $ResolvedTesseractPath
)

if ($ResumeOnly) {
    $CommandArgs += "--resume-only"
}
if ($ForceRecapture) {
    $CommandArgs += "--force-recapture"
}

$CommandArgs += $ResolvedRequestPath

Write-Host "Running collector pipeline..."
Write-Host "Python:      $ResolvedPythonPath"
Write-Host "ADB:         $ResolvedAdbPath"
Write-Host "Tesseract:   $ResolvedTesseractPath"
Write-Host "Device:      $DeviceSerial"
Write-Host "Request:     $ResolvedRequestPath"
Write-Host "OutputDir:   $ResolvedOutputDir"

& $ResolvedPythonPath @CommandArgs
