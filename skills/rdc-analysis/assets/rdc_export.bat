@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHON=%SCRIPT_DIR%..\tools\python36\python.exe"
set "EXPORT_SCRIPT=%SCRIPT_DIR%rdc_export.py"

if "%~1"=="" (
    echo Usage: Drag a .rdc file onto this script, or run:
    echo   %~nx0 "path\to\capture.rdc" [--eid^|-eid ^<eid^-1^|start-end^>] [--skip-slateui-title^|--no-skip-slateui-title]
    if not "%RDC_EXPORT_NO_PAUSE%"=="1" pause
    exit /b 1
)

if not exist "%PYTHON%" (
    echo ERROR: Python not found at: %PYTHON%
    echo Please ensure tools\python36\python.exe exists in the project root.
    if not "%RDC_EXPORT_NO_PAUSE%"=="1" pause
    exit /b 1
)

echo [rdc_export] Using Python: %PYTHON%
echo [rdc_export] Args: %*
"%PYTHON%" "%EXPORT_SCRIPT%" %*
if errorlevel 1 (
    echo.
    echo [rdc_export] Export failed with error code %errorlevel%
    if not "%RDC_EXPORT_NO_PAUSE%"=="1" pause
    exit /b %errorlevel%
)
echo.
if not "%RDC_EXPORT_NO_PAUSE%"=="1" (
    echo [rdc_export] Done. Press any key to close.
    pause >nul
)
endlocal
