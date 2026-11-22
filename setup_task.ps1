param(
    [switch]$Uninstall,
    [int]$IntervalMinutes = 10
)

$TaskName = "MouseBatteryNotifier"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MonitorScript = Join-Path $ScriptDir "monitor.py"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
    } else {
        Write-Host "Scheduled task '$TaskName' was not found."
    }
    exit 0
}

$pyw = (Get-Command pyw.exe -ErrorAction SilentlyContinue).Source
if (-not $pyw) {
    $pyw = (Get-Command py.exe -ErrorAction Stop).Source
}

$Action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$MonitorScript`"" -WorkingDirectory $ScriptDir
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$TriggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger @($TriggerLogon, $TriggerRepeat) `
    -Settings $Settings `
    -Description "Monitors Logitech mouse battery, learns drain rate patterns, and sends Windows notifications if battery won't last until evening." `
    -Force -ErrorAction Stop | Out-Null

Write-Host "Registered scheduled task '$TaskName' (runs silently every $IntervalMinutes minutes)."
