@echo off
setlocal EnableExtensions

set "LAUNCHER_DIR=%~dp0"
for %%I in ("%LAUNCHER_DIR%..") do set "APPDIR=%%~fI"

set "ENV_DIR=%APPDIR%\app_env"
set "GXTB_DIR=%APPDIR%\gxtb\bin"
set "PLUGIN_FILE=%APPDIR%\plugin\pymol_gxtb_plugin.py"
set "PLUGIN_LOADER=%APPDIR%\plugin\load_plugin.py"

set "PATH=%GXTB_DIR%;%ENV_DIR%;%ENV_DIR%\Scripts;%ENV_DIR%\Library\bin;%PATH%"
set "PYMOL_GXTB_XTB_PATH=%GXTB_DIR%\xtb.exe"
set "PYMOL_GXTB_ASE_PYTHON=%ENV_DIR%\python.exe"
set "PYTHONNOUSERSITE=1"

if exist "%ENV_DIR%\python.exe" (
  echo [OK] Python found
) else (
  echo [ERROR] Python not found: "%ENV_DIR%\python.exe"
  exit /b 1
)

if exist "%ENV_DIR%\python.exe" (
  "%ENV_DIR%\python.exe" -c "import pymol; print('[OK] PyMOL Python module import works')" || exit /b 1
) else (
  echo [ERROR] Bundled Python not found: "%ENV_DIR%\python.exe"
  exit /b 1
)

if exist "%GXTB_DIR%\xtb.exe" (
  echo [OK] g-xTB found
) else (
  echo [ERROR] g-xTB executable not found: "%GXTB_DIR%\xtb.exe"
  exit /b 1
)

"%GXTB_DIR%\xtb.exe" --version >nul 2>nul || (
  echo [ERROR] g-xTB executable failed to run: "%GXTB_DIR%\xtb.exe"
  exit /b 1
)
echo [OK] g-xTB executable runs

"%GXTB_DIR%\xtb.exe" --help | findstr /i "gxtb" >nul || (
  echo [ERROR] bundled xtb.exe does not appear to support --gxtb
  exit /b 1
)
echo [OK] g-xTB support advertised

if exist "%PLUGIN_FILE%" (
  echo [OK] Plugin found
) else (
  echo [ERROR] Plugin file not found: "%PLUGIN_FILE%"
  exit /b 1
)

if exist "%PLUGIN_LOADER%" (
  echo [OK] Plugin loader found
) else (
  echo [ERROR] Plugin loader not found: "%PLUGIN_LOADER%"
  exit /b 1
)

"%ENV_DIR%\python.exe" -c "import numpy; print('[OK] NumPy import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import scipy; print('[OK] SciPy import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import ase; print('[OK] ASE import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import sella; print('[OK] Sella import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import jax, jaxlib; print('[OK] JAX/JAXlib import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import matplotlib; print('[OK] matplotlib import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import sys; sys.path.insert(0, r'%APPDIR%\plugin'); import pymol_gxtb_plugin; print('[OK] Plugin Python import works')" || exit /b 1
"%ENV_DIR%\python.exe" -m pymol -cq -r "%PLUGIN_LOADER%" || exit /b 1
echo [OK] PyMOL plugin loader works

echo.
echo Windows standalone environment looks valid.
endlocal
