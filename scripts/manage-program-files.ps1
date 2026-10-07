[CmdletBinding()]
param(
    [string]$PackageRoot = '',
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator access is required to change files in Program Files.'
}
$programFiles = [System.IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\')
$installPath = Join-Path $programFiles 'Ate'
$binPath = Join-Path $installPath 'bin'
if (-not $binPath.StartsWith($programFiles + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Executable path is outside Program Files.'
}
if ($Uninstall) {
    if (Test-Path -LiteralPath $binPath) {
        if (-not (Test-Path -LiteralPath (Join-Path $binPath 'scripts\uninstall-package.ps1') -PathType Leaf)) {
            throw 'The folder is not a recognized Ate installation.'
        }
        Remove-Item -LiteralPath $binPath -Recurse -Force
    }
    if ((Test-Path -LiteralPath $installPath) -and -not @(Get-ChildItem -LiteralPath $installPath -Force).Count) {
        Remove-Item -LiteralPath $installPath -Force
    }
    exit 0
}
if (-not $PackageRoot) { throw 'PackageRoot is required for installation.' }
$packagePath = (Resolve-Path -LiteralPath $PackageRoot).Path
$files = @(
    'ate.exe', 'res.cmd', 'uninstall.bat',
    'scripts\hidden-run.vbs', 'scripts\uninstall-package.ps1',
    'scripts\manage-program-files.ps1'
)
foreach ($file in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $packagePath $file) -PathType Leaf)) {
        throw "The package is missing $file."
    }
}
New-Item -ItemType Directory -Path (Join-Path $binPath 'scripts') -Force | Out-Null
foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $packagePath $file) -Destination (Join-Path $binPath $file) -Force
}
