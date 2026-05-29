param(
    [string]$BundleDir = (Join-Path $PSScriptRoot "..\build\PyMOL-gxTB-Runner"),
    [switch]$SkipPymolCli
)

$ErrorActionPreference = "Stop"
$BundleDir = [System.IO.Path]::GetFullPath($BundleDir)
$HealthCheck = Join-Path $BundleDir "launcher\health_check.cmd"
$PymolExe = Join-Path $BundleDir "app_env\Scripts\pymol.exe"

if (-not (Test-Path $HealthCheck)) {
    throw "Health check script not found: $HealthCheck"
}

Write-Host "Running bundle health check..."
& $HealthCheck
if ($LASTEXITCODE -ne 0) {
    throw "health_check.cmd failed."
}

if (-not $SkipPymolCli) {
    if (-not (Test-Path $PymolExe)) {
        throw "PyMOL executable not found: $PymolExe"
    }

    Write-Host "Running non-GUI PyMOL import smoke test..."
    & $PymolExe -cq -d "python import ase, sella, numpy, scipy; print('imports ok')"
    if ($LASTEXITCODE -ne 0) {
        throw "PyMOL non-GUI import smoke test failed."
    }
}

Write-Host "Smoke test passed."
