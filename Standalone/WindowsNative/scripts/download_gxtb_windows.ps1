param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\build\gxtb"),
    [string]$XtbVersion = $env:XTB_WINDOWS_VERSION,
    [string]$XtbUrl = $env:XTB_WINDOWS_URL
)

$ErrorActionPreference = "Stop"

# The g-xTB functionality is exposed through recent xTB builds as xtb.exe.
# Prefer an explicit URL for reproducible builds. If XTB_WINDOWS_URL is not
# set, the script queries the configured GitHub release and chooses a Windows
# archive asset containing "windows", "win", or "mingw" in its name.
$Repo = "grimme-lab/xtb"
$AssetNamePattern = "(?i)(windows|win|mingw).*\.(zip|7z|tar\.xz|tar\.gz)$"

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
            throw "Cannot extract '$Archive'. Install 7-Zip or provide a .zip/.tar.* g-xTB/xTB archive."
        }
        & $sevenZip.Source x "-o$Target" $Archive -y
        if ($LASTEXITCODE -ne 0) {
            throw "7z.exe failed to extract '$Archive'."
        }
        return
    }

    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if (-not $tar) {
        throw "Cannot extract '$Archive'. Install tar.exe support or provide a .zip g-xTB/xTB archive."
    }

    & $tar.Source -xf $Archive -C $Target
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe failed to extract '$Archive'."
    }
}

function Get-GitHubAssetUrl {
    if ([string]::IsNullOrWhiteSpace($XtbVersion)) {
        $api = "https://api.github.com/repos/$Repo/releases/latest"
    } else {
        $api = "https://api.github.com/repos/$Repo/releases/tags/$XtbVersion"
    }

    Write-Host "Resolving Windows xTB asset from $api"
    $release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "PyMOL-gxTB-Runner-WindowsNative" }
    $asset = $release.assets | Where-Object { $_.name -match $AssetNamePattern } | Select-Object -First 1
    if (-not $asset) {
        $names = ($release.assets | ForEach-Object { $_.name }) -join ", "
        throw "Could not find a Windows xTB asset in release '$($release.tag_name)'. Set XTB_WINDOWS_URL explicitly. Assets: $names"
    }

    Write-Host "Selected asset: $($asset.name)"
    return $asset.browser_download_url
}

$Destination = [System.IO.Path]::GetFullPath($Destination)
$BuildRoot = Split-Path -Parent $Destination
$DownloadDir = Join-Path $BuildRoot "downloads"
$ExtractDir = Join-Path $BuildRoot "gxtb_extract"

New-CleanDirectory -Path $Destination
New-CleanDirectory -Path $DownloadDir
New-CleanDirectory -Path $ExtractDir

if ([string]::IsNullOrWhiteSpace($XtbUrl)) {
    $XtbUrl = Get-GitHubAssetUrl
}

$archiveName = Split-Path -Leaf ([System.Uri]$XtbUrl).AbsolutePath
if ([string]::IsNullOrWhiteSpace($archiveName)) {
    $archiveName = "xtb-windows.zip"
}
$archive = Join-Path $DownloadDir $archiveName

Write-Host "Downloading xTB/g-xTB Windows archive:"
Write-Host "  $XtbUrl"
Invoke-WebRequest -Uri $XtbUrl -OutFile $archive

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

Write-Host "xTB/g-xTB installed at $binDest"
& (Join-Path $binDest "xtb.exe") --version
