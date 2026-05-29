param(
    [string]$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path,
    [string]$BuildDir = (Join-Path $PSScriptRoot "..\build"),
    [string]$DistDir = (Join-Path $PSScriptRoot "..\dist"),
    [string]$MicromambaExe = $env:MICROMAMBA_EXE,
    [switch]$SkipEnvironment,
    [switch]$SkipGxtbDownload
)

$ErrorActionPreference = "Stop"

$WindowsNativeDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvironmentFile = Join-Path $WindowsNativeDir "environment-win.yml"
$BundleDir = Join-Path $BuildDir "PyMOL-gxTB-Runner"
$EnvDir = Join-Path $BundleDir "app_env"
$PluginDir = Join-Path $BundleDir "plugin"
$LauncherDir = Join-Path $BundleDir "launcher"
$LicensesDir = Join-Path $BundleDir "LICENSES"
$PortableZip = Join-Path $DistDir "PyMOL-gxTB-Runner-Windows-Portable.zip"
$VendoredSella = Join-Path $WindowsNativeDir "third_party\sella"
$Wheelhouse = Join-Path $WindowsNativeDir "wheelhouse"

function New-CleanDirectory {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item -Recurse -Force $Path
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Get-Micromamba {
    if (-not [string]::IsNullOrWhiteSpace($MicromambaExe)) {
        return $MicromambaExe
    }

    $found = Get-Command micromamba.exe -ErrorAction SilentlyContinue
    if ($found) {
        return $found.Source
    }

    $downloadDir = Join-Path $BuildDir "tools"
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    $archive = Join-Path $downloadDir "micromamba.tar.bz2"
    $extractDir = Join-Path $downloadDir "micromamba"
    $exe = Join-Path $extractDir "Library\bin\micromamba.exe"

    if (-not (Test-Path $exe)) {
        Write-Host "Downloading micromamba for Windows..."
        Invoke-WebRequest -Uri "https://micro.mamba.pm/api/micromamba/win-64/latest" -OutFile $archive
        New-CleanDirectory -Path $extractDir
        tar.exe -xjf $archive -C $extractDir
    }

    if (-not (Test-Path $exe)) {
        throw "micromamba.exe was not found after download."
    }
    return $exe
}

New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
New-CleanDirectory -Path $BundleDir

if (-not $SkipEnvironment) {
    $mamba = Get-Micromamba
    Write-Host "Creating bundled environment at $EnvDir"
    & $mamba create -y -p $EnvDir -f $EnvironmentFile
    if ($LASTEXITCODE -ne 0) {
        throw "micromamba failed to create the bundled environment."
    }

    & (Join-Path $EnvDir "python.exe") -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip upgrade failed."
    }

    if (Test-Path (Join-Path $VendoredSella "setup.py")) {
        Write-Host "Installing Sella from vendored source: $VendoredSella"
        & (Join-Path $EnvDir "python.exe") -m pip install --no-build-isolation --no-deps $VendoredSella
    } elseif (Test-Path $Wheelhouse) {
        Write-Host "Installing Sella from local wheelhouse if available."
        & (Join-Path $EnvDir "python.exe") -m pip install --no-index --find-links $Wheelhouse sella
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Local wheelhouse Sella install failed; trying normal pip install."
            & (Join-Path $EnvDir "python.exe") -m pip install sella
        }
    } else {
        & (Join-Path $EnvDir "python.exe") -m pip install sella
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Sella could not be installed. Add Windows-compatible wheels to Standalone/WindowsNative/wheelhouse or set up a working pip source."
    }
}

if ($SkipEnvironment -and -not (Test-Path (Join-Path $EnvDir "python.exe"))) {
    throw "SkipEnvironment was set but $EnvDir does not contain python.exe."
}

if (-not $SkipGxtbDownload) {
    & (Join-Path $WindowsNativeDir "scripts\download_gxtb_windows.ps1") -Destination (Join-Path $BuildDir "gxtb")
    if ($LASTEXITCODE -ne 0) {
        throw "g-xTB/xTB download failed."
    }
}

Copy-Item -Path (Join-Path $BuildDir "gxtb") -Destination (Join-Path $BundleDir "gxtb") -Recurse -Force

New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
Copy-Item -Path (Join-Path $RootDir "pymol_gxtb_plugin.py") -Destination $PluginDir -Force
Copy-Item -Path (Join-Path $RootDir "pymol_gxtb_plugin_public_v1_0_2.py") -Destination $PluginDir -Force
Copy-Item -Path (Join-Path $RootDir "Pymol_CM_creation.py") -Destination $PluginDir -Force

if (Test-Path $VendoredSella) {
    New-Item -ItemType Directory -Force -Path (Join-Path $BundleDir "third_party") | Out-Null
    Copy-Item -Path $VendoredSella -Destination (Join-Path $BundleDir "third_party\sella") -Recurse -Force
}

$loader = @'
import importlib.util
import os
import sys
import sysconfig
import traceback
from pathlib import Path

