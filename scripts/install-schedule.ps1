[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'Ate',
    [string]$ProjectRoot = '',
    [string]$Python = '',
    [ValidateRange(1, 10080)][int]$EveryMinutes = 5
)
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$rootPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
$statePath = Join-Path $env:LOCALAPPDATA 'Ate\state'
if (-not $Python) {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
}
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
if (-not (Test-Path -LiteralPath (Join-Path $statePath 'profile.bin'))) {
    throw 'Run the CLI setup command before installing the scheduler.'
}
if (-not (Test-Path -LiteralPath (Join-Path $statePath 'order.bin'))) {
    throw 'Set a standing order before installing the scheduler.'
}
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and ($existing.Actions.WorkingDirectory -ne $rootPath -or $existing.Description -notlike 'Ate:*')) {
    throw 'A different task uses this name. Choose another -TaskName.'
}
# Use pythonw to avoid flashing a terminal during checks. The CLI records
# scheduled results and errors in the per-user state folder.
$pythonWindowless = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonWindowless) {
    $pythonPath = $pythonWindowless
}
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-m reserve_cli --state-dir "{0}" run' -f $statePath
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $rootPath
$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $currentUser),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes))
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, "Register online reservation checks at sign-in and every $EveryMinutes minutes")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal `
        -Description 'Ate: fulfill the current personal meal order when online.' -Force | Out-Null
    Write-Output "Installed '$TaskName'. Checks every $EveryMinutes minutes while this Windows user is signed in and online."
}
