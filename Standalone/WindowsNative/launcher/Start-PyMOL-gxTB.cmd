@echo off
setlocal

set "LAUNCHER_DIR=%~dp0"
for %%I in ("%LAUNCHER_DIR%..") do set "APPDIR=%%~fI"

set "ENV_DIR=%APPDIR%\app_env"
set "GXTB_DIR=%APPDIR%\gxtb\bin"
set "PLUGIN_LOADER=%APPDIR%\plugin\load_plugin.py"

set "PATH=%GXTB_DIR%;%ENV_DIR%;%ENV_DIR%\Scripts;%ENV_DIR%\Library\bin;%PATH%"
set "PYMOL_GXTB_XTB_PATH=%GXTB_DIR%\xtb.exe"
set "PYMOL_GXTB_ASE_PYTHON=%ENV_DIR%\python.exe"

if not exist "%ENV_DIR%\Scripts\pymol.exe" (
  echo [ERROR] PyMOL executable was not found: "%ENV_DIR%\Scripts\pymol.exe"
  exit /b 1
)

if not exist "%PLUGIN_LOADER%" (
  echo [ERROR] Plugin loader was not found: "%PLUGIN_LOADER%"
  exit /b 1
)

start "PyMOL-gxTB Runner" "%ENV_DIR%\Scripts\pymol.exe" -r "%PLUGIN_LOADER%"

endlocal
