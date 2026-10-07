[CmdletBinding()]
param(
    [string]$InstallRoot = '',
    [switch]$PurgeData
)
$ErrorActionPreference = 'Stop'
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:ProgramFiles 'Ate' }
$base = [System.IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\')
$target = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$programFiles = [System.IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\')
$programInstall = Join-Path $programFiles 'Ate'
$isProgramInstall = $target -ieq $programInstall
if (-not $isProgramInstall -and -not $target.StartsWith($base + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Uninstall target must be Ate in Program Files or stay inside LocalAppData.'
}
if ($target -ieq $base) { throw 'Refusing to remove the LocalAppData root.' }
$binPath = Join-Path $target 'bin'
$statePath = if ($isProgramInstall) { Join-Path $base 'Ate\state' } else { Join-Path $target 'state' }
$taskName = 'Ate'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Description -notlike 'Ate:*') { throw 'Scheduled task name belongs to another app.' }
    $expectedExecutable = Join-Path $binPath 'ate.exe'
    if ($existing.Actions.Arguments.IndexOf($expectedExecutable, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    } else {
        Write-Host 'A different Ate installation owns the scheduled task; leaving it in place.' -ForegroundColor Yellow
    }
}
$oldUserPath = [Environment]::GetEnvironmentVariable('Path','User')
$entries = @($oldUserPath -split ';' | Where-Object { $_.Trim() -and $_.TrimEnd('\') -ine $binPath.TrimEnd('\') })
[Environment]::SetEnvironmentVariable('Path', ($entries -join ';'), 'User')
if ($isProgramInstall) {
    $helper = Join-Path $PSScriptRoot 'manage-program-files.ps1'
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'The Program Files uninstaller helper is missing.' }
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Uninstall' -f $helper
    $process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Program Files removal failed (exit code $($process.ExitCode))." }
} elseif (Test-Path -LiteralPath $binPath) {
    $binTarget = [System.IO.Path]::GetFullPath($binPath).TrimEnd('\')
    if (-not $binTarget.StartsWith($target + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Executable path is outside the installation folder.'
    }
    Remove-Item -LiteralPath $binTarget -Recurse -Force
}
if ($PurgeData) {
    $stateTarget = [System.IO.Path]::GetFullPath($statePath).TrimEnd('\')
    $stateBase = if ($isProgramInstall) { Join-Path $base 'Ate' } else { $target }
    if (-not $stateTarget.StartsWith($stateBase + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Account data path is outside the expected folder.'
    }
    if (Test-Path -LiteralPath $stateTarget) { Remove-Item -LiteralPath $stateTarget -Recurse -Force }
    if ((Test-Path -LiteralPath $stateBase) -and -not @(Get-ChildItem -LiteralPath $stateBase -Force).Count) {
        Remove-Item -LiteralPath $stateBase -Force
    }
    Write-Host 'Executable, scheduler, PATH entry and local account data removed.' -ForegroundColor Green
} else {
    Write-Host "Executable, scheduler and PATH entry removed. Encrypted account data remains at $statePath" -ForegroundColor Green
}
