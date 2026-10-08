# Removes the "DisplayMonitor" and "DisplayMonitor Watchdog" scheduled tasks (stop the program first: python -m displaymonitor --send quit).
Unregister-ScheduledTask -TaskName "DisplayMonitor" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "DisplayMonitor Watchdog" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Scheduled tasks removed (if they existed)."