def _resolve_plugin_dir():
    env_dir = os.environ.get("PYMOL_GXTB_PLUGIN_DIR", "").strip()
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir))
    file_value = globals().get("__file__")
    if file_value:
        candidates.append(Path(file_value).resolve().parent)
    if getattr(sys, "prefix", None):
        candidates.append(Path(sys.prefix).resolve().parent / "plugin")
    if getattr(sys, "executable", None):
        candidates.append(Path(sys.executable).resolve().parent.parent / "plugin")
    candidates.append(Path.cwd())

    for candidate in candidates:
        try:
            if (candidate / "pymol_gxtb_plugin.py").is_file():
                return candidate
        except Exception:
            pass
    raise FileNotFoundError(
        "Could not locate pymol_gxtb_plugin.py. Set PYMOL_GXTB_PLUGIN_DIR "
        "to the bundle plugin directory."
    )

def _preload_stdlib_cmd():
    """Ensure JAX imports Python stdlib cmd, not pymol/cmd.py as top-level cmd."""
    existing = sys.modules.get("cmd")
    existing_file = str(getattr(existing, "__file__", "")) if existing else ""
    if existing and "pymol" not in existing_file.lower():
        return

    stdlib = Path(sysconfig.get_path("stdlib"))
    cmd_py = stdlib / "cmd.py"
    if not cmd_py.is_file():
        return

    spec = importlib.util.spec_from_file_location("cmd", cmd_py)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cmd"] = module
    spec.loader.exec_module(module)

plugin_dir = _resolve_plugin_dir()
app_dir = plugin_dir.parent
xtb_path = app_dir / "gxtb" / "bin" / "xtb.exe"
python_path = app_dir / "app_env" / "python.exe"

os.environ.setdefault("PYMOL_GXTB_XTB_PATH", str(xtb_path))
os.environ.setdefault("PYMOL_GXTB_ASE_PYTHON", str(python_path))
os.environ.setdefault("PYMOL_GXTB_PLUGIN_DIR", str(plugin_dir))

plugin_dir_text = str(plugin_dir)
if plugin_dir_text not in sys.path:
    sys.path.insert(0, plugin_dir_text)
_preload_stdlib_cmd()

try:
    from pymol import cmd
    import pymol_gxtb_plugin
    import sella

    cmd.extend("gxtb_runner", pymol_gxtb_plugin.run_plugin_gui)
    try:
        pymol_gxtb_plugin.__init_plugin__(None)
    except Exception:
        print("Warning: PyMOL menu registration failed; the gxtb_runner command is still available.")
        traceback.print_exc()
    if os.environ.get("PYMOL_GXTB_AUTO_OPEN", "").strip() == "1":
        try:
            from pymol.Qt import QtCore
            QtCore.QTimer.singleShot(500, pymol_gxtb_plugin.run_plugin_gui)
        except Exception:
            print("Warning: automatic plugin dialog open failed; use Plugin > PyMOL g-xTB Runner or command gxtb_runner.")
            traceback.print_exc()
    print("PyMOL g-xTB Runner plugin loaded from", plugin_dir)
    print("Bundled xTB path:", os.environ["PYMOL_GXTB_XTB_PATH"])
except Exception:
    print("Failed to load PyMOL g-xTB Runner plugin from", plugin_dir)
    traceback.print_exc()
    raise
'@
Set-Content -Path (Join-Path $PluginDir "load_plugin.py") -Value $loader -Encoding UTF8

New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null
Copy-Item -Path (Join-Path $WindowsNativeDir "launcher\*") -Destination $LauncherDir -Recurse -Force

New-Item -ItemType Directory -Force -Path $LicensesDir | Out-Null
Copy-Item -Path (Join-Path $RootDir "LICENSE") -Destination (Join-Path $LicensesDir "REPOSITORY_LICENSE.txt") -Force
Copy-Item -Path (Join-Path $WindowsNativeDir "THIRD_PARTY_NOTICES.md") -Destination $LicensesDir -Force
if (Test-Path (Join-Path $BundleDir "gxtb\licenses")) {
    Copy-Item -Path (Join-Path $BundleDir "gxtb\licenses\*") -Destination $LicensesDir -Force
}
if (Test-Path (Join-Path $VendoredSella "LICENSE")) {
    Copy-Item -Path (Join-Path $VendoredSella "LICENSE") -Destination (Join-Path $LicensesDir "SELLA_LICENSE.txt") -Force
}

$readmeFirst = @"
PyMOL-gxTB Runner for Windows
=============================

Double-click launcher\Start-PyMOL-gxTB.cmd to start PyMOL with the g-xTB plugin loaded.

Run launcher\health_check.cmd if PyMOL does not start or the plugin cannot find dependencies.

This bundle is self-contained. Users do not need Docker, WSL, Apptainer, Conda, Python, PyMOL, ASE, Sella, NumPy, SciPy, JAX, or g-xTB installed separately.
"@
Set-Content -Path (Join-Path $BundleDir "README_FIRST.txt") -Value $readmeFirst -Encoding UTF8

& (Join-Path $WindowsNativeDir "scripts\smoke_test_bundle.ps1") -BundleDir $BundleDir
if ($LASTEXITCODE -ne 0) {
    throw "Bundle smoke test failed."
}

if (Test-Path $PortableZip) {
    Remove-Item -Force $PortableZip
}
Compress-Archive -Path $BundleDir -DestinationPath $PortableZip -Force

Write-Host "Portable ZIP created:"
Write-Host $PortableZip
