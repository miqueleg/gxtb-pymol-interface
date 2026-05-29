param(
    [string]$WindowsNativeDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$InnoSetupCompiler = $env:ISCC_EXE
)

$ErrorActionPreference = "Stop"

$BuildDir = Join-Path $WindowsNativeDir "build"
$DistDir = Join-Path $WindowsNativeDir "dist"
$BundleDir = Join-Path $BuildDir "PyMOL-gxTB-Runner"
$IssFile = Join-Path $WindowsNativeDir "installer\pymol-gxtb-runner.iss"
$OutputExe = Join-Path $DistDir "PyMOL-gxTB-Runner-Windows-Setup.exe"

if (-not (Test-Path $BundleDir)) {
    throw "Bundle directory does not exist. Run scripts\build_portable.ps1 first: $BundleDir"
}

if ([string]::IsNullOrWhiteSpace($InnoSetupCompiler)) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $InnoSetupCompiler = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if ([string]::IsNullOrWhiteSpace($InnoSetupCompiler) -or -not (Test-Path $InnoSetupCompiler)) {
    throw "Inno Setup compiler not found. Install Inno Setup 6 or set ISCC_EXE to ISCC.exe."
}

New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
if (Test-Path $OutputExe) {
    Remove-Item -Force $OutputExe
}

& $InnoSetupCompiler "/DBundleDir=$BundleDir" "/DOutputDir=$DistDir" $IssFile
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed."
}

if (-not (Test-Path $OutputExe)) {
    throw "Installer was not produced: $OutputExe"
}

Write-Host "Installer created:"
Write-Host $OutputExe
