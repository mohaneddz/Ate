[CmdletBinding()]
param([string]$Version = '0.5.0', [switch]$SkipExecutable)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$release = Join-Path $root 'release'
$work = Join-Path $root 'build\pyinstaller'
$package = Join-Path $release "Ate-$Version-win64"
$releasePath = [System.IO.Path]::GetFullPath($release).TrimEnd('\')
$packagePath = [System.IO.Path]::GetFullPath($package)
if (-not $packagePath.StartsWith($releasePath + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Release package path must stay inside the release directory.'
}
if (Test-Path -LiteralPath $packagePath) { Remove-Item -LiteralPath $packagePath -Recurse -Force }
New-Item -ItemType Directory -Path $release,$work,$package -Force | Out-Null
Push-Location $root
try {
    if (-not $SkipExecutable) {
        python scripts\pyinstaller_driver.py --noconfirm --clean --onefile --name ate --paths $root `
            --exclude-module IPython --exclude-module matplotlib --exclude-module numpy `
            --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 `
            --exclude-module scipy --exclude-module pandas --exclude-module notebook --exclude-module nbformat `
            --exclude-module sklearn --exclude-module tkinter `
            --collect-all tzdata `
            --distpath $release --workpath $work --specpath $work `
            scripts\frozen_entry.py
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $release 'ate.exe'))) { throw 'Executable is missing.' }
    Copy-Item -LiteralPath (Join-Path $release 'ate.exe') -Destination (Join-Path $package 'ate.exe') -Force
    Copy-Item -LiteralPath 'install.bat','uninstall.bat','res.cmd','README.md' -Destination $package -Force
    New-Item -ItemType Directory -Path (Join-Path $package 'scripts') -Force | Out-Null
    foreach ($name in @('install-package.ps1','uninstall-package.ps1','hidden-run.vbs')) {
        Copy-Item -LiteralPath (Join-Path 'scripts' $name) -Destination (Join-Path (Join-Path $package 'scripts') $name) -Force
    }
    $zip = Join-Path $release "Ate-$Version-win64.zip"
    Compress-Archive -LiteralPath $package -DestinationPath $zip -Force
    $digest = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
    [System.IO.File]::WriteAllText("$zip.sha256", "$digest  $(Split-Path -Leaf $zip)`n")
    Write-Host "Package: $zip" -ForegroundColor Green
    Write-Host "SHA256: $digest" -ForegroundColor Green
} finally {
    Pop-Location
}
