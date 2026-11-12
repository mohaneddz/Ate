[CmdletBinding()]
param(
    [string]$PackageRoot = '',
    [string]$UserName = '',
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
$updateTask = 'AteUpdate'
if ($Uninstall) {
    $oldTask = Get-ScheduledTask -TaskName $updateTask -ErrorAction SilentlyContinue
    if ($oldTask -and $oldTask.Description -like 'Ate:*') { Unregister-ScheduledTask -TaskName $updateTask -Confirm:$false }
    if (Test-Path -LiteralPath $binPath) {
        if (-not (Test-Path -LiteralPath (Join-Path $binPath 'scripts\uninstall-package.ps1') -PathType Leaf)) {
            throw 'The folder is not a recognized Ate installation.'
        }
        Remove-Item -LiteralPath $binPath -Recurse -Force
    }
    Remove-Item -LiteralPath (Join-Path $installPath 'update-status.txt') -Force -ErrorAction SilentlyContinue
    if ((Test-Path -LiteralPath $installPath) -and -not @(Get-ChildItem -LiteralPath $installPath -Force).Count) {
        Remove-Item -LiteralPath $installPath -Force
    }
    exit 0
}
if (-not $PackageRoot) { throw 'PackageRoot is required for installation.' }
$packagePath = (Resolve-Path -LiteralPath $PackageRoot).Path
$files = @(
    'ate.exe', 'res.cmd', 'uninstall.bat', 'VERSION',
    'scripts\hidden-run.vbs', 'scripts\uninstall-package.ps1',
    'scripts\manage-program-files.ps1', 'scripts\update-package.ps1'
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

# On-demand elevated task so the signed-in user can apply updates without a UAC prompt each time.
# It only runs update-package.ps1 from this admin-only folder, which installs the official release.
if ($UserName) {
    $existingUpdate = Get-ScheduledTask -TaskName $updateTask -ErrorAction SilentlyContinue
    if ($existingUpdate -and $existingUpdate.Description -notlike 'Ate:*') {
        throw 'A different scheduled task uses the AteUpdate name.'
    }
    $updateScript = Join-Path $binPath 'scripts\update-package.ps1'
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $action = New-ScheduledTaskAction -Execute $powershell -WorkingDirectory $binPath `
        -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $updateScript)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    $principal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $updateTask -Action $action -Settings $settings -Principal $principal `
        -Description 'Ate: install Ate updates from the official GitHub release.' -Force | Out-Null
}
