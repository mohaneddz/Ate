[CmdletBinding()]
param()
# Runs elevated through the AteUpdate scheduled task. It takes no input: it fetches the latest
# official release itself, checks the published SHA-256, then swaps the files in Program Files.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repo = 'mohaneddz/Ate'
$programFiles = [System.IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\')
$installPath = Join-Path $programFiles 'Ate'
$binPath = Join-Path $installPath 'bin'
$statusFile = Join-Path $installPath 'update-status.txt'
$staging = Join-Path $installPath 'staging'
$headers = @{ 'User-Agent' = 'ate-updater' }
$files = @(
    'ate.exe', 'res.cmd', 'uninstall.bat', 'VERSION',
    'scripts\hidden-run.vbs', 'scripts\uninstall-package.ps1',
    'scripts\manage-program-files.ps1', 'scripts\update-package.ps1'
)

function Write-Status([string]$text) {
    Set-Content -LiteralPath $statusFile -Value $text -Encoding UTF8
}

function Read-Text($response) {
    if ($response.Content -is [byte[]]) { return [System.Text.Encoding]::ASCII.GetString($response.Content) }
    return [string]$response.Content
}

$swapped = $false
try {
    if (-not (Test-Path -LiteralPath $installPath -PathType Container)) { throw 'Ate is not installed in Program Files.' }
    Write-Status 'running'
    $scriptHome = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
    if ($scriptHome -ine $binPath) { throw 'This updater is not running from the installed Ate folder.' }

    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -Headers $headers -TimeoutSec 30
    if ($release.tag_name -notmatch '^v(\d+\.\d+\.\d+)$') { throw 'The latest release has an unexpected tag.' }
    $version = $Matches[1]
    $tag = $release.tag_name

    $versionFile = Join-Path $binPath 'VERSION'
    if (Test-Path -LiteralPath $versionFile -PathType Leaf) {
        $installed = (Get-Content -LiteralPath $versionFile -Raw).Trim()
        if ($installed -match '^\d+\.\d+\.\d+$' -and [version]$installed -ge [version]$version) {
            Write-Status "ok $installed"
            exit 0
        }
    }

    $name = "Ate-$version-win64.zip"
    $base = "https://github.com/$repo/releases/download/$tag"
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    New-Item -ItemType Directory -Path $staging | Out-Null
    $zip = Join-Path $staging $name
    Invoke-WebRequest -Uri "$base/$name" -OutFile $zip -UseBasicParsing -Headers $headers -TimeoutSec 600
    $checksum = Read-Text (Invoke-WebRequest -Uri "$base/$name.sha256" -UseBasicParsing -Headers $headers -TimeoutSec 30)
    if ($checksum -notmatch '^\s*([0-9a-fA-F]{64})\s+\*?(\S+)') { throw 'The checksum file is not in the expected format.' }
    if ($Matches[2] -cne $name) { throw 'The checksum file is for a different archive.' }
    $expected = $Matches[1]
    $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
    if ($actual -ine $expected) { throw 'The download does not match its published checksum; nothing was changed.' }

    $extract = Join-Path $staging 'package'
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
    $packageRoot = Join-Path $extract "Ate-$version-win64"
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $file) -PathType Leaf)) {
            throw "The release is missing $file."
        }
    }

    # A running executable cannot be overwritten but can be renamed, so move it aside first.
    $exe = Join-Path $binPath 'ate.exe'
    $old = "$exe.old"
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $exe) { Move-Item -LiteralPath $exe -Destination $old -Force; $swapped = $true }
    foreach ($file in $files) {
        Copy-Item -LiteralPath (Join-Path $packageRoot $file) -Destination (Join-Path $binPath $file) -Force
    }
    $swapped = $false
    Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
    Write-Status "ok $version"
} catch {
    if ($swapped -and (Test-Path -LiteralPath "$binPath\ate.exe.old")) {
        Move-Item -LiteralPath "$binPath\ate.exe.old" -Destination "$binPath\ate.exe" -Force -ErrorAction SilentlyContinue
    }
    Write-Status "error $($_.Exception.Message)"
    exit 1
} finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }
}
