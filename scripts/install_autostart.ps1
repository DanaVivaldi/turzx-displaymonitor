# Registers the "DisplayMonitor" scheduled task: starts at logon (15 s delay, so USB and services are up),
# runs hidden with the highest privileges (LibreHardwareMonitor needs admin for CPU / motherboard sensors),
# restarts itself if it dies. It does NOT start the program now. Run from an elevated PowerShell.
#   install:   .\scripts\install_autostart.ps1
#   remove:    Unregister-ScheduledTask -TaskName DisplayMonitor, 'DisplayMonitor Watchdog' -Confirm:$false
$root = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { throw "venv not found: $py" }

$action  = New-ScheduledTaskAction -Execute $py -Argument "-m displaymonitor" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = "PT15S"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName "DisplayMonitor" -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "TURZX 3.5 display monitor (D:\DisplayMonitor)" -Force | Out-Null

# The watchdog: every 5 minutes it starts the program again if it crashed or froze (and leaves it alone after a deliberate quit).
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$wAction  = New-ScheduledTaskAction -Execute $pyw -Argument "-m displaymonitor --watchdog" -WorkingDirectory $root
$wTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$wSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "DisplayMonitor Watchdog" -Action $wAction -Trigger $wTrigger -Settings $wSettings `
    -Principal $principal -Description "Restarts DisplayMonitor if it crashed or froze" -Force | Out-Null
Get-ScheduledTask -TaskName "DisplayMonitor", "DisplayMonitor Watchdog" | Select TaskName, State | Format-Table -AutoSize
