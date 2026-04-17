param(
    [string]$PythonPath = ".collector-venv\Scripts\python.exe",
    [string]$TesseractPath = "C:\Program Files\Tesseract-OCR\tesseract.exe",
    [string]$FixtureDir = "collector\tests\fixtures\blue_archive",
    [double]$MinFieldAccuracy = 0.9
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
$ResolvedTesseractPath = Resolve-RepoPath $TesseractPath
$ResolvedFixtureDir = Resolve-RepoPath $FixtureDir

foreach ($RequiredPath in @(
    $ResolvedPythonPath,
    $ResolvedTesseractPath,
    $ResolvedFixtureDir
)) {
    if (-not (Test-Path $RequiredPath)) {
        throw "필수 경로를 찾을 수 없습니다: $RequiredPath"
    }
}

Write-Host "Evaluating Blue Archive OCR fixtures..."
Write-Host "Python:      $ResolvedPythonPath"
Write-Host "Tesseract:   $ResolvedTesseractPath"
Write-Host "FixtureDir:  $ResolvedFixtureDir"
Write-Host "MinAccuracy: $MinFieldAccuracy"

& $ResolvedPythonPath `
    collector\evaluate_blue_archive_fixtures.py `
    --fixture-dir $ResolvedFixtureDir `
    --ocr-command $ResolvedTesseractPath `
    --min-field-accuracy $MinFieldAccuracy
