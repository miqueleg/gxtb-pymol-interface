# Windows-Native Standalone Build

This directory builds a native Windows distribution of PyMOL g-xTB Runner. The output is a portable ZIP and, when Inno Setup is available, a Windows installer:

```text
dist/
  PyMOL-gxTB-Runner-Windows-Portable.zip
  PyMOL-gxTB-Runner-Windows-Setup.exe
```

The installed or unzipped application contains its own Windows Python environment, Open-Source PyMOL, NumPy, SciPy, ASE, Sella, matplotlib, and a downloaded Windows `xtb.exe` with its required DLLs. End users do not need Docker, WSL2, Apptainer, Conda/Mamba, Python, PyMOL, ASE, Sella, NumPy, SciPy, or g-xTB installed separately.

The ZIP and installer are generated outputs. They are not committed to the repository. For normal users, publish them through GitHub Releases by pushing a version tag.

Sella 2.3.5 source code is vendored in this repository under:

```text
Standalone/WindowsNative/third_party/sella/
```

The build installs Sella from that local source tree with `pip install --no-build-isolation --no-deps`, so the builder does not depend on cloning the Sella Git repository or resolving the Sella package from PyPI. Sella runtime dependencies are declared in `environment-win.yml`.

## Build Locally on Windows

Requirements for builders only:

- Windows 10 or newer, x64.
- PowerShell.
- Internet access for micromamba, conda-forge packages, pip packages, and the xTB/g-xTB release archive.
- Inno Setup 6 if you want the installer EXE.

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\Standalone\WindowsNative\scripts\build_portable.ps1
```

Build the installer after the portable bundle exists:

```powershell
powershell -ExecutionPolicy Bypass -File .\Standalone\WindowsNative\scripts\build_installer.ps1
```

To pin or override the xTB/g-xTB download, set one of these before running `build_portable.ps1`:

```powershell
$env:XTB_WINDOWS_VERSION = "v6.7.1"
$env:XTB_WINDOWS_URL = "https://example.invalid/path/to/windows-xtb.zip"
```

`XTB_WINDOWS_URL` is the most reproducible option. If it is not set, `download_gxtb_windows.ps1` queries `grimme-lab/xtb` releases and selects the first Windows-looking archive asset.

## Build with GitHub Actions

Run the workflow named **Build Windows Native Standalone** from the GitHub Actions tab. It can also run on pushes that touch this directory or the workflow file.

The workflow runs on `windows-latest`, builds the portable ZIP, attempts the Inno Setup installer, and uploads both artifacts when available. If Inno Setup fails, the workflow still uploads the portable ZIP and adds a clear warning.

## Publish a Release for Users

From a clean local checkout, commit the changes and push a version tag:

```bash
git tag v1.0.3
git push origin v1.0.3
```

When the tag workflow finishes, GitHub Releases will contain:

```text
PyMOL-gxTB-Runner-Windows-Portable.zip
PyMOL-gxTB-Runner-Windows-Setup.exe
```

Users should download from:

```text
https://github.com/miqueleg/gxtb-pymol-interface/releases
```

## Download CI Artifacts for Testing

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Select **Build Windows Native Standalone**.
4. Open the completed run.
5. Download `PyMOL-gxTB-Runner-Windows-Portable` or `PyMOL-gxTB-Runner-Windows-Setup`.

These CI artifacts are useful for maintainers testing a build. GitHub Releases are the intended download path for final users.

## Normal Windows User Workflow

Portable ZIP:

1. Download `PyMOL-gxTB-Runner-Windows-Portable.zip`.
2. Extract it.
3. Double-click `PyMOL-gxTB-Runner\launcher\Start-PyMOL-gxTB.cmd`.

Installer:

1. Download `PyMOL-gxTB-Runner-Windows-Setup.exe`.
2. Run the installer.
3. Start **PyMOL-gxTB Runner** from the Start menu or desktop shortcut.

The launcher sets:

```bat
PYMOL_GXTB_XTB_PATH=<app>\gxtb\bin\xtb.exe
PYMOL_GXTB_ASE_PYTHON=<app>\app_env\python.exe
```

It also prepends the bundled g-xTB and Python environment directories to `PATH` before starting PyMOL with `plugin\load_plugin.py`.

## Troubleshooting

### PyMOL does not start

Run:

```bat
PyMOL-gxTB-Runner\launcher\health_check.cmd
```

If PyMOL is missing, the bundled environment was not created correctly. Rebuild the portable ZIP and check the GitHub Actions log around the micromamba environment creation step.

### g-xTB not found

Run `launcher\health_check.cmd`. If it reports that `xtb.exe` is missing, the xTB/g-xTB archive did not download or did not contain a Windows `xtb.exe`. Rebuild with a known-good URL:

```powershell
$env:XTB_WINDOWS_URL = "https://example.invalid/path/to/windows-xtb.zip"
powershell -ExecutionPolicy Bypass -File .\Standalone\WindowsNative\scripts\build_portable.ps1
```

### Sella import fails

The build installs Sella from the vendored source directory:

```text
Standalone/WindowsNative/third_party/sella/
```

using:

```bat
python -m pip install --no-build-isolation --no-deps Standalone\WindowsNative\third_party\sella
```

If Sella import still fails, check that `jax` and `jaxlib` installed correctly in the bundled environment. The vendored source avoids cloning or downloading Sella itself, but Sella's runtime dependencies still have to be present in the build environment. The portable ZIP is not valid for ASE/Sella workflows unless `health_check.cmd` reports `[OK] Sella import works`.

### Antivirus blocks the installer

The installer is generated by Inno Setup in CI and is not code-signed by default. Some antivirus products flag unsigned installers. Use the portable ZIP if needed, or sign the installer in your release process.

## Why This Does Not Use Docker or WSL

This distribution is for Windows users who need a normal double-click application. Docker, WSL, Apptainer, and Linux containers add separate runtime requirements and do not integrate cleanly with a native PyMOL GUI. The build may use micromamba on Windows to assemble the environment, but the final ZIP and installer are self-contained and do not require conda or mamba on the user's machine.
