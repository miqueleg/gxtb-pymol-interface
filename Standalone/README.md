# PyMOL g-xTB Runner Standalone

The standalone distribution is Windows-native only.

There is intentionally no committed ZIP or installer in this folder. The distributable files are built by GitHub Actions and attached to GitHub Releases.

## For Windows Users

Download the latest release from the repository's **Releases** page:

```text
https://github.com/miqueleg/gxtb-pymol-interface/releases
```

Use one of these release assets:

```text
PyMOL-gxTB-Runner-Windows-Setup.exe
PyMOL-gxTB-Runner-Windows-Portable.zip
```

Then:

```text
Download installer or portable ZIP
Install or unzip
Start "PyMOL-gxTB Runner"
PyMOL opens with the gxtb-pymol plugin already loaded
ASE, Sella, NumPy, SciPy, PyMOL, and g-xTB are already available
```

Users do not need Docker, WSL2, Apptainer, Conda/Mamba, Python, PyMOL, ASE, Sella, NumPy, SciPy, JAX, or g-xTB installed separately.

## For Maintainers

Build documentation is in:

```text
Standalone/WindowsNative/README.md
```

To publish a user-downloadable release, push a version tag:

```bash
git tag v1.0.3
git push origin v1.0.3
```

The **Build Windows Native Standalone** workflow builds the Windows artifacts and attaches them to that GitHub Release. Manual workflow runs also build artifacts, but those are CI artifacts for maintainers, not the normal download path for users.

The old Docker, WSL, Linux-container, macOS tarball, Linux tarball, and legacy Windows ZIP standalone packages have been removed from the repository.
