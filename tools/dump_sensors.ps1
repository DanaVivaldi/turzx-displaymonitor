# Dumps every sensor LibreHardwareMonitor can see (name + current value), including motherboard Super I/O.
# Run from Windows PowerShell 5.1, ELEVATED:   powershell -ExecutionPolicy Bypass -File tools\dump_sensors.ps1
# (the net472 build of LibreHardwareMonitor loads natively in 5.1, not in PowerShell 7)
$d = Join-Path $PSScriptRoot "lhm"
Set-Location $d
[Reflection.Assembly]::LoadFrom("$d\LibreHardwareMonitorLib.dll") | Out-Null
$c = New-Object LibreHardwareMonitor.Hardware.Computer
$c.IsCpuEnabled = $true; $c.IsGpuEnabled = $true
$c.IsMotherboardEnabled = $true; $c.IsStorageEnabled = $true
$c.Open()
function Walk($hw, $ind) {
    $hw.Update()
    "{0}[{1}] {2}" -f $ind, $hw.HardwareType, $hw.Name
    foreach ($s in $hw.Sensors) { "{0}  {1,-14} {2,-34} {3}" -f $ind, $s.SensorType, $s.Name, $s.Value }
    foreach ($sub in $hw.SubHardware) { Walk $sub ($ind + '    ') }
}
Start-Sleep -Milliseconds 800
foreach ($hw in $c.Hardware) { Walk $hw '' }
$c.Close()
