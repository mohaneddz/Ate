[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$rootPath = (Resolve-Path -LiteralPath $root).Path
$task = Get-ScheduledTask -TaskName 'Ate' -ErrorAction SilentlyContinue
if ($task) {
    if ($task.Actions.WorkingDirectory -ne $rootPath -or $task.Description -notlike 'Ate:*') {
        throw 'The Ate task belongs to a different installation; leaving it in place.'
    }
    Stop-ScheduledTask -TaskName 'Ate' -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName 'Ate' -Confirm:$false
}
Write-Host 'Source background task removed. Encrypted data remains in LocalAppData\Ate\state.' -ForegroundColor Green
Write-Host 'To remove the Python command too, run: python -m pip uninstall ate-cli' -ForegroundColor Cyan
