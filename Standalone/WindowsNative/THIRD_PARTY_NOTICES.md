# Third-Party Notices

This Windows-native distribution bundles open-source components so end users can run PyMOL g-xTB Runner without installing Python, PyMOL, ASE, Sella, NumPy, SciPy, or g-xTB separately.

Review the license files shipped by each dependency in the bundled conda environment under `app_env/conda-meta/` and package metadata directories. This notice is a summary, not a replacement for the upstream licenses.

## PyMOL Open-Source

The bundle uses the open-source PyMOL package from conda-forge. PyMOL Open-Source is distributed under its upstream open-source license terms. See the package metadata in `app_env/conda-meta/` and the upstream PyMOL project for complete license text.

## ASE

ASE, the Atomic Simulation Environment, is distributed under the GNU LGPL license. See the ASE package metadata in the bundled environment for details.

## Sella

The Windows-native build vendors Sella 2.3.5 source code under `Standalone/WindowsNative/third_party/sella` and installs it locally during the build with `pip install --no-build-isolation --no-deps <path-to-vendored-sella>`. Sella is distributed under the GNU LGPL v3 license. The vendored source includes `LICENSE` and `NOTICE/` files, and the built bundle also carries this source under `third_party/sella`.

## NumPy and SciPy

NumPy and SciPy are distributed under BSD-style licenses. See their package metadata in the bundled environment for complete license text.

## matplotlib

matplotlib is distributed under its upstream open-source license terms. It is included because PyMOL and scientific Python workflows commonly need plotting support.

## g-xTB / xTB

The bundled `xtb.exe` is downloaded from the configured upstream Windows release during the build. See the upstream xTB/g-xTB project and any license files included in the extracted archive for complete terms.

## This Repository

The PyMOL g-xTB Runner plugin files are distributed under this repository's `LICENSE`, which is copied into `LICENSES/REPOSITORY_LICENSE.txt` in the bundle.
