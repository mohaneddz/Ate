@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall-package.ps1" %*
if errorlevel 1 (
    echo Uninstall failed. Press any key to close this window.
    pause >nul
    exit /b 1
)
echo Couscous Cron was removed. Press any key to close this window.
pause >nul
