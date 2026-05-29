param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\build\gxtb"),
    [string]$GxtbVersion = $(if ($env:GXTB_WINDOWS_VERSION) { $env:GXTB_WINDOWS_VERSION } else { "2.0.1" }),
    [string]$GxtbUrl = $(if ($env:GXTB_WINDOWS_URL) { $env:GXTB_WINDOWS_URL } else { "https://github.com/grimme-lab/g-xtb/raw/refs/heads/main/binaries/xtb-6.7.1-gxtb-140526-windows-x86_64.zip" }),
    [string]$GxtbSha256 = $(if ($env:GXTB_WINDOWS_SHA256) { $env:GXTB_WINDOWS_SHA256 } else { "fa6d6491b38d895196e2312c6ce34b74e60cd974f9c01da6c3ee567b3ca41830" })
)

$ErrorActionPreference = "Stop"

# g-xTB 2.0.1 is distributed by grimme-lab/g-xtb as a modified xtb 6.7.1
# executable plus required DLLs. Keep the URL and SHA configurable, but default
# to the pinned Windows archive used for this standalone distribution.

function New-CleanDirectory {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item -Recurse -Force $Path
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Expand-ArchiveByExtension {
    param(
        [string]$Archive,
        [string]$Target
    )

    if ($Archive -match "\.zip$") {
        Expand-Archive -Path $Archive -DestinationPath $Target -Force
        return
    }

    if ($Archive -match "\.7z$") {
        $sevenZip = Get-Command 7z.exe -ErrorAction SilentlyContinue
        if (-not $sevenZip) {
            throw "Cannot extract '$Archive'. Install 7-Zip or provide a .zip/.tar.* g-xTB archive."
        }
        & $sevenZip.Source x "-o$Target" $Archive -y
        if ($LASTEXITCODE -ne 0) {
            throw "7z.exe failed to extract '$Archive'."
        }
        return
    }

    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if (-not $tar) {
        throw "Cannot extract '$Archive'. Install tar.exe support or provide a .zip g-xTB archive."
    }

    & $tar.Source -xf $Archive -C $Target
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe failed to extract '$Archive'."
    }
}

$Destination = [System.IO.Path]::GetFullPath($Destination)
$BuildRoot = Split-Path -Parent $Destination
$DownloadDir = Join-Path $BuildRoot "downloads"
$ExtractDir = Join-Path $BuildRoot "gxtb_extract"

New-CleanDirectory -Path $Destination
New-CleanDirectory -Path $DownloadDir
New-CleanDirectory -Path $ExtractDir

if ([string]::IsNullOrWhiteSpace($GxtbUrl)) {
    throw "GXTB_WINDOWS_URL is empty. Set it to a Windows g-xTB archive containing xtb.exe."
}

$archiveName = Split-Path -Leaf ([System.Uri]$GxtbUrl).AbsolutePath
if ([string]::IsNullOrWhiteSpace($archiveName)) {
    $archiveName = "gxtb-windows.zip"
}
$archive = Join-Path $DownloadDir $archiveName

Write-Host "Downloading g-xTB $GxtbVersion Windows archive:"
Write-Host "  $GxtbUrl"
Invoke-WebRequest -Uri $GxtbUrl -OutFile $archive

if (-not [string]::IsNullOrWhiteSpace($GxtbSha256)) {
    $actualSha256 = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash.ToLowerInvariant()
    $expectedSha256 = $GxtbSha256.Trim().ToLowerInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "SHA256 mismatch for '$archiveName'. Expected $expectedSha256 but got $actualSha256."
    }
    Write-Host "SHA256 verified: $actualSha256"
}

Expand-ArchiveByExtension -Archive $archive -Target $ExtractDir

$xtb = Get-ChildItem -Path $ExtractDir -Recurse -File -Filter "xtb.exe" | Select-Object -First 1
if (-not $xtb) {
    throw "Downloaded archive did not contain xtb.exe."
}

$binSource = $xtb.Directory.FullName
$binDest = Join-Path $Destination "bin"
New-Item -ItemType Directory -Force -Path $binDest | Out-Null
Copy-Item -Path (Join-Path $binSource "*") -Destination $binDest -Recurse -Force

$licenseFiles = Get-ChildItem -Path $ExtractDir -Recurse -File | Where-Object {
    $_.Name -match "(?i)^(license|copying|notice|readme)"
}
if ($licenseFiles) {
    $licenseDest = Join-Path $Destination "licenses"
    New-Item -ItemType Directory -Force -Path $licenseDest | Out-Null
    $licenseFiles | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $licenseDest $_.Name) -Force
    }
}

Write-Host "g-xTB installed at $binDest"
& (Join-Path $binDest "xtb.exe") --version
if ($LASTEXITCODE -ne 0) {
    throw "xtb.exe --version failed."
}

$helpText = & (Join-Path $binDest "xtb.exe") --help
if ($LASTEXITCODE -ne 0 -or -not ($helpText -match "gxtb")) {
    throw "The downloaded xtb.exe help output did not advertise g-xTB support."
}
Write-Host "g-xTB support verified in xtb.exe --help."
