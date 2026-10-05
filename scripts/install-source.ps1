[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$rootPath = (Resolve-Path -LiteralPath $root).Path
$existing = Get-ScheduledTask -TaskName 'Ate' -ErrorAction SilentlyContinue
if ($existing -and $existing.Actions.WorkingDirectory -ne $rootPath) {
    throw 'Ate already has a background task from another installation. Remove that installation first.'
}
$python = (Get-Command python.exe -ErrorAction Stop).Source
& $python -m pip install -e $rootPath
if ($LASTEXITCODE -ne 0) { throw 'Python package installation failed.' }
$statePath = Join-Path $env:LOCALAPPDATA 'Ate\state'
$oldState = Join-Path $rootPath '.reserve'
New-Item -ItemType Directory -Path $statePath -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $statePath 'profile.bin')) -and
    (Test-Path -LiteralPath (Join-Path $oldState 'profile.bin'))) {
    foreach ($name in @('profile.bin','order.bin','run_state.bin','journal.bin',
                         'reservation_cache.bin','depot_cache.bin','runs.jsonl')) {
        $from = Join-Path $oldState $name
        $to = Join-Path $statePath $name
        if ((Test-Path -LiteralPath $from -PathType Leaf) -and -not (Test-Path -LiteralPath $to)) {
            Copy-Item -LiteralPath $from -Destination $to
        }
    }
    Write-Host 'Existing encrypted state copied from this checkout.' -ForegroundColor Green
}
if (-not (Test-Path -LiteralPath (Join-Path $statePath 'profile.bin'))) {
    & $python -m reserve_cli.short auth
    if ($LASTEXITCODE -ne 0) { throw 'Account setup did not finish. No scheduler was installed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $statePath 'order.bin'))) {
    throw 'No standing order is configured. Run ate auth or ate 3 first.'
}
& (Join-Path $PSScriptRoot 'install-schedule.ps1') -ProjectRoot $rootPath -Python $python
$scriptsPath = (& $python -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $scriptsPath -PathType Container)) {
    throw 'Could not find the Python Scripts directory for the ate command.'
}
$oldUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$entries = @($oldUserPath -split ';' | Where-Object { $_.Trim() })
if (-not @($entries | Where-Object { $_.TrimEnd('\') -ieq $scriptsPath.TrimEnd('\') }).Count) {
    [Environment]::SetEnvironmentVariable('Path', ($scriptsPath + ';' + ($entries -join ';')).TrimEnd(';'), 'User')
}
$env:Path = $scriptsPath + ';' + $env:Path
Write-Host 'Ate is ready. The res command is on your PATH.' -ForegroundColor Green
# Open a terminal that already sees res, so the user can keep going right away.
Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', 'res show'
