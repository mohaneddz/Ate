[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'Couscous Cron',
    [string]$ProjectRoot = '',
    [string]$Python = '',
    [ValidateRange(1, 60)][int]$EveryMinutes = 5
)
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$rootPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $Python) {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
}
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
if (-not (Test-Path -LiteralPath (Join-Path $rootPath '.reserve\profile.bin'))) {
    throw 'Run the CLI setup command before installing the scheduler.'
}
if (-not (Test-Path -LiteralPath (Join-Path $rootPath '.reserve\order.bin'))) {
    throw 'Set a standing order before installing the scheduler.'
}
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and ($existing.Actions.WorkingDirectory -ne $rootPath -or $existing.Description -notlike 'Couscous Cron:*')) {
    throw 'A different task uses this name. Choose another -TaskName.'
}
# Use pythonw to avoid flashing a terminal every five minutes. The CLI records
# scheduled results and errors in .reserve/runs.jsonl.
$pythonWindowless = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonWindowless) {
    $pythonPath = $pythonWindowless
}
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-m reserve_cli --state-dir "{0}" run' -f (Join-Path $rootPath '.reserve')
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $rootPath
$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $currentUser),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes))
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, 'Register online reservation checks at sign-in and every five minutes')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal `
        -Description 'Couscous Cron: fulfill the current personal meal order once daily when online.' -Force | Out-Null
    Write-Output "Installed '$TaskName'. Checks every $EveryMinutes minutes while this Windows user is signed in and online."
}
