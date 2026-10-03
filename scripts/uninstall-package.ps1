[CmdletBinding()]
param(
    [string]$InstallRoot = '',
    [switch]$PurgeData
)
$ErrorActionPreference = 'Stop'
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA 'CouscousCron' }
$base = [System.IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\')
$target = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
if (-not $target.StartsWith($base + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Uninstall target must stay inside LocalAppData.'
}
if ($target -ieq $base) { throw 'Refusing to remove the LocalAppData root.' }
$binPath = Join-Path $target 'bin'
$statePath = Join-Path $target 'state'
$taskName = 'Couscous Cron'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Description -notlike 'Couscous Cron:*') { throw 'Scheduled task name belongs to another app.' }
    $expectedExecutable = Join-Path $binPath 'res.exe'
    if ($existing.Actions.Arguments.IndexOf($expectedExecutable, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    } else {
        Write-Host 'A different Couscous Cron installation owns the scheduled task; leaving it in place.' -ForegroundColor Yellow
    }
}
$oldUserPath = [Environment]::GetEnvironmentVariable('Path','User')
$entries = @($oldUserPath -split ';' | Where-Object { $_.Trim() -and $_.TrimEnd('\') -ine $binPath.TrimEnd('\') })
[Environment]::SetEnvironmentVariable('Path', ($entries -join ';'), 'User')
if (Test-Path -LiteralPath $binPath) { Remove-Item -LiteralPath $binPath -Recurse -Force }
if ($PurgeData) {
    if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath -Recurse -Force }
    if ((Test-Path -LiteralPath $target) -and -not @(Get-ChildItem -LiteralPath $target -Force).Count) {
        Remove-Item -LiteralPath $target -Force
    }
    Write-Host 'Executable, scheduler, PATH entry and local account data removed.' -ForegroundColor Green
} else {
    Write-Host "Executable, scheduler and PATH entry removed. Encrypted account data remains at $statePath" -ForegroundColor Green
}
