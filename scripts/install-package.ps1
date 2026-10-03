[CmdletBinding()]
param(
    [string]$PackageRoot = '',
    [string]$InstallRoot = '',
    [string]$MigrateFrom = '',
    [switch]$NoSchedule,
    [switch]$NoSetup
)
$ErrorActionPreference = 'Stop'
if (-not $PackageRoot) { $PackageRoot = Split-Path -Parent $PSScriptRoot }
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA 'CouscousCron' }
$packagePath = (Resolve-Path -LiteralPath $PackageRoot).Path
$installPath = [System.IO.Path]::GetFullPath($InstallRoot)
$binPath = Join-Path $installPath 'bin'
$statePath = Join-Path $installPath 'state'
$sourceExe = Join-Path $packagePath 'res.exe'
if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) { throw 'res.exe is missing from this package.' }
if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'scripts\hidden-run.vbs') -PathType Leaf)) {
    throw 'The background runner is missing from this package.'
}
New-Item -ItemType Directory -Path $binPath,$statePath -Force | Out-Null

$taskName = 'Couscous Cron'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -notlike 'Couscous Cron:*') {
    throw 'A different scheduled task uses the Couscous Cron name.'
}
if ($existing -and -not $NoSchedule) { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue }

$exePath = Join-Path $binPath 'res.exe'
Copy-Item -LiteralPath $sourceExe -Destination $exePath -Force
Copy-Item -LiteralPath (Join-Path $packagePath 'uninstall.cmd') -Destination (Join-Path $binPath 'uninstall.cmd') -Force
New-Item -ItemType Directory -Path (Join-Path $binPath 'scripts') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $packagePath 'scripts\hidden-run.vbs') -Destination (Join-Path $binPath 'scripts\hidden-run.vbs') -Force
Copy-Item -LiteralPath (Join-Path $packagePath 'scripts\uninstall-package.ps1') -Destination (Join-Path $binPath 'scripts\uninstall-package.ps1') -Force

if ($MigrateFrom) {
    $oldPath = (Resolve-Path -LiteralPath $MigrateFrom).Path
    if (-not (Test-Path -LiteralPath (Join-Path $oldPath 'profile.bin'))) {
        throw 'Migration folder has no encrypted profile.'
    }
    foreach ($name in @('profile.bin','order.bin','run_state.bin','journal.bin',
                         'reservation_cache.bin','depot_cache.bin','runs.jsonl')) {
        $from = Join-Path $oldPath $name
        $to = Join-Path $statePath $name
        if ((Test-Path -LiteralPath $from -PathType Leaf) -and -not (Test-Path -LiteralPath $to)) {
            Copy-Item -LiteralPath $from -Destination $to
        }
    }
    Write-Host 'Existing encrypted account and order copied for this Windows user.' -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath (Join-Path $statePath 'profile.bin'))) {
    if ($NoSetup) { throw 'No account is configured. Run the installer without -NoSetup.' }
    & $exePath setup
    if ($LASTEXITCODE -ne 0) { throw 'Account setup did not finish. No scheduler was installed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $statePath 'order.bin'))) {
    throw 'No standing order is configured. Run res setup or set an order first.'
}

$oldUserPath = [Environment]::GetEnvironmentVariable('Path','User')
$entries = @($oldUserPath -split ';' | Where-Object { $_.Trim() })
$entries = @($entries | Where-Object { $_.TrimEnd('\') -ine $binPath.TrimEnd('\') })
[Environment]::SetEnvironmentVariable('Path', (($binPath) + ';' + ($entries -join ';')).TrimEnd(';'), 'User')
$env:Path = $binPath + ';' + $env:Path

if (-not $NoSchedule) {
    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $scriptPath = Join-Path $binPath 'scripts\hidden-run.vbs'
    $arguments = '"{0}" "{1}"' -f $scriptPath, $exePath
    $action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\wscript.exe') `
        -Argument $arguments -WorkingDirectory $binPath
    $triggers = @(
        (New-ScheduledTaskTrigger -AtLogOn -User $currentUser),
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5))
    )
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal `
        -Description 'Couscous Cron: fulfill the current personal meal order once daily when online.' -Force | Out-Null
    Write-Host 'Background checks installed for sign-in and every five minutes while online.' -ForegroundColor Green
    Start-ScheduledTask -TaskName $taskName
} else {
    Write-Host 'Scheduler registration skipped for this test install.' -ForegroundColor Yellow
}
Write-Host "Installed at $installPath" -ForegroundColor Cyan
Write-Host 'Open a new Command Prompt, then run: res show' -ForegroundColor Cyan
