<#
  One-time setup for DisplayMonitor (Windows 10/11).
    1. creates the Python virtual environment (.venv) and installs requirements.txt
    2. downloads LibreHardwareMonitor into tools\lhm  (pinned release, SHA-256 verified)
    3. offers to install the PawnIO driver (needed for CPU / motherboard sensors)
    4. installs a language pack (English or Italiano) as config\config.yaml / config\pages.yaml if you have none

  Usage:   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  Needs:   Python 3.12 on PATH (py -3.12 or python), internet access.
#>
param([ValidateSet("en", "it")][string]$Language)      # language pack: en (English) or it (Italiano); asked if omitted
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# ---- pinned third-party release --------------------------------------------------------------
$lhmVersion = "v0.9.6"
$lhmUrl     = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/$lhmVersion/LibreHardwareMonitor.zip"
$lhmSha256  = "086D9F1B5A99E643EDC2CFAAAC16051685B551E4C5AC0B32A57C58C0E529C001"

# ---- 1. Python environment -------------------------------------------------------------------
$py = $null
foreach ($cand in @("py -3.12", "python")) {
    try { $v = & cmd /c "$cand --version 2>&1"; if ($v -match "Python 3\.(1[0-3])") { $py = $cand; break } } catch {}
}
if (-not $py) { throw "Python 3.10-3.13 not found. Install Python 3.12 (e.g. 'winget install Python.Python.3.12') and re-run." }
Write-Host "Using $py ($v)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & cmd /c "$py -m venv .venv" }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# ---- 2. LibreHardwareMonitor -----------------------------------------------------------------
$lhmDir = Join-Path $root "tools\lhm"
if (-not (Test-Path (Join-Path $lhmDir "LibreHardwareMonitorLib.dll"))) {
    $zip = Join-Path $env:TEMP "LibreHardwareMonitor-$lhmVersion.zip"
    Write-Host "Downloading LibreHardwareMonitor $lhmVersion ..."
    Invoke-WebRequest $lhmUrl -OutFile $zip
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash
    if ($hash -ne $lhmSha256) { Remove-Item $zip -Force; throw "SHA-256 mismatch for LibreHardwareMonitor ($hash). Aborting." }
    New-Item -ItemType Directory -Force $lhmDir | Out-Null
    Expand-Archive $zip $lhmDir -Force
    Remove-Item $zip -Force
    Write-Host "LibreHardwareMonitor installed in tools\lhm"
} else { Write-Host "LibreHardwareMonitor already present." }

# ---- 3. PawnIO driver ------------------------------------------------------------------------
if (-not (Get-Service PawnIO -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "CPU temperatures, clocks, power and motherboard sensors need the PawnIO kernel driver"
    Write-Host "(signed, used by LibreHardwareMonitor 0.9.5+). GPU, disks, RAM and network work without it."
    $ans = Read-Host "Install PawnIO with winget now? [y/N]"
    if ($ans -match "^[yY]") { winget install --id namazso.PawnIO -e --accept-package-agreements --accept-source-agreements }
} else { Write-Host "PawnIO already installed." }

# ---- 4. configuration: language pack ---------------------------------------------------------
if (-not (Test-Path "config\config.yaml") -and -not (Test-Path "config\pages.yaml")) {
    if (-not $Language) {
        $ans = Read-Host "Language pack - en (English) or it (Italiano) [en]"
        $Language = if ($ans -match "^[iI]") { "it" } else { "en" }
    }
    & .\.venv\Scripts\python.exe -m displaymonitor --init $Language
} else { Write-Host "config\config.yaml / pages.yaml already exist: left untouched (change language with:  python -m displaymonitor --init it --force)" }

Write-Host ""
Write-Host "Done. Try it (elevated PowerShell):  .\.venv\Scripts\python.exe -m displaymonitor"
Write-Host "Autostart at logon:                  .\scripts\install_autostart.ps1"
