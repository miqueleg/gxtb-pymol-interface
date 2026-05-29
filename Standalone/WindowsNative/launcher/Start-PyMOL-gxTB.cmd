@echo off
setlocal EnableExtensions

set "LAUNCHER_DIR=%~dp0"
for %%I in ("%LAUNCHER_DIR%..") do set "APPDIR=%%~fI"

set "ENV_DIR=%APPDIR%\app_env"
set "GXTB_DIR=%APPDIR%\gxtb\bin"
set "PLUGIN_LOADER=%APPDIR%\plugin\load_plugin.py"
set "PYTHON_EXE=%ENV_DIR%\python.exe"

set "PATH=%GXTB_DIR%;%ENV_DIR%;%ENV_DIR%\Scripts;%ENV_DIR%\Library\bin;%PATH%"
set "PYMOL_GXTB_XTB_PATH=%GXTB_DIR%\xtb.exe"
set "PYMOL_GXTB_ASE_PYTHON=%ENV_DIR%\python.exe"
set "PYMOL_GXTB_PLUGIN_DIR=%APPDIR%\plugin"
set "PYMOL_GXTB_AUTO_OPEN=1"
set "PYTHONNOUSERSITE=1"

set "LOG_ROOT=%LOCALAPPDATA%\PyMOL-gxTB-Runner\logs"
if "%LOCALAPPDATA%"=="" set "LOG_ROOT=%TEMP%\PyMOL-gxTB-Runner\logs"
if not exist "%LOG_ROOT%" mkdir "%LOG_ROOT%" >nul 2>nul
set "STARTUP_LOG=%LOG_ROOT%\startup.log"

echo PyMOL-gxTB Runner startup log>"%STARTUP_LOG%"
echo Date: %DATE% %TIME%>>"%STARTUP_LOG%"
echo APPDIR="%APPDIR%">>"%STARTUP_LOG%"
echo ENV_DIR="%ENV_DIR%">>"%STARTUP_LOG%"
echo GXTB_DIR="%GXTB_DIR%">>"%STARTUP_LOG%"
echo PYTHON_EXE="%PYTHON_EXE%">>"%STARTUP_LOG%"
echo PLUGIN_LOADER="%PLUGIN_LOADER%">>"%STARTUP_LOG%"
echo PYMOL_GXTB_PLUGIN_DIR="%PYMOL_GXTB_PLUGIN_DIR%">>"%STARTUP_LOG%"
echo PYMOL_GXTB_AUTO_OPEN="%PYMOL_GXTB_AUTO_OPEN%">>"%STARTUP_LOG%"
echo.>>"%STARTUP_LOG%"

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Bundled Python executable was not found: "%PYTHON_EXE%"
  echo [ERROR] Bundled Python executable was not found: "%PYTHON_EXE%">>"%STARTUP_LOG%"
  pause
  exit /b 1
)

if not exist "%PLUGIN_LOADER%" (
  echo [ERROR] Plugin loader was not found: "%PLUGIN_LOADER%"
  echo [ERROR] Plugin loader was not found: "%PLUGIN_LOADER%">>"%STARTUP_LOG%"
  pause
  exit /b 1
)

echo Starting PyMOL-gxTB Runner...
echo Startup log: "%STARTUP_LOG%"
echo.

"%PYTHON_EXE%" -m pymol -r "%PLUGIN_LOADER%" >>"%STARTUP_LOG%" 2>>&1
set "PYMOL_EXIT=%ERRORLEVEL%"

if not "%PYMOL_EXIT%"=="0" (
  echo.
  echo [ERROR] PyMOL exited with code %PYMOL_EXIT%.
  echo [ERROR] PyMOL exited with code %PYMOL_EXIT%.>>"%STARTUP_LOG%"
  echo.
  echo Last startup log lines:
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath $env:STARTUP_LOG -Tail 80" 2>nul
  echo.
  echo Full log: "%STARTUP_LOG%"
  pause
  exit /b %PYMOL_EXIT%
)

echo PyMOL has closed.
echo Full startup log: "%STARTUP_LOG%"
pause
endlocal
