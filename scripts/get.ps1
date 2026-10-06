<#
  Installer for people WITHOUT Python or git (Windows 10/11): downloads DisplayMonitor, installs Python if it is missing,
  and runs the normal setup. Nothing needs to be installed beforehand.

  One line (PowerShell, run as Administrator if you want CPU / motherboard sensors and autostart):
      irm https://raw.githubusercontent.com/DanaVivaldi/turzx-displaymonitor/main/scripts/get.ps1 | iex

  With options:
      & ([scriptblock]::Create((irm https://raw.githubusercontent.com/DanaVivaldi/turzx-displaymonitor/main/scripts/get.ps1))) -Language it -Autostart

  Options:
      -Dir <folder>      where to install (default %LOCALAPPDATA%\DisplayMonitor). An existing install is UPDATED: your config\ and assets\ are kept.
      -Language en|it    language pack (asked if omitted)
      -Ref <name>        branch or tag to download (default main)
      -Autostart         also start it at every logon (needs an elevated PowerShell)
      -NoSetup           only download and extract (no Python, no setup)
      -Source <zip>      use this zip file (or URL) instead of downloading from GitHub (offline installs, testing)

  What it does, in order: 1) finds Python 3.10-3.13, otherwise installs Python 3.12 for the current user (winget, or the python.org
  installer, SHA-256 checked)  2) downloads the repository zip from GitHub  3) runs scripts\setup.ps1 (virtual environment,
  dependencies, LibreHardwareMonitor with hash check, optional PawnIO driver).
#>
param(
    [string]$Dir = (Join-Path $env:LOCALAPPDATA "DisplayMonitor"),
    [ValidateSet("en", "it")][string]$Language,
    [string]$Ref = "main",
    [switch]$Autostart,
    [switch]$NoSetup,
    [string]$Source
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$repo = "DanaVivaldi/turzx-displaymonitor"
$pyUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
$pySha = "67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB"

function Find-Python {
    foreach ($cand in @("py -3.12", "py -3.13", "py -3.11", "py -3.10", "python")) {
        try { $v = & cmd /c "$cand --version 2>&1"; if ($v -match "Python 3\.(1[0-3])") { return $cand } } catch {}
    }
    return $null
}
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

# ---- 1. download and unpack the program ----------------------------------------------------------
Write-Host "Downloading DisplayMonitor ($Ref) ..."
$tmp = Join-Path $env:TEMP "displaymonitor-get"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory $tmp | Out-Null
$zip = Join-Path $tmp "src.zip"
if ($Source -and (Test-Path $Source)) { Copy-Item $Source $zip }
else {
    $kind = if ($Ref -match "^v?\d+(\.\d+)*$") { "tags" } else { "heads" }
    $url = if ($Source) { $Source } else { "https://github.com/$repo/archive/refs/$kind/$Ref.zip" }
    Invoke-WebRequest $url -OutFile $zip
}
Expand-Archive $zip (Join-Path $tmp "x") -Force
$src = (Get-ChildItem (Join-Path $tmp "x") | Select-Object -First 1).FullName

New-Item -ItemType Directory -Force $Dir | Out-Null
# program files are replaced; the user's own files (config\*.yaml that are not examples, assets\, logs\, .venv, tools\lhm) are never touched
$skip = @("assets", "logs", ".venv")
foreach ($item in Get-ChildItem $src -Force) {
    if ($skip -contains $item.Name) { continue }
    if ($item.Name -eq "config") {
        New-Item -ItemType Directory -Force (Join-Path $Dir "config") | Out-Null
        Get-ChildItem $item.FullName -Force | Where-Object { $_.Name -like "*.example.yaml" -or $_.PSIsContainer } |
            ForEach-Object { Copy-Item $_.FullName (Join-Path $Dir "config") -Recurse -Force }
        continue
    }
    if ($item.Name -eq "tools" -and (Test-Path (Join-Path $Dir "tools\lhm"))) {
        Get-ChildItem $item.FullName -Force | ForEach-Object { Copy-Item $_.FullName (Join-Path $Dir "tools") -Recurse -Force }
        continue
    }
    Copy-Item $item.FullName $Dir -Recurse -Force
}
if (-not (Test-Path (Join-Path $Dir "assets"))) { New-Item -ItemType Directory (Join-Path $Dir "assets") | Out-Null }
Remove-Item $tmp -Recurse -Force
Write-Host "Installed in $Dir"
if ($NoSetup) { return }

# ---- 2. Python ---------------------------------------------------------------------------------
$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.10-3.13 not found: installing Python 3.12 for your user ..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
    }
    Refresh-Path
    $py = Find-Python
    if (-not $py) {
        $exe = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
        Invoke-WebRequest $pyUrl -OutFile $exe
        $hash = (Get-FileHash $exe -Algorithm SHA256).Hash
        if ($hash -ne $pySha) { Remove-Item $exe -Force; throw "SHA-256 mismatch for the Python installer ($hash). Aborting." }
        Start-Process $exe -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_test=0" -Wait
        Remove-Item $exe -Force
        Refresh-Path
        $py = Find-Python
    }
    if (-not $py) { throw "Python could not be installed automatically. Install Python 3.12 from https://www.python.org/downloads/ and run this again." }
}
Write-Host "Python OK ($py)"

# ---- 3. the normal setup -------------------------------------------------------------------------
$setupArgs = @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $Dir "scripts\setup.ps1"))
if ($Language) { $setupArgs += @("-Language", $Language) }
& powershell @setupArgs
if ($Autostart) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) { & powershell -ExecutionPolicy Bypass -File (Join-Path $Dir "scripts\install_autostart.ps1") }
    else { Write-Host "Autostart needs an elevated PowerShell: run  $Dir\scripts\install_autostart.ps1  as Administrator." }
}
Write-Host ""
Write-Host "Start it (elevated PowerShell):  cd '$Dir'; .\.venv\Scripts\python.exe -m displaymonitor"
