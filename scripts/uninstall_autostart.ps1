# Removes the "DisplayMonitor" scheduled task (stop the program first: python -m displaymonitor --send quit).
Unregister-ScheduledTask -TaskName "DisplayMonitor" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Scheduled task removed (if it existed)."
