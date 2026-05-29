# PyMOL g-xTB Runner Standalone Builds

The standalone distribution is now Windows-native only.

Use:

```text
Standalone/WindowsNative/
```

The old Docker, WSL, Linux-container, macOS tarball, Linux tarball, and legacy Windows ZIP standalone packages have been removed from the repository.

## Current Output

The Windows-native build creates:

```text
Standalone/WindowsNative/dist/
  PyMOL-gxTB-Runner-Windows-Portable.zip
  PyMOL-gxTB-Runner-Windows-Setup.exe
```

The final Windows user experience is:

```text
Download installer or portable ZIP
Install or unzip
Double-click "PyMOL-gxTB Runner"
PyMOL opens with the gxtb-pymol plugin already loaded
ASE, Sella, NumPy, SciPy, PyMOL, and g-xTB are already available
```

Users do not need Docker, WSL2, Apptainer, Conda/Mamba, Python, PyMOL, ASE, Sella, NumPy, SciPy, or g-xTB installed separately.

## Build Documentation

See:

```text
Standalone/WindowsNative/README.md
```

## GitHub Actions

Run the workflow:

```text
Build Windows Native Standalone
```

The workflow uploads the portable ZIP and, when Inno Setup succeeds, the installer EXE.
