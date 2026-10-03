@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-package.ps1"
if errorlevel 1 (
    echo.
    echo Installation stopped. Press any key to close this window.
    pause >nul
    exit /b 1
)
echo.
echo Open a new Command Prompt and type: res show
echo Press any key to close this window.
pause >nul
