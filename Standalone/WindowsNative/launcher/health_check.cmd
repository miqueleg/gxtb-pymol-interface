@echo off
setlocal EnableExtensions

set "LAUNCHER_DIR=%~dp0"
for %%I in ("%LAUNCHER_DIR%..") do set "APPDIR=%%~fI"

set "ENV_DIR=%APPDIR%\app_env"
set "GXTB_DIR=%APPDIR%\gxtb\bin"
set "PLUGIN_FILE=%APPDIR%\plugin\pymol_gxtb_plugin.py"

set "PATH=%GXTB_DIR%;%ENV_DIR%;%ENV_DIR%\Scripts;%ENV_DIR%\Library\bin;%PATH%"
set "PYMOL_GXTB_XTB_PATH=%GXTB_DIR%\xtb.exe"
set "PYMOL_GXTB_ASE_PYTHON=%ENV_DIR%\python.exe"

if exist "%ENV_DIR%\python.exe" (
  echo [OK] Python found
) else (
  echo [ERROR] Python not found: "%ENV_DIR%\python.exe"
  exit /b 1
)

if exist "%ENV_DIR%\Scripts\pymol.exe" (
  echo [OK] PyMOL found
) else (
  echo [ERROR] PyMOL not found: "%ENV_DIR%\Scripts\pymol.exe"
  exit /b 1
)

if exist "%GXTB_DIR%\xtb.exe" (
  echo [OK] g-xTB found
) else (
  echo [ERROR] g-xTB executable not found: "%GXTB_DIR%\xtb.exe"
  exit /b 1
)

if exist "%PLUGIN_FILE%" (
  echo [OK] Plugin found
) else (
  echo [ERROR] Plugin file not found: "%PLUGIN_FILE%"
  exit /b 1
)

"%ENV_DIR%\python.exe" -c "import numpy; print('[OK] NumPy import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import scipy; print('[OK] SciPy import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import ase; print('[OK] ASE import works')" || exit /b 1
"%ENV_DIR%\python.exe" -c "import sella; print('[OK] Sella import works')" || exit /b 1

echo.
echo Windows standalone environment looks valid.
endlocal
