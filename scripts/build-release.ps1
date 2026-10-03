[CmdletBinding()]
param([string]$Version = '0.3.0', [switch]$SkipExecutable)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$release = Join-Path $root 'release'
$work = Join-Path $root 'build\pyinstaller'
$package = Join-Path $release "CouscousCron-$Version-win64"
New-Item -ItemType Directory -Path $release,$work,$package -Force | Out-Null
Push-Location $root
try {
    if (-not $SkipExecutable) {
        python scripts\pyinstaller_driver.py --noconfirm --clean --onefile --name res --paths $root `
            --exclude-module IPython --exclude-module matplotlib --exclude-module numpy `
            --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 `
            --exclude-module scipy --exclude-module pandas --exclude-module notebook --exclude-module nbformat `
            --exclude-module sklearn --exclude-module tkinter `
            --collect-all hermes_dec --collect-all tzdata `
            --distpath $release --workpath $work --specpath $work `
            scripts\frozen_entry.py
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $release 'res.exe'))) { throw 'Executable is missing.' }
    Copy-Item -LiteralPath (Join-Path $release 'res.exe') -Destination (Join-Path $package 'res.exe') -Force
    Copy-Item -LiteralPath 'install.cmd','uninstall.cmd','INSTALL.md','README.md','THIRD_PARTY_NOTICES.md' -Destination $package -Force
    New-Item -ItemType Directory -Path (Join-Path $package 'scripts') -Force | Out-Null
    foreach ($name in @('install-package.ps1','uninstall-package.ps1','hidden-run.vbs')) {
        Copy-Item -LiteralPath (Join-Path 'scripts' $name) -Destination (Join-Path (Join-Path $package 'scripts') $name) -Force
    }
    $license = python -c "import importlib.metadata as m; d=m.distribution('hermes-dec'); print(d.locate_file(next(f for f in d.files if str(f).endswith('licenses/LICENSE'))))"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $license)) { throw 'Bundled importer license was not found.' }
    New-Item -ItemType Directory -Path (Join-Path $package 'LICENSES') -Force | Out-Null
    Copy-Item -LiteralPath $license -Destination (Join-Path $package 'LICENSES\hermes-dec-LICENSE.txt') -Force
    $zip = Join-Path $release "CouscousCron-$Version-win64.zip"
    Compress-Archive -LiteralPath $package -DestinationPath $zip -Force
    $digest = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
    [System.IO.File]::WriteAllText("$zip.sha256", "$digest  $(Split-Path -Leaf $zip)`n")
    Write-Host "Package: $zip" -ForegroundColor Green
    Write-Host "SHA256: $digest" -ForegroundColor Green
} finally {
    Pop-Location
}
