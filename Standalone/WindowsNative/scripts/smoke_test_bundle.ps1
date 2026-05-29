param(
    [string]$BundleDir = (Join-Path $PSScriptRoot "..\build\PyMOL-gxTB-Runner"),
    [switch]$SkipPymolCli
)

$ErrorActionPreference = "Stop"
$BundleDir = [System.IO.Path]::GetFullPath($BundleDir)
$HealthCheck = Join-Path $BundleDir "launcher\health_check.cmd"
$PythonExe = Join-Path $BundleDir "app_env\python.exe"
$PluginDir = Join-Path $BundleDir "plugin"

if (-not (Test-Path $HealthCheck)) {
    throw "Health check script not found: $HealthCheck"
}

Write-Host "Running bundle health check..."
& $HealthCheck
if ($LASTEXITCODE -ne 0) {
    throw "health_check.cmd failed."
}

if (-not $SkipPymolCli) {
    if (-not (Test-Path $PythonExe)) {
        throw "Python executable not found: $PythonExe"
    }

    $env:PYMOL_GXTB_PLUGIN_DIR = $PluginDir
    $env:PYMOL_GXTB_XTB_PATH = Join-Path $BundleDir "gxtb\bin\xtb.exe"
    $env:PYMOL_GXTB_ASE_PYTHON = $PythonExe
    $env:PYTHONNOUSERSITE = "1"

    Write-Host "Running non-GUI PyMOL import smoke test..."
    & $PythonExe -m pymol -cq -d "python import ase, sella, numpy, scipy, jax, jaxlib, matplotlib; print('imports ok')"
    if ($LASTEXITCODE -ne 0) {
        throw "PyMOL non-GUI import smoke test failed."
    }

    $pluginLoader = Join-Path $BundleDir "plugin\load_plugin.py"
    Write-Host "Running non-GUI PyMOL plugin-loader smoke test..."
    & $PythonExe -m pymol -cq -r $pluginLoader -d "python import sella, jax, jaxlib; print('sella ok after plugin load')"
    if ($LASTEXITCODE -ne 0) {
        throw "PyMOL plugin-loader smoke test failed."
    }
}

Write-Host "Smoke test passed."
