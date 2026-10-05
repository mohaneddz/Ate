@echo off
setlocal
if exist "%~dp0ate.exe" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-package.ps1"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-source.ps1"
)
if errorlevel 1 (
    echo.
    echo Installation stopped. Press any key to close this window.
    pause >nul
    exit /b 1
)
echo.
echo Ate is installed. A ready-to-use terminal just opened; this window can close.
pause >nul
