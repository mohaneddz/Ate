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
$defaultInstall = -not $InstallRoot
if ($defaultInstall) { $InstallRoot = Join-Path $env:ProgramFiles 'Ate' }
$packagePath = (Resolve-Path -LiteralPath $PackageRoot).Path
$installPath = [System.IO.Path]::GetFullPath($InstallRoot)
$oldInstall = Join-Path $env:LOCALAPPDATA 'Ate'
$oldBin = Join-Path $oldInstall 'bin'
$legacyPath = Join-Path $env:LOCALAPPDATA 'CouscousCron'
$legacyBin = Join-Path $legacyPath 'bin'
$legacyState = Join-Path $legacyPath 'state'
$binPath = Join-Path $installPath 'bin'
$statePath = if ($defaultInstall) { Join-Path $oldInstall 'state' } else { Join-Path $installPath 'state' }
$sourceExe = Join-Path $packagePath 'ate.exe'
if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) { throw 'ate.exe is missing from this package.' }
if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'scripts\hidden-run.vbs') -PathType Leaf)) {
    throw 'The background runner is missing from this package.'
}
New-Item -ItemType Directory -Path $statePath -Force | Out-Null

$taskName = 'Ate'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -notlike 'Ate:*') {
    throw 'A different scheduled task uses the Ate name.'
}
if ($existing -and -not $NoSchedule) { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue }

$exePath = Join-Path $binPath 'ate.exe'
$freshExecutable = -not (Test-Path -LiteralPath $exePath -PathType Leaf)
if ($defaultInstall) {
    $helper = Join-Path $packagePath 'scripts\manage-program-files.ps1'
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'The Program Files installer helper is missing.' }
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -PackageRoot "{1}"' -f $helper, $packagePath
    $process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Program Files installation failed (exit code $($process.ExitCode))." }
} else {
    New-Item -ItemType Directory -Path $binPath,(Join-Path $binPath 'scripts') -Force | Out-Null
    Copy-Item -LiteralPath $sourceExe -Destination $exePath -Force
    Copy-Item -LiteralPath (Join-Path $packagePath 'res.cmd') -Destination (Join-Path $binPath 'res.cmd') -Force
    Copy-Item -LiteralPath (Join-Path $packagePath 'uninstall.bat') -Destination (Join-Path $binPath 'uninstall.bat') -Force
    Copy-Item -LiteralPath (Join-Path $packagePath 'scripts\hidden-run.vbs') -Destination (Join-Path $binPath 'scripts\hidden-run.vbs') -Force
    Copy-Item -LiteralPath (Join-Path $packagePath 'scripts\uninstall-package.ps1') -Destination (Join-Path $binPath 'scripts\uninstall-package.ps1') -Force
}

