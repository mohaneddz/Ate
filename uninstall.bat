@echo off
setlocal
if exist "%~dp0ate.exe" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall-package.ps1" %*
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall-source.ps1" %*
)
if errorlevel 1 (
    echo Uninstall failed. Press any key to close this window.
    pause >nul
    exit /b 1
)
echo Done. Press any key to close this window.
pause >nul