if ($MigrateFrom) {
    $oldPath = (Resolve-Path -LiteralPath $MigrateFrom).Path
    if (-not (Test-Path -LiteralPath (Join-Path $oldPath 'profile.bin'))) {
        throw 'Migration folder has no encrypted profile.'
    }
    foreach ($name in @('profile.bin','order.bin','run_state.bin','journal.bin','config.bin','auth-transaction.bin',
                         'reservation_cache.bin','depot_cache.bin','runs.jsonl')) {
        $from = Join-Path $oldPath $name
        $to = Join-Path $statePath $name
        if ((Test-Path -LiteralPath $from -PathType Leaf) -and -not (Test-Path -LiteralPath $to)) {
            Copy-Item -LiteralPath $from -Destination $to
        }
    }
    Write-Host 'Existing encrypted account and order copied for this Windows user.' -ForegroundColor Green
}
if ($defaultInstall -and -not (Test-Path -LiteralPath (Join-Path $statePath 'profile.bin')) -and
    (Test-Path -LiteralPath (Join-Path $legacyState 'profile.bin') -PathType Leaf)) {
    foreach ($name in @('profile.bin','order.bin','run_state.bin','journal.bin','config.bin','auth-transaction.bin',
                         'reservation_cache.bin','depot_cache.bin','runs.jsonl')) {
        $from = Join-Path $legacyState $name
        $to = Join-Path $statePath $name
        if ((Test-Path -LiteralPath $from -PathType Leaf) -and -not (Test-Path -LiteralPath $to)) {
            Copy-Item -LiteralPath $from -Destination $to
        }
    }
    Write-Host 'Existing encrypted account and order migrated from Couscous Cron.' -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath (Join-Path $statePath 'profile.bin'))) {
    if ($NoSetup) { throw 'No account is configured. Run the installer without -NoSetup.' }
    & $exePath auth
    if ($LASTEXITCODE -ne 0) {
        if ($freshExecutable) {
            if ($defaultInstall) {
                $helper = Join-Path $packagePath 'scripts\manage-program-files.ps1'
                $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Uninstall' -f $helper
                $cleanup = Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments -Wait -PassThru
                if ($cleanup.ExitCode -ne 0) { Write-Warning 'Partial app files could not be removed from Program Files.' }
            } elseif (Test-Path -LiteralPath $binPath) {
                Remove-Item -LiteralPath $binPath -Recurse -Force
            }
        }
        throw 'Account setup did not finish. No scheduler was installed.'
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $statePath 'order.bin'))) {
    throw 'No standing order is configured. Run res auth or set an order first.'
}
$everyMinutes = [int](& $exePath config --minutes)
if ($LASTEXITCODE -ne 0 -or $everyMinutes -lt 1 -or $everyMinutes -gt 10080) {
    throw 'Could not read the saved check interval.'
}

$oldUserPath = [Environment]::GetEnvironmentVariable('Path','User')
$entries = @($oldUserPath -split ';' | Where-Object { $_.Trim() })
$entries = @($entries | Where-Object { $_.TrimEnd('\') -ine $binPath.TrimEnd('\') })
if ($defaultInstall) {
    $entries = @($entries | Where-Object {
        $_.TrimEnd('\') -ine $legacyBin.TrimEnd('\') -and $_.TrimEnd('\') -ine $oldBin.TrimEnd('\')
    })
}
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
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $everyMinutes))
    )
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal `
        -Description 'Ate: fulfill the current personal meal order when online.' -Force | Out-Null
    if ($defaultInstall) {
        $oldTask = Get-ScheduledTask -TaskName 'Couscous Cron' -ErrorAction SilentlyContinue
        $oldExe = Join-Path $legacyBin 'res.exe'
        if ($oldTask -and $oldTask.Description -like 'Couscous Cron:*' -and
            $oldTask.Actions.Arguments.IndexOf($oldExe, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Stop-ScheduledTask -TaskName 'Couscous Cron' -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName 'Couscous Cron' -Confirm:$false
            Write-Host 'Previous Couscous Cron background task replaced.' -ForegroundColor Green
        }
    }
    Write-Host "Background checks installed for sign-in and every $everyMinutes minutes while online." -ForegroundColor Green
    Start-ScheduledTask -TaskName $taskName
} else {
    Write-Host 'Scheduler registration skipped for this test install.' -ForegroundColor Yellow
}
if ($defaultInstall -and -not $NoSchedule -and (Test-Path -LiteralPath (Join-Path $oldBin 'ate.exe') -PathType Leaf) -and
    (Test-Path -LiteralPath (Join-Path $oldBin 'scripts\uninstall-package.ps1') -PathType Leaf)) {
    $oldBinPath = [System.IO.Path]::GetFullPath($oldBin).TrimEnd('\')
    $oldRootPath = [System.IO.Path]::GetFullPath($oldInstall).TrimEnd('\')
    if (-not $oldBinPath.StartsWith($oldRootPath + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Old executable path is outside the previous Ate folder.'
    }
    Remove-Item -LiteralPath $oldBinPath -Recurse -Force
    Write-Host 'Previous per-user executable removed.' -ForegroundColor Green
}
Write-Host "Installed at $installPath" -ForegroundColor Cyan
Write-Host 'The res command is on your PATH.' -ForegroundColor Green
# Open a terminal that already sees res, so the user can keep going right away.
Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', 'res show'
